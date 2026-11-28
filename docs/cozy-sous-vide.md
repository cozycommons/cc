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

The cook measures the steak: thickness, weight, width and length if they have
calipers, where the bone sits, the starting core temperature and the target.
A probe log from one cook then fits the model's constants to their kitchen.

## The canonical steak

The page opens on a bone-in ribeye, 51 mm (2″) thick, 1.33 kg (2.94 lb), the
rib through its middle, from 5 °C to 54.5 °C (130 °F).

**The tables in this section and under "What the experiments found" were
computed at the earlier bath h of 95 W/m²·K and have not been rerun.** At the
shipped h of 400 the planner gives this steak 2 h 34 classic and 1 h 16 for
hot, then pull at +3 °C (pull at 50.3 °C, center peaks at 54.0 °C), against
3 h 10 and 1 h 37 before. The pull and peak temperatures barely moved; the
times did. At +3 °C the bath now leaves 1 mm past target under the face before
the sear, against none at h 95.

**Size.** 1.33 kg at 1050 kg/m³ is 1,267 cm³. At 51 mm thick that is 248 cm² of
footprint, taken as 180 × 140 mm.

**Bone.** A rib 28 mm wide crossing the full thickness, a 2 mm cortical shell
around marrow, running the 180 mm length and leaving 56 mm of meat each side.
The truth below is a 2-D solve of that cross-section with the bone as its own
material, times the 1-D solution along the length
(`experiments/ribeye.py`).

| Method, 45 s sear a side | Bath time | Planner | A 51 mm slab says |
| --- | --- | --- | --- |
| Classic (coldest meat at 54.0 °C, then sear) | 3 h 12 | 3 h 12 | 4 h 08, 30 % long |
| Hot, then pull, bath at target | 2 h 12 | 2 h 13 | 2 h 52, 31 % long |
| +1 °C | 1 h 56 | 1 h 57 | 2 h 30, 30 % long |
| +2 °C | 1 h 46 | 1 h 46 | 2 h 15, 28 % long |
| +3 °C | 1 h 38 | 1 h 38 | 2 h 04, 27 % long |
| +4 °C | 1 h 31 | 1 h 31 | 1 h 55, 27 % long |
| +5 °C | 1 h 26 | 1 h 26 | 1 h 48, 26 % long |

The slab is long for two reasons: the steak is only 2.7 thicknesses wide, so
its edges heat the middle (worth 33 min of the classic time), and the bone
heats faster than the meat it displaces (worth another 23 min).

The classic time moves with the marrow: 3 h 06 to 3 h 21 across the sourced
range of marrow conductivity, 3 h 03 for solid cortical bone. Moving the bone
changes it more:

| Where the bone is | Classic | Coldest meat, at mid-thickness |
| --- | --- | --- |
| Through the middle, along the length | 3 h 12 | 5 mm from the bone |
| Through the middle, across the length | 3 h 18 | 12 mm from the bone |
| Through the middle, behind a 6 mm fat seam | 3 h 08 | at the seam |
| Along one edge (where a rib usually sits) | 3 h 33 | 44 mm from the bone, the middle of the whole steak |
| No bone, same footprint | 3 h 35 | the centre |

**Where the probe goes.** Tip at mid-thickness, 5 to 10 mm from the bone,
halfway along it, not touching it. Anywhere from against the bone to 10 mm out
reads within 0.1 °C of the coldest meat. At the +3 °C pull the middle of the
meat (28 mm from the bone) reads 1.1 °C high, 10 mm in from the open edge reads
3.7 °C high, and a tip 10 mm off mid-thickness reads 0.8 °C high.

**Overcooked depth** (meat that peaked over 56.5 °C), per side:

