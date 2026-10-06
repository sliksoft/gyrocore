# GyroCore

GyroCore is an open-source desktop platform for Betaflight flight-log analysis, diagnostics, tuning, system identification and automated tune assistance.

## Goals

GyroCore brings together:

- Betaflight Blackbox decoding and analysis
- Blackbox Viewer
- Configurable flight-signal graphs
- FFT, spectral and resonance analysis
- eRPM and motor diagnostics
- Step-response analysis
- PID and filter analysis
- Autotune / CHIRP system identification
- Frequency-response analysis
- Bode magnitude and phase plots
- Coherence analysis
- Automated tuning assistance
- Mechanical and tuning-output safety
- Before/after run comparison
- Local and offline operation
- Windows and Linux desktop support

## Architecture

GyroCore is built around a reusable Python Core. The desktop application is a separate consumer of that Core, allowing the same analysis and tuning engine to be reused by projects such as Redline Race Control.

## Betaflight

GyroCore builds on the Betaflight ecosystem.

Relevant upstream projects include:

- Betaflight firmware
- Betaflight Configurator
- Betaflight Blackbox Viewer / Blackbox Explorer
- Betaflight blackbox-tools

GyroCore will reuse, adapt and improve relevant GPL-licensed Betaflight functionality, including Blackbox Viewer and Autotune / CHIRP functionality, instead of unnecessarily rebuilding those components from scratch.

Upstream copyright, license and SPDX notices will be retained where applicable.

## Development status

GyroCore is under active development.

The Core is currently being extracted and validated using donor-parity and regression tests before the complete desktop Blackbox Viewer and Autotune / CHIRP interface is integrated.

## License

GyroCore is distributed under the GNU General Public License version 3.

See `LICENSE` and `THIRD_PARTY_NOTICES.md`.
