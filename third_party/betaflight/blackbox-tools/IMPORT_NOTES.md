# blackbox-tools import notes (WU5)

Copied from https://github.com/betaflight/blackbox-tools at the commit in `UPSTREAM_COMMIT`.

## Included
- `src/` decoding/parsing sources (`parser`, `decoders`, `stream`, `blackbox_decode`, fielddefs, tools, …)
- `test/`, `LICENSE`, `Makefile`, `Readme.md`

## Intentionally excluded
- `lib/` platform static/shared binaries (~105MB: cairo/freetype/png for Windows/macOS)
- `src/blackbox_render.c` (cairo-dependent video renderer)
- `src/embeddedfont.*` and `SourceSansPro-Regular.otf` (render-only assets)

## Local patches
- `src/parser.c`, `src/blackbox_fielddefs.h`, `src/blackbox_decode.c`: consume FLIGHTMODE (30) and
  DISARM (15) event payloads so valid frames after mode changes are not dropped. Marked
  `GyroCore local patch`; details in `docs/upstream/PATCHES.md`.

GyroCore already wraps an installed `blackbox_decode` binary via `gyrocore.decode`.
This tree is the upstream source foundation for future parity/improvement work, not a
runtime build of the decoder in WU5.
