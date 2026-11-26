"""The canonical steak: a 2 inch bone-in ribeye, about 3 lb, the rib through its middle.

Size. 1.33 kg at 1050 kg/m^3 is 1,267 cm^3; at 51 mm thick that is 248 cm^2 of
footprint, taken as 180 x 140 mm.

Bone. A rib 28 mm wide crossing the full 51 mm thickness: a 2 mm cortical shell
around marrow (constants in bone.py). In the primary layout it runs the 180 mm
length through the middle of the 140 mm width, leaving 56 mm of meat each side.
The other layouts move it: across the length (76 mm of meat each side), along
one edge (where a rib usually sits on a ribeye), and behind a 6 mm fat seam.

Truth. A 2-D solve of the cut across the bone (width x thickness), times the
1-D solution along the bone's length. The product is exact in the bath for
uniform meat; the bone's different alpha along its own length is neglected.
The finish is split the way model.Finish.run splits it: the cut uniformly at
bath temperature going through the sear (faces to the pan, edges in air) and
the rest, plus the shortfall at the pull relaxing with nothing heating it.

Run from backend/: python -m sousvide.experiments.ribeye
"""
from __future__ import annotations

from sousvide import model
from sousvide.model import Finish, Steak

from .bone import CORTICAL, FAT, MARROW, MARROW_K, MEAT, SHELL_MM, Cut, Material
from .common import PHYSICS, pct, section, table

THICKNESS_MM = 51.0
MASS_KG = 1.33
DENSITY = 1050.0  # kg/m^3, whole steak; relayed with the canonical case
LENGTH_MM, WIDTH_MM = 180.0, 140.0
BONE_MM = 28.0
START_C = 5.0
TARGET_C = 54.5
SEAR = Finish(45)
GOAL_C = TARGET_C - model.READY_WITHIN_C
OVER_C = TARGET_C + model.OVERCOOKED_BY_C


def half_bone(marrow: Material | None) -> list[tuple[float, Material]]:
    """From the bone's surface to its centre line."""
    if marrow is None:
        return [(BONE_MM / 2, CORTICAL)]
    return [(SHELL_MM, CORTICAL), (BONE_MM / 2 - SHELL_MM, marrow)]


def whole_bone(marrow: Material | None) -> list[tuple[float, Material]]:
    return half_bone(marrow) + half_bone(marrow)[::-1]


MARROW_LOW, MARROW_HIGH = Material(MARROW_K[0], MARROW.rc), Material(MARROW_K[1], MARROW.rc)

# name: (segments from the open edge, mirror at the far side, length along the bone in mm)
LAYOUTS = {
    'bone along the length, through the middle': lambda m: ([((WIDTH_MM - BONE_MM) / 2, MEAT)] + half_bone(m), True, LENGTH_MM),
    'bone across the length, through the middle': lambda m: ([((LENGTH_MM - BONE_MM) / 2, MEAT)] + half_bone(m), True, WIDTH_MM),
    'bone along one edge': lambda m: ([(WIDTH_MM - BONE_MM, MEAT)] + whole_bone(m), False, LENGTH_MM),
    'through the middle, 6 mm fat seam beside it': lambda m: ([((WIDTH_MM - BONE_MM) / 2 - 6, MEAT), (6, FAT)] + half_bone(m), True, LENGTH_MM),
    'no bone (all meat)': lambda m: ([(WIDTH_MM / 2, MEAT)], True, LENGTH_MM),
}
PRIMARY = 'bone along the length, through the middle'


