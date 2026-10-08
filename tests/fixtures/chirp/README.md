# CHIRP fixtures (WU5–WU7)

| File | Role |
|------|------|
| `header_cases.json` | WU5 Autotune denom-only upstream mirror cases |
| `sample_rate_parity_vectors.json` | WU6 resolver parity (upstream + GyroCore improvements) |
| `system_id_parity_vectors.json` | WU6 Hanning + Welch TF foundation vectors |
| `wu7/bbl/*.bbl.gz`, `wu7/cases.json` | WU7 synthetic CHIRP logs + case manifest (classification, expectations) |
| `wu7/math_inputs.json` | WU7 FFT / Welch / spectrogram inputs |
| `wu7/upstream_reference.json` | WU7 expected values from vendored `parseChirpLog` + autotune analysis |
| `wu7/upstream_math_reference.json` | WU7 expected values from vendored `fft.ts` / `spectral_analysis.ts` |

WU7 files are generated, not hand-written:
`tools/chirp_reference/make_cases.py` then
`node --experimental-strip-types tools/chirp_reference/reference_harness.mjs`.

Policy: `docs/upstream/CHIRP_SAMPLE_RATE_POLICY.md`  
System-ID map: `docs/upstream/SYSTEM_ID_FOUNDATION.md`  
WU7 parity: `docs/upstream/CHIRP_SYSTEM_ID_PARITY.md`
