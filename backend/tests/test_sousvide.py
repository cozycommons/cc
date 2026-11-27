import math

import pytest

from dataclasses import replace

from sousvide import calibrate, model
from sousvide.model import Body, Finish, Physics, Steak

PHYSICS = Physics()


def core_after(steak: Steak, bath_c: float, seconds: float) -> float:
    body = Body(steak)
    for _ in range(round(seconds / model.BATH_STEP_S)):
        body.step(bath_c, PHYSICS.h_bath, model.BATH_STEP_S)
    return body.core


def test_slab_core_matches_the_series_solution():
    # Plane wall with convection, first term of the series (valid for Fourier number > 0.2):
    # (T0 - Tb) / (Ti - Tb) = C1 exp(-z^2 Fo), where z tan z = Bi.
    steak = Steak(38, start_c=5)
    half = steak.half_m
    biot = PHYSICS.h_bath * half / PHYSICS.conductivity
    lo, hi = 1e-6, math.pi / 2 - 1e-9
    for _ in range(100):
        z = (lo + hi) / 2
        lo, hi = (z, hi) if z * math.tan(z) < biot else (lo, z)
    c1 = 4 * math.sin(z) / (2 * z + math.sin(2 * z))
    seconds = 3600
    fourier = PHYSICS.diffusivity * seconds / half ** 2
    expected = 55 + (5 - 55) * c1 * math.exp(-z * z * fourier)
    assert core_after(steak, 55, seconds) == pytest.approx(expected, abs=0.3)


def test_a_steak_already_at_bath_temperature_stays_there():
    assert core_after(Steak(30, start_c=55), 55, 1800) == pytest.approx(55, abs=1e-9)


def test_cook_time_grows_nearly_with_the_square_of_thickness_and_cylinders_are_faster():
    def minutes(steak):
        return model.classic(steak, 55, Finish(0)).minutes
    thin, thick = minutes(Steak(20)), minutes(Steak(40))
    # Baldwin's tables (h 95) put a 1 inch steak from the fridge at 1 to 1.5 h; the measured
    # cooks in experiments/results/validation.md heat faster, and h 400 gives about 50 min.
    assert 40 <= minutes(Steak(25)) <= 65
    # Conduction alone gives 4x; the bag's surface resistance matters more for thin steaks.
    assert 2.7 <= thick / thin < 4
    assert minutes(Steak(40, 'cylinder')) < 0.7 * thick


def test_a_hotter_bath_saves_time_and_a_small_boost_costs_no_doneness():
    steak, target, finish = Steak(38), 54.5, Finish(0)
    base = model.classic(steak, target, finish).summary(target)
    plus2 = model.hot_and_pull(steak, target, 2, finish).summary(target)
    plus10 = model.hot_and_pull(steak, target, 10, finish).summary(target)
    assert base['minutes'] > plus2['minutes'] + 30 > plus10['minutes'] + 30
    assert plus2['overcooked_mm'] == 0
    assert plus10['overcooked_mm'] > 3
    # Pulled at the right moment, the core still lands on target.
    assert plus10['core_peak_c'] == pytest.approx(target - model.READY_WITHIN_C, abs=0.2)


def test_dropping_the_bath_holds_the_core_at_target():
    steak, target = Steak(38), 54.5
    drop = model.hot_then_drop(steak, target, 10, Finish(0))
    assert drop.switch_minutes < drop.minutes
    body = drop.pulled.copy()
    for _ in range(360):  # another hour at the target
        body.step(target, PHYSICS.h_bath, model.BATH_STEP_S)
        assert body.core <= target + model.READY_WITHIN_C


def test_a_sear_carries_the_core_past_a_classic_cook():
    steak, target = Steak(38), 54.5
    seared = model.classic(steak, target, Finish(45))
    assert seared.core_peak_c > target
    assert seared.summary(target)['gray_mm'] > 0


