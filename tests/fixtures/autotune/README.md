# Autotune recommendation fixtures (WU8)

| File | Role |
|------|------|
| `wu8/synthetic_cases.json` | 23 synthetic transfer functions: `makeSyntheticTf` parameters, coherence overrides, current sliders, phase-margin presets |
| `wu8/bbl/*.bbl.gz`, `wu8/bbl_cases.json` | 19 simulated closed-loop CHIRP logs + manifest (headers, plant, classification, expectations, coverage) |
| `wu8/upstream_autotune_reference.json.gz` | expected values from the vendored `recommendGains` and helpers (139 vectors, all intermediates) |

Generated, not hand-written:
`PYTHONPATH=core python tools/autotune_reference/make_autotune_cases.py` then
`node --experimental-strip-types tools/autotune_reference/autotune_harness.mjs`.

Parity record: `docs/upstream/AUTOTUNE_RECOMMENDATION_PARITY.md`.
