# Betaflight firmware snapshot (WU9)

Traceable extract of **Betaflight 2026.6.2** simplified-tuning sources.

| Field | Value |
| --- | --- |
| Repository | https://github.com/betaflight/betaflight |
| Version / tag | `2026.6.2` |
| Commit | `e0b7bb01b17b21351057e9ead2d1ab39dd44fa16` |

Copied from that tag (byte-identical `git show`). `simplified_tuning.c` is also identical on later `vliegai/2026.6.2-research` HEAD; WU9 still pins the release tag.

This is **not** a full firmware tree. MSP helpers/cases that implement
`MSP_VALIDATE_SIMPLIFIED_TUNING` / `MSP_SET_SIMPLIFIED_TUNING` /
`MSP_CALCULATE_SIMPLIFIED_*` are extracted from `src/main/msp/msp.c` into
`src/main/msp/msp_simplified_tuning.c` with original line numbers, because the
parent file is ~5000 lines and otherwise unrelated.

Do not modify files under this directory.
