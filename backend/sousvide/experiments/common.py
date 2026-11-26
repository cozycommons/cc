"""Shared helpers for the experiment scripts."""
from __future__ import annotations

from sousvide import model
from sousvide.model import Finish, Physics, Steak

from .solver2d import Sides, Solver2D, linspace, uniform

PHYSICS = Physics()
NO_SEAR = Finish(0)


def table(headers: list[str], rows: list[list]) -> str:
    """A Markdown table; floats print with the precision they were rounded to."""
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |']
    lines += ['| ' + ' | '.join(str(c) for c in row) + ' |' for row in rows]
    return '\n'.join(lines)


def section(title: str, body: str, note: str = '') -> None:
    print(f'## {title}\n\n{note + chr(10) + chr(10) if note else ""}{body}\n')


def pct(new: float, old: float) -> float:
    return round(100 * (new - old) / old, 1)


def classic_minutes(steak: Steak, target_c: float = 54.5) -> float:
    return model.classic(steak, target_c, NO_SEAR).minutes


def depth_over_mm(r: list[float], peak: list[float], limit_c: float) -> float:
    """model.Body.depth_over_mm for any centre-to-surface line of peaks."""
    half, dr = r[-1], r[1] - r[0]
    inside = [x for x, p in zip(r, peak) if p <= limit_c]
    return half * 1000 if not inside else max(0.0, (half - max(inside) - dr / 2) * 1000)


def meat_section(thickness_mm: float, width_mm: float, start_c: float, nx: int = 31,
                 axisymmetric: bool = False, physics: Physics = PHYSICS) -> Solver2D:
    """A quarter of an all-meat cross-section: x from the middle to the edge, z from the mid-plane to the face."""
    xs, zs = linspace(0, width_mm / 2000, nx), linspace(0, thickness_mm / 2000, model.NODES)
    rc = physics.conductivity / physics.diffusivity
    return Solver2D(xs, zs, uniform(nx, model.NODES, physics.conductivity), uniform(nx, model.NODES, rc),
                    start_c, axisymmetric)


def everywhere(h: float, outside_c: float) -> Sides:
    return Sides(x1=(h, outside_c), z1=(h, outside_c))
