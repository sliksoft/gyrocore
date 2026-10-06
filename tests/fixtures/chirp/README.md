# CHIRP sample-rate fixtures (WU5)

These fixtures document upstream Configurator behavior for the CHIRP analysis
sample-rate path. They are **not** full BBL chirp logs.

## `header_cases.json`

Synthetic header field combinations corresponding to
`useAutotune.computeSampleRate` inputs:

- full-rate logging (`frameIntervalPDenom=1`)
- half-rate logging vs PID (`frameIntervalPDenom=2`) — Blackbox rate &lt; PID rate
- defaults when fields are missing

See `docs/upstream/CHIRP_SAMPLE_RATE.md` and
`tests/core/chirp/test_chirp_sample_rate.py`.

Upstream JS coverage for P-interval header parsing (vendored, not run in
GyroCore CI yet):

`third_party/betaflight/configurator/test/js/blackbox_chirp_p_interval.test.js`
