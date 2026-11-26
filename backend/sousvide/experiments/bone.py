"""Question 2: how much does a bone slow or speed the meat next to it?

The cut is a cross-section through width (x) and thickness (z), long in the
third direction, as a rib or a T-bone's stem is. Bone is a region with its own
k and rho*c. Every case is compared with three boneless answers the planner
could give instead: the infinite slab, the meat alone with its edge in the
water where the bone was, and the bone counted as more meat.

Run from backend/: python -m sousvide.experiments.bone
"""
from __future__ import annotations

from dataclasses import dataclass

from sousvide import model
from sousvide.model import Finish, Steak

from .common import PHYSICS, classic_minutes, pct, section, table
from .solver2d import Sides, Solver2D, linspace

TARGET = 54.5
START = 5.0
NZ = 20


@dataclass(frozen=True)
class Material:
    k: float  # W/(m K)
    rc: float  # rho * c, J/(m^3 K)


MEAT = Material(PHYSICS.conductivity, PHYSICS.conductivity / PHYSICS.diffusivity)
"""The planner's own beef: k 0.46, rho*c 3.83e6 (k / alpha)."""

CORTICAL = Material(0.54, 1800 * 1260)
"""Dense (cortical) bovine bone, from the sourced literature report for this work: k 0.54 W/(m K)
(directional measurements 0.53 to 0.58, one study 0.64), rho 1800 kg/m^3, cp 1.26 kJ/(kg K),
so alpha is about 2.4e-7, twice the meat's."""

MARROW_K = (0.22, 0.42)
"""Marrow conductivity, W/(m K). The report's sources disagree across this range."""

MARROW = Material(sum(MARROW_K) / 2, 980 * 2070)
"""Marrow, from the same report: rho about 980 kg/m^3, cp about 2.07 kJ/(kg K), k mid-range."""

FAT = Material(0.21, 0.21 / 1.05e-7)
"""Beef fat, from the same report: k 0.19 to 0.23, alpha 0.9e-7 to 1.2e-7. Mid-range of both."""

RANGE = {'low k, low rho*c': Material(0.2, 1.8e6), 'low k, high rho*c': Material(0.2, 3.2e6),
         'high k, low rho*c': Material(0.7, 1.8e6), 'high k, high rho*c': Material(0.7, 3.2e6)}
"""Corners well outside the sourced values, to show how little the answer depends on the constants."""

SHELL_MM = 2.0
"""Cortical wall around a rib's marrow core. Assumed, not sourced; the solid-cortical and
marrow-core cases bracket it."""


def marrow_bone(width_mm: float, marrow: Material = MARROW) -> list[tuple[float, Material]]:
    return [(SHELL_MM, CORTICAL), (width_mm - 2 * SHELL_MM, marrow), (SHELL_MM, CORTICAL)]


class Cut:
    """Segments of (width_mm, material) side by side along x, heated through the faces and the open edges.

    x=0 is always an open edge. The far side is open too, unless mirror=True makes
    it a symmetry plane (half of a steak with the bone through its middle).
    """

    def __init__(self, thickness_mm: float, segments: list[tuple[float, Material]], bone_thickness_mm: float | None = None,
                 start_c: float = START, mirror: bool = False):
        self.thickness_mm, self.mirror = thickness_mm, mirror
        xs, materials, self.meat_spans = [0.0], [], []
        for width, material in segments:
            n = max(2, round(width))  # about 1 mm elements
            start = xs[-1]
            xs += [start + width / 1000 * (i + 1) / n for i in range(n)]
            materials += [material] * n
            if material is MEAT:
                self.meat_spans.append((start, xs[-1]))
        zs = linspace(0, thickness_mm / 2000, NZ)
        bone_half = (bone_thickness_mm or thickness_mm) / 2000
        # Above a bone thinner than the steak, the element is meat.
        def at(material: Material, ez: int) -> Material:
            return material if material is MEAT or (zs[ez] + zs[ez + 1]) / 2 < bone_half else MEAT
        self.solver = Solver2D(xs, zs, [[at(m, ez).k for ez in range(NZ - 1)] for m in materials],
                               [[at(m, ez).rc for ez in range(NZ - 1)] for m in materials], start_c)
        # Mid-plane nodes of meat: inside a meat segment or on an open edge of one, not on a seam.
        ends = [0.0] if mirror else [0.0, xs[-1]]
        self.meat_nodes = [i for i, x in enumerate(xs)
                           if any(a < x < b or (x in ends and a - 1e-12 <= x <= b + 1e-12) for a, b in self.meat_spans)]

    def sides(self, face: tuple[float, float], edge: tuple[float, float]) -> Sides:
        return Sides(x0=edge, x1=None if self.mirror else edge, z1=face)

    def node_near(self, x_mm: float) -> int:
        return min(self.meat_nodes, key=lambda n: abs(self.solver.xs[n] * 1000 - x_mm))

    def classic(self) -> tuple[float, float, dict[int, float]]:
        """Minutes until every mid-plane meat node is within 0.5 C of the bath, where the last one is,
        and the minute each mid-plane node got there."""
        s, goal = self.solver, TARGET - model.READY_WITHIN_C
        bath = (PHYSICS.h_bath, TARGET)
        sides = self.sides(bath, bath)
        reached: dict[int, float] = {}
        t = 0.0
        while len(reached) < len(self.meat_nodes):
            s.step(sides, model.BATH_STEP_S)
            t += model.BATH_STEP_S
            for i in self.meat_nodes:
                if i not in reached and s.T[i][0] >= goal:
                    reached[i] = t / 60
        last = max(reached, key=reached.get)
        return reached[last], s.xs[last] * 1000, reached

    def minute_near(self, reached: dict[int, float], x_mm: float) -> float:
        return reached[self.node_near(x_mm)]