class Ribeye:
    """One layout in the bath and through the finish. Temperatures are on the cut through the middle of the length."""

    def __init__(self, layout: str, marrow: Material | None = MARROW):
        self.segments, self.mirror, self.along_mm = LAYOUTS[layout](marrow)
        self.axis = model.axis(self.along_mm / 2000, 0, model.SIDE_NODES, PHYSICS.conductivity, PHYSICS.diffusivity)
        self.meat_end_mm = self.segments[0][0]  # where the first meat segment stops: a seam, the bone, or the mirror

    def cut(self, start_c: float) -> Cut:
        return Cut(THICKNESS_MM, self.segments, start_c=start_c, mirror=self.mirror)

    def bath(self, bath_c: float, keep_every_s: float | None = None):
        """Cook until the coldest mid-plane meat is within 0.5 C of the target.

        Returns (minutes, cut, along, snapshots). The cut holds the shortfall below
        the bath; times `along` (the field along the bone's length) it is the meat's
        temperature minus bath_c.
        """
        cut = self.cut(START_C - bath_c)
        s, along = cut.solver, self.axis.ones
        sides = cut.sides((PHYSICS.h_bath, 0.0), (PHYSICS.h_bath, 0.0))
        t, snapshots = 0.0, []
        while bath_c + min(s.T[i][0] for i in cut.meat_nodes) * along[0] < GOAL_C:
            s.step(sides, model.BATH_STEP_S)
            along = self.axis.relax(along, PHYSICS.h_bath, model.BATH_STEP_S)
            t += model.BATH_STEP_S
            if keep_every_s and t % keep_every_s == 0:
                snapshots.append((t / 60, [list(row) for row in s.T], along))
        return t / 60, cut, along, snapshots

    def uniform_finish(self, bath_c: float) -> list[list[list[float]]]:
        """The cut, uniformly at bath_c, after each step of the sear and rest."""
        cut = self.cut(bath_c)
        out = []
        for resting, outside_c, h, _, dt in SEAR.steps(PHYSICS):
            air = (PHYSICS.h_air, PHYSICS.air_c)
            cut.solver.step(cut.sides(air if resting else (h, outside_c), air), dt)
            out.append([list(row) for row in cut.solver.T])
        return out

    def finish(self, bath_c: float, shortfall: list[list[float]], along: list[float], uniform: list[list[list[float]]]):
        """Peak temperature of every node from the pull to the end of the rest, as a field."""
        cut = self.cut(0.0)
        s = cut.solver
        s.T = [list(row) for row in shortfall]
        peak = [[bath_c + v * along[0] for v in row] for row in s.T]
        for (resting, _, h, side_h, dt), base in zip(SEAR.steps(PHYSICS), uniform):
            s.step(cut.sides((h, 0.0), (PHYSICS.h_air, 0.0)), dt)
            along = self.axis.relax(along, side_h, dt)
            a = along[0]
            peak = [[max(p, u + v * a) for p, u, v in zip(pr, ur, vr)] for pr, ur, vr in zip(peak, base, s.T)]
        return cut, peak

    def pull(self, boost_c: float):
        """Earliest whole minute at which the sear and rest carry the meat that is coldest at the pull to the target."""
        bath_c = TARGET_C + boost_c
        _, _, _, snapshots = self.bath(bath_c, keep_every_s=60.0)
        uniform = self.uniform_finish(bath_c)

        def run(i: int):
            minute, shortfall, along = snapshots[i]
            cut, peak = self.finish(bath_c, shortfall, along, uniform)
            return minute, shortfall, along, cut, peak
        lo, hi = 0, len(snapshots) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            _, shortfall, _, cut, peak = run(mid)
            # Judge the meat that was coldest at the pull. Meat near the open edge was warmer
            # then but gains nothing from the sear, and would hold a +0 C bath to the classic time.
            if peak[min(cut.meat_nodes, key=lambda i: shortfall[i][0])][0] >= GOAL_C:
                hi = mid
            else:
                lo = mid + 1
        return run(lo)


def depth_from(distances_mm: list[float], peaks: list[float], limit_c: float) -> float:
    """How far past limit_c reaches along a line of nodes ordered from a surface inward."""
    for k, p in enumerate(peaks):
        if p <= limit_c:
            return 0.0 if k == 0 else round((distances_mm[k - 1] + distances_mm[k]) / 2, 1)
    return round(distances_mm[-1], 1)


def describe(cut: Cut, ribeye: Ribeye, x_mm: float) -> str:
    if ribeye.meat_end_mm - x_mm < 0.75:
        return 'against the bone'
    return f'{round(ribeye.meat_end_mm - x_mm)} mm from the bone'


def planner(boost_c: float | None, steak: Steak) -> model.Cook:
    return model.classic(steak, TARGET_C, SEAR) if boost_c is None else model.hot_and_pull(steak, TARGET_C, boost_c, SEAR)


BOX = Steak(THICKNESS_MM, width_mm=WIDTH_MM, length_mm=LENGTH_MM)  # the bone counted as meat
RULE = Steak(THICKNESS_MM, width_mm=WIDTH_MM, length_mm=LENGTH_MM, bone='middle', bone_mm=BONE_MM)  # what ships
SLAB = Steak(THICKNESS_MM)