| Bath | Out of the bath: under the face | in from the open edge | out from the bone | After the sear: under the face | Gray band (65 °C) |
| --- | --- | --- | --- | --- | --- |
| +0 to +2 °C | 0 mm | 0 mm | 0 mm | 10 mm | 3.4 mm |
| +3 °C | 0 mm | 0.5 mm | 0 mm | 10 to 11 mm | 3.4 mm |
| +4 °C | 2.0 mm | 3.5 mm | 0 mm | 10 to 11 mm | 3.4 mm |
| +5 °C | 3.4 mm | 6.5 mm | 0 mm | 10 to 11 mm | 3.4 mm |

Meat next to the bone never overcooks: it is the last to heat. The open edge
overcooks first, because it is heated from the side and both faces. After a
sear the faces are past target to 10 mm whatever the bath did, so on this
steak a boost up to +3 °C costs nothing the sear does not already cost.

## Model

`backend/sousvide/model.py` solves transient heat conduction,
ρc ∂T/∂t = ∇·(k∇T), with heat entering through the surface as
h(T_outside − T_surface). It stays one-dimensional and stdlib-only because
conduction is linear:

- A box that starts uniform and sees one outside temperature on every face has
  the product solution: (T − T_out)/(T_start − T_out) is the product of the 1-D
  solutions along thickness, width and length. A round filet is a slab times a
  cylinder; a roast is a cylinder times a slab along its length.
- A change of outside temperature (bath to pan to air, or a hot bath dropped)
  adds a uniform offset that relaxes on its own. The temperature is the outside
  temperature plus a sum of such parts.

Each 1-D solve is 40 finite volumes (20 along width and length), stepped by
backward Euler: 10 s in the bath, 1 s in the pan, 5 s resting. The model
reports the line through the thickness at the middle of the steak. Doneness
follows the hottest temperature each layer reached, so a layer that peaked at
60 °C stays medium after the bath drops back. "Past target" is meat that
peaked more than 2 °C over the target; the gray band is meat past 65 °C.

A plan for the canonical steak costs 0.5 s of CPU, a 38 mm slab 0.3 s and a
100 mm box 1.1 s, so inputs are rounded and plans are cached per process.

| Constant | Value | Source |
| --- | --- | --- |
| Meat diffusivity α | 1.2e-7 m²/s | Literature pass: 1.07e-7 to 1.44e-7 for marbled ribeye lean |
| Meat conductivity k | 0.46 W/m·K | Literature pass: 0.37 to 0.51 |
| Bath h | 400 W/m²·K | Measured bath cooks fit 400 to 1000 (`experiments/results/validation.md`); was Baldwin's 95, which ran 40 to 126 % long on all five |
| Air h, air temperature | 10 W/m²·K, 22 °C | First-version values, uncited |
| Sear | h 400 toward 100 °C | First-version guess: a wet surface boils, holding the meat under the crust near 100 °C |
| Meat density | 1050 kg/m³ | Relayed with the canonical case |
| Cortical bone | k 0.54, ρ 1800, c 1.26 kJ/kg·K, α 2.4e-7 | Literature pass (experiments only) |
| Marrow | k 0.22 to 0.42, ρ 980, c 2.07 | Literature pass; sources disagree on k (experiments only) |
| Beef fat | k 0.19 to 0.23, α 0.9e-7 to 1.2e-7 | Literature pass (experiments only) |

The literature pass is separate work whose citations live in its own report.
Every constant is a documented field of `model.Physics` or a named constant
beside the code that uses it.

## What the experiments found

Scripts are in `backend/sousvide/experiments/`, their output in
`experiments/results/`. Run one from `backend/` with
`python -m sousvide.experiments.ribeye` (also `finite_size`, `bone`, `cut_fat`,
`shortcut_map`, `sear`, `calibration`). They are stdlib-only. `solver2d.py` is a
2-D solver with per-element k and ρc, used only here.

### 1. Finite size

Per cent by which an infinite slab overstates the classic time, 50 mm thick:

| Width / thickness | 1.5 | 2 | 2.5 | 3 | 4 | 5 | 6 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Long strip | 43 | 24 | 14 | 9 | 3 | 1 | 0 |
| Square | 82 | 45 | 27 | 16 | 6 | 2 | 1 |
| Round | 97 | 54 | 33 | 21 | 9 | 4 | 1 |

