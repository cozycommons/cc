"""Heat conduction through a steak in a water bath, a pan and the air.

The steak is a 1-D body: a slab heated through both faces (a steak wider than
about three times its thickness) or an infinite cylinder heated around its side
(a tenderloin roast). Heat moves by conduction, rho*c*dT/dt = div(k grad T),
and enters through the surface by convection, q = h*(T_outside - T_surface).
Properties are constant, the meat never freezes or loses water, and a bath
or pan change is instant.

Doneness follows the hottest temperature each layer reached: myoglobin and
myosin denature within minutes at these temperatures, so a layer that once
peaked at 60 C stays medium even after the bath drops back to 55 C.

The solver is backward Euler on a finite-volume grid. It is unconditionally
stable, so a 10 s step works for the bath and a 1 s step resolves a sear's
few millimetres. Each step solves a tridiagonal system (Thomas algorithm).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Shape = Literal['slab', 'cylinder']

# Whole-muscle beef near 55 C. Literature values for alpha run 1.1e-7 to
# 1.4e-7 m^2/s (fat lowers it a few per cent); Baldwin's tables assume about
# 1.1e-7 to 1.3e-7, so cook times here carry roughly +/-10 %.
CONDUCTIVITY = 0.46  # k, W/(m K)
DIFFUSIVITY = 1.2e-7  # alpha, m^2/s
# Surface heat transfer coefficients, W/(m^2 K). A bagged steak in a
# circulating bath sees about 95 (Baldwin). Still air around a resting steak
# is about 10. In a hot pan a wet steak's surface boils, which holds the meat
# just under the crust near 100 C while the sear lasts: the sear is modelled
# as a stiff contact (h=400) with 100 C. Heat that leaves as steam or builds
# the crust never enters the meat, so this is not the pan's temperature.
H_BATH = 95.0
H_AIR = 10.0
H_SEAR = 400.0
SEAR_SURFACE_C = 100.0
AIR_C = 22.0

NODES = 40
BATH_STEP_S = 10.0
SEAR_STEP_S = 1.0
REST_STEP_S = 5.0
REST_MAX_S = 20 * 60

READY_WITHIN_C = 0.5  # Baldwin's "core within 0.5 C of the bath"
OVERCOOKED_BY_C = 2.0  # a layer that peaked this far over the target reads as past it
GRAY_C = 65.0  # medium-well and beyond: the gray band under a sear
BOOSTS_C = (0.0, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0)
# Below 54.4 C (130 F) C. perfringens can still grow; keep those cooks under 4 h.
DANGER_C = 54.4
DANGER_HOURS = 4.0


@dataclass(frozen=True)
class Steak:
    thickness_mm: float  # slab thickness, or cylinder diameter
    shape: Shape = 'slab'
    start_c: float = 5.0

    @property
    def half_m(self) -> float:
        return self.thickness_mm / 2000.0

    @property
    def m(self) -> int:
        """Geometry exponent: 0 for a slab, 1 for a cylinder."""
        return 0 if self.shape == 'slab' else 1


class Body:
    """Temperatures on a radial grid from the centre (node 0) to the surface (node N-1)."""

    def __init__(self, steak: Steak, temps: list[float] | None = None):
        self.steak = steak
        n, m, R = NODES, steak.m, steak.half_m
        self.dr = R / (n - 1)
        self.r = [i * self.dr for i in range(n)]
        # Control volume i spans [r_i - dr/2, r_i + dr/2], clipped to [0, R],
        # with face areas and volumes per unit area (slab) or per radian-metre (cylinder).
        lo = [max(0.0, x - self.dr / 2) for x in self.r]
        hi = [min(R, x + self.dr / 2) for x in self.r]
        self.volume = [(b ** (m + 1) - a ** (m + 1)) / (m + 1) for a, b in zip(lo, hi)]
        self.face = [hi[i] ** m for i in range(n - 1)]  # between node i and i+1
        self.surface = R ** m
        self.T = list(temps) if temps else [steak.start_c] * n
        self.peak = list(self.T)

    def copy(self) -> 'Body':
        body = Body(self.steak, self.T)
        body.peak = list(self.peak)
        return body

    @property
    def core(self) -> float:
        return self.T[0]

    def step(self, outside_c: float, h: float, dt: float) -> None:
        """Advance dt seconds with the surface exposed to outside_c through coefficient h."""
        n, T = len(self.T), self.T
        g = [DIFFUSIVITY * dt * a / self.dr for a in self.face]  # conductance * dt / (rho c)
        surf = h * dt * self.surface * DIFFUSIVITY / CONDUCTIVITY  # h / (rho c) * dt * area
        # Tridiagonal system a_i T_{i-1} + b_i T_i + c_i T_{i+1} = d_i.
        a = [0.0] + [-x for x in g]
        c = [-x for x in g] + [0.0]
        b = [self.volume[i] + (g[i - 1] if i else 0.0) + (g[i] if i < n - 1 else 0.0) for i in range(n)]
        d = [self.volume[i] * T[i] for i in range(n)]
        b[-1] += surf
        d[-1] += surf * outside_c
        for i in range(1, n):
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            d[i] -= w * d[i - 1]
        T[-1] = d[-1] / b[-1]
        for i in range(n - 2, -1, -1):
            T[i] = (d[i] - c[i] * T[i + 1]) / b[i]
        self.peak = [max(p, t) for p, t in zip(self.peak, T)]

    def depth_over_mm(self, limit_c: float) -> float:
        """Depth from the surface of meat whose peak passed limit_c, per side."""
        inside = [r for r, p in zip(self.r, self.peak) if p <= limit_c]
        if not inside:
            return self.steak.half_m * 1000
        return max(0.0, (self.steak.half_m - max(inside) - self.dr / 2) * 1000)

    def share_over(self, limit_c: float) -> float:
        """Fraction of the meat (by volume) whose peak passed limit_c."""
        over = sum(v for v, p in zip(self.volume, self.peak) if p > limit_c)
        return over / sum(self.volume)


@dataclass(frozen=True)
class Finish:
    sear_s: float = 45.0  # per side; modelled as both faces at once, like flipping every 15 s

    def run(self, body: Body, record=None) -> float:
        """Sear, then rest until the core stops rising. Returns the core's highest temperature."""
        top = body.core
        t = 0.0
        while t < self.sear_s:
            body.step(SEAR_SURFACE_C, H_SEAR, SEAR_STEP_S)
            t += SEAR_STEP_S
            top = max(top, body.core)
            if record:
                record(SEAR_STEP_S, body)
        rested = 0.0
        while rested < REST_MAX_S:
            before = body.core
            body.step(AIR_C, H_AIR, REST_STEP_S)
            rested += REST_STEP_S
            top = max(top, body.core)
            if record:
                record(REST_STEP_S, body)
            if body.core < before and rested >= 60:
                break
        return top


