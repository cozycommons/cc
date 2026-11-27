"""Does the model reproduce measured core temperatures of real beef?

Loads every data/*.csv (format: docs/handoff/sousvide-validation.md and
data/SOURCES.md), rebuilds each cook with the shipped constants and scores it
against the brief's targets:

- bath: core RMS error <= 1.5 C and the time to within 1 C of the bath within 10 %;
- sear and rest: the core's peak rise within 1.5 C, its time within 5 min.

Then it fits alpha (and h when the log pins it) to one bath dataset with
sousvide/calibrate.py and scores every other bath dataset with that fit.

A cook is rebuilt twice where it has a sear:

- "planner": model.Body, the code the API runs. It is symmetric about the
  mid-plane, so a sear of a seconds on one face and b on the other becomes both
  faces at once for (a + b) / 2, which is what model.Finish assumes.
- "as cooked": the experiments' 2-D solver on the width x thickness section,
  one face on the pan at a time and the others in air. The length is ignored.

Besides the brief's header keys a file may carry:

    # schedule: bath 120 52; sear 1 a; sear 1 b; rest 3
        minutes per step, then the bath temperature or the face on the pan
        (a, b or both). Without it the steps follow the rows: each phase lasts
        to its last row and a sear is on both faces.
    # air_c: 25
    # shape: slab | puck | cylinder
    # reading_time: unknown
        the source does not say when after the sear the core was read. The
        reading is then compared with the model's range over the scheduled rest.

A header value written "unknown (5 assumed ...)" is read as 5.

Run from backend/: python -m sousvide.experiments.validate
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from sousvide import calibrate, model
from sousvide.model import Body, Physics, Steak

from .common import PHYSICS, section, table
from .solver2d import Sides, Solver2D, linspace, uniform

DATA = Path(__file__).parent / 'data'
PHASES = ('bath', 'sear', 'rest')
FACES = ('a', 'b', 'both')
BATH_RMS_C, BATH_TIME_PCT = 1.5, 10.0
RISE_C, PEAK_MIN = 1.5, 5.0
NUMBER = r'(?:unknown\s*\(\s*)?(-?\d+(?:\.\d+)?)'

# (label, h toward a surface temperature). The first is what ships; the rest test it.
SEARS: list[tuple[str, dict[str, float]]] = [
    ('shipped: h 400 to 100 C', {}),
    ('h 800 to 100 C', {'h_sear': 800.0}),
    ('surface pinned at 100 C', {'h_sear': 1e5}),
    ('h 400 to 125 C', {'sear_surface_c': 125.0}),
    ('h 400 to 150 C', {'sear_surface_c': 150.0}),
    ('h 400 to 200 C', {'sear_surface_c': 200.0}),
    ('h 120 to 215 C (Moya et al. contact, no evaporation)', {'h_sear': 120.0, 'sear_surface_c': 215.0}),
    ('shipped sear, alpha 1.44e-7 (top of the sourced range)', {'diffusivity': 1.44e-7}),
]

# Bath coefficients to try at the shipped alpha and at the top of its sourced range.
BATH_H = (95.0, 200.0, 400.0, 1000.0, 1e4)
BATH_ALPHA = (1.2e-7, 1.44e-7)
BATH_LIMIT_FACTOR = 4.0  # the model may take this many times the logged bath before "never reached"


@dataclass(frozen=True)
class Row:
    minute: float
    phase: str
    core_c: float
    bath_c: float | None = None
    surface_c: float | None = None


@dataclass(frozen=True)
class Step:
    phase: str
    minutes: float
    bath_c: float | None = None  # bath steps
    face: str = 'both'  # sear steps


@dataclass
class Dataset:
    slug: str
    steak: Steak
    rows: list[Row]
    steps: list[Step]
    bath_c: float | None  # the header's, the cook's target
    air_c: float
    reading_time_known: bool = True
    assumed: list[str] = field(default_factory=list)

    def of(self, *phases: str) -> list[Row]:
        return [r for r in self.rows if r.phase in phases]

    @property
    def bath_varies(self) -> bool:
        return any(r.bath_c is not None for r in self.rows)


def load(path: Path) -> Dataset:
    """One CSV as a cook. Raises ValueError naming the file when it does not follow the format."""
    def bad(why: str) -> ValueError:
        return ValueError(f'{path.name}: {why}')
    lines = path.read_text(encoding='utf-8').splitlines()
    head = '\n'.join(line[1:] for line in lines if line.startswith('#'))
    assumed: list[str] = []

    def number(key: str) -> float | None:
        found = re.search(rf'\b{key}:\s*{NUMBER}', head)
        if found and 'unknown' in found.group(0):
            assumed.append(key)
        return float(found.group(1)) if found else None

    def word(key: str, choices: tuple[str, ...], default: str) -> str:
        found = re.search(rf'\b{key}:\s*({"|".join(choices)})\b', head)
        return found.group(1) if found else default

    thickness, start = number('thickness_mm'), number('start_c')
    if thickness is None or start is None:
        raise bad('the header needs thickness_mm and start_c (a number, or "unknown (N assumed)")')
    steak = model.sized(Steak(thickness, word('shape', ('slab', 'puck', 'cylinder'), 'slab'), start,
                              number('width_mm'), number('length_mm'), PHYSICS, word('bone', ('none', 'edge', 'middle'), 'none')),
                        number('weight_g'))

    body = [line for line in lines if line.strip() and not line.startswith('#')]
    reader = csv.DictReader(body)
    if not reader.fieldnames or list(reader.fieldnames[:3]) != ['min', 'phase', 'core_c']:
        raise bad('the column line must start min,phase,core_c')
    rows = []
    for raw in reader:
        try:
            row = Row(float(raw['min']), raw['phase'].strip(), float(raw['core_c']),
                      *(float(raw[c]) if raw.get(c) not in (None, '') else None for c in ('bath_c', 'surface_c')))
        except (TypeError, ValueError) as error:
            raise bad(f'unreadable row {raw}') from error
        if row.phase not in PHASES:
            raise bad(f'phase {row.phase!r} is not one of {PHASES}')
        if rows and (row.minute < rows[-1].minute or PHASES.index(row.phase) < PHASES.index(rows[-1].phase)):
            raise bad(f'rows must run forward in time and phase, at minute {row.minute:g}')
        rows.append(row)
    if not rows:
        raise bad('no readings')

    bath_c = number('bath_c')
    schedule = re.search(r'\bschedule:\s*(.+)', head)
    steps: list[Step] = []
    if schedule:
        for part in filter(None, (p.strip() for p in schedule.group(1).split(';'))):
            bits = part.split()
            if len(bits) < 2 or bits[0] not in PHASES:
                raise bad(f'schedule step {part!r}')
            minutes = float(bits[1])
            if bits[0] == 'bath':
                if len(bits) < 3:
                    raise bad(f'schedule step {part!r} needs the bath temperature')
                steps.append(Step('bath', minutes, bath_c=float(bits[2])))
            elif bits[0] == 'sear':
                if len(bits) > 2 and bits[2] not in FACES:
                    raise bad(f'schedule step {part!r}: the face is one of {FACES}')
                steps.append(Step('sear', minutes, face=bits[2] if len(bits) > 2 else 'both'))
            else:
                steps.append(Step('rest', minutes))
    else:
        clock = 0.0
        for phase in PHASES:
            mine = [r for r in rows if r.phase == phase]
            if mine:
                if phase == 'bath' and bath_c is None and mine[0].bath_c is None:
                    raise bad('bath rows need bath_c in the header or a bath_c column')
                steps.append(Step(phase, mine[-1].minute - clock, bath_c=bath_c if phase == 'bath' else None))
                clock = mine[-1].minute
    return Dataset(path.stem, steak, rows, steps, bath_c, number('air_c') or PHYSICS.air_c,
                   not re.search(r'\breading_time:\s*unknown', head), assumed)


def load_all(folder: Path = DATA) -> list[Dataset]:
    return [load(p) for p in sorted(folder.glob('*.csv'))]


# ---- rebuilding a cook -------------------------------------------------------------------------

Trace = list[tuple[float, float]]  # (real seconds since the start, core C)


def bath_at(data: Dataset, step: Step, minute: float) -> float:
    """The bath temperature at a minute: the logged column when there is one, held to the next row."""
    logged = [(r.minute, r.bath_c) for r in data.of('bath') if r.bath_c is not None]
    if not logged:
        return step.bath_c
    return next((c for m, c in reversed(logged) if m <= minute + 1e-9), logged[0][1])


def planner(data: Dataset, physics: Physics = PHYSICS) -> Trace:
    """The cook through model.Body, as the API would run it."""
    body = Body(replace(data.steak, physics=physics))
    trace, t = [(0.0, body.core)], 0.0
    steps = list(data.steps)
    while steps:
        step = steps.pop(0)
        end = t + step.minutes * 60
        if step.phase == 'bath':
            while t < end - 1e-6:
                body.step(bath_at(data, step, t / 60), physics.h_bath, model.BATH_STEP_S)
                t += model.BATH_STEP_S
                trace.append((t, body.core))
        elif step.phase == 'sear':
            # model.Finish's convention: a sear given per face runs on both faces at once, for half as long.
            faces = [step.face]
            while steps and steps[0].phase == 'sear':
                faces.append(steps[0].face)
                end += steps.pop(0).minutes * 60
            stretch = 1.0 if all(face == 'both' for face in faces) else 2.0
            for _ in range(round((end - t) / stretch / model.SEAR_STEP_S)):
                body.step(physics.sear_surface_c, physics.h_sear, model.SEAR_STEP_S, side_h=0.0)
                t += model.SEAR_STEP_S * stretch
                trace.append((t, body.core))
        else:
            while t < end - 1e-6:
                body.step(data.air_c, physics.h_air, model.REST_STEP_S)
                t += model.REST_STEP_S
                trace.append((t, body.core))
    return trace


def as_cooked(data: Dataset, physics: Physics = PHYSICS) -> Trace:
    """The cook on the width x thickness section, the pan under one face at a time."""
    steak = data.steak
    round_ = steak.shape == 'puck'
    if steak.shape == 'cylinder':
        raise ValueError(f'{data.slug}: no as-cooked section for a roast')
    width = steak.heated_width_mm
    nx = 11 if width else 2
    xs = linspace(0.0, width / 2000 if width else 1.0, nx)  # no measured width: no heat flows sideways
    nz = 2 * model.NODES - 1
    zs = linspace(0.0, steak.thickness_mm / 1000, nz)
    rc = physics.conductivity / physics.diffusivity
    solver = Solver2D(xs, zs, uniform(nx, nz, physics.conductivity), uniform(nx, nz, rc), steak.start_c, round_)
    mid = nz // 2
    trace, t = [(0.0, solver.T[0][mid])], 0.0
    air = (physics.h_air, data.air_c)
    pan = (physics.h_sear, physics.sear_surface_c)
    for step in data.steps:
        end = t + step.minutes * 60
        dt = {'bath': model.BATH_STEP_S, 'sear': model.SEAR_STEP_S, 'rest': model.REST_STEP_S}[step.phase]
        while t < end - 1e-6:
            if step.phase == 'bath':
                wet = (physics.h_bath, bath_at(data, step, t / 60))
                sides = Sides(x1=wet if width else None, z0=wet, z1=wet)
            elif step.phase == 'sear':
                sides = Sides(x1=air if width else None, z0=pan if step.face in ('a', 'both') else air,
                              z1=pan if step.face in ('b', 'both') else air)
            else:
                sides = Sides(x1=air if width else None, z0=air, z1=air)
            solver.step(sides, dt)
            t += dt
            trace.append((t, solver.T[0][mid]))
    return trace


def at(trace: Trace, minute: float) -> float:
    """The traced core at a minute, linearly between steps."""
    s = minute * 60
    if s <= trace[0][0]:
        return trace[0][1]
    for (t0, c0), (t1, c1) in zip(trace, trace[1:]):
        if s <= t1:
            return c0 + (c1 - c0) * (s - t0) / (t1 - t0) if t1 > t0 else c1
    return trace[-1][1]


def first_minute(points: list[tuple[float, float]], level_c: float) -> float | None:
    """The first minute a rising (minute, core) series reaches level_c, linearly between points."""
    for (m0, c0), (m1, c1) in zip(points, points[1:]):
        if c0 < level_c <= c1:
            return m0 + (m1 - m0) * (level_c - c0) / (c1 - c0)
    return None


def rms(errors: list[float]) -> float:
    return math.sqrt(sum(e * e for e in errors) / len(errors))


# ---- scoring -----------------------------------------------------------------------------------

def bath_score(data: Dataset, physics: Physics = PHYSICS) -> dict:
    rows = data.of('bath')
    steps = [s for s in data.steps if s.phase == 'bath']
    # Keep the model in the last bath past the end of the log, so a slow model still gets a time.
    steps.append(Step('bath', (BATH_LIMIT_FACTOR - 1) * sum(s.minutes for s in steps), bath_c=steps[-1].bath_c))
    trace = planner(replace_steps(data, steps), physics)
    errors = [at(trace, r.minute) - r.core_c for r in rows]
    target = data.bath_c if data.bath_c is not None else rows[-1].bath_c
    top = max(r.core_c for r in rows)
    level, reached = (target - 1.0, True) if top >= target - 1.0 else (top, False)
    measured = first_minute([(r.minute, r.core_c) for r in rows], level)
    modelled = first_minute([(t / 60, c) for t, c in trace], level)
    off = None if not measured or modelled is None else 100 * (modelled - measured) / measured
    return {'rms': rms(errors), 'bias': sum(errors) / len(errors), 'level': level, 'reached': reached,
            'measured_min': measured, 'model_min': modelled, 'time_pct': off,
            'ok': rms(errors) <= BATH_RMS_C and off is not None and abs(off) <= BATH_TIME_PCT}


def replace_steps(data: Dataset, steps: list[Step]) -> Dataset:
    return Dataset(data.slug, data.steak, data.rows, steps, data.bath_c, data.air_c, data.reading_time_known, data.assumed)


def finish_score(data: Dataset, trace: Trace) -> dict:
    """The sear and rest readings against one rebuilt cook.

    The rise is counted from the core when the bag came out: the last bath reading
    when there is one, otherwise the model's own. Both rises use the same base then,
    so the error in the rise is the error in the core.
    """
    rows = data.of('sear', 'rest')
    pull_min = sum(s.minutes for s in data.steps if s.phase == 'bath')
    end_min = sum(s.minutes for s in data.steps)
    base_model = at(trace, pull_min)
    bath_rows = data.of('bath')
    base_measured = bath_rows[-1].core_c if bath_rows else base_model
    best = max(rows, key=lambda r: r.core_c)
    window = [(t / 60, c) for t, c in trace if pull_min * 60 <= t <= end_min * 60 + 1e-6]
    peak_min, peak_c = max(window, key=lambda p: p[1])
    out = {'measured_rise': best.core_c - base_measured, 'rms': rms([at(trace, r.minute) - r.core_c for r in rows]),
           'model_peak_rise': peak_c - base_model, 'model_peak_after_min': peak_min - pull_min, 'peak_error_min': None}
    if data.reading_time_known:
        out['model_rise'] = max(at(trace, r.minute) for r in rows) - base_model
        out['error'] = out['model_rise'] - out['measured_rise']
        if len(data.of('rest')) >= 3:
            out['peak_error_min'] = peak_min - best.minute
    else:
        # When the reading was taken is unknown: it may be anywhere in the scheduled rest.
        after_sear = sum(s.minutes for s in data.steps if s.phase != 'rest')
        rises = [c - base_model for m, c in window if m >= after_sear - 1e-6]
        out['model_rise'] = (min(rises), max(rises))
        measured = out['measured_rise']
        out['error'] = 0.0 if min(rises) <= measured <= max(rises) else (
            max(rises) - measured if measured > max(rises) else min(rises) - measured)
    out['ok'] = abs(out['error']) <= RISE_C and (out['peak_error_min'] is None or abs(out['peak_error_min']) <= PEAK_MIN)
    return out


def f(value, digits: int = 1) -> str:
    if value is None:
        return 'n/a'
    if isinstance(value, tuple):
        return f'{value[0]:.{digits}f} to {value[1]:.{digits}f}'
    return f'{value:.{digits}f}'


def verdict(ok: bool) -> str:
    return 'pass' if ok else 'FAIL'


def report_bath(baths: list[Dataset]) -> None:
    rows = []
    for data in baths:
        s = bath_score(data)
        steak = data.steak
        size = f'{steak.thickness_mm:g}' + (f' x {steak.width_mm:.0f}' if steak.width_mm else '') + (
            f' x {steak.length_mm:.0f}' if steak.length_mm else '')
        rows.append([data.slug, size, len(data.of('bath')), f(s['rms'], 2), f(s['bias'], 2),
                     f"{s['level']:.1f}" + ('' if s['reached'] else ' (log stops short of bath - 1)'),
                     f(s['measured_min']), f(s['model_min']), f(s['time_pct']), verdict(s['ok'])])
    section('Bath, shipped constants', table(
        ['dataset', 'mm', 'readings', 'core RMS C', 'mean model - measured C', 'time to reach C', 'measured min',
         'model min', 'time off %', f'RMS <= {BATH_RMS_C} and time within {BATH_TIME_PCT:g} %'], rows),
        'The core through model.Body with alpha 1.2e-7, k 0.46, h_bath 95, the logged bath where there is a bath column. '
        'The time is to the bath target minus 1 C, or to the highest logged core when the log stops before that; '
        f'n/a means the model had not got there in {BATH_LIMIT_FACTOR:g} times the logged bath.')


def report_bath_h(baths: list[Dataset]) -> None:
    rows = []
    for alpha in BATH_ALPHA:
        for h in BATH_H:
            scores = [bath_score(d, replace(PHYSICS, diffusivity=alpha, h_bath=h)) for d in baths]
            rows.append([f'{alpha * 1e7:.2f}', f'{h:g}', *(f"{f(s['rms'], 2)} / {f(s['time_pct'])}" for s in scores),
                         f'{sum(s["ok"] for s in scores)} of {len(scores)}'])
    section('The bath coefficient, tested directly', table(
        ['alpha 1e-7 m2/s', 'h_bath', *(f'{d.slug}: RMS C / time off %' for d in baths), 'passes'], rows),
        'Nothing fitted: the same scoring with h_bath and alpha set by hand. h 1e4 is a surface at bath temperature.')


def report_finish(finishes: list[Dataset]) -> None:
    rows = []
    for data in finishes:
        for label, run in (('planner', planner), ('as cooked', as_cooked)):
            s = finish_score(data, run(data))
            rows.append([data.slug, label, len(data.of('sear', 'rest')), f(s['measured_rise']), f(s['model_rise']), f(s['error']),
                         f(s['rms']) if data.reading_time_known else 'n/a', f(s['model_peak_rise']), f(s['model_peak_after_min']),
                         f(s['peak_error_min']), verdict(s['ok'])])
    section('Sear and rest, shipped constants', table(
        ['dataset', 'rebuilt', 'readings', 'measured rise C', 'model rise C', 'rise error C', 'core RMS C',
         'model peak rise C', 'model peak, min after the pull', 'peak time error min', f'rise within {RISE_C} C'], rows),
        'Rise is the core above its temperature when the sear began. "Model rise" is at the reading times; where the source does '
        'not say when it read the core, it is the model\'s range over the scheduled rest and the error is the distance to that range. '
        'Peak time is scored only with three or more rest readings.')

    rows = []
    for label, changes in SEARS:
        physics = replace(PHYSICS, **changes)
        errors = [finish_score(data, as_cooked(data, physics))['error'] for data in finishes]
        rows.append([label, *(f(e) for e in errors), f(rms(errors))])
    section('The sear boundary, tested directly', table(['sear (as cooked)', *(d.slug for d in finishes), 'RMS of the errors'], rows),
            'Rise error in C (model - measured) with only the pan contact changed. A positive number means the model heats too much.')


def report_fits(baths: list[Dataset]) -> None:
    fits = {}
    for data in baths:
        if data.bath_varies or len(data.of('bath')) < 5:
            continue
        readings = [(r.minute, r.core_c) for r in data.of('bath')]
        fits[data.slug] = calibrate.fit(data.steak, data.bath_c, readings, fit_h=True)
    if len(baths) < 2 or not fits:
        section('Leave-one-out fit', 'Needs two bath datasets, one of them at a constant bath temperature.')
        return
    rows = []
    for slug, fit in fits.items():
        physics = replace(PHYSICS, diffusivity=fit['alpha'], h_bath=fit['h_bath'])
        scores = {d.slug: bath_score(d, physics) for d in baths}
        others = [s for name, s in scores.items() if name != slug]
        rows.append([slug, f"{fit['alpha'] * 1e7:.2f}" + (' (on a bound)' if fit['alpha_on_bound'] else ''),
                     f"{fit['h_bath']:g}" + (' fitted' if fit['h_fitted'] else ''), f(fit['default_rms_c'], 2), f(fit['rms_c'], 2),
                     *(f"{f(s['rms'], 2)} / {f(s['time_pct'])}" if name != slug else 'fitted on' for name, s in scores.items()),
                     f'{sum(s["ok"] for s in others)} of {len(others)}'])
    section('Leave-one-out fit', table(
        ['fitted on', 'alpha 1e-7 m2/s', 'h_bath', 'own RMS before C', 'own RMS after C',
         *(f'{d.slug}: RMS C / time off %' for d in baths), 'held-out passes'], rows),
        'calibrate.fit on one bath log (h kept only when the log pins it), then every other bath dataset scored with that fit. '
        'A log with a varying bath is scored but never fitted on: calibrate.fit takes one bath temperature.')


def main() -> None:
    datasets = load_all()
    baths = [d for d in datasets if len(d.of('bath')) >= 3]
    finishes = [d for d in datasets if d.of('sear', 'rest')]
    print('# Validation against measured cooks\n')
    print(f'{len(datasets)} datasets in data/: {len(baths)} with a bath log, {len(finishes)} with sear or rest readings. '
          'Sources and their quality: data/SOURCES.md.\n')
    assumed = [[d.slug, ', '.join(d.assumed)] for d in datasets if d.assumed]
    if assumed:
        section('Values the sources do not give', table(['dataset', 'assumed in the header'], assumed))
    if baths:
        report_bath(baths)
        report_bath_h(baths)
    if finishes:
        report_finish(finishes)
    report_fits(baths)


if __name__ == '__main__':
    main()