The slab is good to 3 % only once a steak is five thicknesses wide (four for a
long strip). The first version's "three times" hid 9 to 21 % at this
thickness. Thin steaks are a few points worse and hot-then-pull a few points
better.

The planner ships the product solution, not a fitted correction. Against a
direct 2-D solve, including a sear on the faces only with the edges in air,
it agrees on the pull core to 0.05 °C, on the finished core to 0.15 °C (worst
for a square cross-section) and on both depths to 0.5 mm. It needs no
calibration and costs two extra 1-D solves per step.

A round steak entered as a square of its diameter runs 5 to 9 % long, so
`puck` is its own shape. A footprint known only by area (from weight) is
assumed 1.3 times longer than wide. Among rectangles of one area, a ratio of
1.5 cooks 1 to 3 % faster than a square and a ratio of 2 cooks 3 to 8 %
faster, so the assumption costs a few per cent at most for ordinary steaks.

The planner reports the middle line. Near the edges more is done: at +3 °C a
38 × 76 mm section has 0 % of its middle line past target and 14 % of its
whole cross-section.

### 2. Bone

Bone needs about half the heat of the meat it displaces (ρc 2.0e6 to 2.3e6
against 3.8e6 J/m³·K) and cortical bone conducts twice as fast, so a bone that
crosses the thickness warms ahead of the meat beside it.

- **Along an edge:** count the bone as meat. Measured across the bone, the
  boneless box is within 2.5 % of the 2-D truth for 15 and 30 mm bones in 25 to
  50 mm steaks, and within 2.3 % at the corners of a deliberately wide range
  (k 0.2 to 0.7, ρc 1.8e6 to 3.2e6).
- **Through the middle:** counting it as meat runs 7 to 18 % long on the
  canonical steak. The planner narrows the heated width by 1.5 bone widths
  (`BONE_MIDDLE_FACTOR`). That matches the canonical steak to 1 % for classic
  and every boost, and lands within 5.3 % on classic for bones 15 to 40 mm wide
  in steaks 25 to 64 mm thick with the mid-range marrow. Across the marrow
  range and solid cortical bone it runs from 12 % short (a 40 mm bone,
  low-conductivity marrow) to 7 % long (solid cortical bone, 38 mm steak).
- A bone thinner than the steak, with meat over it, behaves the same to 1 %.
- A T-bone's 8 mm stem: bone as meat runs 3 to 4 % long.

Pulled early from a hot bath (+3 to +8 °C), meat 3 mm from an edge bone is 2 to
6 °C warmer than the core and 1 to 3 °C cooler than meat 3 mm from the open
edge.

### 3. Cut and fat

One change at a time on the canonical steak:

| Change | Classic time |
| --- | --- |
| α 1.07e-7 to 1.44e-7 (the range for one cut) | +12 % to −17 % |
| k 0.37 to 0.51 | −5 % to +3 % |
| Bath h 60 to 200 | +15 % to −13 % |
| Thickness ±2 mm | ±5 % |
| A "2 inch" steak that is 46 mm | −12 % |
| Width ±10 mm | −5 % to +4 % |
| Width and length unknown | +30 % |
| Bone ignored | +12 % |
| Start 2 °C or 10 °C instead of 5 | +1 % to −2 % |

The cut is not worth more than a shape and a bone position. The α range inside
a single cut is as wide as the difference between cuts, so a cut name cannot
pin α to better than about ±15 %. Calipers, a scale and one probe log each buy
more. α and k do not move the gray band by more than 0.7 mm.

### 4. Where the hot bath is free

"Free" means no layer peaks more than 2 °C over target in the bath (pulled
when the core will coast to target − 0.5 °C, no sear).

