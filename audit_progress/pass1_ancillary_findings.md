# Pass-1 Findings — Ancillary Roots

- `data/README.md` still promotes FSD auto-scanning feature; revise to reflect coordinator-first architecture and clarify headless workflows.
- `configs/fsd_mode_example.json` enforces FSD semantics (IBKR backend, short time limit); ensure documentation highlights headless/paper config options.
- `.github/workflows/ci.yml` pins linting to Python 3.9 while typecheck/tests target 3.9–3.11; align with supported runtime (pyright config set to 3.11).
- `.gitignore` excludes `data/**/*.json`; confirm this doesn’t block versioning of curated manifests or required fixtures.
