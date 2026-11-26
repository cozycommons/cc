"""Question 1: when does the infinite slab stop being accurate, and what should replace it?

Run from backend/: python -m sousvide.experiments.finite_size
"""
from __future__ import annotations

from sousvide import model
from sousvide.model import Body, Finish, Steak

from .common import PHYSICS, classic_minutes, depth_over_mm, everywhere, meat_section, pct, section, table
from .solver2d import Sides

TARGET = 54.5
RATIOS = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0)


def slab_error() -> None:
    """How much the infinite slab overstates the time, by width / thickness."""
    def pull(steak: Steak) -> float:
        return model.hot_and_pull(steak, TARGET, 3.0, Finish(45)).minutes
    for name, minutes in (('classic, core within 0.5 C', classic_minutes), ('hot bath +3 C, pulled for a 45 s sear', pull)):
        rows = []
        for t in (20, 38, 50, 65):
            slab = minutes(Steak(t))
            for label, make in (('strip (long)', lambda w: Steak(t, width_mm=w)),
                                ('square', lambda w: Steak(t, width_mm=w, length_mm=w)),
                                ('round puck', lambda w: Steak(t, 'puck', width_mm=w))):
                rows.append([t, label, round(slab)] + [pct(slab, minutes(make(t * r))) for r in RATIOS])
        section(f'Infinite-slab time error, {name}',
                table(['thickness mm', 'outline', 'slab min'] + [f'w/t {r:g}' for r in RATIOS], rows),
                'Per cent by which the infinite slab overstates the time of the finite steak (product solution).')


def against_2d() -> None:
    """The product solution and the finish's side approximation, against a direct 2-D solve."""
    p = PHYSICS
    rows = []
    for t, w, axi in ((38, 38, False), (38, 57, False), (38, 76, False), (38, 114, False), (25, 50, False),
                      (50, 65, True), (40, 60, True), (65, 65, True)):
        steak = Steak(t, 'puck' if axi else 'slab', width_mm=w)
        for boost in (0.0, 3.0):
            cook = (model.classic if not boost else lambda s, c, f: model.hot_and_pull(s, c, boost, f))(steak, TARGET, Finish(45))
            # 2-D: the same bath for the same time, then a sear on the faces with the edge in air, then air all round.
            s = meat_section(t, w, steak.start_c, axisymmetric=axi)
            s.run(everywhere(p.h_bath, cook.bath_c), cook.minutes * 60, model.BATH_STEP_S, track_peak=True)
            pulled_2d = s.T[0][0]
            s.run(Sides(x1=(p.h_air, p.air_c), z1=(p.h_sear, p.sear_surface_c)), 45, model.SEAR_STEP_S, track_peak=True)
            top, rested = s.T[0][0], 0.0
            while rested < model.REST_MAX_S:
                before = s.T[0][0]
                s.step(everywhere(p.h_air, p.air_c), model.REST_STEP_S, track_peak=True)
                rested += model.REST_STEP_S
                top = max(top, s.T[0][0])
                if s.T[0][0] < before and rested >= 60:
                    break
            line = s.peak[0]
            done = cook.finished
            rows.append([f'{t} x {w}' + (' puck' if axi else ''), f'+{boost:g}', round(cook.minutes),
                         round(cook.pulled.core, 2), round(pulled_2d, 2), round(cook.core_peak_c, 2), round(top, 2),
                         round(done.depth_over_mm(TARGET + 2), 1), round(depth_over_mm(s.zs, line, TARGET + 2), 1),
                         round(done.depth_over_mm(model.GRAY_C), 1), round(depth_over_mm(s.zs, line, model.GRAY_C), 1)])
    section('Shipped product model against a direct 2-D solve',
            table(['steak mm', 'bath', 'bath min', 'pull core model', 'pull core 2-D', 'core peak model', 'core peak 2-D',
                   'past target mm model', '2-D', 'gray mm model', '2-D'], rows),
            'Same bath time in both. The 2-D finish sears the faces only, with the edge in 22 C air; the model '
            'insulates the edge during the sear. Depths are along the middle line.')


def outline() -> None:
    """Does the outline matter once the area is known? A round puck against boxes, and rectangles of one area."""
    rows = []
    for t, d in ((40, 60), (50, 65), (38, 90)):
        puck = classic_minutes(Steak(t, 'puck', width_mm=d))
        box = classic_minutes(Steak(t, width_mm=d, length_mm=d))
        same_area = round(d * 0.8862)
        area = classic_minutes(Steak(t, width_mm=same_area, length_mm=same_area))
        rows.append([f'{t} x {d} dia', round(puck, 1), round(box, 1), pct(box, puck), round(area, 1), pct(area, puck)])
    section('A round steak as a box', table(['puck mm', 'puck min', 'square of side d', '% off', 'square of equal area', '% off'], rows))
    rows = []
    for t, area_cm2 in ((38, 60), (38, 120), (38, 180), (25, 120), (50, 80)):
        side = (area_cm2 * 100) ** 0.5
        square = classic_minutes(Steak(t, width_mm=side, length_mm=side))
        row = [t, area_cm2, round(side), round(classic_minutes(Steak(t))), round(square, 1)]
        for aspect in (1.5, 2.0, 3.0):
            w = side / aspect ** 0.5
            row.append(pct(classic_minutes(Steak(t, width_mm=w, length_mm=w * aspect)), square))
        rows.append(row)
    section('Knowing only the plan area (from weight and thickness)',
            table(['thickness mm', 'area cm2', 'square side mm', 'slab min', 'square min', 'aspect 1.5 % off', 'aspect 2 % off', 'aspect 3 % off'], rows),
            'Classic minutes for rectangles of the same area, against the square the planner would assume.')


def edges() -> None:
    """Meat near the edge is heated from two directions. How much of the whole steak is past target?"""
    p = PHYSICS
    rows = []
    for t, w in ((38, 76), (38, 114), (50, 65)):
        for boost in (0.0, 3.0, 5.0):
            steak = Steak(t, width_mm=w)
            cook = model.hot_and_pull(steak, TARGET, boost, Finish(0))
            s = meat_section(t, w, steak.start_c)
            s.run(everywhere(p.h_bath, cook.bath_c), cook.minutes * 60, model.BATH_STEP_S, track_peak=True)
            total = sum(sum(row) for row in s.C)
            over = sum(c for crow, prow in zip(s.C, s.peak) for c, pk in zip(crow, prow) if pk > TARGET + 2)
            rows.append([f'{t} x {w}', f'+{boost:g}', round(cook.minutes), round(100 * cook.pulled.share_over(TARGET + 2), 1),
                         round(100 * over / total, 1)])
    section('Past target out of the bath: the middle line against the whole cross-section',
            table(['steak mm', 'bath', 'min', '% of middle line', '% of cross-section'], rows))


if __name__ == '__main__':
    print('# Finite size\n')
    slab_error()
    against_2d()
    outline()
    edges()
