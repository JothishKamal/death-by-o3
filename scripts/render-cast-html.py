#!/usr/bin/env python3
"""Render demo/terminal.cast into a self-playing terminal-styled HTML page.

The page is recorded with agent-browser to produce demo/terminal.mp4
(via ffmpeg from WebM). ANSI SGR codes are converted to spans.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CAST = REPO / "demo" / "terminal.cast"
OUT = REPO / "demo" / "_terminal_player.html"

_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_COLORS = {"30": "#3b4252", "31": "#f7768e", "32": "#9ece6a", "33": "#e0af68",
           "34": "#7aa2f7", "35": "#bb9af7", "36": "#7dcfff", "37": "#d8dee9",
           "90": "#6b7280", "91": "#f7768e", "92": "#9ece6a", "93": "#e0af68",
           "94": "#7aa2f7", "95": "#bb9af7", "96": "#7dcfff", "97": "#ffffff"}


def ansi_to_html(text: str) -> str:
    out, open_spans = [], 0
    pos = 0
    spans = []
    for m in _SGR.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        pos = m.end()
        codes = m.group(1).split(";") if m.group(1) else ["0"]
        for c in codes:
            if c == "0":
                if open_spans:
                    out.append("</span>" * open_spans)
                    open_spans = 0
            elif c == "1":
                out.append('<span style="font-weight:bold">')
                open_spans += 1
            elif c in _COLORS:
                out.append(f'<span style="color:{_COLORS[c]}">')
                open_spans += 1
    out.append(html.escape(text[pos:]))
    if open_spans:
        out.append("</span>" * open_spans)
    return "".join(out).replace("\n", "<br>")


def main() -> None:
    header = None
    frames = []
    for line in CAST.read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            header = e
        elif isinstance(e, list) and len(e) >= 3 and e[1] == "o":
            frames.append((max(0.4, float(e[0])), e[2]))

    total = sum(d for d, _ in frames)
    data = [{"delay": d, "html": ansi_to_html(t)} for d, t in frames]

    OUT.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{margin:0;background:#0f1115;display:flex;align-items:center;"
        "justify-content:center;height:100vh}"
        ".term{background:#161920;border:1px solid #262b36;border-radius:8px;"
        "width:900px;padding:18px 22px;font:14px/1.55 ui-monospace,Menlo,"
        "monospace;color:#d8dee9;white-space:pre-wrap;min-height:480px}"
        ".bar{height:10px}</style></head><body>"
        "<div class='term' id='t'><div class='bar'></div></div>"
        "<script>const F=" + json.dumps(data) + ";"
        "let i=0,t=document.getElementById('t');"
        "function step(){if(i>=F.length)return;"
        "const d=document.createElement('div');d.innerHTML=F[i].html;"
        "t.appendChild(d);i++;setTimeout(step,F[i-1].delay*1000);}"
        "setTimeout(step,800);</script></body></html>")
    print(f"wrote {OUT} ({len(frames)} frames, {total:.1f}s)")


if __name__ == "__main__":
    main()
