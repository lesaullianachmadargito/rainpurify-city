"""City-scale rainwater harvesting: drainage effect and fleet telemetry."""

from .fleet import FleetSummary, NodeStatus, NodeWindow, aggregate, by_district, screen
from .stormwater import (
    AttenuationResult,
    DesignStorm,
    HarvestingScheme,
    UrbanCatchment,
    attenuate,
    supply_offset,
)

__version__ = "0.1.0"

__all__ = [
    "AttenuationResult",
    "DesignStorm",
    "FleetSummary",
    "HarvestingScheme",
    "NodeStatus",
    "NodeWindow",
    "UrbanCatchment",
    "aggregate",
    "attenuate",
    "by_district",
    "screen",
    "supply_offset",
]