def test_a_finite_steak_follows_the_product_of_the_series_solutions():
    # A box heated on every face: (T - Tb) / (Ti - Tb) is the product of the plane-wall solutions
    # along each axis. Four series terms per axis, so this holds from early on.
    def wall(half_m: float, seconds: float) -> float:
        biot, fourier = PHYSICS.h_bath * half_m / PHYSICS.conductivity, PHYSICS.diffusivity * seconds / half_m ** 2
        total = 0.0
        for n in range(4):
            lo, hi = n * math.pi + 1e-9, n * math.pi + math.pi / 2 - 1e-9
            for _ in range(100):
                z = (lo + hi) / 2
                lo, hi = (z, hi) if z * math.tan(z) < biot else (lo, z)
            total += 4 * math.sin(z) / (2 * z + math.sin(2 * z)) * math.exp(-z * z * fourier)
        return total
    steak, seconds = Steak(38, width_mm=60, length_mm=90), 2400
    expected = 55 + (5 - 55) * wall(0.019, seconds) * wall(0.030, seconds) * wall(0.045, seconds)
    assert core_after(steak, 55, seconds) == pytest.approx(expected, abs=0.3)
    assert core_after(steak, 55, seconds) > core_after(Steak(38), 55, seconds) + 3


def test_a_bath_change_matches_a_direct_two_dimensional_solve():
    # The model superposes 1-D parts; the experiments' 2-D solver steps temperatures directly.
    from sousvide.experiments.common import everywhere, meat_section
    steak = Steak(30, width_mm=70)
    body, direct = Body(steak), meat_section(30, 70, steak.start_c, nx=21)
    for bath_c in (60.0, 50.0):
        for _ in range(120):
            body.step(bath_c, PHYSICS.h_bath, 10)
        direct.run(everywhere(PHYSICS.h_bath, bath_c), 1200, 10, track_peak=True)
    assert body.core < body.T[-1] < 50 < max(body.peak)  # the outside peaked in the hot bath, then fell back
    assert body.T == pytest.approx(direct.T[0], abs=0.05)
    assert body.peak == pytest.approx(direct.peak[0], abs=0.05)


def test_the_finish_shortcut_matches_stepping_the_sear_and_rest_directly():
    steak, finish = Steak(38, width_mm=80, length_mm=120), Finish(45)
    pulled = Body(steak)
    for _ in range(300):
        pulled.step(57.5, PHYSICS.h_bath, 10)
    direct = pulled.copy()
    fast = finish.run(pulled)
    top = direct.core
    for _, outside_c, h, side_h, dt in finish.steps(PHYSICS):
        before = direct.core
        direct.step(outside_c, h, dt, side_h)
        top = max(top, direct.core)
        if outside_c == PHYSICS.air_c and direct.core < before:
            break
    assert fast == pytest.approx(top, abs=1e-6)


def test_trace_layers_show_the_sear_band_and_the_rest_carrying_heat_inward():
    steak, target = Steak(thickness_mm=50), 54.5
    finish = Finish(45)
    cook = model.hot_and_pull(steak, target, 3.0, finish)
    points = model.trace(steak, target, cook, finish)
    assert all(len(p['layers']) == len(model.LAYER_RHO) for p in points)
    assert all(abs(p['layers'][0] - p['core']) <= 0.06 and abs(p['layers'][-1] - p['surface']) <= 0.06 for p in points)
    bath_end = cook.minutes
    sear = [p for p in points if p['phase'] == 'finish' and p['min'] <= bath_end + 0.75 + 1e-6]
    assert len(sear) == 9  # every 5 s through a 45 s sear
    hottest = max(sear, key=lambda p: p['surface'])
    assert hottest['layers'][-1] > 80 and hottest['layers'][-5] < target + 8  # a thin hot band
    assert hottest['layers'][0] == pytest.approx(sear[0]['layers'][0], abs=0.2)  # the center has not felt it
    rest = [p for p in points if p['phase'] == 'finish' and p['min'] > bath_end + 0.75]
    five = next(p for p in rest if p['min'] >= bath_end + 0.75 + 5)
    assert five['core'] > rest[0]['core'] and five['surface'] < rest[0]['surface']


def test_width_shortens_the_cook_and_a_bone_changes_it_by_where_it_sits():
    def minutes(**measured):
        return model.classic(Steak(51, **measured), 54.5, Finish(0)).minutes
    slab, boneless = minutes(), minutes(width_mm=140, length_mm=180)
    middle = minutes(width_mm=140, length_mm=180, bone='middle', bone_mm=28)
    # At h 400: 194 min as a slab, 173 as a box, 155 with the rib through the middle
    # (experiments/ribeye.py found 248, 215 and 192 at the earlier h 95).
    assert slab == pytest.approx(194, abs=2) and boneless == pytest.approx(173, abs=2) and middle == pytest.approx(155, abs=2)
    assert minutes(width_mm=140, length_mm=180, bone='edge') == boneless
    assert minutes(width_mm=100) > minutes(width_mm=100, length_mm=100) > model.classic(
        Steak(51, 'puck', width_mm=100), 54.5, Finish(0)).minutes


