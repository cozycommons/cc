"""Heat conduction through a steak in a water bath, a pan and the air.

Heat moves by conduction, rho*c*dT/dt = div(k grad T), and enters through the
surface by convection, q = h*(T_outside - T_surface). Properties are constant,
the meat never freezes or loses water, and a bath or pan change is instant.

The steak is a box (thickness x width x length), a round puck (a filet) or a
roast (a cylinder with a length). Conduction is linear, so two facts keep the
solve one-dimensional and stdlib-only:

- A box that starts uniform and sees one outside temperature on every face has
  the product solution: (T - T_out) / (T_start - T_out) is the product of the
  1-D solutions along each axis. A steak measured only by thickness has one
  axis, the infinite slab.
- When the outside temperature changes (bath to pan to air, or a hot bath
  dropped to the target), the change is a uniform offset that relaxes on its
  own. The temperature is the outside temperature plus a sum of such parts,
  each a product of 1-D solutions (Body.parts).

The model reports temperatures along the line through the middle of the steak:
through the thickness at the centre of a slab or puck, along the radius at the
middle of a roast.

Doneness follows the hottest temperature each layer reached: myoglobin and
myosin denature within minutes at these temperatures, so a layer that once
peaked at 60 C stays medium even after the bath drops back to 55 C.

Each 1-D solve is backward Euler on a finite-volume grid. It is unconditionally
stable, so a 10 s step works for the bath and a 1 s step resolves a sear's
few millimetres. Each step solves a tridiagonal system (Thomas algorithm).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal

Shape = Literal['slab', 'cylinder', 'puck']
Bone = Literal['none', 'edge', 'middle']


@dataclass(frozen=True)
class Physics:
    """Every physical constant the heat solve uses.

    None of these has been measured on the cook's own steak or kitchen. Each
    field says where its value came from. "First-version value" means it is
    carried from the first version of this model, which took it from general
    food-engineering knowledge rather than a cited table. A probe log
    (calibrate.py) replaces alpha and sometimes h_bath for one cook's setup.
    """

    conductivity: float = 0.46
    """k of the meat, W/(m K). The sourced literature pass for this work gives 0.37 to 0.51 for
    marbled ribeye lean; 0.46 sits inside it. Only the ratio h/k matters to the solve, so an
    error here acts like an error in h: about -5 % to +3 % on time across that range."""

    diffusivity: float = 1.2e-7
    """alpha of the meat, m^2/s. The same literature pass gives 1.07e-7 to 1.44e-7 for marbled
    ribeye lean (beef fat alone: 0.9e-7 to 1.2e-7); 1.2e-7 sits inside it. Cook time scales as
    1/alpha, so that range is +12 % to -17 % on time. The constant a probe log fits (calibrate.py)."""

    h_bath: float = 95.0
    """Surface heat transfer coefficient of a bagged steak in a circulating bath, W/(m^2 K).
    The value Baldwin uses for his tables. Depends on the circulator and the bag's contact."""

    h_air: float = 10.0
    """Still air around a resting steak, W/(m^2 K). First-version value, a textbook
    free-convection-plus-radiation figure. Ignores evaporation, which cools a wet surface faster."""

    air_c: float = 22.0
    """Room temperature while the steak rests, C. Assumed."""

    h_sear: float = 400.0
    """Stiffness of the pan contact, W/(m^2 K), toward sear_surface_c. First-version guess.
    The least certain constant: see experiments/sear.py for what it does to the carryover."""

    sear_surface_c: float = 100.0
    """Temperature the sear drives the meat's surface toward, C. A wet surface boils, which
    holds the meat just under the crust near 100 C while the sear lasts. Heat that leaves as
    steam or builds the crust never enters the meat, so this is not the pan's temperature."""


BONE_MIDDLE_FACTOR = 1.5
"""A bone through the middle of a slab narrows the width the planner heats by this many bone
widths. Fitted to 2-D solves with a cortical-and-marrow rib (experiments/ribeye.py): the bone
needs about half the heat of the meat it displaces and conducts faster, so the meat beside it
is ready sooner than with the bone simply removed (which would be 1.0). Classic times land
within 5.3 % for bones 15 to 40 mm wide in steaks 25 to 64 mm thick at mid-range marrow
conductivity, and from 12 % short to 7 % long across the marrow range and solid bone."""

