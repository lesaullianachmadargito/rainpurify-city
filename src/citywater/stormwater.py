"""Rooftop harvesting as drainage infrastructure.

A rainwater tank is usually argued for as a water supply. In a city its larger
effect is often on the other side of the ledger: every litre held on a roof is a
litre that did not arrive at the drain during the storm peak.

That distinction matters because the two benefits are sized by different things.
Water supply depends on the **annual total** a tank can capture. Peak
attenuation depends on how much empty space the tank happens to have **at the
moment the storm starts** — which is a very different, and much less flattering,
question.

The rational method is used here:

    Q = C x i x A / 360        Q in m3/s, i in mm/h, A in hectares

It is crude. It assumes uniform rainfall over the catchment and a single runoff
coefficient, and it says nothing about routing. It is also what municipal
drainage in Indonesia is dimensioned with, so a claim expressed in its terms is
a claim a drainage engineer can check.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignStorm:
    """A storm of a given intensity and duration.

    `return_period_years` is carried for reporting only — the model does not
    derive intensity from it. Deriving intensity needs local IDF curves, and
    inventing them would be worse than requiring the number.
    """

    intensity_mm_h: float
    duration_min: int
    return_period_years: int | None = None

    def __post_init__(self) -> None:
        if self.intensity_mm_h <= 0:
            raise ValueError("rainfall intensity must be positive")
        if self.duration_min <= 0:
            raise ValueError("storm duration must be positive")

    @property
    def depth_mm(self) -> float:
        return self.intensity_mm_h * self.duration_min / 60.0


@dataclass(frozen=True)
class UrbanCatchment:
    """A district, described the way a drainage study describes one."""

    name: str
    area_ha: float
    roof_area_ha: float
    runoff_coefficient: float = 0.75   # mixed urban surface
    roof_runoff_coefficient: float = 0.85

    def __post_init__(self) -> None:
        if self.area_ha <= 0:
            raise ValueError("catchment area must be positive")
        if not 0 <= self.roof_area_ha <= self.area_ha:
            raise ValueError("roof area must fit inside the catchment")
        for c in (self.runoff_coefficient, self.roof_runoff_coefficient):
            if not 0 < c <= 1:
                raise ValueError("runoff coefficients must be in (0, 1]")

    @property
    def roof_share(self) -> float:
        return self.roof_area_ha / self.area_ha

    def peak_flow_m3s(self, storm: DesignStorm) -> float:
        """Rational-method peak, with no harvesting."""
        return self.runoff_coefficient * storm.intensity_mm_h * self.area_ha / 360.0

    def roof_volume_m3(self, storm: DesignStorm) -> float:
        """Total volume landing on roofs during the storm."""
        return (
            storm.depth_mm
            * self.roof_area_ha
            * 10_000.0
            / 1000.0
            * self.roof_runoff_coefficient
        )


@dataclass(frozen=True)
class HarvestingScheme:
    """Tanks fitted to some share of the roofs."""

    adoption: float              # share of roof area fitted
    tank_l_per_m2_roof: float    # storage per square metre served
    available_fraction: float = 0.5  # share of that storage empty when it rains

    def __post_init__(self) -> None:
        if not 0 <= self.adoption <= 1:
            raise ValueError("adoption must be a fraction")
        if self.tank_l_per_m2_roof <= 0:
            raise ValueError("storage must be positive")
        if not 0 <= self.available_fraction <= 1:
            raise ValueError("available fraction must be a fraction")

    def storage_m3(self, catchment: UrbanCatchment) -> float:
        """Storage actually free to accept runoff when the storm begins.

        `available_fraction` is the whole argument. A tank kept full for supply
        security attenuates nothing; a tank kept empty for flood control
        supplies nothing. Halfway is the usual compromise and it halves the
        drainage benefit — which is exactly the trade a city has to decide
        deliberately rather than discover afterwards.
        """
        roof_m2 = catchment.roof_area_ha * 10_000.0 * self.adoption
        return roof_m2 * self.tank_l_per_m2_roof / 1000.0 * self.available_fraction


@dataclass(frozen=True)
class AttenuationResult:
    catchment: str
    peak_before_m3s: float
    peak_after_m3s: float
    roof_volume_m3: float
    storage_m3: float
    captured_m3: float
    storage_filled: bool

    @property
    def peak_reduction(self) -> float:
        if self.peak_before_m3s <= 0:
            return 0.0
        return 1.0 - self.peak_after_m3s / self.peak_before_m3s

    @property
    def spilled_m3(self) -> float:
        return max(0.0, self.roof_volume_m3 - self.captured_m3)


def attenuate(
    catchment: UrbanCatchment, storm: DesignStorm, scheme: HarvestingScheme
) -> AttenuationResult:
    """Peak flow with and without harvesting.

    The roof contribution to the peak is reduced in proportion to how much of
    the roof volume the tanks could actually hold. Once tanks fill they pass
    everything, and a storm long enough to fill them delivers its later — often
    most intense — minutes straight to the drain. That is why the result
    reports `storage_filled` rather than only a percentage.
    """
    roof_volume = catchment.roof_volume_m3(storm)
    storage = scheme.storage_m3(catchment)

    # Capture is bounded by the volume landing on **fitted** roofs, not on all
    # of them. Tanks on a quarter of the roofs cannot hold water from the other
    # three quarters, and comparing storage against the whole catchment's roof
    # volume silently credits them with doing so.
    fitted_volume = roof_volume * scheme.adoption
    captured = min(fitted_volume, storage)

    roof_peak = (
        catchment.roof_runoff_coefficient
        * storm.intensity_mm_h
        * catchment.roof_area_ha
        / 360.0
    )
    other_peak = catchment.peak_flow_m3s(storm) - roof_peak

    retained_share = captured / roof_volume if roof_volume > 0 else 0.0
    peak_after = other_peak + roof_peak * (1.0 - retained_share)

    return AttenuationResult(
        catchment=catchment.name,
        peak_before_m3s=catchment.peak_flow_m3s(storm),
        peak_after_m3s=peak_after,
        roof_volume_m3=roof_volume,
        storage_m3=storage,
        captured_m3=captured,
        storage_filled=captured >= storage - 1e-9 and fitted_volume > storage,
    )


def supply_offset(
    catchment: UrbanCatchment,
    annual_rainfall_mm: float,
    scheme: HarvestingScheme,
    demand_l_per_capita_day: float,
    population: int,
    *,
    usable_fraction: float = 0.6,
) -> dict[str, float]:
    """The water-supply side, for comparison against the drainage side.

    `usable_fraction` accounts for what a real system loses: first flush,
    overflow in the wet season when tanks are already full, and dry-season
    months when there is nothing to collect. Assuming a tank captures every
    millimetre that lands on the roof is the error that makes rooftop
    harvesting look like a municipal water solution.
    """
    if not 0 < usable_fraction <= 1:
        raise ValueError("usable fraction must be in (0, 1]")

    roof_m2 = catchment.roof_area_ha * 10_000.0 * scheme.adoption
    gross_m3 = (
        annual_rainfall_mm / 1000.0 * roof_m2 * catchment.roof_runoff_coefficient
    )
    usable_m3 = gross_m3 * usable_fraction

    demand_m3 = demand_l_per_capita_day * population * 365 / 1000.0

    return {
        "gross_harvest_m3": gross_m3,
        "usable_harvest_m3": usable_m3,
        "annual_demand_m3": demand_m3,
        "offset": usable_m3 / demand_m3 if demand_m3 else 0.0,
    }
