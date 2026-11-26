import math

import pytest

from sousvide import model
from sousvide.model import Body, Finish, Steak


def core_after(steak: Steak, bath_c: float, seconds: float) -> float:
    body = Body(steak)
    for _ in range(round(seconds / model.BATH_STEP_S)):
        body.step(bath_c, model.H_BATH, model.BATH_STEP_S)
    return body.core


def test_slab_core_matches_the_series_solution():
    # Plane wall with convection, first term of the series (valid for Fourier number > 0.2):
    # (T0 - Tb) / (Ti - Tb) = C1 exp(-z^2 Fo), where z tan z = Bi.
    steak = Steak(38, start_c=5)
    half = steak.half_m
    biot = model.H_BATH * half / model.CONDUCTIVITY
    lo, hi = 1e-6, math.pi / 2 - 1e-9
    for _ in range(100):
        z = (lo + hi) / 2
        lo, hi = (z, hi) if z * math.tan(z) < biot else (lo, z)
    c1 = 4 * math.sin(z) / (2 * z + math.sin(2 * z))
    seconds = 3600
    fourier = model.DIFFUSIVITY * seconds / half ** 2
    expected = 55 + (5 - 55) * c1 * math.exp(-z * z * fourier)
    assert core_after(steak, 55, seconds) == pytest.approx(expected, abs=0.3)


def test_a_steak_already_at_bath_temperature_stays_there():
    assert core_after(Steak(30, start_c=55), 55, 1800) == pytest.approx(55, abs=1e-9)


def test_cook_time_grows_nearly_with_the_square_of_thickness_and_cylinders_are_faster():
    def minutes(steak):
        return model.classic(steak, 55, Finish(0)).minutes
    thin, thick = minutes(Steak(20)), minutes(Steak(40))
    # Baldwin's tables put a 1 inch (25 mm) steak from the fridge at roughly 1 to 1.5 h.
    assert 60 <= minutes(Steak(25)) <= 95
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
        body.step(target, model.H_BATH, model.BATH_STEP_S)
        assert body.core <= target + model.READY_WITHIN_C


def test_a_sear_carries_the_core_past_a_classic_cook():
    steak, target = Steak(38), 54.5
    seared = model.classic(steak, target, Finish(45))
    assert seared.core_peak_c > target
    assert seared.summary(target)['gray_mm'] > 0


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
    assert body['trace']['classic'][0] == {'min': 0, 'phase': 'bath', 'core': 5, 'mid': 5, 'surface': 5}
    assert body['warnings'] == []


def test_plan_warns_about_long_cooks_below_pasteurizing_temperature(client):
    body = client.get('/sousvide/plan', params={'thickness_mm': 90, 'target_c': 50, 'boost_c': 0}).json()
    assert 'below 54.4 C' in body['warnings'][0]


def test_plan_rejects_a_steak_too_thick_to_model(client):
    assert client.get('/sousvide/plan', params={'thickness_mm': 200}).status_code == 422
