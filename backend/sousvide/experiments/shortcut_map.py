"""Question 4: where is the hot bath free, and how sturdy is that boundary?

"Free" means no layer peaks more than 2 C over the target in the bath. The
steak is pulled when its core will coast to within 0.5 C of the target, with no
sear, so the map shows the bath's own effect.

Run from backend/: python -m sousvide.experiments.shortcut_map
"""
from __future__ import annotations

from dataclasses import replace

from sousvide import model
from sousvide.model import Finish, Steak

from .common import PHYSICS, section, table

NO_SEAR = Finish(0)
THICKNESSES = (15, 25, 38, 51, 64, 75)
TARGETS = (52.0, 54.5, 57.0, 60.0, 65.0)


def pull(steak: Steak, target: float, boost: float) -> model.Cook:
    return model.hot_and_pull(steak, target, boost, NO_SEAR)


def free_boost(steak: Steak, target: float) -> float:
    """Largest boost, to 0.1 C, that leaves no layer more than 2 C over the target."""
    lo, hi = 2.0, 10.0  # a bath 2 C over cannot overcook by more than 2 C
    while hi - lo > 0.1:
        mid = (lo + hi) / 2
        if pull(steak, target, mid).pulled.depth_over_mm(target + model.OVERCOOKED_BY_C) > 0:
            hi = mid
        else:
            lo = mid
    return round(lo, 1)


def the_map() -> None:
    rows_free, rows_saved = [], []
    for t in THICKNESSES:
        free_row, saved_row = [t], [t]
        for target in TARGETS:
            steak = Steak(t)
            classic = model.classic(steak, target, NO_SEAR).minutes
            boost = free_boost(steak, target)
            minutes = pull(steak, target, boost).minutes
            free_row.append(boost)
            saved_row.append(f'{round(classic - minutes)} of {round(classic)} ({round(100 * (classic - minutes) / classic)} %)')
        rows_free.append(free_row)
        rows_saved.append(saved_row)
    heads = ['thickness mm'] + [f'target {t:g} C' for t in TARGETS]
    section('Largest free boost, C over target', table(heads, rows_free), 'Slabs from 5 C, no sear.')
    section('Minutes saved at that boost, of the classic time', table(heads, rows_saved))


def by_boost() -> None:
    rows = []
    for name, steak in (('15 mm slab', Steak(15)), ('38 mm slab', Steak(38)),
                        ('canonical ribeye', Steak(51, width_mm=140, length_mm=180, bone='middle')), ('75 mm slab', Steak(75))):
        classic = model.classic(steak, 54.5, NO_SEAR).minutes
        row = [name, round(classic)]
        for boost in (0, 1, 2, 3, 4, 5, 6, 8, 10):
            cook = pull(steak, 54.5, float(boost))
            row.append(f'{round(100 * (classic - cook.minutes) / classic)} % / {cook.pulled.depth_over_mm(56.5):.1f}')
        rows.append(row)
    section('Time saved and depth past target, by boost, target 54.5 C',
            table(['steak', 'classic min'] + [f'+{b}' for b in (0, 1, 2, 3, 4, 5, 6, 8, 10)], rows),
            'Each cell: per cent of the classic time saved / mm a side past 56.5 C out of the bath. '
            '+0 is the classic bath pulled 0.5 C early because the outside is warmer than the core.')


def sensitivity() -> None:
    rows = []
    for label, changes in (('default', {}), ('bath h 60', {'h_bath': 60.0}), ('bath h 200', {'h_bath': 200.0}),
                           ('bath h 500', {'h_bath': 500.0}), ('alpha 1.07e-7', {'diffusivity': 1.07e-7}),
                           ('alpha 1.44e-7', {'diffusivity': 1.44e-7}), ('k 0.37', {'conductivity': 0.37}), ('k 0.51', {'conductivity': 0.51})):
        physics = replace(PHYSICS, **changes)
        row = [label]
        for t in (25, 51):
            steak = Steak(t, physics=physics)
            boost = free_boost(steak, 54.5)
            cook = pull(steak, 54.5, boost)
            at3 = pull(steak, 54.5, 3.0)
            row += [boost, round(cook.pulled.T[-1], 2), round(at3.pulled.T[-1] - 54.5, 2), round(at3.pulled.depth_over_mm(56.5), 1)]
        rows.append(row)
    section('How the boundary moves with h and alpha, target 54.5 C',
            table(['constants', '25 mm: free boost', 'surface at pull C', 'surface over target at +3', 'mm past at +3',
                   '51 mm: free boost', 'surface at pull C', 'surface over target at +3', 'mm past at +3'], rows))


if __name__ == '__main__':
    print('# Hot-bath shortcut map\n')
    the_map()
    by_boost()
    sensitivity()
