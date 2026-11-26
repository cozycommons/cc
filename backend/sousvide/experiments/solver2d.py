"""A 2-D heat-conduction solver for the offline experiments. Not used by the API.

It solves rho*c*dT/dt = div(k grad T) on a rectangle in (x, z): a cut through a
steak's width and thickness, or, with axisymmetric=True, the (r, z) half-plane
of a round puck. Each side takes its own outside temperature and coefficient,
and k and rho*c can differ per element, which is what the shipped 1-D model
cannot do: a sear on the faces only, or a bone next to the meat.

The grid is vertex-centred, like model.Axis: nodes sit on the boundaries and
own half-width control volumes there. Material is per element (the rectangle
between four nodes), so a bone's edge lies on a node line and conductances
along it add in parallel. Time stepping is Douglas-Rachford ADI: implicit in x,
then implicit in z, each a set of tridiagonal solves. It is unconditionally
stable and damps stiff modes like backward Euler, with an extra splitting
error of order dt^2 that check_solver2d.py measures against the series solution.

Pure Python on purpose: the backend's dependency policy makes numpy more
trouble than the few minutes these runs take.
"""
from __future__ import annotations

from dataclasses import dataclass

Side = tuple[float, float] | None  # (h in W/(m^2 K), outside temperature in C), or None for insulated


@dataclass
class Sides:
    x0: Side = None  # x = xs[0]: the symmetry plane or axis unless given
    x1: Side = None  # x = xs[-1]: the steak's edge
    z0: Side = None  # z = zs[0]: the mid-plane unless given
    z1: Side = None  # z = zs[-1]: the face


def linspace(lo: float, hi: float, n: int) -> list[float]:
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


