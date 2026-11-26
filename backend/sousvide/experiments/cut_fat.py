"""Question 3: is the cut worth more than a preset shape?

Sweeps the meat's alpha and k across the sourced range for lean and marbled
beef, and sets the result beside what an ordinary measurement error does.

Run from backend/: python -m sousvide.experiments.cut_fat
"""
from __future__ import annotations

from dataclasses import replace

from sousvide import model
from sousvide.model import Finish, Steak

from .common import PHYSICS, pct, section, table

TARGET = 54.5
SEAR = Finish(45)
RIBEYE = Steak(51, width_mm=140, length_mm=180, bone='middle')
STRIP = Steak(38)

ALPHAS = (0.9e-7, 1.07e-7, 1.2e-7, 1.44e-7)
"""0.9e-7 is beef fat's low end; 1.07e-7 to 1.44e-7 is the sourced range for marbled ribeye lean."""
KS = (0.37, 0.46, 0.51)
"""The sourced range of k for marbled ribeye lean, around the planner's 0.46."""


def numbers(steak: Steak) -> tuple[float, float, float, float]:
    classic = model.classic(steak, TARGET, Finish(0))
    pull = model.hot_and_pull(steak, TARGET, 3.0, SEAR)
    hot = model.hot_and_pull(steak, TARGET, 5.0, Finish(0))
    return classic.minutes, pull.minutes, hot.pulled.depth_over_mm(TARGET + 2), pull.finished.depth_over_mm(model.GRAY_C)


def properties() -> None:
    for name, steak in (('the canonical bone-in ribeye', RIBEYE), ('a 38 mm slab', STRIP)):
        base = numbers(steak)
        rows = []
        for alpha in ALPHAS:
            for k in KS:
                got = numbers(replace(steak, physics=replace(PHYSICS, diffusivity=alpha, conductivity=k)))
                rows.append([f'{alpha * 1e7:.2f}', k, round(got[0]), pct(got[0], base[0]), round(got[1]), pct(got[1], base[1]),
                             round(got[2], 1), round(got[3], 1)])
        section(f'alpha and k, {name}',
                table(['alpha, 1e-7 m2/s', 'k W/m K', 'classic min', '% vs default', 'pull +3 C min', '% vs default',
                       'past target at +5 C, mm', 'gray band mm'], rows),
                'Defaults are alpha 1.2e-7 and k 0.46. Past target is out of the bath, no sear; the gray band follows a 45 s sear.')


def measurement() -> None:
    """What moves the classic time: one change at a time on the canonical steak."""
    base = numbers(RIBEYE)

    def row(label: str, steak: Steak) -> list:
        got = numbers(steak)
        return [label, round(got[0]), pct(got[0], base[0]), round(got[1]), pct(got[1], base[1])]
    def physics(**changes) -> Steak:
        return replace(RIBEYE, physics=replace(PHYSICS, **changes))
    rows = [
        row('as measured', RIBEYE),
        row('alpha 1.07e-7 (low end for marbled lean)', physics(diffusivity=1.07e-7)),
        row('alpha 1.44e-7 (high end)', physics(diffusivity=1.44e-7)),
        row('k 0.37', physics(conductivity=0.37)),
        row('k 0.51', physics(conductivity=0.51)),
        row('thickness 49 mm (-2)', replace(RIBEYE, thickness_mm=49)),
        row('thickness 53 mm (+2)', replace(RIBEYE, thickness_mm=53)),
        row('thickness 46 mm (a 1.8 in steak sold as 2 in)', replace(RIBEYE, thickness_mm=46)),
        row('width 130 mm (-10)', replace(RIBEYE, width_mm=130)),
        row('width 150 mm (+10)', replace(RIBEYE, width_mm=150)),
        row('width and length unknown (slab)', Steak(51)),
        row('bone ignored', replace(RIBEYE, bone='none')),
        row('start 2 C', replace(RIBEYE, start_c=2)),
        row('start 10 C', replace(RIBEYE, start_c=10)),
        row('bath h 60 (weak circulation)', physics(h_bath=60)),
        row('bath h 200 (strong)', physics(h_bath=200)),
    ]
    section('What moves the time, canonical ribeye', table(['change', 'classic min', '%', 'pull +3 C min', '%'], rows))


if __name__ == '__main__':
    print('# Cut and fat\n')
    properties()
    measurement()