def test_weight_fills_in_the_sides_nobody_measured():
    ribeye = model.sized(Steak(51), 1330)
    assert (round(ribeye.width_mm), round(ribeye.length_mm)) == (138, 180)
    assert round(model.sized(Steak(51, width_mm=120), 1330).length_mm) == 207
    assert model.sized(Steak(51, width_mm=120, length_mm=150), 1330) == Steak(51, width_mm=120, length_mm=150)
    assert round(model.sized(Steak(50, 'puck'), 250).width_mm) == 78
    assert model.sized(Steak(51), None) == Steak(51)


def probe_log(steak: Steak, bath_c: float, minutes: list[float]) -> list[tuple[float, float]]:
    return list(zip(minutes, calibrate.core_curve(steak, bath_c, minutes)))


def test_calibration_recovers_alpha_from_a_probe_log():
    measured = Steak(38, width_mm=110, length_mm=160)
    truth = replace(measured, physics=replace(PHYSICS, diffusivity=1.4e-7))
    readings = probe_log(truth, 57.5, [float(m) for m in range(0, 71, 5)])
    fit = calibrate.fit(measured, 57.5, readings)
    assert fit['alpha'] == pytest.approx(1.4e-7, rel=0.01)
    assert fit['rms_c'] < 0.05 < fit['default_rms_c']
    assert not fit['h_fitted'] and fit['h_bath'] == PHYSICS.h_bath


def test_calibration_fits_h_only_when_the_log_pins_it():
    measured = Steak(38)
    truth = replace(measured, physics=replace(PHYSICS, diffusivity=1.3e-7, h_bath=160.0))
    clean = probe_log(truth, 57.5, [float(m) for m in range(0, 91, 2)])
    fit = calibrate.fit(measured, 57.5, clean, fit_h=True)
    assert fit['h_fitted'] and fit['h_bath'] == pytest.approx(160, rel=0.05)
    assert fit['alpha'] == pytest.approx(1.3e-7, rel=0.02)
    # Four readings 0.4 C apart in noise cannot separate h from alpha.
    noisy = [(m, c + bump) for (m, c), bump in zip(clean[10::10], (0.4, -0.4, 0.4, -0.4))]
    vague = calibrate.fit(measured, 57.5, noisy, fit_h=True)
    assert vague['h_identifiable'] is False and vague['h_bath'] == PHYSICS.h_bath


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sousvide import routes
    app = FastAPI()
    app.include_router(routes.router, prefix='/sousvide')
    return TestClient(app)


def test_plan_compares_classic_with_both_shortcuts(client):
    body = client.get('/sousvide/plan', params={'thickness_mm': 20, 'target_c': 57, 'boost_c': 4}).json()
    assert body['classic']['bath_c'] == 57
    assert body['hot_and_pull']['bath_c'] == body['hot_then_drop']['bath_c'] == 61
    assert body['hot_and_pull']['saved_minutes'] > 0
    assert [row['bath_c'] for row in body['sweep']] == [57, 58, 59, 60, 61, 62, 65, 67]
    assert set(body['trace']) == set(body['profile']) == {'classic', 'hot_and_pull', 'hot_then_drop'}
    assert body['trace']['classic'][0] == {'min': 0, 'phase': 'bath', 'core': 5, 'mid': 5, 'surface': 5, 'layers': [5] * 9}
    assert body['layer_rho'][0] == 0 and body['layer_rho'][-1] == 1
    assert body['warnings'] == []
    assert body['steak'] == {'width_mm': None, 'length_mm': None, 'heated_width_mm': None, 'bone': 'none', 'sized_by': 'thickness'}
    assert body['thickness_only_minutes'] == body['classic']['minutes']


