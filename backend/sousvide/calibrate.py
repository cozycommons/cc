"""Fit the model's constants to one cook's probe log.

The cook logs (minute, core temperature) with the probe tip at the coldest
point, in a bath held at one temperature. The fit finds the diffusivity alpha
that makes model.Body reproduce the log, by least squares, and optionally the
bath coefficient h as well.

alpha is always identifiable: with k and h fixed it only rescales time. h is
weaker. It shows only in the shape of the core's approach, which probe noise
and a tip a few millimetres off-centre bend just as much. On synthetic logs
(experiments/calibration.py) a two-parameter fit recovers h from readings
0.1 C clean, and with 0.5 C noise or a tip 5 mm off it settles confidently
on a wrong pair such as alpha 2.2e-7 with h 32. So a fitted h is kept only
when its standard error is under H_SE_LIMIT and it lies inside H_PLAUSIBLE;
otherwise the fit keeps the given h and says so.

The fitted alpha is an effective value. It absorbs whatever the model gets
wrong about this steak's shape, bone and probe position, which is what makes
the next plan for a similar steak land.
"""
from __future__ import annotations

import math
from dataclasses import replace

from .model import BATH_STEP_S, Body, Steak

ALPHA_RANGE = (0.6e-7, 2.5e-7)
"""Bounds on a fitted alpha, m^2/s: about half to double the sourced range for beef
(model.Physics.diffusivity). A fit that stops on a bound means the log and the steak's
measurements disagree, not that the meat is unusual."""

H_RANGE = (20.0, 2000.0)
"""Bounds on a fitted bath h, W/(m^2 K): still water to a surface effectively at bath temperature."""

H_SE_LIMIT = 0.15
"""h counts as identified when its standard error is under this fraction of its value."""

H_PLAUSIBLE = (100.0, 1500.0)
"""What a bagged steak in a circulating bath can plausibly see, W/(m^2 K), around the planner's
400: the measured bath cooks in experiments/results/validation.md fit 400 to 1000. An assumption,
not a measurement. A two-parameter fit that leaves it is bending h to absorb
something else, usually the probe's position."""

Readings = list[tuple[float, float]]  # (minutes since the steak went in, core C)


def core_curve(steak: Steak, bath_c: float, minutes: list[float]) -> list[float]:
    """The model's core temperature at each of the minutes, which must be ascending."""
    body, h = Body(steak), steak.physics.h_bath
    out, t, before = [], 0.0, body.core
    for minute in minutes:
        while t < minute * 60:
            before = body.core
            body.step(bath_c, h, BATH_STEP_S)
            t += BATH_STEP_S
        over = (t - minute * 60) / BATH_STEP_S  # fraction of the last step past the reading
        out.append(body.core - over * (body.core - before))
    return out


