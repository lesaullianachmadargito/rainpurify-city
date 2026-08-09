"""Command line.

    python -m citywater storm --roof-share 0.30 --adoption 0.25
    python -m citywater storm --available 0.9   # tanks kept empty for flood control
    python -m citywater supply --roof-share 0.30 --adoption 0.25
    python -m citywater fleet --demo
"""

from __future__ import annotations

import argparse
import sys

from .fleet import NodeWindow, aggregate, by_district
from .stormwater import (
    DesignStorm,
    HarvestingScheme,
    UrbanCatchment,
    attenuate,
    supply_offset,
)


def build_catchment(args) -> UrbanCatchment:
    return UrbanCatchment(
        name=args.name,
        area_ha=args.area,
        roof_area_ha=args.area * args.roof_share,
        runoff_coefficient=args.runoff,
    )


def cmd_storm(args) -> int:
    catchment = build_catchment(args)
    storm = DesignStorm(args.intensity, args.duration, args.return_period)
    scheme = HarvestingScheme(args.adoption, args.tank_per_m2, args.available)

    result = attenuate(catchment, storm, scheme)

    print(f"{catchment.name}: {catchment.area_ha:.0f} ha, "
          f"{catchment.roof_share:.0%} roof")
    print(f"Storm: {storm.intensity_mm_h:.0f} mm/h for {storm.duration_min} min "
          f"= {storm.depth_mm:.0f} mm"
          + (f", {storm.return_period_years}-year" if storm.return_period_years else ""))
    print(f"Scheme: {scheme.adoption:.0%} of roofs, "
          f"{scheme.tank_l_per_m2_roof:.0f} L/m2, "
          f"{scheme.available_fraction:.0%} empty at storm start")
    print()
    print(f"  Peak flow before   {result.peak_before_m3s:>8.2f} m3/s")
    print(f"  Peak flow after    {result.peak_after_m3s:>8.2f} m3/s")
    print(f"  Reduction          {result.peak_reduction:>8.1%}")
    print()
    print(f"  Roof volume        {result.roof_volume_m3:>8.0f} m3")
    print(f"  Storage available  {result.storage_m3:>8.0f} m3")
    print(f"  Captured           {result.captured_m3:>8.0f} m3")
    print(f"  To the drain       {result.spilled_m3:>8.0f} m3")

    if result.storage_filled:
        print("\n  ! Tanks filled before the storm ended. Everything after that")
        print("  ! point went straight to the drain — including the most")
        print("  ! intense minutes, which usually come mid-storm.")

    return 0


def cmd_supply(args) -> int:
    catchment = build_catchment(args)
    scheme = HarvestingScheme(args.adoption, args.tank_per_m2, args.available)

    result = supply_offset(
        catchment, args.annual_rainfall, scheme,
        args.demand_per_capita, args.population,
    )

    print(f"{catchment.name}: {args.population:,} people, "
          f"{args.demand_per_capita:.0f} L/capita/day")
    print(f"  Annual demand      {result['annual_demand_m3']:>12,.0f} m3")
    print(f"  Gross harvest      {result['gross_harvest_m3']:>12,.0f} m3")
    print(f"  Usable harvest     {result['usable_harvest_m3']:>12,.0f} m3")
    print(f"  Demand offset      {result['offset']:>12.1%}")

    storm = DesignStorm(args.intensity, args.duration, args.return_period)
    attenuation = attenuate(catchment, storm, scheme)

    print()
    print("Against the same scheme's drainage effect:")
    print(f"  Peak flow reduction{attenuation.peak_reduction:>12.1%}")
    print()
    if attenuation.peak_reduction > result["offset"] * 1.5:
        print("  The flood benefit is the larger one here. A scheme sold as")
        print("  municipal water supply will disappoint; the same scheme sold")
        print("  as distributed drainage capacity will not.")
    elif result["offset"] > attenuation.peak_reduction * 1.5:
        print("  The supply benefit is the larger one here, and that is the")
        print("  common case. A design storm delivers several times the total")
        print("  tank volume in an hour, so storage that covers months of")
        print("  household demand barely dents the peak.")
        print()
        print("  A Smart City pitch that promises flood mitigation from rooftop")
        print("  tanks should be made to show this number before it is believed.")
    return 0


def demo_fleet() -> list[NodeWindow]:
    """A fleet containing every failure worth screening for."""
    healthy = [
        NodeWindow(f"RP-{i:03d}",
                   tuple(1.2 + 0.35 * ((i * 7 + k * 3) % 5) for k in range(12)),
                   district="Umbulharjo" if i % 2 else "Gondokusuman")
        for i in range(1, 13)
    ]
    return healthy + [
        # Reads a plausible constant. Passes every range check.
        NodeWindow("RP-013", tuple([2.40] * 12), "Umbulharjo"),
        NodeWindow("RP-014", tuple([0.00] * 12), "Gondokusuman"),
        # Disconnected probe pinned at the rail.
        NodeWindow("RP-015", tuple([880.0] * 12), "Umbulharjo"),
        # Reported twice then stopped.
        NodeWindow("RP-016", (1.9, 2.1), "Gondokusuman"),
        # Never reported.
        NodeWindow("RP-017", (), "Umbulharjo"),
    ]


def cmd_fleet(args) -> int:
    if not args.demo:
        print("only --demo is implemented; point it at real telemetry to extend",
              file=sys.stderr)
        return 1

    windows = demo_fleet()
    summary = aggregate(windows)

    print("City-wide")
    print(summary.report())

    print("\nBy district")
    for name, district in by_district(windows).items():
        print(f"\n{name}")
        print(district.report())

    naive = [v for w in windows for v in w.turbidity_ntu]
    naive_mean = sum(naive) / len(naive)
    print()
    print(f"Unscreened mean across every reading: {naive_mean:.2f} NTU")
    print(f"Screened median:                      {summary.median_ntu:.2f} NTU")
    print("\nThe gap is one disconnected probe and two stuck sensors. Neither")
    print("was offline, and neither would have shown up on an uptime chart.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="citywater", description=__doc__)
    ap.add_argument("--name", default="District")
    ap.add_argument("--area", type=float, default=500.0, help="hectares")
    ap.add_argument("--roof-share", type=float, default=0.30)
    ap.add_argument("--runoff", type=float, default=0.75)
    ap.add_argument("--adoption", type=float, default=0.25)
    ap.add_argument("--tank-per-m2", type=float, default=40.0, help="L per m2 roof")
    ap.add_argument("--available", type=float, default=0.5,
                    help="share of storage empty when the storm starts")
    ap.add_argument("--intensity", type=float, default=90.0, help="mm/h")
    ap.add_argument("--duration", type=int, default=60, help="minutes")
    ap.add_argument("--return-period", type=int, default=5)

    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("storm", help="peak flow with and without harvesting").set_defaults(
        func=cmd_storm
    )

    p = sub.add_parser("supply", help="demand offset, against the drainage effect")
    p.add_argument("--annual-rainfall", type=float, default=2000.0, help="mm")
    p.add_argument("--population", type=int, default=60_000)
    p.add_argument("--demand-per-capita", type=float, default=130.0, help="L/day")
    p.set_defaults(func=cmd_supply)

    p = sub.add_parser("fleet", help="aggregate unit telemetry")
    p.add_argument("--demo", action="store_true")
    p.set_defaults(func=cmd_fleet)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