| Thickness | 15 mm | 25 mm | 38 mm | 51 mm | 64 mm | 75 mm |
| --- | --- | --- | --- | --- | --- | --- |
| Largest free boost | +5.5 °C | +4.0 | +3.2 | +2.9 | +2.7 | +2.6 |
| Classic time saved there | 52 % | 47 % | 43 % | 41 % | 40 % | 39 % |

The boundary does not depend on the target (52 to 65 °C all agree to 0.1 °C)
or on α. It depends on how closely the surface follows the bath, so on h and
thickness: at h 60 the 51 mm boundary is +3.5 °C, at h 200 it is +2.4, at
h 500 it is +2.1. k 0.37 to 0.51 moves it 0.4 °C. Past the boundary the cost
grows fast: on the canonical steak +4 °C puts 2.3 mm a side past target, +5
puts 4.2 mm and +10 puts 7.5 mm, for 45, 49 and 61 % saved.

The safe rule: +2 °C is free by definition and saves 34 to 35 % at every
thickness; +3 °C is free up to about 40 mm at the assumed h.

### 5. Sear

The assumed sear delivers 308 kJ/m² in 45 s, an average of 6.8 kW/m². Nobody
has measured it on the cook's pan. What it does to the canonical steak and to
a 25 mm steak, each pulled at the planner's time for a +3 °C bath:

| Sear | Core lands at, 51 mm (planned 54.0) | Gray band | Core lands at, 25 mm | Gray band |
| --- | --- | --- | --- | --- |
| Half the contact (h 200), 45 s | 53.5 °C | 2.3 mm | 52.5 °C | 2.4 mm |
| As assumed (h 400 to 100 °C), 45 s | 54.0 | 3.6 | 54.0 | 3.4 |
| Double (h 800), 45 s | 54.4 | 4.2 | 55.2 | 4.0 |
| As assumed, 30 s | 53.5 | 2.3 | 52.6 | 2.4 |
| As assumed, 90 s | 55.3 | 5.6 | 57.7 | 5.3 |
| Surface at 150 °C, 45 s | 56.3 | 6.9 | 60.0 | 7.2 |
| Dry surface, hot pan (h 150 to 200 °C), 45 s | 56.1 | 6.2 | 59.3 | 6.6 |

Carryover follows the heat delivered, and a thin steak has less meat to
absorb it: a classic 51 mm steak gains 1.3 °C after the assumed sear, a 25 mm
steak 4.4 °C. Resting on a cold plate or in a draught (air h 40 instead of 10)
cuts those to 0.5 and 2.7 °C. The core peaks 15 minutes after the pull in the
51 mm steak and 6 minutes after in the 25 mm one.

So the planner says three things. It gives the core reading to pull at, which
does not depend on the bath's h or the steak's α the way the time does. It
quotes the core peak as a range across half to double the assumed contact.
And the docs say plainly that a surface hotter than boiling lands outside
that range: for hot-then-pull on a steak under about 30 mm, the sear decides
the result more than the bath does, and classic or hot-then-drop is the
predictable choice.

### Calibrating from a probe log

The synthetic study below was run at the earlier default h of 95. The fit
now holds h at the shipped 400 when the log cannot pin it, and accepts a
fitted h between 100 and 1500 W/m²·K.

`POST /sousvide/calibrate` fits α by least squares to (minute, core °C)
readings from one cook in a bath held at one temperature, running the same
solver on the steak as measured. With k and h fixed, α only rescales time, so
it is always identifiable.

On synthetic logs from the canonical steak with a true α of 1.35e-7 and a true
h of 130 (`experiments/calibration.py`):

| Log | α fitted with h held at 95 | Is h recovered? |
| --- | --- | --- |
| Every 5 min, 0.1 °C noise | 1.44e-7 | 5 of 12 logs, h 109 ± 12 |
| Every 5 min, 0.5 °C noise | 1.44e-7 | never |
| Every 1 min, 0.1 °C noise | 1.44e-7 | 12 of 12, h 133 ± 10, α 1.35 |
| Tip 5 mm off mid-thickness | 1.50e-7 | never |
| Tip 10 mm off mid-thickness | 1.65e-7 | never |
| Thickness entered 2 mm thin | 1.37e-7 | never |

