"""Aggregating a fleet of units without letting the broken ones speak.

A city dashboard showing "average turbidity across 240 units: 2.1 NTU" is a
number produced by whichever sensors happened to report. Some of those sensors
are stuck, some are drifting, and a few are reading a disconnected probe at the
rail. None of them announce it.

The failure that matters most is the quiet one. **A stuck sensor reports a
perfectly plausible constant.** It passes every range check, it never goes
missing, and it drags the fleet mean toward whatever value it froze at — for
weeks. The only thing that gives it away is that it does not move.

So aggregation here does three things in order:

1. screen every node and record why each excluded one was excluded,
2. aggregate only the survivors,
3. report the exclusion count alongside the result, always.

Step three is the one that gets dropped in practice, and dropping it turns a
degrading fleet into a dashboard that looks fine right up until it doesn't.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import Enum


class NodeStatus(str, Enum):
    OK = "ok"
    OFFLINE = "offline"              # no readings at all
    STUCK = "stuck"                  # readings never change
    OUT_OF_RANGE = "out_of_range"    # physically impossible values
    TOO_FEW = "too_few_readings"


@dataclass(frozen=True)
class NodeWindow:
    """One unit's readings over a reporting window."""

    node_id: str
    turbidity_ntu: tuple[float, ...]
    district: str = "unknown"

    @property
    def count(self) -> int:
        return len(self.turbidity_ntu)


@dataclass(frozen=True)
class ScreeningRules:
    min_readings: int = 6
    valid_low_ntu: float = 0.0
    valid_high_ntu: float = 300.0

    # A working turbidity sensor on a working unit never returns the same
    # value all window. Even clean water wanders by a few hundredths.
    min_stddev_ntu: float = 0.02

    # Share of a node's readings allowed outside the valid range before the
    # node itself is rejected rather than just those readings.
    max_out_of_range_share: float = 0.2


@dataclass
class NodeVerdict:
    node_id: str
    status: NodeStatus
    reason: str = ""
    usable: tuple[float, ...] = ()


def screen(window: NodeWindow, rules: ScreeningRules | None = None) -> NodeVerdict:
    rules = rules or ScreeningRules()

    if window.count == 0:
        return NodeVerdict(window.node_id, NodeStatus.OFFLINE, "no readings")

    in_range = tuple(
        v for v in window.turbidity_ntu
        if rules.valid_low_ntu <= v <= rules.valid_high_ntu
    )
    out_share = 1.0 - len(in_range) / window.count

    if out_share > rules.max_out_of_range_share:
        return NodeVerdict(
            window.node_id, NodeStatus.OUT_OF_RANGE,
            f"{out_share:.0%} of readings outside "
            f"{rules.valid_low_ntu:g}-{rules.valid_high_ntu:g} NTU",
        )

    if len(in_range) < rules.min_readings:
        return NodeVerdict(
            window.node_id, NodeStatus.TOO_FEW,
            f"{len(in_range)} usable readings, need {rules.min_readings}",
        )

    spread = statistics.pstdev(in_range)
    if spread < rules.min_stddev_ntu:
        return NodeVerdict(
            window.node_id, NodeStatus.STUCK,
            f"readings vary by {spread:.4f} NTU — the sensor is not moving",
        )

    return NodeVerdict(window.node_id, NodeStatus.OK, usable=in_range)


@dataclass
class FleetSummary:
    total_nodes: int
    included: int = 0
    excluded: dict[NodeStatus, list[str]] = field(default_factory=dict)
    readings: int = 0

    median_ntu: float | None = None
    mean_ntu: float | None = None
    p90_ntu: float | None = None
    worst_node: tuple[str, float] | None = None

    @property
    def exclusion_rate(self) -> float:
        return 1 - self.included / self.total_nodes if self.total_nodes else 0.0

    @property
    def trustworthy(self) -> bool:
        """Whether the aggregate is worth showing at all."""
        return self.included >= 3 and self.exclusion_rate <= 0.4

    def report(self) -> str:
        lines = [
            f"{self.included} of {self.total_nodes} units included "
            f"({self.exclusion_rate:.0%} excluded)"
        ]
        if self.median_ntu is not None:
            lines.append(f"  median  {self.median_ntu:.2f} NTU")
            lines.append(f"  mean    {self.mean_ntu:.2f} NTU")
            lines.append(f"  p90     {self.p90_ntu:.2f} NTU")
        if self.worst_node:
            node, value = self.worst_node
            lines.append(f"  worst unit {node} at {value:.2f} NTU")

        for status, nodes in self.excluded.items():
            if nodes:
                lines.append(f"  {status.value:<16}{len(nodes):>4}  "
                             f"{', '.join(nodes[:6])}"
                             f"{' …' if len(nodes) > 6 else ''}")

        if not self.trustworthy:
            lines.append("")
            lines.append("  ! Too few units survived screening. Do not publish")
            lines.append("  ! this aggregate — fix the fleet first.")
        return "\n".join(lines)


def aggregate(
    windows: list[NodeWindow], rules: ScreeningRules | None = None
) -> FleetSummary:
    summary = FleetSummary(total_nodes=len(windows))
    summary.excluded = {status: [] for status in NodeStatus if status is not NodeStatus.OK}

    pooled: list[float] = []
    per_node_median: list[tuple[str, float]] = []

    for window in windows:
        verdict = screen(window, rules)
        if verdict.status is not NodeStatus.OK:
            summary.excluded[verdict.status].append(verdict.node_id)
            continue

        summary.included += 1
        summary.readings += len(verdict.usable)
        pooled.extend(verdict.usable)
        per_node_median.append(
            (verdict.node_id, statistics.median(verdict.usable))
        )

    if not pooled:
        return summary

    ordered = sorted(pooled)
    summary.median_ntu = statistics.median(ordered)
    summary.mean_ntu = statistics.fmean(ordered)
    summary.p90_ntu = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
    summary.worst_node = max(per_node_median, key=lambda kv: kv[1])
    return summary


def by_district(
    windows: list[NodeWindow], rules: ScreeningRules | None = None
) -> dict[str, FleetSummary]:
    districts: dict[str, list[NodeWindow]] = {}
    for window in windows:
        districts.setdefault(window.district, []).append(window)
    return {
        name: aggregate(group, rules)
        for name, group in sorted(districts.items())
    }