BONE_MM = 28.0
"""Width of a beef rib where it crosses a steak, mm. The canonical case's assumption, for
when the bone was not measured."""

MEAT_DENSITY = 1050.0
"""kg/m^3, for turning a weight into a footprint. The value relayed with the canonical case;
lean beef is usually quoted between 1040 and 1080. Bone is denser, so a bone-in steak's
footprint comes out a few per cent large."""

PLAN_ASPECT = 1.3
"""Length / width assumed for a footprint known only by its area (the canonical ribeye is
180 x 140 mm). experiments/finite_size.py: among rectangles of one area, an aspect of 1.5
cooks 1 to 3 % faster than a square and an aspect of 2 cooks 3 to 8 % faster."""

SEAR_SPREAD = (0.5, 2.0)
"""Factors on h_sear for the range a plan quotes around its core peak. experiments/sear.py:
half to double the contact moves a 51 mm steak's finish by about -0.5 to +0.4 C and a 25 mm
steak's by -1.5 to +1.2 C. A surface that runs hotter than boiling lands outside this range."""

NODES = 40  # along the reported line: centre to surface
SIDE_NODES = 20  # along width and length, where only the centre value is used
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


class Axis:
    """One direction heat moves along: half a slab's thickness, or a cylinder's radius.

    Nodes run from the centre (0) to the surface (n-1). relax() advances the
    homogeneous problem: the outside is at 0 and the field decays toward it.
    """

    def __init__(self, half_m: float, m: int, nodes: int, conductivity: float, diffusivity: float):
        # m is the geometry exponent: 0 for a slab, 1 for a cylinder.
        self.half_m, self.alpha, self.k = half_m, diffusivity, conductivity
        n, R = nodes, half_m
        self.dr = R / (n - 1)
        self.r = [i * self.dr for i in range(n)]
        # Control volume i spans [r_i - dr/2, r_i + dr/2], clipped to [0, R],
        # with face areas and volumes per unit area (slab) or per radian-metre (cylinder).
        lo = [max(0.0, x - self.dr / 2) for x in self.r]
        hi = [min(R, x + self.dr / 2) for x in self.r]
        self.volume = [(b ** (m + 1) - a ** (m + 1)) / (m + 1) for a, b in zip(lo, hi)]
        self.face = [hi[i] ** m for i in range(n - 1)]  # between node i and i+1
        self.surface = R ** m
        self.ones = [1.0] * n
        self._factored: dict[tuple[float, float], tuple[list[float], list[float], list[float]]] = {}
        self._shared: dict[tuple[int, float, float], tuple[list[float], list[float]]] = {}

    def _factor(self, h: float, dt: float) -> tuple[list[float], list[float], list[float]]:
        """Thomas elimination of the step's tridiagonal matrix, which is fixed for a given h and dt."""
        n = len(self.r)
        g = [self.alpha * dt * a / self.dr for a in self.face]  # conductance * dt / (rho c)
        surf = h * dt * self.surface * self.alpha / self.k  # h / (rho c) * dt * area
        # Row i: -g[i-1] T_{i-1} + b_i T_i - g[i] T_{i+1} = volume_i * T_i(old).
        b = [self.volume[i] + (g[i - 1] if i else 0.0) + (g[i] if i < n - 1 else 0.0) for i in range(n)]
        b[-1] += surf
        w = [0.0] * n
        for i in range(1, n):
            w[i] = -g[i - 1] / b[i - 1]
            b[i] += w[i] * g[i - 1]
        return w, [1.0 / x for x in b], g

    def relax(self, field: list[float], h: float, dt: float, share: bool = False) -> list[float]:
        """The field dt seconds later, its surface losing heat to 0 through coefficient h.

        share=True remembers the answer for this very list. Every bath starts from
        the same uniform field whatever its temperature, so a plan's baths then
        solve each step once between them. forget() drops what was remembered.
        """
        if share:
            hit = self._shared.get((id(field), h, dt))
            if hit is not None and hit[0] is field:  # the id could belong to a new list after forget()
                return hit[1]
        key = (h, dt)
        if key not in self._factored:
            self._factored[key] = self._factor(h, dt)
        w, inv, g = self._factored[key]
        n = len(field)
        d = [v * t for v, t in zip(self.volume, field)]
        for i in range(1, n):
            d[i] -= w[i] * d[i - 1]
        out = [0.0] * n
        out[-1] = d[-1] * inv[-1]
        for i in range(n - 2, -1, -1):
            out[i] = (d[i] + g[i] * out[i + 1]) * inv[i]
        if share:
            self._shared[(id(field), h, dt)] = (field, out)
        return out

    def forget(self) -> None:
        self._shared.clear()