def classic_by_layout() -> None:
    rows = []
    variants = [(PRIMARY, name, m) for name, m in (('marrow core', MARROW), ('marrow k 0.22', MARROW_LOW),
                                                   ('marrow k 0.42', MARROW_HIGH), ('solid cortical', None))]
    variants += [(layout, 'marrow core', MARROW) for layout in LAYOUTS if layout != PRIMARY]
    box, slab, rule = planner(None, BOX).minutes, planner(None, SLAB).minutes, planner(None, RULE).minutes
    for layout, name, marrow in variants:
        ribeye = Ribeye(layout, marrow)
        minutes, cut, along, _ = ribeye.bath(TARGET_C)
        s = cut.solver
        coldest = min(cut.meat_nodes, key=lambda i: s.T[i][0])
        temp = lambda x_mm: TARGET_C + s.T[cut.node_near(x_mm)][0] * along[0]
        end = ribeye.meat_end_mm
        rows.append([layout, name if 'no bone' not in layout else '', round(minutes), describe(cut, ribeye, s.xs[coldest] * 1000),
                     round(temp(end / 2) - GOAL_C, 2), round(temp(end - 5) - GOAL_C, 2),
                     round(rule), pct(rule, minutes), round(box), pct(box, minutes), round(slab), pct(slab, minutes)])
    section('Classic: bath at 54.5 C until the coldest meat is at 54.0 C',
            table(['layout', 'bone', 'minutes', 'coldest meat, mid-thickness', 'meat mid-lobe reads, C over coldest',
                   '5 mm from bone reads, C over coldest', 'planner, bone in the middle, min', '% off',
                   'bone as meat (180 x 140 box) min', '% off', '51 mm slab min', '% off'], rows),
            '"% off" is positive when the simpler model is too long. The lobe is the meat between the open edge and the bone. '
            'The planner column is its middle-bone rule; for the bone along one edge the planner uses the box instead.')


def pull_by_boost() -> None:
    rows, depths = [], []
    ribeye = Ribeye(PRIMARY)
    for boost in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0):
        minute, shortfall, along, cut, peak = ribeye.pull(boost)
        s, bath_c = cut.solver, TARGET_C + boost
        at_pull = lambda i: bath_c + shortfall[i][0] * along[0]
        coldest = min(cut.meat_nodes, key=lambda i: shortfall[i][0])
        box, slab, rule = planner(boost, BOX), planner(boost, SLAB), planner(boost, RULE)
        rows.append([f'+{boost:g}', round(minute), describe(cut, ribeye, s.xs[coldest] * 1000), round(at_pull(coldest), 1),
                     round(peak[coldest][0], 2), round(rule.minutes), pct(rule.minutes, minute), round(rule.pulled.core, 1),
                     round(box.minutes), pct(box.minutes, minute), round(slab.minutes), pct(slab.minutes, minute)])
        mm = [x * 1000 for x in s.xs]
        zs_in = [(s.zs[-1] - z) * 1000 for z in reversed(s.zs)]
        lobe, by_bone, seam = cut.node_near(ribeye.meat_end_mm / 2), cut.node_near(ribeye.meat_end_mm - 3), cut.node_near(ribeye.meat_end_mm)
        from_bone = [ribeye.meat_end_mm - x for x in reversed(mm[:seam + 2])]
        depths.append([f'+{boost:g}',
                       depth_from(zs_in, peak[lobe][::-1], OVER_C), depth_from(zs_in, peak[by_bone][::-1], OVER_C),
                       depth_from(mm, [row[0] for row in peak], OVER_C),
                       depth_from(from_bone, [peak[i][0] for i in range(seam + 1, -1, -1)], OVER_C),
                       depth_from(zs_in, peak[lobe][::-1], model.GRAY_C),
                       round(rule.finished.depth_over_mm(OVER_C), 1), round(rule.finished.depth_over_mm(model.GRAY_C), 1)])
    section('Hot, then pull: the primary layout with a 45 s sear a side',
            table(['bath', 'pull, min', 'coldest meat at pull', 'it reads, C', 'it finishes at, C',
                   'planner min', '% off', 'planner pull core C', 'bone as meat min', '% off', '51 mm slab min', '% off'], rows),
            'The pull is the first whole minute at which the sear and rest carry the meat that is coldest at the pull to 54.0 C.')
    section('Meat past target + 2 C (56.5 C) after the sear and rest, mm',
            table(['bath', 'under the open face, mid-lobe', 'under the face, 3 mm from the bone', 'in from the open edge, mid-thickness',
                   'out from the bone, mid-thickness', 'gray band (65 C) under the face', 'planner past target', 'planner gray'], depths),
            'Depths at the pull times above. The bone side is measured from the bone into the meat along the mid-plane.')