The fitted α is 7 % high because it absorbs the wrong h. That is the point:
with that α and h still at 95, the next cook of the same steak is predicted
to 0.5 % (the defaults were 21 % long), a 38 mm boneless steak to 3 % and a
25 mm strip to 6 %. A probe 10 mm off-centre costs 15 % on α, more than
anything else, so placement matters more than sample rate.

h is fitted too only when the log pins it: its standard error must be under
15 % and it must lie between 60 and 300 W/m²·K (now 100 and 1500). Before those guards a
two-parameter fit on a log with 0.5 °C noise or a tip 5 mm off settled
confidently on pairs like α 2.2e-7 with h 32. In practice h needs a logging
probe (a reading a minute) with about 0.1 °C repeatability.

## Page

The page leads with the answer for the default steak: one method as steps
(bath, where the thermometer tip goes, when to take it out, the sear and rest),
with a tab per method showing its time. It recommends hot, then pull unless it
saves under 10 minutes or overcooks more than 1 mm a side beyond the classic
cook, and never recommends a cook that breaks the 4 h rule below 54.4 °C when
the other does not; hot, then cool is always slower than pulling and is there
for a steak that has to wait. The page states the 4 h rule only where it
applies and makes no other food-safety claim: the model checks bath time and
temperature, not pasteurization. The center's finish is shown as the range
between a weaker and a stronger sear, named by doneness only when the whole
range is one. Depths are shown to the nearest sixteenth of an inch.

**Screens.** The page is a flow, one screen at a time:

1. **Your steak** (`#steak`): cut, thickness with the No ruler? guide, weight,
   bone and starting temperature; width and length sit behind **More**.
2. **Your cook** (`#cook`): doneness with its strip, the hot bath and the sear.
3. **The plan** (`#plan`): the method tabs, the steps and the schedule with Eat
   at. Start cook sits in the sticky bar.
4. **Cooking** (`#cooking`): the schedule as clock times, Set alarms in my
   calendar, the thermometer and Log, the pull banner and End cook. The steps
   fold away under **The steps**.
5. **Learn** (`#learn`): the chart, the cut-open view, the replay, every hot
   bath, the sizing and Tune to your kitchen.

The screen lives in the URL hash, read with `useSyncExternalStore`, so the
phone's back button and browser history move between screens. Next pushes a
history entry and the page's Back walks history back; when the entry before
is not this flow (a link straight to `#plan`), Back replaces the entry
instead of leaving the page. A running cook owns the plan screen and an empty
hash, so a reload during a cook opens on Cooking; Start and End cook replace
the history entry rather than adding one. The steak, the cook and Learn stay
reachable mid-cook. A progress bar tracks steps 1 to 4, and later screens show
the steak on a chip ("2″ bone-in ribeye, 2.94 lb · 130°F") that jumps back to
edit it. Back and Next stick to the bottom of a phone; a laptop puts the
steak's controls, and the plan's steps and schedule, in two columns. The steak
and cook settings are kept in `localStorage` (`sousvide.steak`), so a reload
keeps them.

**During the cook nothing ticks.** The clock times come from when Start was
pressed. The thermometer stepper starts at what the steak should read now:
the model's center temperature, or after a reading, that reading plus the
model's rise since, so a steak running behind the model stays behind and a
log is a tap or two. "Now" is read when the screen renders and whenever the
page comes back into view (`visibilitychange`, `pageshow`, `focus`), which is
when a cook picks the phone up. The alarm is the phone's own calendar: **Set
alarms in my calendar** opens `GET /sousvide/alarm.ics`, an event for each
moment the cook must act (cool the bath, take it out) with alarms 10 minutes
before and at it. It is served rather than built in the page because iOS
Safari adds events from a `text/calendar` response, not from a downloaded data
URL. The alarm times are the model's estimate; the thermometer decides.