class Solver2D:
    """Temperatures T[i][j] at node (xs[i], zs[j])."""

    def __init__(self, xs: list[float], zs: list[float], k: list[list[float]], rc: list[list[float]],
                 start_c: float, axisymmetric: bool = False):
        """k[ex][ez] and rc[ex][ez] are conductivity and rho*c of the element between nodes ex..ex+1, ez..ez+1."""
        self.xs, self.zs = xs, zs
        nx, nz = len(xs), len(zs)
        self.nx, self.nz = nx, nz
        xm = [(a + b) / 2 for a, b in zip(xs, xs[1:])]  # element midpoints: control-volume faces
        zm = [(a + b) / 2 for a, b in zip(zs, zs[1:])]

        def span(lo: float, hi: float) -> float:  # area of [lo, hi] along x, per unit length or per radian
            return (hi * hi - lo * lo) / 2 if axisymmetric else hi - lo
        # wx[i][s]: the part of node i's control volume inside element i-1 (s=0) or i (s=1).
        wx = [[span(xm[i - 1], xs[i]) if i else 0.0, span(xs[i], xm[i]) if i < nx - 1 else 0.0] for i in range(nx)]
        wz = [[zs[j] - zm[j - 1] if j else 0.0, zm[j] - zs[j] if j < nz - 1 else 0.0] for j in range(nz)]
        face_x = [xm[i] if axisymmetric else 1.0 for i in range(nx - 1)]
        self.edge_x = [xs[0] if axisymmetric else 1.0, xs[-1] if axisymmetric else 1.0]

        def elements(i: int, j: int):
            for s, ex in ((0, i - 1), (1, i)):
                for t, ez in ((0, j - 1), (1, j)):
                    if 0 <= ex < nx - 1 and 0 <= ez < nz - 1:
                        yield ex, ez, wx[i][s], wz[j][t]
        self.C = [[sum(rc[ex][ez] * a * b for ex, ez, a, b in elements(i, j)) for j in range(nz)] for i in range(nx)]
        # gx[i][j] joins (i, j) to (i+1, j); gz[i][j] joins (i, j) to (i, j+1).
        self.gx = [[sum(k[i][ez] * wz[j][t] for t, ez in ((0, j - 1), (1, j)) if 0 <= ez < nz - 1)
                    * face_x[i] / (xs[i + 1] - xs[i]) for j in range(nz)] for i in range(nx - 1)]
        self.gz = [[sum(k[ex][j] * wx[i][s] for s, ex in ((0, i - 1), (1, i)) if 0 <= ex < nx - 1)
                    / (zs[j + 1] - zs[j]) for j in range(nz - 1)] for i in range(nx)]
        self.area_x = [sum(wz[j]) for j in range(nz)]  # of an x-side, owned by row j (times edge_x)
        self.area_z = [sum(wx[i]) for i in range(nx)]  # of a z-side, owned by column i
        self.T = [[start_c] * nz for _ in range(nx)]
        self.peak = [list(row) for row in self.T]
        self._setup: tuple | None = None
        self._key: tuple | None = None

    def _prepare(self, sides: Sides, dt: float):
        nx, nz, C, gx, gz = self.nx, self.nz, self.C, self.gx, self.gz
        hx0, tx0 = sides.x0 or (0.0, 0.0)
        hx1, tx1 = sides.x1 or (0.0, 0.0)
        hz0, tz0 = sides.z0 or (0.0, 0.0)
        hz1, tz1 = sides.z1 or (0.0, 0.0)
        bx0 = [hx0 * self.edge_x[0] * a for a in self.area_x]
        bx1 = [hx1 * self.edge_x[1] * a for a in self.area_x]
        bz0 = [hz0 * a for a in self.area_z]
        bz1 = [hz1 * a for a in self.area_z]
        # Heat arriving from outside per second, by node.
        source = [[0.0] * nz for _ in range(nx)]
        for j in range(nz):
            source[0][j] += bx0[j] * tx0
            source[-1][j] += bx1[j] * tx1
        for i in range(nx):
            source[i][0] += bz0[i] * tz0
            source[i][-1] += bz1[i] * tz1
        # Thomas factors for each x-line (fixed j) and each z-line (fixed i).
        x_lines = []
        for j in range(nz):
            off = [dt * gx[i][j] for i in range(nx - 1)]
            diag = [C[i][j] + (off[i - 1] if i else 0.0) + (off[i] if i < nx - 1 else 0.0) for i in range(nx)]
            diag[0] += dt * bx0[j]
            diag[-1] += dt * bx1[j]
            x_lines.append(_factor(diag, off))
        z_lines = []
        for i in range(nx):
            off = [dt * gz[i][j] for j in range(nz - 1)]
            diag = [C[i][j] + (off[j - 1] if j else 0.0) + (off[j] if j < nz - 1 else 0.0) for j in range(nz)]
            diag[0] += dt * bz0[i]
            diag[-1] += dt * bz1[i]
            z_lines.append(_factor(diag, off))
        return bz0, bz1, source, x_lines, z_lines

    def step(self, sides: Sides, dt: float, track_peak: bool = False) -> None:
        key = (sides.x0, sides.x1, sides.z0, sides.z1, dt)
        if key != self._key:
            self._setup, self._key = self._prepare(sides, dt), key
        bz0, bz1, source, x_lines, z_lines = self._setup
        nx, nz, C, gz, T = self.nx, self.nz, self.C, self.gz, self.T
        # kz[i][j]: heat leaving node (i, j) along z per second, at the old temperatures.
        kz = []
        for i in range(nx):
            t, g = T[i], gz[i]
            row = [0.0] * nz
            for j in range(nz - 1):
                flow = g[j] * (t[j] - t[j + 1])
                row[j] += flow
                row[j + 1] -= flow
            row[0] += bz0[i] * t[0]
            row[-1] += bz1[i] * t[-1]
            kz.append(row)
        # Implicit in x.
        star = [[0.0] * nz for _ in range(nx)]
        for j in range(nz):
            w, inv, off = x_lines[j]
            d = [C[i][j] * T[i][j] + dt * (source[i][j] - kz[i][j]) for i in range(nx)]
            for i in range(1, nx):
                d[i] -= w[i] * d[i - 1]
            prev = d[-1] * inv[-1]
            star[-1][j] = prev
            for i in range(nx - 2, -1, -1):
                prev = (d[i] + off[i] * prev) * inv[i]
                star[i][j] = prev
        # Implicit in z.
        for i in range(nx):
            w, inv, off = z_lines[i]
            c, s, q = C[i], star[i], kz[i]
            d = [c[j] * s[j] + dt * q[j] for j in range(nz)]
            for j in range(1, nz):
                d[j] -= w[j] * d[j - 1]
            out = [0.0] * nz
            out[-1] = d[-1] * inv[-1]
            for j in range(nz - 2, -1, -1):
                out[j] = (d[j] + off[j] * out[j + 1]) * inv[j]
            T[i] = out
        if track_peak:
            self.peak = [[max(p, t) for p, t in zip(pr, tr)] for pr, tr in zip(self.peak, T)]

    def run(self, sides: Sides, seconds: float, dt: float, track_peak: bool = False) -> None:
        for _ in range(round(seconds / dt)):
            self.step(sides, dt, track_peak)


def _factor(diag: list[float], off: list[float]) -> tuple[list[float], list[float], list[float]]:
    """Thomas elimination of the symmetric tridiagonal matrix with diagonal diag and off-diagonals -off."""
    n = len(diag)
    b = list(diag)
    w = [0.0] * n
    for i in range(1, n):
        w[i] = -off[i - 1] / b[i - 1]
        b[i] += w[i] * off[i - 1]
    return w, [1.0 / x for x in b], off


def uniform(nx: int, nz: int, value: float) -> list[list[float]]:
    return [[value] * (nz - 1) for _ in range(nx - 1)]
