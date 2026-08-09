# RainPurify at city scale

Two questions a city asks about rooftop rainwater harvesting that a single unit
cannot answer: **how much does it actually help**, and **can you believe the
dashboard**.

Entered at **GEMASTIK's Smart City division** and **UNITY UNY** as the
city-scale framing of RainPurify.

> **On this repository.** The competition entries were concept submissions.
> This is the analysis behind the claim, written afterwards — and it does not
> support the flood-mitigation half of it. That result is left standing.

**Three repositories, three different questions.** Do not confuse them:

| | |
|---|---|
| [rainwater-harvesting-sizing](https://github.com/lesaullianachmadargito/rainwater-harvesting-sizing) | how big should one tank be |
| [rainpurify-iot](https://github.com/lesaullianachmadargito/rainpurify-iot) | the device that treats what lands in it |
| **this one** | what a city gets from a thousand of them |

---

## Part 1 — the flood claim does not survive the arithmetic

Every Smart City pitch for rooftop harvesting promises two benefits: water
supply and flood mitigation. The second one is the exciting one, and it is the
one that fails.

```
$ citywater --adoption 0.8 --available 0.95 storm

  Peak flow before      93.75 m3/s
  Peak flow after       81.08 m3/s
  Reduction             13.5%

  Roof volume          114750 m3
  Storage available     45600 m3
  Captured              45600 m3
  To the drain          69150 m3

  ! Tanks filled before the storm ended. Everything after that
  ! point went straight to the drain — including the most
  ! intense minutes, which usually come mid-storm.
```

That is **80 % adoption with tanks kept 95 % empty** — a scheme no city will
ever get — and a 5-year design storm still gets 13.5 % off the peak. At a
realistic 25 % adoption with tanks half full, it is 2.2 %.

The reason is a volume comparison, not a modelling subtlety. A 90 mm/h storm
drops 114,750 m³ on this district's roofs in an hour. Realistic storage is
7,500 m³. The storm is fifteen times the tanks.

Meanwhile the supply side does considerably better:

```
$ citywater supply

  Annual demand         2,847,000 m3
  Usable harvest          382,500 m3
  Demand offset             13.4%

Against the same scheme's drainage effect:
  Peak flow reduction        2.2%

  The supply benefit is the larger one here, and that is the common case.
  A design storm delivers several times the total tank volume in an hour,
  so storage that covers months of household demand barely dents the peak.

  A Smart City pitch that promises flood mitigation from rooftop tanks
  should be made to show this number before it is believed.
```

**Six times the benefit, on the boring axis.** That is worth knowing before
writing the proposal, not after.

### The trade nobody states

A tank kept full for supply security attenuates nothing. A tank kept empty for
flood control supplies nothing. `available_fraction` is that dial, and it sits
in the model as an explicit parameter because a city has to choose it
deliberately rather than discover it afterwards.

### A modelling bug worth recording

Capture was originally bounded by the volume landing on *all* roofs. Tanks on a
quarter of the roofs cannot hold water from the other three quarters, and the
model was silently crediting them with doing so — inflating attenuation exactly
where adoption is low, which is every real city. Capture is now bounded by
fitted-roof volume, with a test that drives storage to absurd levels and checks
it still cannot exceed the fitted share.

The method is the **rational method**, `Q = C·i·A/360`. It is crude — uniform
rainfall, one runoff coefficient, no routing — and it is what municipal drainage
in Indonesia is dimensioned with, so a claim in its terms is one a drainage
engineer can check.

## Part 2 — the dashboard is lying, and uptime will not tell you

```
$ citywater fleet --demo

17 units, city-wide
13 of 17 units included (24% excluded)
  median  1.90 NTU
  stuck              2  RP-013, RP-014
  out_of_range       1  RP-015
  too_few_readings   1  RP-016
  offline            1  RP-017

Unscreened mean across every reading: 59.71 NTU
Screened median:                      1.90 NTU
```

**59.71 against 1.90.** The gap is one disconnected probe reading at the rail
and two stuck sensors.

The stuck ones are the dangerous ones. A stuck turbidity sensor reports a
perfectly plausible constant — 2.40 NTU, forever. It passes every range check,
it never goes missing, it appears on no uptime chart, and it drags the city
average toward whatever value it froze at for as long as nobody notices. The
only thing that gives it away is that it does not move, so that is what is
tested: a working sensor's readings vary by more than 0.02 NTU across a window,
even in clean water.

Screening runs in a fixed order — screen, aggregate the survivors, then **report
the exclusions alongside the number, always**. That third step is the one that
gets dropped in practice, and dropping it turns a degrading fleet into a
dashboard that looks fine right until it doesn't.

When too much of the fleet fails, the summary refuses to stand behind itself:

```
  ! Too few units survived screening. Do not publish
  ! this aggregate — fix the fleet first.
```

A node with a handful of bad readings is not condemned — only the readings are
dropped. A node where more than 20 % are impossible is condemned, because at
that point the instrument is the problem, not the water.

## Running it

```bash
pip install -e ".[dev]"
pytest
```

```bash
citywater --roof-share 0.30 --adoption 0.25 storm
citywater --adoption 0.8 --available 0.95 storm
citywater supply --population 60000 --annual-rainfall 2000
citywater fleet --demo
```

33 tests, no dependencies — standard library only.

## Layout

```
src/citywater/
  stormwater.py   rational method, attenuation, supply offset
  fleet.py        node screening, robust aggregation, district rollup
  cli.py          command line
tests/            33 tests
```

## What this does not model

- **Routing and timing.** The rational method gives a peak, not a hydrograph.
  Whether attenuated roofs actually shift their contribution off the catchment's
  time of concentration is a question this cannot answer, and it could make the
  real benefit better or worse than 13.5 %.
- **Where the flooding is.** A city-wide peak reduction says nothing about the
  intersection that floods. Distributed storage helps most upstream of the
  bottleneck, and this model has no geography in it.
- **Cost.** Nothing here compares a thousand household tanks against one
  retention basin, and that is the comparison a public works budget actually
  faces.

## License

MIT — see [LICENSE](LICENSE).