The plan is asked for as soon as the steak and cook settle, on the first two
screens, and the cached promise records its result, so by the time the plan
screen shows, `use()` reads it without suspending.

When the rest is long (10 minutes or more) and the center still climbs, the
sear step says what cutting at 5 minutes gives instead, and how cool a full rest
leaves the crust.

**No typing.** Every value on the page is set by touch: sliders, chips, and
steppers with a coarse and a fine step either side of the value (weight ½ and
0.05 lb; width and length ½ and 0.1″; the thermometer 5 and 1 °F; dinner 1 h and
15 min). Width and length start unset and show the planner's own estimate from
the weight (the same density and 1.3 aspect as `model.sized`); the first tap
starts from it, and **From weight** unsets it again. **Don't know** unsets the
weight, which sizes the steak by thickness alone. Each tap of a measurement asks
for a plan, so several quick taps can fetch the plans in between.

**Schedule** lists the cook's milestones (into the bath, cooling the bath, out,
eat) as offsets, or as clock times worked back from an "eat at" time. The eat-at
stepper starts at the earliest dinner on a quarter hour (read when it is tapped)
and never goes earlier. **Start cook** stamps the start once and shows clock
times from it; nothing ticks, so the page holds no timer. While cooking, the
schedule, in large clock times, and a thermometer stepper sit above the steps. The stepper starts from
the last reading, or the steak's starting temperature, and **Log** saves it as
minutes since the start. Once a reading reaches the pull temperature, a banner
says to take it out (or cool the bath). The running cook and its log survive a
reload in `localStorage` (`sousvide.cook`, and `sousvide.log` as `{ bathF,
readings: [[minutes, °F]] }`; an older text log is read once and kept).

**Tune to your kitchen** fits that log: the readings are listed with a delete
button each, and the bath is the one the cook started with. There is no free
log or bath box; a cook that wants to calibrate logs one cook-along.

**Look and motion.** The page departs from cozy-wabi on purpose, scoped to
`.sv-page`: a vivid pixel palette (grass, gold, lava, sky) over the cozy paper,
2 px ink outlines, and chunky keys whose hard bottom edge presses down. Cuts,
methods, steps, the finger and the title are pixel sprites drawn as SVG
paths built once at load; the No ruler? panel draws the steak's side to scale
beside a standing finger or stacked fingers. A doneness strip under the slider
shows each target's meat colour. Starting a cook, logging a reading, a finished
fit and a replay that plays to the end of the rest set off a pixel burst. Each
screen is keyed on its name and slides in on mount: from the right going
forward, from the left going back (the direction is kept in state, adjusted
during render), and not at all on the first screen of a visit; the progress
fill springs to its step. All motion is CSS on transform and opacity, started
by a mount or a key change (no timers or effects), and is off under
`prefers-reduced-motion`. Bursts are absolutely placed, the slide is clipped
sideways, and stepper values keep their width, so nothing shifts.

**No ruler?** On the steak screen, under the thickness slider, a short tutorial measures with a
finger, two ways: stand an index finger beside the steak and see which crease
its top reaches (taken as 23 mm to the first crease, 46 mm to the second), or
lay fingers flat and count them (19 mm each). A drawing shows the steak at the
thickness picked. Fingers vary by about 15 %, which the page states as about
30 % on cook time (time goes roughly as thickness squared).

Sliders and typed measurements ask for a plan when they are let go or left,
not on every tick or keystroke; each distinct plan is fetched once and cached
in the page, and the previous plan stays on screen, dimmed, while the next one
loads (`use()`, Suspense and `useDeferredValue`, no fetching effects or timers).

