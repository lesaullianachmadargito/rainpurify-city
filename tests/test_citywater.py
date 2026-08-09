import pytest

from citywater.fleet import (
    NodeStatus,
    NodeWindow,
    ScreeningRules,
    aggregate,
    by_district,
    screen,
)
from citywater.stormwater import (
    DesignStorm,
    HarvestingScheme,
    UrbanCatchment,
    attenuate,
    supply_offset,
)


def district(roof_share: float = 0.30) -> UrbanCatchment:
    return UrbanCatchment("Test", 500.0, 500.0 * roof_share)


def storm() -> DesignStorm:
    return DesignStorm(90.0, 60, 5)


# -- stormwater -------------------------------------------------------------


def test_rational_method_matches_the_formula():
    # 0.75 x 90 mm/h x 500 ha / 360
    assert district().peak_flow_m3s(storm()) == pytest.approx(93.75)


def test_storm_depth_is_intensity_times_duration():
    assert DesignStorm(60.0, 30).depth_mm == pytest.approx(30.0)


def test_no_harvesting_changes_nothing():
    result = attenuate(district(), storm(), HarvestingScheme(0.0, 40.0))
    assert result.peak_reduction == pytest.approx(0.0)
    assert result.captured_m3 == 0.0


def test_capture_is_bounded_by_fitted_roofs_not_all_roofs():
    """The modelling bug this was fixed for.

    Enormous storage on a quarter of the roofs still cannot hold water from
    the other three quarters.
    """
    huge = HarvestingScheme(adoption=0.25, tank_l_per_m2_roof=100_000,
                            available_fraction=1.0)
    result = attenuate(district(), storm(), huge)
    fitted_volume = result.roof_volume_m3 * 0.25
    assert result.captured_m3 == pytest.approx(fitted_volume)
    assert result.captured_m3 < result.roof_volume_m3


def test_full_adoption_and_unlimited_storage_removes_the_roof_contribution():
    everything = HarvestingScheme(1.0, 100_000, 1.0)
    result = attenuate(district(), storm(), everything)
    # Only the non-roof surfaces still contribute.
    assert result.peak_after_m3s < result.peak_before_m3s
    assert result.peak_reduction == pytest.approx(0.34, abs=0.02)


def test_keeping_tanks_empty_buys_more_attenuation():
    half = attenuate(district(), storm(), HarvestingScheme(0.5, 40, 0.5))
    empty = attenuate(district(), storm(), HarvestingScheme(0.5, 40, 0.95))
    assert empty.peak_reduction > half.peak_reduction


def test_a_design_storm_overwhelms_realistic_storage():
    """The finding: rooftop tanks barely dent a design-storm peak."""
    result = attenuate(district(), storm(), HarvestingScheme(0.8, 40, 0.95))
    assert result.storage_filled
    assert result.peak_reduction < 0.2


def test_spilled_volume_is_what_did_not_fit():
    result = attenuate(district(), storm(), HarvestingScheme(0.25, 40, 0.5))
    assert result.spilled_m3 == pytest.approx(
        result.roof_volume_m3 - result.captured_m3
    )


def test_supply_offset_falls_when_losses_are_counted():
    scheme = HarvestingScheme(0.25, 40)
    generous = supply_offset(district(), 2000, scheme, 130, 60_000,
                             usable_fraction=1.0)
    realistic = supply_offset(district(), 2000, scheme, 130, 60_000,
                              usable_fraction=0.6)
    assert realistic["offset"] < generous["offset"]
    assert realistic["usable_harvest_m3"] < realistic["gross_harvest_m3"]


def test_supply_beats_attenuation_at_realistic_adoption():
    scheme = HarvestingScheme(0.25, 40, 0.5)
    offset = supply_offset(district(), 2000, scheme, 130, 60_000)["offset"]
    reduction = attenuate(district(), storm(), scheme).peak_reduction
    assert offset > reduction * 1.5


@pytest.mark.parametrize(
    "kwargs",
    [{"area_ha": 0}, {"roof_area_ha": 900}, {"runoff_coefficient": 0},
     {"runoff_coefficient": 1.4}],
)
def test_impossible_catchments_are_rejected(kwargs):
    base = {"name": "x", "area_ha": 500.0, "roof_area_ha": 150.0}
    with pytest.raises(ValueError):
        UrbanCatchment(**{**base, **kwargs})