def test_plan_uses_the_measured_steak(client):
    ribeye = {'thickness_mm': 51, 'weight_g': 1330, 'bone': 'middle', 'target_c': 54.5, 'boost_c': 3}
    body = client.get('/sousvide/plan', params=ribeye).json()
    assert body['steak'] == {'width_mm': 138, 'length_mm': 180, 'heated_width_mm': 96, 'bone': 'middle', 'sized_by': 'weight'}
    assert body['thickness_only_minutes'] > 1.25 * body['classic']['minutes']
    pull = body['hot_and_pull']
    assert pull['pull_core_c'] < pull['core_peak_c'] == pytest.approx(54, abs=0.1)
    low, high = pull['core_peak_range_c']
    assert low < pull['core_peak_c'] < high
    measured = client.get('/sousvide/plan', params={**ribeye, 'width_mm': 140, 'length_mm': 180}).json()
    assert measured['steak']['sized_by'] == 'measured'
    assert measured['classic']['minutes'] == pytest.approx(body['classic']['minutes'], rel=0.02)
    faster = client.get('/sousvide/plan', params={**ribeye, 'alpha': 1.44, 'h_bath': 1000}).json()
    assert faster['classic']['minutes'] < 0.85 * body['classic']['minutes']
    assert client.get('/sousvide/plan', params={**ribeye, 'width_mm': 25, 'length_mm': 180}).status_code == 422


def test_calibrate_fits_a_probe_log_and_rejects_a_flat_one(client):
    steak = {'thickness_mm': 38, 'width_mm': 110, 'length_mm': 160, 'start_c': 5}
    truth = Steak(38, width_mm=110, length_mm=160, physics=replace(PHYSICS, diffusivity=1.4e-7))
    readings = probe_log(truth, 57.5, [float(m) for m in range(0, 71, 5)])
    body = client.post('/sousvide/calibrate', json={**steak, 'bath_c': 57.5, 'readings': readings}).json()
    assert body['alpha'] == pytest.approx(1.4, rel=0.01)
    assert body['readings'] == 15 and len(body['curve']) == 15
    flat = [[0, 5], [5, 5.5], [10, 6]]
    assert client.post('/sousvide/calibrate', json={**steak, 'bath_c': 57.5, 'readings': flat}).status_code == 422


def test_plan_warns_about_long_cooks_below_pasteurizing_temperature(client):
    body = client.get('/sousvide/plan', params={'thickness_mm': 90, 'target_c': 50, 'boost_c': 0}).json()
    assert 'below 54.4 C' in body['warnings'][0]


def test_plan_rejects_a_steak_too_thick_to_model(client):
    assert client.get('/sousvide/plan', params={'thickness_mm': 200}).status_code == 422


def test_validation_loader_reads_assumed_values_and_rejects_a_bad_phase(tmp_path):
    from sousvide.experiments import validate

    good = tmp_path / 'sear_example.csv'
    good.write_text('# source: example\n'
                    '# cut: ribeye   thickness_mm: 20 ("about 2 cm")   weight_g: unknown (150 assumed)   width_mm: unknown   bone: none\n'
                    '# start_c: unknown (5 assumed, fridge)   bath_c: 52\n'
                    '# schedule: bath 120 52; sear 1 a; sear 1 b; rest 3\n'
                    'min,phase,core_c,bath_c\n'
                    '0,bath,5,52.5\n'
                    '120,bath,51.8,\n'
                    '122.5,rest,60\n')
    data = validate.load(good)
    assert (data.steak.thickness_mm, data.steak.start_c, data.bath_c) == (20, 5, 52)
    assert data.steak.width_mm and data.steak.length_mm  # filled in from the assumed weight
    assert data.assumed == ['start_c', 'weight_g']
    assert [(s.phase, s.minutes, s.bath_c, s.face) for s in data.steps] == [
        ('bath', 120, 52, 'both'), ('sear', 1, None, 'a'), ('sear', 1, None, 'b'), ('rest', 3, None, 'both')]
    assert [(r.phase, r.core_c, r.bath_c) for r in data.rows] == [('bath', 5, 52.5), ('bath', 51.8, None), ('rest', 60, None)]
    # The logged bath column drives the model, not the header's nominal 52.
    assert validate.at(validate.planner(data), 120) == pytest.approx(52.5, abs=0.05)

    bad = tmp_path / 'bath_bad.csv'
    bad.write_text('# thickness_mm: 25   start_c: 5   bath_c: 55\nmin,phase,core_c\n0,bath,5\n10,oven,30\n')
    with pytest.raises(ValueError, match='bath_bad.csv.*phase'):
        validate.load(bad)
