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

## Files

- `demo.script.md` — the beat-by-beat demo script (spec §12)
- `terminal.cast` — asciinema recording of the CLI loop:
  capture → diagnose → veto, with guard verification and prefix proof
- `screenshots/` — the web UI: timeline + evidence card (`ui-full.png`),
  the before/after IR diff of the culprit invocation (`ui-diff.png`),
  and scaffolding-node handling (`ui-scaffolding.png`)

## Reproduce everything from scratch

```bash
make bootstrap && make build          # plugin + venv
make test                             # 157 pytest tests
cd web && npm i && npx vitest run     # 31 vitest tests
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

Play the cast in a terminal: `asciinema play demo/terminal.cast`
