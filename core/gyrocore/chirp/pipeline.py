"""End-to-end CHIRP system identification entry point (analysis only).

    decoded log -> sysConfig -> CHIRP extraction -> per-segment sample-rate
    resolution -> Welch transfer function (+ sensitivity / step / open loop)
    -> validity gates -> :class:`ChirpSystemIdResult`

Mirrors ``useAutotune.ts`` ``analyzeLog`` / ``computeAxisResult`` up to, and
excluding, ``recommendGains``. No gain recommendation, PID/filter
application, MSP write or CLI output is produced here.

GyroCore hardening relative to upstream (see
``docs/upstream/CHIRP_SYSTEM_ID_PARITY.md``):

- the analysis rate comes from :func:`resolve_chirp_sample_rate` (PNum/PDenom
  aware, timestamp cross-checked) instead of Autotune's denom-only formula
- spacing / gap / excitation / coherence gates mark results unusable instead
  of silently analysing them
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .extraction import AXIS_NAMES, ChirpExtraction, ChirpSegment, extract_chirp, validate_chirp_debug_mode
from .frames import ChirpFrames, ChirpFramesError, chirp_frames_from_parsed_samples, read_chirp_frames_from_csv
from .quality import QualityReport, analysis_band, post_analysis_report, pre_analysis_gates
from .sample_rate import (
    SampleRateEvidence,
    TimestampSpacing,
    analyze_timestamp_spacing,
    resolve_chirp_sample_rate,
    upstream_autotune_compute_sample_rate_hz,
)
from .sysconfig import ChirpSysConfig, parse_chirp_sysconfig, read_bbl_header_text
from .system_id import (
    OpenLoopResponse,
    Sensitivity,
    Spectrogram,
    StepResponse,
    TransferFunction,
    choose_segment_size,
    compute_sensitivity,
    compute_spectrogram,
    compute_step_response,
    open_loop_response,
    transfer_function_to_dict,
    welch_transfer_function,
)

WELCH_OVERLAP = 0.5

UPSTREAM_PROVENANCE: dict[str, Any] = {
    "configurator_commit": "a38c4a797a86a580106162653db92af7e14be787",
    "blackbox_tools_commit": "f832acf9cd9dbe5ad8220de1a5f4eb4021523d72",
    "reference_functions": [
        "chirp_bbl_parser.ts:parseChirpLog",
        "chirp_bbl_parser.ts:validateDebugModeIsChirp",
        "useAutotune.ts:analyzeLog",
        "useAutotune.ts:computeAxisResult",
        "useAutotune.ts:chooseSegmentSize",
        "spectral_analysis.ts:welchTransferFunction",
        "spectral_analysis.ts:computeSensitivity",
        "spectral_analysis.ts:computeStepResponse",
        "spectral_analysis.ts:computeSpectrogram",
        "spectral_analysis.ts:openLoopResponse",
        "fft.ts:ComplexFFT",
    ],
    "not_ported": ["spectral_analysis.ts:recommendGains", "useAutotune.ts:applyGains"],
}


@dataclass(frozen=True)
class ChirpAxisResult:
    axis: int
    segment: ChirpSegment
    sample_rate: SampleRateEvidence
    spacing: TimestampSpacing
    upstream_sample_rate_hz: float
    segment_size: int | None
    overlap: float
    transfer_function: TransferFunction | None
    sensitivity: Sensitivity | None
    step_response: StepResponse | None
    open_loop: OpenLoopResponse | None
    spectrogram: Spectrogram | None
    quality: QualityReport
    warnings: tuple[str, ...] = ()

    @property
    def axis_name(self) -> str:
        return AXIS_NAMES[self.axis]

    @property
    def usable(self) -> bool:
        return self.transfer_function is not None and self.quality.usable

    @property
    def effective_rate_hz(self) -> float | None:
        return self.sample_rate.effective_rate_hz

    def to_dict(self, *, include_arrays: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "axis": self.axis,
            "axis_name": self.axis_name,
            "usable": self.usable,
            "segment": self.segment.to_dict(),
            "effective_rate_hz": self.effective_rate_hz,
            "upstream_autotune_rate_hz": self.upstream_sample_rate_hz,
            "sample_rate": self.sample_rate.to_dict(),
            "timestamp_spacing": self.spacing.to_dict(),
            "segment_size": self.segment_size,
            "overlap": self.overlap,
            "quality": self.quality.to_dict(),
            "warnings": list(self.warnings),
        }
        tf = self.transfer_function
        if tf is not None:
            out["num_segments"] = tf.num_segments
            out["num_bins"] = tf.num_bins
            if include_arrays:
                out["transfer_function"] = transfer_function_to_dict(tf)
                out["usable_mask"] = self.quality.usable_mask.astype(bool).tolist()
        if self.sensitivity is not None:
            out["sensitivity_peak_db"] = self.sensitivity.peak_db
        if self.step_response is not None:
            sr = self.step_response
            out["step_response"] = {
                "overshoot_pct": sr.overshoot_pct,
                "rise_time_ms": sr.rise_time_ms,
                "settling_time_ms": sr.settling_time_ms,
            }
            if include_arrays:
                out["step_response"]["time_ms"] = sr.time_ms.tolist()
                out["step_response"]["response"] = sr.response.tolist()
        return out


@dataclass(frozen=True)
class ChirpSystemIdResult:
    status: str  # "ok" | "usable_with_warnings" | "unusable" | "error"
    sysconfig: ChirpSysConfig | None
    extraction: ChirpExtraction | None
    axes: dict[int, ChirpAxisResult]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return any(a.usable for a in self.axes.values())

    @property
    def detected(self) -> bool:
        return bool(self.extraction and self.extraction.detected)

    def axis(self, axis: int | str) -> ChirpAxisResult | None:
        key = AXIS_NAMES.index(axis) if isinstance(axis, str) else axis
        return self.axes.get(key)

    def to_dict(self, *, include_arrays: bool = True) -> dict[str, Any]:
        return {
            "status": self.status,
            "usable": self.usable,
            "detected": self.detected,
            "analysis_only": True,
            "tuning_recommendations": None,
            "sysconfig": self.sysconfig.to_dict() if self.sysconfig else None,
            "extraction": self.extraction.to_dict() if self.extraction else None,
            "axes": {AXIS_NAMES[a]: r.to_dict(include_arrays=include_arrays) for a, r in sorted(self.axes.items())},
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "provenance": dict(self.provenance),
        }


def _error(code: str, *, sysconfig: ChirpSysConfig | None = None, extraction: ChirpExtraction | None = None, warnings: Sequence[str] = ()) -> ChirpSystemIdResult:
    return ChirpSystemIdResult(
        status="error",
        sysconfig=sysconfig,
        extraction=extraction,
        axes={},
        warnings=tuple(warnings),
        errors=(code,),
        provenance=dict(UPSTREAM_PROVENANCE),
    )


def analyze_chirp_segment(
    extraction: ChirpExtraction,
    segment: ChirpSegment,
    sysconfig: ChirpSysConfig | None,
    *,
    segment_size: int | None = None,
    include_spectrogram: bool = False,
) -> ChirpAxisResult:
    """Resolve rate, gate, and identify H(f) for one extracted segment."""
    x, y, ts = extraction.segment_signals(segment)
    rate_inputs = sysconfig.sample_rate_inputs() if sysconfig else {}
    rate = resolve_chirp_sample_rate(**rate_inputs, timestamps_us=ts)
    spacing = analyze_timestamp_spacing(ts)
    upstream_rate = upstream_autotune_compute_sample_rate_hz(
        sysconfig.upstream_value("looptime") if sysconfig else None,
        sysconfig.upstream_value("pid_process_denom") if sysconfig else None,
        sysconfig.upstream_value("p_interval_denom") if sysconfig else None,
    )
    fs = rate.effective_rate_hz
    seg_size = segment_size or (choose_segment_size(fs) if fs else None)
    gates = pre_analysis_gates(sample_count=segment.sample_count, segment_size=seg_size, rate=rate, spacing=spacing)
    if fs:
        band, band_gates = analysis_band(extraction.frequency_range_hz, fs)
        gates += band_gates
    else:
        band = (0.0, 0.0)

    can_compute = fs is not None and seg_size is not None and segment.sample_count >= seg_size
    tf = sens = step = ol = sg = None
    if can_compute:
        tf = welch_transfer_function(x, y, fs, seg_size, WELCH_OVERLAP)
        sens = compute_sensitivity(tf)
        step = compute_step_response(tf, fs, seg_size)
        ol = open_loop_response(tf)
        if include_spectrogram:
            sg = compute_spectrogram(y, fs)
    report = post_analysis_report(gates=gates, tf=tf, input_signal=x, band_hz=band)
    return ChirpAxisResult(
        axis=segment.axis,
        segment=segment,
        sample_rate=rate,
        spacing=spacing,
        upstream_sample_rate_hz=upstream_rate,
        segment_size=seg_size,
        overlap=WELCH_OVERLAP,
        transfer_function=tf,
        sensitivity=sens,
        step_response=step,
        open_loop=ol,
        spectrogram=sg,
        quality=report,
        warnings=tuple(rate.warnings),
    )


def identify_chirp_system(
    *,
    csv_text: str | None = None,
    frames: ChirpFrames | None = None,
    parsed: Mapping[str, Any] | None = None,
    headers: bytes | str | Mapping[str, Any] | ChirpSysConfig | None = None,
    log_index: int = 0,
    api_version: str | None = None,
    axes: Sequence[int | str] | None = None,
    segment_size: int | None = None,
    include_spectrogram: bool = False,
    require_flight_mode_flags: bool = False,
) -> ChirpSystemIdResult:
    """CHIRP system identification from decoded Blackbox data.

    Exactly one of ``csv_text`` (``blackbox_decode`` CSV, preferred),
    ``frames`` or ``parsed`` (``parse_blackbox_csv`` output) supplies the rows.
    ``headers`` supplies sysConfig: BBL bytes, ``H`` header text,
    Field/Value CSV, a mapping or a :class:`ChirpSysConfig`.
    """
    sources = [s is not None for s in (csv_text, frames, parsed)]
    if sum(sources) != 1:
        raise ValueError("pass exactly one of csv_text, frames, parsed")

    sysconfig: ChirpSysConfig | None
    if headers is None:
        sysconfig = None
    elif isinstance(headers, ChirpSysConfig):
        sysconfig = headers
    else:
        try:
            sysconfig = parse_chirp_sysconfig(headers, log_index=log_index)
        except ValueError as exc:
            return _error(f"invalid_headers:{exc}")
    if sysconfig is not None:
        _, _, err = validate_chirp_debug_mode(sysconfig, api_version)
        if err:
            return _error(err, sysconfig=sysconfig)

    try:
        if csv_text is not None:
            frames = read_chirp_frames_from_csv(csv_text)
        elif parsed is not None:
            frames = chirp_frames_from_parsed_samples(parsed)
    except ChirpFramesError as exc:
        return _error(str(exc), sysconfig=sysconfig)
    assert frames is not None

    extraction = extract_chirp(
        frames, sysconfig, api_version=api_version, require_flight_mode_flags=require_flight_mode_flags
    )
    if extraction.errors:
        return _error(extraction.errors[0], sysconfig=sysconfig, extraction=extraction, warnings=extraction.warnings)
    if not extraction.detected:
        return ChirpSystemIdResult(
            status="unusable",
            sysconfig=sysconfig,
            extraction=extraction,
            axes={},
            warnings=extraction.warnings,
            errors=("no_chirp_segments",),
            provenance=dict(UPSTREAM_PROVENANCE),
        )

    wanted = None
    if axes is not None:
        wanted = {AXIS_NAMES.index(a) if isinstance(a, str) else int(a) for a in axes}
    results: dict[int, ChirpAxisResult] = {}
    for axis, seg_index in sorted(extraction.selected_by_axis.items()):
        if wanted is not None and axis not in wanted:
            continue
        results[axis] = analyze_chirp_segment(
            extraction,
            extraction.segments[seg_index],
            sysconfig,
            segment_size=segment_size,
            include_spectrogram=include_spectrogram,
        )

    warnings = list(extraction.warnings)
    for r in results.values():
        warnings += [f"{r.axis_name}:{w}" for w in r.quality.warnings]
    if not results:
        status = "unusable"
    elif not any(r.usable for r in results.values()):
        status = "unusable"
    elif all(r.usable for r in results.values()) and not any(r.quality.warnings for r in results.values()) and not extraction.warnings:
        status = "ok"
    else:
        status = "usable_with_warnings"
    errors = tuple(f"{r.axis_name}:{code}" for r in results.values() for code in r.quality.failed)
    return ChirpSystemIdResult(
        status=status,
        sysconfig=sysconfig,
        extraction=extraction,
        axes=results,
        warnings=tuple(dict.fromkeys(warnings)),
        errors=errors,
        provenance=dict(UPSTREAM_PROVENANCE),
    )


def identify_chirp_system_from_bbl(
    path: str | Path,
    *,
    log_index: int | None = None,
    config: Any = None,
    **kwargs: Any,
) -> ChirpSystemIdResult:
    """Decode a BBL with GyroCore's ``decode_bbl`` and run :func:`identify_chirp_system`."""
    from gyrocore.decode import decode_bbl

    result = decode_bbl(path, log_index=log_index, config=config)
    index = result.decoded_embedded_log_index or 0
    headers = read_bbl_header_text(Path(path).read_bytes(), index)
    return identify_chirp_system(csv_text=result.csv_text, headers=headers, log_index=index, **kwargs)


__all__ = [
    "ChirpAxisResult",
    "ChirpSystemIdResult",
    "UPSTREAM_PROVENANCE",
    "WELCH_OVERLAP",
    "analyze_chirp_segment",
    "identify_chirp_system",
    "identify_chirp_system_from_bbl",
]