@lru_cache(maxsize=64)
def axis(half_m: float, m: int, nodes: int, conductivity: float, diffusivity: float) -> Axis:
    """Axes are shared so each (h, dt) matrix is factored once per geometry, not once per Body."""
    return Axis(half_m, m, nodes, conductivity, diffusivity)


@dataclass(frozen=True)
class Steak:
    thickness_mm: float  # slab or puck thickness, or a roast's diameter
    shape: Shape = 'slab'
    start_c: float = 5.0
    width_mm: float | None = None  # a slab's shorter side, or a puck's diameter
    length_mm: float | None = None  # a slab's longer side, or a roast's length
    physics: Physics = Physics()
    bone: Bone = 'none'  # slabs only; the width is measured across the bone
    bone_mm: float = BONE_MM  # the bone's width

    @property
    def half_m(self) -> float:
        return self.thickness_mm / 2000.0

    @property
    def heated_width_mm(self) -> float | None:
        """The width of all-meat slab that heats like this one.

        A bone along an edge counts as meat: it shields that edge about as well as
        more steak would (experiments/bone.py, within 2.5 %). A bone through the
        middle narrows the steak by BONE_MIDDLE_FACTOR bone widths, but never below
        one lobe of meat with the bone as good as water.
        """
        if self.width_mm is None or self.bone != 'middle' or self.shape != 'slab':
            return self.width_mm
        return max(self.width_mm - BONE_MIDDLE_FACTOR * self.bone_mm, (self.width_mm - self.bone_mm) / 2)

    @property
    def axes(self) -> tuple[Axis, ...]:
        """The reported line first, then the directions whose only effect is on the middle.

        An unmeasured side is treated as infinite: it gets no axis.
        """
        if self.shape == 'cylinder':
            line, sides = 1, [(self.length_mm, 0)]
        elif self.shape == 'puck':
            line, sides = 0, [(self.width_mm, 1)]
        else:
            line, sides = 0, [(self.heated_width_mm, 0), (self.length_mm, 0)]
        k, alpha = self.physics.conductivity, self.physics.diffusivity
        return (axis(self.half_m, line, NODES, k, alpha),
                *(axis(mm / 2000.0, m, SIDE_NODES, k, alpha) for mm, m in sides if mm))


def sized(steak: Steak, weight_g: float | None) -> Steak:
    """The steak with the sides nobody measured filled in from its weight."""
    if not weight_g:
        return steak
    volume_mm3 = weight_g / 1000 / MEAT_DENSITY * 1e9
    if steak.shape == 'cylinder':
        return steak if steak.length_mm else replace(steak, length_mm=volume_mm3 / (math.pi * (steak.thickness_mm / 2) ** 2))
    area = volume_mm3 / steak.thickness_mm
    if steak.shape == 'puck':
        return steak if steak.width_mm else replace(steak, width_mm=(4 * area / math.pi) ** 0.5)
    width, length = steak.width_mm, steak.length_mm
    if width and length:
        return steak
    if width or length:
        return replace(steak, width_mm=width or area / length, length_mm=length or area / width)
    width = (area / PLAN_ASPECT) ** 0.5
    return replace(steak, width_mm=width, length_mm=width * PLAN_ASPECT)


