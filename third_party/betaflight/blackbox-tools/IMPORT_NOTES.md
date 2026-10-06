# blackbox-tools import notes (WU5)

Copied from https://github.com/betaflight/blackbox-tools at the commit in `UPSTREAM_COMMIT`.

## Included
- `src/` decoding/parsing sources (`parser`, `decoders`, `stream`, `blackbox_decode`, fielddefs, tools, …)
- `test/`, `LICENSE`, `Makefile`, `Readme.md`

## Intentionally excluded
- `lib/` platform static/shared binaries (~105MB: cairo/freetype/png for Windows/macOS)
- `src/blackbox_render.c` (cairo-dependent video renderer)
- `src/embeddedfont.*` and `SourceSansPro-Regular.otf` (render-only assets)

GyroCore already wraps an installed `blackbox_decode` binary via `gyrocore.decode`.
This tree is the upstream source foundation for future parity/improvement work, not a
runtime build of the decoder in WU5.