def _least_squares(residuals, start: list[float], bounds: list[tuple[float, float]]):
    """Levenberg-Marquardt on a handful of parameters. Returns (params, residuals, J^T J)."""
    x, r = list(start), residuals(start)
    sse, damping = sum(v * v for v in r), 1e-3
    normal = [[0.0] * len(x) for _ in x]
    for _ in range(25):
        columns = []
        for i in range(len(x)):
            nudged = list(x)
            nudged[i] += 0.01
            columns.append([(a - b) / 0.01 for a, b in zip(residuals(nudged), r)])
        normal = [[sum(a * b for a, b in zip(ci, cj)) for cj in columns] for ci in columns]
        gradient = [sum(a * b for a, b in zip(c, r)) for c in columns]
        while True:
            damped = [[v * (1 + damping) if i == j else v for j, v in enumerate(row)] for i, row in enumerate(normal)]
            move = _solve(damped, [-g for g in gradient])
            trial = [min(hi, max(lo, v + d)) for v, d, (lo, hi) in zip(x, move, bounds)]
            trial_r = residuals(trial)
            trial_sse = sum(v * v for v in trial_r)
            if trial_sse <= sse or damping > 1e6:
                break
            damping *= 4
        moved = max(abs(a - b) for a, b in zip(trial, x))
        if trial_sse <= sse:
            x, r, sse, damping = trial, trial_r, trial_sse, damping / 3
        if moved < 1e-4 or damping > 1e6:
            break
    return x, r, normal


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve the 1x1 or 2x2 system a x = b."""
    if len(b) == 1:
        return [b[0] / a[0][0]]
    det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
    return [(b[0] * a[1][1] - b[1] * a[0][1]) / det, (a[0][0] * b[1] - a[1][0] * b[0]) / det]


def fit(steak: Steak, bath_c: float, readings: Readings, fit_h: bool = False) -> dict:
    """Least-squares alpha (and h when the log identifies it) for this steak and probe log.

    steak carries the measured shape and start temperature, and the constants the
    fit starts from. Uncertainties are one standard error from the fit's own scatter,
    so they are too small when the misfit is systematic (a misplaced probe).
    """
    readings = sorted(readings)
    minutes, measured = [m for m, _ in readings], [c for _, c in readings]
    base = steak.physics

    def run(log_params: list[float]) -> list[float]:
        physics = replace(base, diffusivity=math.exp(log_params[0]),
                          h_bath=math.exp(log_params[1]) if len(log_params) > 1 else base.h_bath)
        return [a - b for a, b in zip(core_curve(replace(steak, physics=physics), bath_c, minutes), measured)]

    def rms(r: list[float]) -> float:
        return math.sqrt(sum(v * v for v in r) / len(r))

    def errors(r: list[float], normal: list[list[float]]) -> list[float]:
        """Standard error of each log-parameter: sqrt of the diagonal of sigma^2 (J^T J)^-1."""
        n = len(normal)
        if len(r) <= n:
            return [math.inf] * n
        variance = sum(v * v for v in r) / (len(r) - n)
        if n == 1:
            return [math.sqrt(variance / normal[0][0])]
        det = normal[0][0] * normal[1][1] - normal[0][1] * normal[1][0]
        if det <= 0:
            return [math.inf, math.inf]
        return [math.sqrt(variance * normal[1][1] / det), math.sqrt(variance * normal[0][0] / det)]

    log_alpha = [(math.log(ALPHA_RANGE[0]), math.log(ALPHA_RANGE[1]))]
    log_h = [(math.log(H_RANGE[0]), math.log(H_RANGE[1]))]
    start = [math.log(base.diffusivity)]
    default_rms = rms(run(start))
    params, r, normal = _least_squares(run, start, log_alpha)
    se = errors(r, normal)
    h_fitted, h_identifiable = False, None
    if fit_h:
        both, r2, normal2 = _least_squares(run, [params[0], math.log(base.h_bath)], log_alpha + log_h)
        se2 = errors(r2, normal2)
        h_identifiable = se2[1] < H_SE_LIMIT and H_PLAUSIBLE[0] <= math.exp(both[1]) <= H_PLAUSIBLE[1]
        if h_identifiable:
            params, r, se, h_fitted = both, r2, se2, True
    alpha = math.exp(params[0])
    h = math.exp(params[1]) if h_fitted else base.h_bath
    fitted = replace(steak, physics=replace(base, diffusivity=alpha, h_bath=h))
    return {
        'alpha': alpha, 'alpha_se_pct': round(100 * se[0], 1) if math.isfinite(se[0]) else None,
        'alpha_on_bound': any(abs(params[0] - edge) < 1e-6 for edge in log_alpha[0]),
        'h_bath': round(h, 1), 'h_fitted': h_fitted, 'h_identifiable': h_identifiable,
        'h_se_pct': round(100 * se[1], 1) if h_fitted else None,
        'rms_c': round(rms(r), 2), 'default_rms_c': round(default_rms, 2), 'readings': len(readings),
        'curve': [{'min': m, 'core': round(c, 2)} for m, c in zip(minutes, core_curve(fitted, bath_c, minutes))],
    }