class Body:
    """Temperatures from the centre (node 0) to the surface (node N-1) along the steak's middle line.

    The state is the outside temperature plus parts. Each part is one past change
    of the outside temperature: a coefficient times the product of a 1-D field per
    axis, each field relaxing toward 0 (see the module docstring).
    """

    def __init__(self, steak: Steak):
        self.steak = steak
        self.axes = steak.axes
        line = self.axes[0]
        self.r, self.dr, self.volume = line.r, line.dr, line.volume
        # The meat starts in equilibrium with an outside at its own temperature.
        self.outside = steak.start_c
        self.parts: list[tuple[float, list[list[float]]]] = []
        self.T = [steak.start_c] * len(self.r)
        self.peak = list(self.T)

    def copy(self) -> 'Body':
        body = object.__new__(Body)
        body.steak, body.axes, body.r, body.dr, body.volume = self.steak, self.axes, self.r, self.dr, self.volume
        body.outside = self.outside
        body.parts = list(self.parts)  # fields are replaced each step, never mutated
        body.T = list(self.T)
        body.peak = list(self.peak)
        return body

    @property
    def core(self) -> float:
        return self.T[0]

    def step(self, outside_c: float, h: float, dt: float, side_h: float | None = None, share: bool = False) -> None:
        """Advance dt seconds with every surface exposed to outside_c.

        h is the coefficient on the surface the reported line ends at (a slab's
        faces, a roast's side); side_h is the coefficient on the others and
        defaults to h. share is Axis.relax's.
        """
        if outside_c != self.outside:
            self.parts.append((self.outside - outside_c, [a.ones for a in self.axes]))
            self.outside = outside_c
        self.relax(h, dt, side_h, share=share)

    def relax(self, h: float, dt: float, side_h: float | None = None, base: list[float] | None = None,
              share: bool = False) -> None:
        """Advance the parts dt seconds and rebuild the temperatures on top of base.

        base is the temperature the line would have with no parts: the outside
        temperature, unless the caller is superposing a solution of its own
        (Finish.run does).
        """
        side = h if side_h is None else side_h
        line, sides = self.axes[0], self.axes[1:]
        T = [self.outside] * len(self.r) if base is None else base
        parts = []
        for coef, fields in self.parts:
            fields = [line.relax(fields[0], h, dt, share), *(a.relax(f, side, dt, share) for a, f in zip(sides, fields[1:]))]
            parts.append((coef, fields))
            for f in fields[1:]:
                coef *= f[0]
            T = [t + coef * x for t, x in zip(T, fields[0])]
        self.parts = parts
        self.T = T
        self.peak = [max(p, t) for p, t in zip(self.peak, T)]

    def depth_over_mm(self, limit_c: float) -> float:
        """Depth from the surface of meat whose peak passed limit_c, per side."""
        inside = [r for r, p in zip(self.r, self.peak) if p <= limit_c]
        if not inside:
            return self.steak.half_m * 1000
        return max(0.0, (self.steak.half_m - max(inside) - self.dr / 2) * 1000)

    def share_over(self, limit_c: float) -> float:
        """Fraction of the middle line's meat (by volume) whose peak passed limit_c."""
        over = sum(v for v, p in zip(self.volume, self.peak) if p > limit_c)
        return over / sum(self.volume)


