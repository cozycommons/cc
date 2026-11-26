"""Question 5: how much do the sear constants drive the carryover and the gray band?

The shipped sear is a contact of h=400 W/(m^2 K) toward 100 C. Nobody has
measured that on the cook's pan, so this sweeps it and reports what the
planner's advice would get wrong.

Run from backend/: python -m sousvide.experiments.sear
"""
from __future__ import annotations

from dataclasses import replace

from sousvide import model
from sousvide.model import Body, Finish, Physics, Steak

from .common import PHYSICS, section, table

TARGET = 54.5
RIBEYE = Steak(51, width_mm=140, length_mm=180, bone='middle')
STRIP = Steak(25)
SEARS = {
    'default: h 400 to 100 C': {},
    'h 200 to 100 C': {'h_sear': 200.0},
    'h 800 to 100 C': {'h_sear': 800.0},
    'h 1600 to 100 C': {'h_sear': 1600.0},
    'h 400 to 150 C': {'sear_surface_c': 150.0},
    'h 400 to 200 C': {'sear_surface_c': 200.0},
    'h 150 to 200 C (dry surface, hot pan)': {'h_sear': 150.0, 'sear_surface_c': 200.0},
}


def delivered_kj_m2(steak: Steak, bath_c: float, sear_s: float) -> float:
    """Heat the sear puts into a steak that starts uniformly at bath_c, per square metre of face."""
    p = steak.physics
    body = Body(replace(steak, start_c=bath_c, width_mm=None, length_mm=None))
    total = 0.0
    for _ in range(round(sear_s)):
        body.step(p.sear_surface_c, p.h_sear, model.SEAR_STEP_S)
        total += p.h_sear * (p.sear_surface_c - body.T[-1]) * model.SEAR_STEP_S
    return total / 1000


def sweep() -> None:
    for name, steak in (('canonical ribeye (51 mm)', RIBEYE), ('25 mm slab', STRIP)):
        rows = []
        planned = model.hot_and_pull(steak, TARGET, 3.0, Finish(45))
        for label, changes in SEARS.items():
            for sear_s in (30, 45, 90):
                real = replace(steak, physics=replace(PHYSICS, **changes))
                finish = Finish(sear_s)
                classic = model.classic(real, TARGET, finish)
                own = model.hot_and_pull(real, TARGET, 3.0, finish)
                # The planner's pull (default constants, 45 s) finished with this sear instead.
                body = Body(real)
                for _ in range(round(planned.minutes * 60 / model.BATH_STEP_S)):
                    body.step(planned.bath_c, real.physics.h_bath, model.BATH_STEP_S)
                landed = finish.run(body)
                rows.append([label, sear_s, round(delivered_kj_m2(real, TARGET, sear_s)),
                             round(classic.core_peak_c - classic.pulled.core, 1), round(classic.finished.depth_over_mm(model.GRAY_C), 1),
                             round(classic.finished.depth_over_mm(TARGET + 2), 1), round(own.minutes), round(own.pulled.core, 1),
                             round(landed, 1)])
        section(f'Sear sweep, {name}',
                table(['sear', 'seconds a side', 'heat in, kJ/m2', 'classic carryover C', 'gray band mm', 'past target mm',
                       'pull +3 C at, min', 'pull core C', 'planner\'s pull lands at C'], rows),
                f'The planner pulls at {planned.minutes:.0f} min (core {planned.pulled.core:.1f} C) expecting {TARGET - 0.5:g} C. '
                'The last column is where the core really peaks if the sear is the one in that row.')


def rest() -> None:
    rows = []
    for label, changes in (('still air, h 10', {}), ('h 5', {'h_air': 5.0}), ('h 20 (draught, wet surface)', {'h_air': 20.0}),
                           ('h 40 (on a cold plate, or fanned)', {'h_air': 40.0})):
        for name, steak in (('ribeye', RIBEYE), ('25 mm', STRIP)):
            real = replace(steak, physics=replace(PHYSICS, **changes))
            classic = model.classic(real, TARGET, Finish(45))
            trace = model.trace(real, TARGET, classic, Finish(45), every_s=5.0)
            finish = [p for p in trace if p['phase'] == 'finish']
            peak_at = max(finish, key=lambda p: p['core'])['min'] - classic.minutes
            rows.append([label, name, round(classic.core_peak_c - classic.pulled.core, 1), round(peak_at, 1)])
    section('The rest', table(['air', 'steak', 'classic carryover C', 'core peaks, min after the pull'], rows))


if __name__ == '__main__':
    print('# Sear and rest\n')
    sweep()
    rest()
