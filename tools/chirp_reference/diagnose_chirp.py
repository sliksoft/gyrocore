"""Real-flight CHIRP data-quality diagnostics (read-only, diagnostic only).

Runs the unchanged reference pipeline (``identify_chirp_system_from_bbl``) on
every embedded log of a BBL and explains *why* each selected CHIRP segment is
or is not usable: sweep coverage, excitation, spectra, coherence by band,
operating point, saturation, pilot input, body motion and axis coupling.

Nothing here feeds a gate or changes a threshold; the reference result is
reported verbatim and the extra metrics come from the same decoded CSV.

    PYTHONPATH=.:core python3 tools/chirp_reference/diagnose_chirp.py LOG.BBL [--json out.json]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from gyrocore.chirp import identify_chirp_system
from gyrocore.chirp.extraction import AXIS_NAMES
from gyrocore.chirp.frames import BOXCHIRP_BIT, FLIGHT_MODE_FLAG_NAMES, decode_flight_mode_flags
from gyrocore.chirp.quality import MEAN_COHERENCE_BAND_HZ as COHERENCE_BAND_HZ
from gyrocore.chirp.quality import MIN_MEAN_BAND_COHERENCE as MIN_MEAN_COHERENCE
from gyrocore.chirp.quality import USABLE_COHERENCE_MIN as USABLE_COHERENCE
from gyrocore.chirp.sysconfig import find_log_boundaries, read_bbl_header_text
from gyrocore.chirp.system_id import welch_spectra
from gyrocore.decode import decode_bbl

# Report bands (Hz); diagnostic grouping only.
BANDS = ((0.2, 1), (1, 2), (2, 5), (5, 10), (10, 20), (20, 50), (50, 100), (100, 200), (200, 600))
MOTOR_HIGH_FRACTION = 0.98  # of the motorOutput span
GYRO_CLIP_DPS = 1990.0  # 2000 dps gyro full scale
STICK_ACTIVE = 20  # rcCommand counts (of +/-500) treated as deliberate stick input
DISTURBANCE_GYRO_DPS = 500.0  # any-axis gyro above this during a <=230 deg/s excitation = loss of control
THROTTLE_CUT_RC = 1050  # rcCommand[3] at/below this = throttle chopped
ANGLE_BIT = FLIGHT_MODE_FLAG_NAMES.index("ANGLE_MODE")


def _f(x: Any) -> float | None:
    if x is None:
        return None
    x = float(x)
    return round(x, 6) if math.isfinite(x) else None


def _csv_columns(csv_text: str) -> dict[str, np.ndarray]:
    rows = list(csv.reader(io.StringIO(csv_text)))
    header = [h.strip().split(" (")[0] for h in rows[0]]
    cols: dict[str, list[float]] = {h: [] for h in header}
    for r in rows[1:]:
        for h, cell in zip(header, r):
            cell = cell.strip()
            if h == "flightModeFlags":
                bits = decode_flight_mode_flags(cell)
                cols[h].append(float("nan") if bits is None else float(bits))
                continue
            try:
                cols[h].append(float(cell))
            except ValueError:
                cols[h].append(float("nan"))
    return {h: np.asarray(v) for h, v in cols.items()}


def _band_stats(freqs: np.ndarray, values: np.ndarray, lo: float, hi: float) -> dict[str, Any]:
    m = (freqs >= lo) & (freqs <= hi) if hi >= lo else np.zeros(freqs.shape, dtype=bool)
    v = values[m]
    if not v.size:
        return {"bins": 0}
    return {
        "bins": int(v.size),
        "min": _f(v.min()),
        "median": _f(np.median(v)),
        "mean": _f(v.mean()),
        "pct_ge_usable": _f(100.0 * np.mean(v >= USABLE_COHERENCE)),
        "pct_ge_gate": _f(100.0 * np.mean(v >= MIN_MEAN_COHERENCE)),
    }


def _db(x: np.ndarray) -> float | None:
    s = float(np.mean(x)) if x.size else 0.0
    return _f(10.0 * math.log10(s)) if s > 0 else None


def _segment_end_cause(cols: dict[str, np.ndarray], end_row: int, axis: int) -> str:
    n = cols["time"].size
    if end_row >= n - 1:
        return "log_ended_during_chirp"
    flags = cols.get("flightModeFlags")
    nxt = end_row + 1
    if flags is not None and math.isfinite(flags[nxt]) and not (int(flags[nxt]) >> BOXCHIRP_BIT) & 1:
        return "chirp_mode_switched_off"
    d1 = cols["debug[1]"][nxt]
    if d1 == -1:
        return "chirp_finished_or_aborted (axis -1)"
    if d1 != axis:
        return f"axis_changed_to_{int(d1)}"
    return "unknown"


def diagnose_axis(result, axis: int, cols: dict[str, np.ndarray], motor_range: tuple[float, float]) -> dict[str, Any]:
    ax = result.axes[axis]
    ext = result.extraction
    sc = result.sysconfig
    seg = ax.segment
    x, y, t = ext.segment_signals(seg)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    # Map segment to CSV rows by timestamp (unique within a log).
    tcsv = cols["time"]
    r0 = int(np.searchsorted(tcsv, seg.start_time_us, side="left"))
    r1 = int(np.searchsorted(tcsv, seg.end_time_us, side="right")) - 1
    rows = slice(r0, r1 + 1)

    configured_s = float(sc.chirp_time_seconds) if sc and sc.chirp_time_seconds else None
    f0, f1 = (ext.frequency_range_hz or (None, None))
    freq_dbg = ext.debug[2, seg.start_idx : seg.end_idx + 1].astype(np.float64) * 0.1  # "Chirp Frequency", 0.1 Hz
    reached = float(np.nanmax(freq_dbg)) if freq_dbg.size else None
    expo_reached = (
        f0 * (f1 / f0) ** min(1.0, seg.duration_s / configured_s) if f0 and f1 and configured_s else None
    )
    amp_cfg = {0: sc.chirp_amplitude_roll, 1: sc.chirp_amplitude_pitch, 2: sc.chirp_amplitude_yaw}[axis] if sc else None

    amp_by_band = {}
    for lo, hi in BANDS:
        m = (freq_dbg >= lo) & (freq_dbg < hi)
        if m.sum() >= 8:
            amp_by_band[f"{lo:g}-{hi:g}"] = {
                "setpoint_peak_dps": _f(np.max(np.abs(x[m]))),
                "setpoint_rms_dps": _f(np.sqrt(np.mean(x[m] ** 2))),
                "gyro_rms_dps": _f(np.sqrt(np.mean(y[m] ** 2))),
                "seconds": _f(m.sum() / ax.effective_rate_hz),
            }

    tf = ax.transfer_function
    sp = tf.spectra
    freqs = tf.frequencies
    coh = tf.coherence
    band_lo, band_hi = ax.quality.analysis_band_hz
    swept_hi = min(band_hi, reached) if reached else band_hi
    swept_lo = max(band_lo, f0 or band_lo)

    coherence_by_band = {}
    spectra_by_band = {}
    for lo, hi in BANDS:
        m = (freqs >= lo) & (freqs < hi)
        if not m.any():
            continue
        coherence_by_band[f"{lo:g}-{hi:g}"] = _f(np.mean(coh[m]))
        spectra_by_band[f"{lo:g}-{hi:g}"] = {"input_db": _db(sp.sxx[m]), "response_db": _db(sp.syy[m])}

    # Off-axis coupling: excited setpoint -> other-axis gyro, same Welch settings.
    coupling = {}
    for other in range(3):
        if other == axis:
            continue
        yo = np.asarray(ext.gyro[other, seg.start_idx : seg.end_idx + 1], dtype=np.float64)
        so = welch_spectra(x, yo, sp.segment_size, 0.5)
        den = so.sxx * so.syy
        c = np.where(den > 1e-30, (so.sxy_re**2 + so.sxy_im**2) / np.where(den > 1e-30, den, 1.0), 0.0)
        m = (freqs >= max(swept_lo, COHERENCE_BAND_HZ[0])) & (freqs <= min(swept_hi, COHERENCE_BAND_HZ[1]))
        coupling[AXIS_NAMES[other]] = {
            "gyro_rms_ratio": _f(np.sqrt(np.mean(yo**2)) / max(1e-9, np.sqrt(np.mean(y**2)))),
            "coherence_with_excitation_mean": _f(np.mean(c[m])) if m.any() else None,
            "setpoint_rms_dps": _f(np.sqrt(np.mean(ext.setpoint[other, seg.start_idx : seg.end_idx + 1].astype(np.float64) ** 2))),
        }

    def col(name: str) -> np.ndarray | None:
        return cols[name][rows] if name in cols else None

    motors = [col(f"motor[{i}]") for i in range(4) if f"motor[{i}]" in cols]
    motor_lo, motor_hi = motor_range
    operating: dict[str, Any] = {}
    thr = col("rcCommand[3]")
    if thr is not None:
        operating["throttle_rc"] = {"mean": _f(np.nanmean(thr)), "min": _f(np.nanmin(thr)), "max": _f(np.nanmax(thr))}
    if motors:
        mot = np.vstack(motors)
        span = motor_hi - motor_lo
        operating["motor_pct"] = {
            "mean": _f(100 * (np.nanmean(mot) - motor_lo) / span),
            "min": _f(100 * (np.nanmin(mot) - motor_lo) / span),
            "max": _f(100 * (np.nanmax(mot) - motor_lo) / span),
        }
        operating["motor_saturated_high_pct"] = _f(100 * np.mean(np.any(mot >= motor_lo + MOTOR_HIGH_FRACTION * span, axis=0)))
        operating["motor_at_min_pct"] = _f(100 * np.mean(np.any(mot <= motor_lo + 0.01 * span, axis=0)))
    vbat = col("vbatLatest")
    if vbat is not None:
        operating["vbat_v"] = {"start": _f(vbat[0]), "min": _f(np.nanmin(vbat))}

    gyro_all = [col(f"gyroADC[{i}]") for i in range(3)]
    clipping = {
        "gyro_clip_pct": _f(100 * np.mean(np.any(np.abs(np.vstack(gyro_all)) >= GYRO_CLIP_DPS, axis=0))),
        "setpoint_peak_dps": _f(np.max(np.abs(x))),
        "gyro_peak_dps": _f(np.max(np.abs(y))),
    }

    pilot = {}
    for i, name in enumerate(AXIS_NAMES):
        rc = col(f"rcCommand[{i}]")
        if rc is not None:
            pilot[name] = {
                "mean": _f(np.nanmean(rc)),
                "std": _f(np.nanstd(rc)),
                "max_abs": _f(np.nanmax(np.abs(rc))),
                "off_center_pct": _f(100 * np.mean(np.abs(rc) > STICK_ACTIVE)),
                "corr_with_excitation": _f(np.corrcoef(rc, x)[0, 1]) if rc.size == x.size and np.std(rc) > 0 else None,
            }
    flags = col("flightModeFlags")
    modes = {}
    if flags is not None:
        fl = flags[np.isfinite(flags)].astype(int)
        modes = {
            "angle_mode_pct": _f(100 * np.mean((fl >> ANGLE_BIT) & 1)) if fl.size else None,
            "mode_changes": int(np.count_nonzero(np.diff(fl))) if fl.size > 1 else 0,
        }
    body = {}
    for name, dbg in (("roll_angle_deg", "debug[4]"), ("pitch_angle_deg", "debug[6]")):
        a = col(dbg)
        if a is not None:
            a = a * 0.1
            body[name] = (
                {"min": _f(np.nanmin(a)), "max": _f(np.nanmax(a)), "rms": _f(np.sqrt(np.nanmean(a**2)))}
                if np.any(a)
                else "not_logged"
            )
    acc = [col(f"accSmooth[{i}]") for i in range(3)]

    # Disturbance events: loss of control / saturation / throttle cut (diagnostic only).
    g_abs = np.max(np.abs(np.vstack(gyro_all)), axis=0)
    bad = g_abs > DISTURBANCE_GYRO_DPS
    if motors:
        bad |= np.any(np.vstack(motors) >= motor_lo + MOTOR_HIGH_FRACTION * (motor_hi - motor_lo), axis=0)
    if thr is not None:
        bad |= thr <= THROTTLE_CUT_RC
    t_rel = (tcsv[rows] - seg.start_time_us) / 1e6
    events = _runs(bad, t_rel)
    clean = _longest_clean_run(bad, x.size)
    event_free: dict[str, Any] = {"seconds": _f((clean[1] - clean[0]) / ax.effective_rate_hz)}
    if clean[1] - clean[0] >= 4 * sp.segment_size and bad.size == x.size:
        sl = slice(clean[0], clean[1])
        sc_ = welch_spectra(x[sl], y[sl], sp.segment_size, 0.5)
        den = sc_.sxx * sc_.syy
        c2 = np.where(den > 1e-30, (sc_.sxy_re**2 + sc_.sxy_im**2) / np.where(den > 1e-30, den, 1.0), 0.0)
        fr = freq_dbg[sl]
        event_free.update(
            {
                "start_s": _f(t_rel[clean[0]]),
                "end_s": _f(t_rel[clean[1] - 1]),
                "sweep_hz": [_f(fr.min()), _f(fr.max())],
                "coherence_by_band": {
                    f"{lo:g}-{hi:g}": _f(np.mean(c2[(freqs >= lo) & (freqs < hi)]))
                    for lo, hi in BANDS
                    if np.any((freqs >= lo) & (freqs < hi))
                },
            }
        )

    gates = {g.code + ("" if g.severity.value == "blocking" else "(warn)"): {"passed": g.passed, "value": _f(g.value), "threshold": _f(g.threshold)} for g in ax.quality.gates}

    return {
        "axis": ax.axis_name,
        "usable": ax.usable,
        "failed_gates": list(ax.quality.failed),
        "segment": {
            "start_s": _f(seg.start_time_us / 1e6),
            "end_s": _f(seg.end_time_us / 1e6),
            "duration_s": _f(seg.duration_s),
            "configured_chirp_s": configured_s,
            "completion_pct": _f(100 * seg.duration_s / configured_s) if configured_s else None,
            "end_cause": _segment_end_cause(cols, r1, axis),
            "usable_samples": seg.sample_count,
            "welch_segments": ax.transfer_function.num_segments,
            "segment_size": ax.segment_size,
        },
        "sweep": {
            "configured_hz": [f0, f1],
            "reported_start_hz": _f(freq_dbg[0]) if freq_dbg.size else None,
            "reported_reached_hz": _f(reached),
            "exponential_model_reached_hz": _f(expo_reached),
            "analysis_band_hz": [band_lo, band_hi],
            "gate_window_hz": list(COHERENCE_BAND_HZ),
            "gate_window_swept_pct": _f(
                100 * max(0.0, min(swept_hi, COHERENCE_BAND_HZ[1]) - COHERENCE_BAND_HZ[0]) / (COHERENCE_BAND_HZ[1] - COHERENCE_BAND_HZ[0])
            ),
        },
        "excitation": {
            "configured_amplitude_dps": amp_cfg,
            "setpoint_rms_dps": _f(ax.quality.input_rms),
            "by_band": amp_by_band,
        },
        "sample_rate": {
            "effective_hz": ax.effective_rate_hz,
            "timestamp_hz": _f(ax.sample_rate.timestamp_rate_hz),
            "source": ax.sample_rate.source.value if hasattr(ax.sample_rate.source, "value") else str(ax.sample_rate.source),
        },
        "timestamps": {
            "uniform_fraction": _f(ax.spacing.uniform_fraction),
            "gap_count": ax.spacing.gap_count,
            "missing_fraction": _f(ax.spacing.missing_fraction),
            "max_gap_samples": ax.spacing.max_gap_samples,
            "non_positive_deltas": ax.spacing.non_positive_deltas,
        },
        "spectra_by_band": spectra_by_band,
        "coherence_by_band": coherence_by_band,
        "coherence": {
            "gate_window": _band_stats(freqs, coh, *COHERENCE_BAND_HZ),
            "gate_window_swept_part": {
                "hz": [COHERENCE_BAND_HZ[0], _f(min(swept_hi, COHERENCE_BAND_HZ[1]))],
                **_band_stats(freqs, coh, COHERENCE_BAND_HZ[0], min(swept_hi, COHERENCE_BAND_HZ[1])),
            },
            "swept_band": {"hz": [_f(swept_lo), _f(swept_hi)], **_band_stats(freqs, coh, swept_lo, swept_hi)},
            "unswept_band": {"hz": [_f(swept_hi), band_hi], **_band_stats(freqs, coh, swept_hi, band_hi)},
            "usable_range_hz": list(ax.quality.usable_range_hz) if ax.quality.usable_range_hz else None,
            "usable_bins": int(ax.quality.usable_mask.sum()),
            "gate_mean": _f(ax.quality.mean_band_coherence),
        },
        "operating_point": operating,
        "clipping": clipping,
        "pilot_input_rc": pilot,
        "flight_modes": modes,
        "body_motion": body,
        "acc_rms": {f"acc[{i}]": _f(np.sqrt(np.nanmean(a**2))) for i, a in enumerate(acc) if a is not None},
        "axis_coupling": coupling,
        "disturbance_events": events,
        "event_free_window": event_free,
        "gates": gates,
    }


def _runs(mask: np.ndarray, t: np.ndarray, merge_s: float = 0.25) -> list[dict[str, float | None]]:
    """Merged [start, end] seconds of True runs in ``mask``."""
    out: list[list[float]] = []
    idx = np.flatnonzero(mask)
    for i in idx:
        ti = float(t[i])
        if out and ti - out[-1][1] <= merge_s:
            out[-1][1] = ti
        else:
            out.append([ti, ti])
    return [{"start_s": _f(a), "end_s": _f(b)} for a, b in out]


def _longest_clean_run(bad: np.ndarray, n: int) -> tuple[int, int]:
    best, start = (0, 0), None
    for i, b in enumerate(list(bad[:n]) + [True]):
        if not b and start is None:
            start = i
        elif b and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def _motor_range(headers: str) -> tuple[float, float]:
    for line in headers.splitlines():
        if line.startswith("H motorOutput:"):
            lo, hi = line.split(":", 1)[1].split(",")[:2]
            return float(lo), float(hi)
    return 48.0, 2047.0


def diagnose_bbl(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    data = path.read_bytes()
    logs = []
    for li in range(len(find_log_boundaries(data))):
        decoded = decode_bbl(path, log_index=li)
        headers = read_bbl_header_text(data, li)
        result = identify_chirp_system(csv_text=decoded.csv_text, headers=headers, log_index=li)
        entry: dict[str, Any] = {
            "log_index": li,
            "status": result.status,
            "errors": list(result.errors),
            "warnings": list(result.warnings),
            "segments": [s.to_dict() for s in result.extraction.segments] if result.extraction else [],
            "axes": {},
        }
        if result.axes:
            cols = _csv_columns(decoded.csv_text)
            entry["frames"] = int(cols["time"].size)
            for axis in sorted(result.axes):
                entry["axes"][AXIS_NAMES[axis]] = diagnose_axis(result, axis, cols, _motor_range(headers))
        logs.append(entry)
    return {"file": path.name, "logs": logs}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bbl")
    ap.add_argument("--json", help="write the full diagnostic JSON here")
    args = ap.parse_args()
    report = diagnose_bbl(args.bbl)
    text = json.dumps(report, indent=1)
    if args.json:
        Path(args.json).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
