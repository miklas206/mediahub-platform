"""Opt-in torrent cleanup thresholds; never clean incomplete downloads."""

import math
from typing import Literal

from pydantic import Field

from mediahub.contracts import StrictModel


class RetentionRule(StrictModel):
    mode: Literal["disabled", "time", "ratio", "both", "either"] = "disabled"
    seedHours: int = Field(default=48, ge=1, le=8760)
    uploadRatio: float = Field(default=2, ge=0.1, le=100, allow_inf_nan=False)
    action: Literal["remove_job", "delete_files"] = "remove_job"


def reached(rule: RetentionRule, torrent: dict) -> bool:
    if rule.mode == "disabled":
        return False
    try:
        progress = float(torrent["progress"])
        size = int(torrent["size"])
        uploaded = int(torrent["uploaded"])
        seconds = int(torrent["seeding_time"])
        if not math.isfinite(progress) or progress < 1 or size <= 0 or uploaded < 0 or seconds < 0:
            return False
    except (KeyError, ValueError, TypeError, OverflowError):
        return False
    time_met = seconds >= rule.seedHours * 3600
    ratio_met = uploaded >= size * rule.uploadRatio
    return {
        "time": time_met,
        "ratio": ratio_met,
        "both": time_met and ratio_met,
        "either": time_met or ratio_met,
    }[rule.mode]
