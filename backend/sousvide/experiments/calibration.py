"""How well does a probe log recover alpha and h?

Synthetic logs from the canonical ribeye with known "true" constants, read every
5 minutes with probe noise, then fitted by calibrate.fit starting from the
planner's defaults.

Run from backend/: python -m sousvide.experiments.calibration
"""
from __future__ import annotations

import random
from dataclasses import replace
from statistics import mean, pstdev

from sousvide import calibrate
from sousvide.model import BATH_STEP_S, Body, Steak

from .common import PHYSICS, section, table

RIBEYE = Steak(51, width_mm=140, length_mm=180, bone='middle')
TRUE_ALPHA, TRUE_H = 1.35e-7, 130.0
BATH_C = 57.5
SEEDS = 12


def log(steak: Steak, minutes: list[float], noise_c: float, seed: int, off_centre_mm: float = 0.0) -> calibrate.Readings:
    """What a probe would read in the true steak: Gaussian noise, tip possibly off the mid-plane."""
    rng = random.Random(seed)
    body = Body(steak)
    node = round(off_centre_mm / 1000 / body.dr)
    out, t = [], 0.0
    for minute in minutes:
        while t < minute * 60:
            body.step(BATH_C, steak.physics.h_bath, BATH_STEP_S)
            t += BATH_STEP_S
        out.append((minute, body.T[node] + rng.gauss(0, noise_c)))
    return out


def recovery() -> None:
    truth = replace(RIBEYE, physics=replace(PHYSICS, diffusivity=TRUE_ALPHA, h_bath=TRUE_H))
    rows = []
    cases = [('every 5 min to 100 min', list(range(0, 101, 5)), 0.0, RIBEYE),
             ('every 5 min to 60 min (pulled early)', list(range(0, 61, 5)), 0.0, RIBEYE),
             ('every 10 min to 100 min', list(range(0, 101, 10)), 0.0, RIBEYE),
             ('every 1 min to 100 min (logging probe)', list(range(0, 101)), 0.0, RIBEYE),
             ('every 5 min, tip 5 mm off mid-thickness', list(range(0, 101, 5)), 5.0, RIBEYE),
             ('every 5 min, tip 10 mm off mid-thickness', list(range(0, 101, 5)), 10.0, RIBEYE),
             ('every 5 min, thickness entered 2 mm thin (49)', list(range(0, 101, 5)), 0.0, replace(RIBEYE, thickness_mm=49)),
             ('every 5 min, start entered 3 C warm (8 C)', list(range(0, 101, 5)), 0.0, replace(RIBEYE, start_c=8))]
    for label, minutes, off, assumed in cases:
        for noise in (0.1, 0.5):
            alpha_only, both, identified = [], [], 0
            for seed in range(SEEDS):
                readings = log(truth, [float(m) for m in minutes], noise, seed, off)
                alpha_only.append(calibrate.fit(assumed, BATH_C, readings)['alpha'] * 1e7)
                got = calibrate.fit(assumed, BATH_C, readings, fit_h=True)
                if got['h_fitted']:
                    identified += 1
                    both.append((got['alpha'] * 1e7, got['h_bath']))
            rows.append([label, noise, f'{mean(alpha_only):.2f} +/- {pstdev(alpha_only):.2f}', f'{identified} of {SEEDS}',
                         f'{mean(a for a, _ in both):.2f} +/- {pstdev(a for a, _ in both):.2f}' if both else '',
                         f'{mean(h for _, h in both):.0f} +/- {pstdev(h for _, h in both):.0f}' if both else ''])
    section('Recovering alpha and h from a synthetic log',
            table(['log', 'probe noise C', 'alpha, h held at 95', 'h kept', 'alpha when h kept', 'h when kept'], rows),
            f'Truth: alpha {TRUE_ALPHA * 1e7:.2f}e-7, h {TRUE_H:g}, canonical ribeye from 5 C in a {BATH_C:g} C bath. '
            f'Mean and spread over {SEEDS} noise seeds, alpha in 1e-7 m2/s. Fits start from alpha 1.20, h 95.')


def payoff() -> None:
    """Does the alpha fitted with the wrong h still predict the next cook?"""
    truth = replace(RIBEYE, physics=replace(PHYSICS, diffusivity=TRUE_ALPHA, h_bath=TRUE_H))
    readings = log(truth, [float(m) for m in range(0, 101, 5)], 0.3, 1)
    got = calibrate.fit(RIBEYE, BATH_C, readings)
    fitted = replace(PHYSICS, diffusivity=got['alpha'])
    from sousvide import model
    rows = []
    for label, steak in (('same ribeye, classic 54.5 C', RIBEYE), ('same ribeye, +3 C pulled', RIBEYE),
                         ('38 mm boneless, 110 x 160, classic', Steak(38, width_mm=110, length_mm=160)),
                         ('25 mm strip, classic', Steak(25, width_mm=70, length_mm=180))):
        def minutes(physics):
            s = replace(steak, physics=physics)
            if 'pulled' in label:
                return model.hot_and_pull(s, 54.5, 3.0, model.Finish(45)).minutes
            return model.classic(s, 54.5, model.Finish(0)).minutes
        real, default, calibrated = minutes(truth.physics), minutes(PHYSICS), minutes(fitted)
        rows.append([label, round(real), round(default), round(100 * (default - real) / real, 1),
                     round(calibrated), round(100 * (calibrated - real) / real, 1)])
    section('What one calibration buys on the next cook',
            table(['next cook', 'true min', 'default constants', '% off', 'fitted alpha, h still 95', '% off'], rows),
            f'One log (5 min readings, 0.3 C noise) fitted alpha {got["alpha"] * 1e7:.2f}e-7 with h held at 95; '
            f'the truth is alpha {TRUE_ALPHA * 1e7:.2f}e-7 with h {TRUE_H:g}.')


if __name__ == '__main__':
    print('# Calibration from a probe log\n')
    recovery()
    payoff()
