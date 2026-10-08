# Simplified-tuning C reference harness (WU9)

Compiles vendored Betaflight 2026.6.2 `simplified_tuning.c` and feeds a line
protocol used by `tests/core/betaflight/test_simplified_tuning_wu9_math_parity.py`.

The harness binary is a build artifact (gitignored). Tests compile into a
temporary directory.

```
python tools/simplified_tuning_reference/build.py
```

Stub headers under `include/` exist only so the vendored `.c` compiles; PID and
gyro **defaults** are asserted against the vendored `pid.h` / `gyro.h`.