**Replay** draws the cook as pixel art from the plan's `trace`: the bag in the
bath, the pan and the board, and a cut through the steak drawn from the
solver's own temperatures at nine depths (each point's `layers`), linear
between depths and between readings. The cut is coloured by each layer's peak,
the colour cooked meat keeps, with the bone; beside it a bar per layer shows how
hot that layer is now against a dotted target line, so the heat creeping in, the
sear's thin hot band and the rest's crossover (crust cooling while the center
climbs) are visible. Thermometers show the center against the target and the
crust (the surface), and a caption says in plain words what is happening,
including the sear step's cut-at-5-minutes tradeoff once the rest gets there.
The replay gives the bath 55 % of its 16 s, the sear 15 % and the rest the
remainder, and its slider follows the same timeline, so a 45 s sear is not
lost in a two-hour cook. It runs at about 12 frames a second only while playing
and on screen, and never autoplays.

## API

`GET /sousvide/plan`

| Parameter | Range | Meaning |
| --- | --- | --- |
| `thickness_mm` | 5 to 100 | Thickness; a roast's diameter |
| `shape` | `slab`, `puck`, `cylinder` | Steak, round steak, roast |
| `width_mm`, `length_mm` | 20 to 400, 20 to 600 | Optional. A puck's diameter is its width |
| `weight_g` | 50 to 5000 | Optional. Fills in the sides not measured |
| `bone`, `bone_mm` | `none`, `edge`, `middle`; 5 to 60 | Slabs only. Width is measured across the bone |
| `start_c`, `target_c` | 0 to 30, 45 to 75 | Measured core at the start, wanted core at the end |
| `boost_c`, `sear_s` | 0 to 10, 0 to 180 | Bath over target; seconds a side |
| `alpha`, `h_bath` | 0.6 to 2.5, 20 to 2000 | From a calibration. α in units of 1e-7 m²/s |

It returns `classic`, `hot_and_pull` and `hot_then_drop` (minutes, bath,
`pull_core_c`, core peak and its `core_peak_range_c` across the sear spread, mm
past target, gray band, minutes saved), `sweep` (hot and pull at 0, 1, 2, 3, 5,
8 and 10 °C over), `trace` (core, middle, surface and nine `layers` by minute, every 5 s
through the sear, ending the bath at the pull), `layer_rho` (where the layers
sit, 0 at the center to 1 at the surface), `profile`
(peak temperature by depth), `steak` (the sides used and whether they were
measured or sized from the weight) and `thickness_only_minutes` (the classic
time an infinite slab would give). Inputs are rounded to 1 mm of thickness,
5 mm of width and length, 10 g, 0.5 °C and 15 s.

A cook below 54.4 °C (130 °F) longer than 4 hours returns a warning: C.
perfringens can still grow there.

`GET /sousvide/alarm.ics?start=<unix s>&at=<min>&what=<label>` repeats `at`
and `what` in pairs (1 to 4, labels up to 120 characters, within a day of the
start) and returns an iCalendar file: one event per pair, each with a display
alarm 10 minutes before and at it.

`POST /sousvide/calibrate` takes the same steak fields plus `bath_c`,
`readings` (3 to 600 pairs of minutes and core °C, within 10 hours) and
`fit_h`. It returns `alpha` (in 1e-7 m²/s), `h_bath`, whether h was fitted or
could not be identified, the fit's RMS error against the RMS with the starting
constants, and the fitted curve. The page keeps the result in the browser's
local storage and sends it with each plan.

## Not modelled, and uncertain

- The sear is the weakest part: its flux is a guess, and section 5 is the
  size of the consequence.
- The middle-bone rule is fitted to one bone model (2 mm shell, marrow core,
  full thickness). Marrow conductivity alone moves the canonical classic time
  −3 % to +5 %. No bone-in steak has been measured against it.
- The bone's own length direction uses the meat's α, and the bone-in footprint
  from weight ignores that bone is denser than meat.
- Bath h is one number. A crowded bath, a floating bag or an air pocket lowers
  it, and h moves the time ±15 % and the free boundary by a degree.
- Frozen steaks, evaporation during the rest, the crust's own heat, uneven
  thickness and fat seams as separate material (in the planner) are not
  modelled. One 2-D run with a 6 mm fat seam beside the bone moved the classic
  time 2 %.
