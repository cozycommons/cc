# Sous vide steak

`/sousvide` says how long a steak needs in a water bath, and whether a hotter
bath can cut that time without overcooking the outside. It compares three
methods for one steak:

- **Classic.** Bath at the target until the core is within 0.5 °C (1 °F) of it.
- **Hot, then pull.** Bath hotter than the target. Pull at the first moment the
  sear and rest will carry the core to the target.
- **Hot, then drop.** Bath hotter, then cooled to the target (ice or a second
  bath) as late as possible without the core passing target + 0.5 °C. Slower
  than pulling, but the steak can then hold indefinitely.

## Model

`backend/sousvide/model.py` solves transient heat conduction,
ρc ∂T/∂t = ∇·(k∇T), in one dimension: a slab heated through both faces (a steak
wider than about three times its thickness) or a cylinder heated around its
side (a tenderloin roast). Heat enters through the surface as h(T_outside − T_surface).
The grid is 40 finite volumes, stepped by backward Euler (10 s in the bath, 1 s
in the pan). `tests/test_sousvide.py` checks the core against the plane-wall
series solution.

| Constant | Value | Source or reason |
| --- | --- | --- |
| Diffusivity α | 1.2e-7 m²/s | Beef runs 1.1e-7 to 1.4e-7; times carry about ±10 % |
| Conductivity k | 0.46 W/m·K | Lean beef |
| Bath h | 95 W/m²·K | Bagged steak in a circulating bath (Baldwin) |
| Air h | 10 W/m²·K | Still air while resting |
| Sear | h 400 toward 100 °C | A wet surface boils, holding the meat under the crust near 100 °C |

Doneness follows the hottest temperature each layer reached, so a layer that
peaked at 60 °C stays medium after the bath drops back. "Past target" is meat
that peaked more than 2 °C over the target; the gray band is meat past 65 °C.

The cut only sets the shape and a typical thickness. Fat changes α by a few per
cent, much less than thickness does, since time grows with thickness squared
(a bit less for thin steaks, where the bag's surface resistance matters).
A filet is modelled as a slab, which overstates its time because its sides
also take heat. Frozen steaks, evaporation and the crust's own heat are not
modelled.

## What it says

A 38 mm (1.5″) steak from the fridge, to 54.5 °C (130 °F):

| Bath | Time to pull, no sear | Past target |
| --- | --- | --- |
| 54.5 °C (classic) | 2 h 32 | 0 mm |
| +1 °C | 1 h 55 | 0 mm |
| +2 °C | 1 h 39 | 0 mm |
| +3 °C | 1 h 29 | 0 mm |
| +5 °C | 1 h 15 | 2.7 mm a side |
| +10 °C | 57 min | 6.1 mm a side |

Classic cooking spends most of its time on the last couple of degrees, because
the core approaches the bath exponentially. A bath 2 to 3 °C hot removes that
tail, and the outside never gets far enough over the target to show. Past about
+5 °C, the outer layers visibly overcook.

A 45 s sear a side delivers enough heat that the core climbs about 2 °C while
the steak rests. Pulled classic steaks overshoot (56 °C core); pulled early,
the sear finishes the core for you and even a target-temperature bath is ready
in 1 h 30. The sear is the least certain part of the model: the real flux depends
on the pan, the oil and how dry the surface is.

## API

`GET /sousvide/plan` takes `thickness_mm` (5 to 100, the diameter for a
cylinder), `shape` (`slab` or `cylinder`), `start_c` (0 to 30), `target_c` (45
to 75), `boost_c` (0 to 10) and `sear_s` (seconds a side, 0 to 180). It returns
`classic`, `hot_and_pull` and `hot_then_drop` (minutes, bath, core peak, mm past
target, gray band, minutes saved), `sweep` (hot and pull at 0, 1, 2, 3, 5, 8 and
10 °C over), `trace` (core, middle and surface by minute) and `profile` (peak
temperature by depth). A plan costs about half a second of CPU, so inputs are
rounded to 1 mm, 0.5 °C and 15 s and plans are cached per process.

A cook below 54.4 °C (130 °F) longer than 4 hours returns a warning: C.
perfringens can still grow there.
