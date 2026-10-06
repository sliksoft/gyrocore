"""GyroCore global-slider merge for Autotune per-axis proposals.

This is **not** Betaflight behaviour. Upstream Configurator Autotune:

- computes ``recommendGains`` independently per CHIRP axis
- the UI lets the user pick **one** axis
- ``onApply`` / ``applyGains`` writes that axis' full proposed slider set
  via ``MSP_SET_SIMPLIFIED_TUNING`` (sliders are global)
- it does not merge roll/pitch/yaw
- it does not touch ``simplified_pitch_pi_gain``, ``simplified_pitch_d_gain``
  (roll_pitch_ratio), ``simplified_d_max_gain``, or gyro-filter sliders

GyroCore keeps every per-axis WU8 proposal and only auto-resolves a global
set when that is unambiguous. Conflicts return ``MERGE_REQUIRES_REVIEW``.

Policy: ``docs/upstream/AUTOTUNE_GLOBAL_SLIDER_POLICY.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from gyrocore.autotune.engine import AxisRecommendation
from gyrocore.autotune.recommend import SLIDER_KEYS
from gyrocore.betaflight.simplified_tuning import SimplifiedSliders

POLICY_ID = "gyrocore.autotune.global_slider.merge.v1"
POLICY_KIND = "gyrocore"  # never "betaflight"
MERGE_REQUIRES_REVIEW = "MERGE_REQUIRES_REVIEW"

# Autotune proposed keys that firmware simplified sliders understand.
AUTOTUNE_TO_SLIDER = {
    "slider_master_multiplier": "master_multiplier",
    "slider_pi_gain": "pi_gain",
    "slider_i_gain": "i_gain",
    "slider_d_gain": "d_gain",
    "slider_feedforward_gain": "feedforward_gain",
    "slider_dterm_filter_multiplier": "dterm_filter_multiplier",
}

# Firmware sliders Autotune never proposes — current values are retained.
UNTOUCHED_BY_AUTOTUNE = (
    "d_max_gain",
    "pitch_d_gain",
    "pitch_pi_gain",
    "gyro_filter",
    "gyro_filter_multiplier",
    "dterm_filter",
    "pids_mode",
)


@dataclass(frozen=True)
class SliderMergeField:
    key: str
    values_by_axis: dict[str, int]
    agreed: bool
    chosen: int | None
    constrained_by: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GlobalSliderMerge:
    """Result of the GyroCore merge. ``status`` is ``merged`` or MERGE_REQUIRES_REVIEW."""

    status: str
    policy_id: str = POLICY_ID
    policy_kind: str = POLICY_KIND
    participating_axes: tuple[str, ...] = ()
    fields: dict[str, SliderMergeField] = field(default_factory=dict)
    proposed_sliders: dict[str, int] | None = None  # Autotune key space
    simplified: SimplifiedSliders | None = None
    review_reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "policy_id": self.policy_id,
            "policy_kind": self.policy_kind,
            "upstream_or_gyrocore": "gyrocore",
            "participating_axes": list(self.participating_axes),
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "proposed_sliders": self.proposed_sliders,
            "simplified": self.simplified.to_dict() if self.simplified else None,
            "review_reasons": list(self.review_reasons),
            "notes": list(self.notes),
        }


def _axis_proposals(axes: Mapping[int, AxisRecommendation]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for rec in axes.values():
        if rec.blocked or rec.proposed_sliders_unvalidated is None:
            continue
        out[rec.axis_name] = dict(rec.proposed_sliders_unvalidated)
    return out


def merge_autotune_sliders(
    axes: Mapping[int, AxisRecommendation],
    current: SimplifiedSliders,
) -> GlobalSliderMerge:
    """Resolve per-axis Autotune slider integers into one global set, or review."""
    proposals = _axis_proposals(axes)
    notes = [
        "GyroCore merge; upstream Autotune applies one selected axis with no merge.",
        "Autotune does not propose d_max / pitch_pi / pitch_d / gyro-filter sliders; those stay at current.",
    ]
    if not proposals:
        return GlobalSliderMerge(
            status=MERGE_REQUIRES_REVIEW,
            review_reasons=("no_participating_axes",),
            notes=tuple(notes),
        )

    names = tuple(sorted(proposals, key=["roll", "pitch", "yaw"].index))
    fields: dict[str, SliderMergeField] = {}
    disagreements: list[str] = []
    chosen_autotune: dict[str, int] = {}

    for autotune_key, _py in SLIDER_KEYS:
        values = {axis: int(proposals[axis][autotune_key]) for axis in names}
        unique = tuple(sorted(set(values.values())))
        if len(unique) == 1:
            fields[autotune_key] = SliderMergeField(
                autotune_key, values, True, unique[0], names, "unanimous" if len(names) > 1 else "single_axis_matches_upstream_apply"
            )
            chosen_autotune[autotune_key] = unique[0]
        else:
            fields[autotune_key] = SliderMergeField(
                autotune_key, values, False, None, (), MERGE_REQUIRES_REVIEW
            )
            disagreements.append(autotune_key)

    if disagreements:
        return GlobalSliderMerge(
            status=MERGE_REQUIRES_REVIEW,
            participating_axes=names,
            fields=fields,
            review_reasons=tuple(f"slider_disagreement:{k}" for k in disagreements),
            notes=tuple(notes),
        )

    merged = SimplifiedSliders(
        pids_mode=current.pids_mode,
        master_multiplier=chosen_autotune["slider_master_multiplier"],
        i_gain=chosen_autotune["slider_i_gain"],
        d_gain=chosen_autotune["slider_d_gain"],
        pi_gain=chosen_autotune["slider_pi_gain"],
        d_max_gain=current.d_max_gain,
        feedforward_gain=chosen_autotune["slider_feedforward_gain"],
        pitch_d_gain=current.pitch_d_gain,
        pitch_pi_gain=current.pitch_pi_gain,
        dterm_filter=current.dterm_filter,
        dterm_filter_multiplier=chosen_autotune["slider_dterm_filter_multiplier"],
        gyro_filter=current.gyro_filter,
        gyro_filter_multiplier=current.gyro_filter_multiplier,
    )
    return GlobalSliderMerge(
        status="merged",
        participating_axes=names,
        fields=fields,
        proposed_sliders=chosen_autotune,
        simplified=merged,
        notes=tuple(notes),
    )


__all__ = [
    "AUTOTUNE_TO_SLIDER",
    "GlobalSliderMerge",
    "MERGE_REQUIRES_REVIEW",
    "POLICY_ID",
    "POLICY_KIND",
    "SliderMergeField",
    "UNTOUCHED_BY_AUTOTUNE",
    "merge_autotune_sliders",
]
