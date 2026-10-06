# GyroCore WU4: adapted from AeroTuner backend/analysis/multi_axis_fft.py
import numpy as np


def smooth_spectrum(spectrum: np.ndarray | list) -> np.ndarray:
    """5-bin moving average (same as merged-axis path)."""
    s = np.asarray(spectrum, dtype=float)
    if s.size <= 5:
        return s
    kernel = np.ones(5) / 5.0
    return np.convolve(s, kernel, mode="same")


def compute_fft(signal: np.ndarray | list, fs: float = 1000.0) -> tuple[np.ndarray, np.ndarray]:
    signal = np.asarray(signal, dtype=float)
    n = len(signal)
    if n < 2:
        return np.array([]), np.array([])
    freqs = np.fft.rfftfreq(n, 1.0 / float(fs))
    spectrum = np.abs(np.fft.rfft(signal))
    return freqs, spectrum


def merge_axes_fft(
    gx: np.ndarray | list,
    gy: np.ndarray | list,
    gz: np.ndarray | list,
    fs: float = 1000.0,
    remove_dc: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    gx = np.asarray(gx, dtype=float)
    gy = np.asarray(gy, dtype=float)
    gz = np.asarray(gz, dtype=float)
    n = min(len(gx), len(gy), len(gz))
    if n < 2:
        return np.array([]), np.array([])
    gx = gx[:n].copy()
    gy = gy[:n].copy()
    gz = gz[:n].copy()

    if remove_dc:
        gx -= float(np.mean(gx))
        gy -= float(np.mean(gy))
        gz -= float(np.mean(gz))

    fx, sx = compute_fft(gx, fs)
    fy, sy = compute_fft(gy, fs)
    fz, sz = compute_fft(gz, fs)

    # Same frequency bins (identical n, fs)
    spectrum = (sx + sy + sz) / 3.0
    spectrum = smooth_spectrum(spectrum)

    return fx, spectrum


def per_axis_smoothed_spectra(
    gx: np.ndarray | list,
    gy: np.ndarray | list,
    gz: np.ndarray | list,
    fs: float = 1000.0,
    remove_dc: bool = False,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """
    Independent FFT + smoothing per gyro axis (roll=gx, pitch=gy, yaw=gz).
    Uses the same alignment and optional DC removal as merge_axes_fft.
    """
    gx = np.asarray(gx, dtype=float)
    gy = np.asarray(gy, dtype=float)
    gz = np.asarray(gz, dtype=float)
    n = min(len(gx), len(gy), len(gz))
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    if n < 2:
        empty = np.array([]), np.array([])
        return {"roll": empty, "pitch": empty, "yaw": empty}

    for name, arr_full in (
        ("roll", gx[:n]),
        ("pitch", gy[:n]),
        ("yaw", gz[:n]),
    ):
        seg = np.asarray(arr_full, dtype=float).copy()
        if remove_dc:
            seg -= float(np.mean(seg))
        freqs, spec = compute_fft(seg, fs)
        out[name] = (freqs, smooth_spectrum(spec))
    return out