def probe() -> None:
    """What a misplaced probe reads at the pull, +3 C."""
    ribeye = Ribeye(PRIMARY)
    minute, shortfall, along, cut, _ = ribeye.pull(3.0)
    s, bath_c = cut.solver, TARGET_C + 3.0
    rows = []
    coldest = min(shortfall[i][0] for i in cut.meat_nodes)
    for label, x_mm, j in (('mid-thickness, against the bone', ribeye.meat_end_mm - 1, 0), ('mid-thickness, 10 mm from the bone', ribeye.meat_end_mm - 10, 0),
                           ('mid-thickness, mid-lobe (28 mm from the bone)', ribeye.meat_end_mm / 2, 0),
                           ('mid-thickness, 10 mm in from the open edge', 10, 0),
                           ('5 mm off mid-thickness, 10 mm from the bone', ribeye.meat_end_mm - 10, round(5 / (THICKNESS_MM / 2) * (len(s.zs) - 1))),
                           ('10 mm off mid-thickness, 10 mm from the bone', ribeye.meat_end_mm - 10, round(10 / (THICKNESS_MM / 2) * (len(s.zs) - 1)))):
        value = shortfall[cut.node_near(x_mm)][j]
        rows.append([label, round(bath_c + value * along[0], 1), round((value - coldest) * along[0], 1)])
    section(f'What the probe reads at the +3 C pull ({minute:.0f} min), by where its tip is',
            table(['tip', 'reads, C', 'over the coldest meat, C'], rows))


def rule_check() -> None:
    """The shipped middle-bone rule against the 2-D truth, away from the steak it was fitted on."""
    rows = []
    for t, width, length, bone_mm in ((51, 140, 180, 28), (51, 140, 180, 15), (51, 140, 180, 40), (38, 140, 180, 28),
                                      (38, 110, 150, 15), (51, 180, 140, 28), (64, 150, 200, 28), (25, 120, 160, 15)):
        row = [t, f'{width} x {length}', bone_mm]
        rule = planner(None, Steak(t, width_mm=width, length_mm=length, bone='middle', bone_mm=bone_mm)).minutes
        for marrow in (MARROW, MARROW_LOW, MARROW_HIGH, None):
            core = [(bone_mm / 2, CORTICAL)] if marrow is None else [(SHELL_MM, CORTICAL), (bone_mm / 2 - SHELL_MM, marrow)]
            cut = Cut(t, [((width - bone_mm) / 2, MEAT)] + core, start_c=START_C - TARGET_C, mirror=True)
            axis = model.axis(length / 2000, 0, model.SIDE_NODES, PHYSICS.conductivity, PHYSICS.diffusivity)
            s, along, seconds = cut.solver, axis.ones, 0.0
            sides = cut.sides((PHYSICS.h_bath, 0.0), (PHYSICS.h_bath, 0.0))
            while TARGET_C + min(s.T[i][0] for i in cut.meat_nodes) * along[0] < GOAL_C:
                s.step(sides, model.BATH_STEP_S)
                along = axis.relax(along, PHYSICS.h_bath, model.BATH_STEP_S)
                seconds += model.BATH_STEP_S
            row += [round(seconds / 60), pct(rule, seconds / 60)]
        rows.append(row + [round(rule)])
    section('The middle-bone rule on other steaks (classic minutes)',
            table(['thickness mm', 'width x length mm', 'bone mm', 'marrow core', 'rule % off', 'marrow k 0.22', 'rule % off',
                   'marrow k 0.42', 'rule % off', 'solid cortical', 'rule % off', 'rule min'], rows),
            f'The rule narrows the width by {model.BONE_MIDDLE_FACTOR:g} bone widths. Positive: the rule is too long.')


if __name__ == '__main__':
    print('# The canonical bone-in ribeye\n')
    volume_cm3 = MASS_KG / DENSITY * 1e6
    print(f'{MASS_KG} kg at {DENSITY:g} kg/m^3 is {volume_cm3:.0f} cm^3; at {THICKNESS_MM:g} mm thick, '
          f'{volume_cm3 / (THICKNESS_MM / 10):.0f} cm^2 of footprint, taken as {LENGTH_MM:g} x {WIDTH_MM:g} mm. '
          f'From {START_C:g} C to {TARGET_C:g} C.\n')
    classic_by_layout()
    pull_by_boost()
    probe()
    rule_check()
