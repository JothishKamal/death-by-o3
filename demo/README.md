# Optimization Autopsy — Demo

**The opening claim (spec §12):** `-O3` is five times slower than it needs to be,
and here is the single decision responsible.

Demo case: `benchmarks/tierA/A12_simplifycfg_cmov.c` — a perfectly predicted
branch guarding a serial dependence chain. `simplifycfg` folds it into a
`select`, forcing both arms onto the critical path. The pass emits **no
optimization remark**, so it is invisible to every remark-based tool.

## Measured result (this repo, this machine)

```
-O3                                   1.162 ns/rep
-O3, one simplifycfg decision vetoed  0.237 ns/rep     4.91x
CHECK 8126464 — byte-identical across both builds
```

## Watch on GitHub

**Web UI walkthrough**

https://github.com/user-attachments/assets/9f5eab41-c17a-4f50-81d3-2b960716452f

**CLI walkthrough**

https://github.com/user-attachments/assets/ca6a0f97-e117-4626-9b4a-d60094a66c3a

![Optimization Autopsy evidence view](https://github.com/user-attachments/assets/fbd9721f-d1a5-4d53-9cee-b5d2eab87a7c)

## Files

- **`demo-ui.mp4`** — screen recording of the web UI walkthrough (spec §12
  beats): full tree → changed-only filter → the culprit invocation's
  before/after IR diff → evidence card with provenance tracing.
  Regenerate: `.venv/bin/autopsy serve …` + `web: npm run dev`, record with
  any screen recorder.
- **`terminal.mp4`** — the CLI loop as a video (rendered from the asciinema
  cast): measure the regression, capture 513 invocations / 56 decisions,
  diagnose (`#1 loop-unroll on chain`), guard-verified veto with the stock
  clang reproduce command.
- `terminal.cast` — asciinema recording of the same CLI session
  (`asciinema play demo/terminal.cast`). Regenerate with
  `.venv/bin/python scripts/record-demo-cast.py`.
- `demo.script.md` — the beat-by-beat demo script (spec §12)
- `screenshots/` — stills of the web UI

## Reproduce everything from scratch

```bash
make bootstrap && make build          # plugin + venv
make test                             # pytest suite
cd web && npm i && npx vitest run     # vitest suite
npx vite build                        # ~228 KB gzip

# CLI loop
.venv/bin/autopsy capture benchmarks/tierA/A12_simplifycfg_cmov.c -o /tmp/demo
.venv/bin/autopsy diagnose benchmarks/tierA/A12_simplifycfg_cmov.c --top 3
.venv/bin/autopsy veto benchmarks/tierA/A12_simplifycfg_cmov.c \
    --pass-name simplifycfg --function chain

# Full UI
.venv/bin/autopsy serve benchmarks/tierA/A12_simplifycfg_cmov.c   # :8000
cd web && npm run dev                                             # :5173/?run=<id>
```

See the repository README for prerequisites and full usage.
