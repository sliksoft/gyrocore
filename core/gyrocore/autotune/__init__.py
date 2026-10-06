"""Betaflight Autotune recommendation engine (WU8) — recommendations only.

Port of Betaflight Configurator ``recommendGains`` (``spectral_analysis.ts``)
on top of the WU7 CHIRP system identification (:mod:`gyrocore.chirp`).

Output is an :class:`AutotuneRecommendationResult` with ``actionable == False``.
Nothing in this package writes MSP, emits CLI or applies a tune; results must
still pass mechanical safety, safe-tune clamps and ``tuning_output_safety``.
"""

from .current_tune import (
    AXES,
    SIMPLIFIED_PIDS_MODES,
    SLIDER_HEADER_KEYS,
    UPSTREAM_SLIDER_DEFAULT,
    CurrentTune,
    TuneValue,
    ValueSource,
    current_tune_from_sliders,
    extract_current_tune,
)
from .engine import (
    NON_ACTIONABLE_NOTICE,
    RECOMMENDATION_KIND,
    REQUIRED_DOWNSTREAM_STAGES,
    UPSTREAM_PROVENANCE,
    AutotuneRecommendationResult,
    AxisRecommendation,
    RecommendationStatus,
    recommend_autotune_from_bbl,
    recommend_from_system_id,
)
from .recommend import (
    GAIN_SCALE_MAX,
    GAIN_SCALE_MIN,
    MAX_SENSITIVITY_PEAK,
    PHASE_MARGIN_PRESETS,
    SLIDER_KEYS,
    SLIDER_MAX,
    SLIDER_MIN,
    CurrentSliders,
    GainMetrics,
    GainRecommendation,
    GainScales,
    SliderProposal,
    build_gains,
    recommend_gains,
)

__all__ = [
    "AXES",
    "AutotuneRecommendationResult",
    "AxisRecommendation",
    "CurrentSliders",
    "CurrentTune",
    "GAIN_SCALE_MAX",
    "GAIN_SCALE_MIN",
    "GainMetrics",
    "GainRecommendation",
    "GainScales",
    "MAX_SENSITIVITY_PEAK",
    "NON_ACTIONABLE_NOTICE",
    "PHASE_MARGIN_PRESETS",
    "RECOMMENDATION_KIND",
    "REQUIRED_DOWNSTREAM_STAGES",
    "RecommendationStatus",
    "SIMPLIFIED_PIDS_MODES",
    "SLIDER_HEADER_KEYS",
    "SLIDER_KEYS",
    "SLIDER_MAX",
    "SLIDER_MIN",
    "SliderProposal",
    "TuneValue",
    "UPSTREAM_PROVENANCE",
    "UPSTREAM_SLIDER_DEFAULT",
    "ValueSource",
    "build_gains",
    "current_tune_from_sliders",
    "extract_current_tune",
    "recommend_autotune_from_bbl",
    "recommend_from_system_id",
    "recommend_gains",
]
