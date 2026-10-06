# WU0 Fixture Inventory

Donor inspected read-only: `/home/sliksoft/aerotuner`.

## Candidates found

| Kind | Path | Notes |
|------|------|-------|
| Golden CSV | `backend/test/golden_logs/GL-001-clean/` | Tracked; selected as FIXTURE A |
| Golden CSV | `backend/test/golden_logs/GL-002-noisy/` | Tracked; selected as FIXTURE B |
| Golden CSV | `backend/test/golden_logs/GL-003-motor_issue/` | Tracked; not selected for WU0 minimum set |
| CLI + snapshot | `backend/tests/fixtures/75mm_whoop_36219f09/` | Tracked CLI + run_snapshot; **no BBL** |
| Manifest candidates | `backend/tests/fixtures/real_validation_manifest.json` | Status `blocked_no_fixtures` |
| Real BBL candidates | `backend/uploads/*75_WOOP*.BBL` etc. | **MISSING** at WU0 time |
| Tiny upload stubs | `backend/uploads/*.bbl` (6–80 bytes) | Not real logs; rejected |

## Selected for GyroCore

1. `gl001_clean` — live CSV oracle (FIXTURE A)
2. `gl002_noisy` — live CSV oracle (FIXTURE B)
3. `gl001_with_cli` — live CSV + tracked whoop CLI (CLI/safety path)
4. `whoop75_cli_snapshot` — snapshot partial; `BLOCKED_REAL_BBL_FIXTURE`

## Pairing confidence

- CSV goldens: high for partial pipeline parity.
- CSV + whoop CLI: medium synthetic cross-pair (not a real matched flight).
- Whoop CLI + snapshot: high for those artifacts; BBL pairing blocked.