def bath(body: Body, bath_c: float, until, limit_s: float = 24 * 3600) -> list[Body]:
    """Cook in the bath, keeping a snapshot per step, until until(body) or limit_s."""
    states = [body.copy()]
    t = 0.0
    while not until(body) and t < limit_s:
        body.step(bath_c, H_BATH, BATH_STEP_S)
        t += BATH_STEP_S
        states.append(body.copy())
    return states


def earliest(states: list[Body], finish: Finish, goal_c: float) -> int | None:
    """First snapshot index whose finished core peak reaches goal_c (monotone, so bisect)."""
    def done(i: int) -> bool:
        return finish.run(states[i].copy()) >= goal_c
    if not states or not done(len(states) - 1):
        return None
    lo, hi = 0, len(states) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if done(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


@dataclass(frozen=True)
class Cook:
    """One way to cook the steak: when to pull or switch, and what it does to the meat."""
    strategy: str
    bath_c: float
    minutes: float  # in the bath, start to pull
    pulled: Body  # straight out of the bag
    finished: Body  # after the sear and rest
    core_peak_c: float
    switch_minutes: float | None = None

    def summary(self, target_c: float) -> dict:
        over = target_c + OVERCOOKED_BY_C
        return {
            'strategy': self.strategy, 'bath_c': round(self.bath_c, 1), 'minutes': round(self.minutes, 1),
            'switch_minutes': None if self.switch_minutes is None else round(self.switch_minutes, 1),
            'core_peak_c': round(self.core_peak_c, 1),
            'bath_overcooked_mm': round(self.pulled.depth_over_mm(over), 1),
            'overcooked_mm': round(self.finished.depth_over_mm(over), 1),
            'overcooked_pct': round(100 * self.finished.share_over(over), 1),
            'gray_mm': round(self.finished.depth_over_mm(GRAY_C), 1),
        }


def finished(strategy: str, bath_c: float, states: list[Body], i: int, finish: Finish,
             switch: int | None = None) -> Cook:
    pulled = states[i]
    body = pulled.copy()
    peak = finish.run(body)
    return Cook(strategy, bath_c, i * BATH_STEP_S / 60, pulled, body, peak,
                None if switch is None else switch * BATH_STEP_S / 60)


def classic(steak: Steak, target_c: float, finish: Finish) -> Cook:
    """The baseline: bath at the target until the core is within READY_WITHIN_C, then sear."""
    goal = target_c - READY_WITHIN_C
    states = bath(Body(steak), target_c, lambda b: b.core >= goal)
    return finished('classic', target_c, states, len(states) - 1, finish)


def hot_and_pull(steak: Steak, target_c: float, boost_c: float, finish: Finish) -> Cook:
    """Bath at target + boost; pull at the first moment the sear and rest will carry the core to the target.

    With no boost this is classic sous vide pulled early, letting the sear finish the core.
    """
    goal = target_c - READY_WITHIN_C
    states = bath(Body(steak), target_c + boost_c, lambda b: b.core >= goal)
    i = earliest(states, finish, goal)
    return finished('hot_and_pull', target_c + boost_c, states, len(states) - 1 if i is None else i, finish)


def hot_then_drop(steak: Steak, target_c: float, boost_c: float, finish: Finish) -> Cook:
    """Bath at target + boost, then drop the bath to the target and hold until the core is ready.

    Switch as late as possible without the core passing target + READY_WITHIN_C in
    the bath: the fastest cook that still holds indefinitely at the target.
    """
    goal, ceiling = target_c - READY_WITHIN_C, target_c + READY_WITHIN_C
    hot = bath(Body(steak), target_c + boost_c, lambda b: b.core >= goal)

    def held(i: int) -> list[Body]:
        # Hold until the core passes the ceiling, or is ready and has stopped rising.
        last = [hot[i].core]

        def settled(b: Body) -> bool:
            rising = b.core > last[0] + 1e-4
            last[0] = b.core
            return b.core > ceiling or (b.core >= goal and not rising)
        return hot[:i] + bath(hot[i].copy(), target_c, settled)

    lo, hi = 0, len(hot) - 1
    while lo < hi:  # the latest switch that does not overshoot
        mid = (lo + hi + 1) // 2
        if max(b.core for b in held(mid)[mid:]) > ceiling:
            hi = mid - 1
        else:
            lo = mid
    states = held(lo)
    ready = next(j for j in range(lo, len(states)) if states[j].core >= goal)
    return finished('hot_then_drop', target_c + boost_c, states, ready, finish, switch=lo)


def trace(steak: Steak, target_c: float, cook: Cook, finish: Finish, every_s: float = 60.0) -> list[dict]:
    """Core, middle and surface temperatures through the bath and finish, for charts."""
    body = Body(steak)
    points: list[dict] = []
    clock = [0.0, -every_s]
    mid = NODES // 2

    def record(dt: float, b: Body, phase: str) -> None:
        clock[0] += dt
        if clock[0] - clock[1] >= every_s - 1e-9:
            clock[1] = clock[0]
            points.append({'min': round(clock[0] / 60, 2), 'phase': phase,
                           'core': round(b.T[0], 2), 'mid': round(b.T[mid], 2), 'surface': round(b.T[-1], 2)})
    record(0.0, body, 'bath')
    t, end = 0.0, cook.minutes * 60
    while t < end - 1e-9:
        bath_c = cook.bath_c if cook.switch_minutes is None or t < cook.switch_minutes * 60 else target_c
        body.step(bath_c, H_BATH, BATH_STEP_S)
        t += BATH_STEP_S
        record(BATH_STEP_S, body, 'bath')
    finish.run(body, lambda dt, b: record(dt, b, 'finish'))
    return points


def profile(body: Body) -> list[dict]:
    """Peak temperature by depth from the surface, for the cross-section."""
    R = body.steak.half_m
    return [{'depth_mm': round((R - r) * 1000, 2), 'peak_c': round(p, 2)}
            for r, p in sorted(zip(body.r, body.peak), key=lambda x: -x[0])]


def plan(steak: Steak, target_c: float, boost_c: float, finish: Finish) -> dict:
    """Classic sous vide against both shortcuts, with every boost in BOOSTS_C side by side."""
    base = classic(steak, target_c, finish)
    boosts = sorted(set(BOOSTS_C) | {boost_c})
    sweep = [hot_and_pull(steak, target_c, b, finish) for b in boosts]
    cooks = {'classic': base, 'hot_and_pull': sweep[boosts.index(boost_c)],
             'hot_then_drop': hot_then_drop(steak, target_c, boost_c, finish)}
    base_over = base.summary(target_c)['overcooked_mm']

    def row(cook: Cook) -> dict:
        out = cook.summary(target_c)
        out['saved_minutes'] = round(base.minutes - cook.minutes, 1)
        out['extra_overcooked_mm'] = round(out['overcooked_mm'] - base_over, 1)
        return out
    warnings = [f'{cook.minutes / 60:.1f} h at {cook.bath_c:g} C: below {DANGER_C} C, '
                f'keep cooks under {DANGER_HOURS:.0f} h.'
                for cook in cooks.values() if cook.bath_c < DANGER_C and cook.minutes / 60 > DANGER_HOURS][:1]
    return {
        **{name: row(cook) for name, cook in cooks.items()},
        'sweep': [row(c) for c in sweep],
        'trace': {name: trace(steak, target_c, cook, finish) for name, cook in cooks.items()},
        'profile': {name: profile(cook.finished) for name, cook in cooks.items()},
        'warnings': warnings,
    }