@dataclass(frozen=True)
class Finish:
    sear_s: float = 45.0  # per side; modelled as both faces at once, like flipping every 15 s

    def steps(self, physics: Physics) -> list[tuple[bool, float, float, float, float]]:
        """(resting, outside_c, h, side_h, dt) for the sear and then the longest rest.

        The pan touches only the surface the reported line ends at. The other
        surfaces are treated as insulated for the length of the sear: they would
        lose a negligible amount to the air, and a single outside temperature
        keeps the product solution exact.
        """
        sear = (False, physics.sear_surface_c, physics.h_sear, 0.0, SEAR_STEP_S)
        rest = (True, physics.air_c, physics.h_air, physics.h_air, REST_STEP_S)
        return [sear] * round(self.sear_s / SEAR_STEP_S) + [rest] * round(REST_MAX_S / REST_STEP_S)

    def run(self, body: Body, record=None) -> float:
        """Sear, then rest until the core stops rising. Returns the core's highest temperature.

        The body must come straight from a bath. Its temperature is then the bath
        temperature minus a shortfall (its parts), and the finish splits the same
        way: a steak uniformly at the bath temperature going through the sear and
        rest, which is the same for every pull time and is solved once
        (_uniform_finish), plus the shortfall relaxing with nothing heating it.
        The body is left readable (T, peak) but must not be stepped again.
        """
        physics, bath_c = body.steak.physics, body.outside
        uniform = _uniform_finish(replace(body.steak, start_c=0.0), self.sear_s)
        top, rested = body.core, 0.0
        for (resting, _, h, side_h, dt), (cold, per_degree) in zip(self.steps(physics), uniform):
            before = body.core
            body.relax(h, dt, side_h, base=[a + bath_c * b for a, b in zip(cold, per_degree)])
            top = max(top, body.core)
            if record:
                record(dt, body)
            if resting:
                rested += dt
                if body.core < before and rested >= 60:
                    break
        return top


@lru_cache(maxsize=32)
def _uniform_finish(steak: Steak, sear_s: float) -> list[tuple[list[float], list[float]]]:
    """After each finish step: a steak that started uniformly at 0 C, and its gain per degree of start."""
    cold, warm = Body(replace(steak, start_c=0.0)), Body(replace(steak, start_c=1.0))
    out = []
    for _, outside_c, h, side_h, dt in Finish(sear_s).steps(steak.physics):
        cold.step(outside_c, h, dt, side_h)
        warm.step(outside_c, h, dt, side_h)
        out.append((cold.T, [b - a for a, b in zip(cold.T, warm.T)]))
    return out


def bath(body: Body, bath_c: float, until, limit_s: float = 24 * 3600) -> list[Body]:
    """Cook in the bath, keeping a snapshot per step, until until(body) or limit_s."""
    h = body.steak.physics.h_bath
    states = [body.copy()]
    t = 0.0
    while not until(body) and t < limit_s:
        body.step(bath_c, h, BATH_STEP_S, share=True)
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
            'pull_core_c': round(self.pulled.core, 1), 'core_peak_c': round(self.core_peak_c, 1),
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
        body.step(bath_c, steak.physics.h_bath, BATH_STEP_S, share=True)
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
    try:
        return _plan(steak, target_c, boost_c, finish)
    finally:
        for a in steak.axes:  # the baths' shared solves are only worth keeping within one plan
            a.forget()


def _plan(steak: Steak, target_c: float, boost_c: float, finish: Finish) -> dict:
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

    def sear_range(cook: Cook) -> list[float]:
        """The core peak if the pan's contact is half or double the assumed one."""
        peaks = []
        for factor in SEAR_SPREAD:
            body = cook.pulled.copy()
            body.steak = replace(steak, physics=replace(steak.physics, h_sear=steak.physics.h_sear * factor))
            peaks.append(round(finish.run(body), 1))
        return peaks
    warnings = [f'{cook.minutes / 60:.1f} h at {cook.bath_c:g} C: below {DANGER_C} C, '
                f'keep cooks under {DANGER_HOURS:.0f} h.'
                for cook in cooks.values() if cook.bath_c < DANGER_C and cook.minutes / 60 > DANGER_HOURS][:1]
    thickness_only = replace(steak, shape='cylinder' if steak.shape == 'cylinder' else 'slab',
                             width_mm=None, length_mm=None, bone='none')
    return {
        **{name: {**row(cook), 'core_peak_range_c': sear_range(cook)} for name, cook in cooks.items()},
        'sweep': [row(c) for c in sweep],
        'trace': {name: trace(steak, target_c, cook, finish) for name, cook in cooks.items()},
        'profile': {name: profile(cook.finished) for name, cook in cooks.items()},
        'warnings': warnings,
        # What the same cook would take if only the thickness were known.
        'thickness_only_minutes': round(base.minutes if thickness_only == steak
                                        else classic(thickness_only, target_c, Finish(0)).minutes, 1),
    }