@pytest.mark.parametrize(
    "kwargs", [{"adoption": 1.5}, {"tank_l_per_m2_roof": 0},
               {"available_fraction": -0.1}]
)
def test_impossible_schemes_are_rejected(kwargs):
    base = {"adoption": 0.5, "tank_l_per_m2_roof": 40.0}
    with pytest.raises(ValueError):
        HarvestingScheme(**{**base, **kwargs})


# -- fleet ------------------------------------------------------------------


def healthy(node_id: str = "RP-001") -> NodeWindow:
    return NodeWindow(node_id, tuple(1.0 + 0.1 * (k % 4) for k in range(12)))


def test_a_healthy_node_passes():
    assert screen(healthy()).status is NodeStatus.OK


def test_a_stuck_sensor_is_caught_although_its_value_is_plausible():
    stuck = NodeWindow("RP-013", tuple([2.40] * 12))
    verdict = screen(stuck)
    assert verdict.status is NodeStatus.STUCK
    assert "not moving" in verdict.reason


def test_a_sensor_stuck_at_zero_is_also_caught():
    assert screen(NodeWindow("RP-014", tuple([0.0] * 12))).status is NodeStatus.STUCK


def test_a_disconnected_probe_at_the_rail_is_caught():
    assert screen(NodeWindow("RP-015", tuple([880.0] * 12))).status is (
        NodeStatus.OUT_OF_RANGE
    )


def test_a_node_with_too_few_readings_is_excluded():
    assert screen(NodeWindow("RP-016", (1.9, 2.1))).status is NodeStatus.TOO_FEW


def test_a_silent_node_is_offline():
    assert screen(NodeWindow("RP-017", ())).status is NodeStatus.OFFLINE


def test_a_few_bad_readings_do_not_condemn_a_node():
    mostly_fine = NodeWindow("RP-018", tuple([1.0, 1.2, 1.4, 1.1] * 3 + [900.0]))
    assert screen(mostly_fine).status is NodeStatus.OK


def test_screening_thresholds_are_configurable():
    borderline = NodeWindow("RP-019", tuple(2.0 + 0.001 * (k % 3) for k in range(12)))
    assert screen(borderline).status is NodeStatus.STUCK
    lenient = ScreeningRules(min_stddev_ntu=0.0)
    assert screen(borderline, lenient).status is NodeStatus.OK


def test_stuck_nodes_are_kept_out_of_the_aggregate():
    windows = [healthy(f"RP-{i:03d}") for i in range(1, 6)]
    windows.append(NodeWindow("RP-099", tuple([50.0] * 12)))

    summary = aggregate(windows)
    assert summary.included == 5
    assert "RP-099" in summary.excluded[NodeStatus.STUCK]
    assert summary.median_ntu < 2.0


def test_the_unscreened_mean_is_what_screening_prevents():
    windows = [healthy(f"RP-{i:03d}") for i in range(1, 6)]
    windows.append(NodeWindow("RP-099", tuple([50.0] * 12)))

    naive = [v for w in windows for v in w.turbidity_ntu]
    naive_mean = sum(naive) / len(naive)

    assert naive_mean > 8.0
    assert aggregate(windows).mean_ntu < 2.0


def test_exclusions_are_always_reported():
    summary = aggregate([healthy("a"), NodeWindow("b", ())])
    assert "excluded" in summary.report()
    assert "b" in summary.report()


def test_a_mostly_broken_fleet_is_not_trustworthy():
    windows = [healthy("a")] + [NodeWindow(f"x{i}", ()) for i in range(9)]
    summary = aggregate(windows)
    assert not summary.trustworthy
    assert "Do not publish" in summary.report()


def test_a_healthy_fleet_is_trustworthy():
    summary = aggregate([healthy(f"RP-{i:03d}") for i in range(1, 9)])
    assert summary.trustworthy


def test_worst_node_is_identified():
    windows = [healthy(f"RP-{i:03d}") for i in range(1, 5)]
    windows.append(NodeWindow("RP-BAD", tuple(20.0 + 0.1 * (k % 3) for k in range(12))))
    node, value = aggregate(windows).worst_node
    assert node == "RP-BAD"
    assert value > 19


def test_districts_are_screened_independently():
    windows = [
        NodeWindow("a", healthy().turbidity_ntu, "north"),
        NodeWindow("b", healthy().turbidity_ntu, "north"),
        NodeWindow("c", (), "south"),
    ]
    result = by_district(windows)
    assert result["north"].included == 2
    assert result["south"].included == 0


def test_an_empty_fleet_reports_nothing_rather_than_crashing():
    summary = aggregate([])
    assert summary.median_ntu is None
    assert not summary.trustworthy