def edge_bone() -> None:
    """A rib along one edge: meat from x=0 to W, then the bone, its outer edge in the water."""
    rows = []
    W = 110.0
    cases = [(t, b, name, bone, None) for t in (25, 38, 50) for b in (15,) for name, bone in
             (('cortical', lambda b: [(b, CORTICAL)]), ('marrow core', marrow_bone))]
    cases += [(38, 30, 'cortical', lambda b: [(b, CORTICAL)], None), (38, 30, 'marrow core', marrow_bone, None),
              (38, 15, 'cortical, 20 mm thick', lambda b: [(b, CORTICAL)], 20.0),
              (50, 15, 'cortical, 25 mm thick', lambda b: [(b, CORTICAL)], 25.0)]
    cases += [(38, 15, name, (lambda m: lambda b: [(b, m)])(m), None) for name, m in RANGE.items()]
    for t, b, name, bone, bone_t in cases:
        cut = Cut(t, [(W, MEAT)] + bone(b), bone_t)
        minutes, where, reached = cut.classic()
        slab = classic_minutes(Steak(t))
        alone = classic_minutes(Steak(t, width_mm=W))
        as_meat = classic_minutes(Steak(t, width_mm=W + b))
        # Meat 3 mm from the bone against meat 3 mm from the open edge.
        rows.append([t, b, name, round(minutes, 1), round(where), round(slab, 1), pct(slab, minutes),
                     round(alone, 1), pct(alone, minutes), round(as_meat, 1), pct(as_meat, minutes),
                     round(cut.minute_near(reached, W - 3), 1), round(cut.minute_near(reached, 3), 1)])
    section('Bone along one edge of 110 mm of meat',
            table(['thickness mm', 'bone mm', 'bone', 'last meat ready, min', 'at x mm', 'slab min', '% off', 'meat alone min',
                   '% off', 'bone as meat min', '% off', 'meat 3 mm from bone, min', 'meat 3 mm from open edge, min'], rows),
            'Classic bath at 54.5 C from 5 C. "% off" is the boneless answer against the 2-D truth with the bone '
            '(positive: the boneless answer is too long). x runs from the open edge (0) to the bone (110).')


def middle_bone() -> None:
    """A T-bone's stem: strip on one side, tenderloin on the other."""
    rows = []
    for t, strip, b, loin in ((38, 80, 8, 45), (50, 80, 8, 45), (38, 80, 15, 45)):
        for name, bone in (('cortical', [(b, CORTICAL)]), ('marrow core', marrow_bone(b))):
            cut = Cut(t, [(strip, MEAT)] + bone + [(loin, MEAT)])
            minutes, where, reached = cut.classic()
            slab = classic_minutes(Steak(t))
            as_meat = classic_minutes(Steak(t, width_mm=strip + b + loin))
            loin_alone = classic_minutes(Steak(t, width_mm=loin))
            loin_minutes = max(v for i, v in reached.items() if cut.solver.xs[i] * 1000 > strip + b)
            rows.append([t, f'{strip} | {b} | {loin}', name, round(minutes, 1), round(where), round(slab, 1), pct(slab, minutes),
                         round(as_meat, 1), pct(as_meat, minutes), round(loin_minutes, 1), round(loin_alone, 1)])
    section('Bone in the middle (T-bone stem)',
            table(['thickness mm', 'strip | bone | tenderloin mm', 'bone', 'last meat ready, min', 'at x mm', 'slab min', '% off',
                   'bone as meat min', '% off', 'tenderloin side ready, min', 'tenderloin alone, min'], rows))


def pulled_early() -> None:
    """Out of equilibrium (hot bath, pulled early) the bone matters most. How far behind is the meat beside it?"""
    rows = []
    W, b = 110.0, 15.0
    for t in (25, 38, 50):
        for boost in (3.0, 8.0):
            plan = model.hot_and_pull(Steak(t, width_mm=W + b), TARGET, boost, Finish(0))
            for name, bone in (('cortical', [(b, CORTICAL)]), ('marrow core', marrow_bone(b))):
                cut = Cut(t, [(W, MEAT)] + bone)
                s = cut.solver
                bath = (PHYSICS.h_bath, TARGET + boost)
                s.run(cut.sides(bath, bath), plan.minutes * 60, model.BATH_STEP_S)
                mid = [s.T[i][0] for i in cut.meat_nodes]
                rows.append([t, f'+{boost:g}', name, round(plan.minutes, 1), round(plan.pulled.core, 2), round(min(mid), 2),
                             round(s.T[cut.node_near(W - 3)][0], 2), round(s.T[cut.node_near(3)][0], 2)])
    section('Hot bath, pulled at the planner\'s time with the bone counted as meat',
            table(['thickness mm', 'bath', 'bone', 'pull min', 'planned core C', 'coldest meat C', 'meat 3 mm from bone C',
                   'meat 3 mm from open edge C'], rows),
            'Mid-plane temperatures at the pull, 110 mm of meat with a 15 mm bone along one edge.')


if __name__ == '__main__':
    print('# Bone-in\n')
    edge_bone()
    middle_bone()
    pulled_early()
