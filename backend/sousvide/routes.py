"""/sousvide: cook times for a steak in a water bath, classic against two shortcuts.

A plan costs up to about a second of CPU (model.py runs a few hundred
heat-conduction solves, each along up to three axes), so inputs are rounded to
steps a cook can actually measure and plans are cached per process.
"""
from dataclasses import replace
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import calibrate, model

router = APIRouter()

Shape = Literal['slab', 'cylinder', 'puck']
Bone = Literal['none', 'edge', 'middle']


def measured(thickness_mm: float, shape: str, start_c: float, width_mm: float | None, length_mm: float | None,
             weight_g: float | None, bone: str, bone_mm: float, alpha: float | None, h_bath: float | None) -> model.Steak:
    """The steak the cook measured, with unmeasured sides filled from the weight."""
    defaults = model.Physics()
    physics = replace(defaults, diffusivity=alpha * 1e-7 if alpha else defaults.diffusivity,
                      h_bath=h_bath or defaults.h_bath)
    steak = model.sized(model.Steak(thickness_mm, shape, start_c, width_mm, length_mm, physics,
                                    bone if shape == 'slab' else 'none', bone_mm), weight_g)
    if steak.bone == 'middle' and steak.width_mm and steak.bone_mm >= steak.width_mm:
        raise HTTPException(422, 'The bone is as wide as the steak.')
    return steak


def rounded(value: float | None, step: float) -> float | None:
    return None if value is None else round(value / step) * step


@lru_cache(maxsize=256)
def cached_plan(thickness_mm: float, shape: str, start_c: float, target_c: float, boost_c: float, sear_s: float,
                width_mm: float | None, length_mm: float | None, weight_g: float | None, bone: str, bone_mm: float,
                alpha: float | None, h_bath: float | None) -> dict:
    steak = measured(thickness_mm, shape, start_c, width_mm, length_mm, weight_g, bone, bone_mm, alpha, h_bath)
    sides = [width_mm, length_mm] if shape == 'slab' else [width_mm] if shape == 'puck' else [length_mm]
    out = model.plan(steak, target_c, boost_c, model.Finish(sear_s))
    out['steak'] = {
        'width_mm': steak.width_mm and round(steak.width_mm), 'length_mm': steak.length_mm and round(steak.length_mm),
        'heated_width_mm': steak.heated_width_mm and round(steak.heated_width_mm), 'bone': steak.bone,
        # Where the sides came from: the cook's calipers, the scale, or nowhere (an infinite slab).
        'sized_by': 'measured' if all(sides) else 'weight' if weight_g else 'measured' if any(sides) else 'thickness',
    }
    return out


@router.get('/plan')
def plan(
    thickness_mm: float = Query(51, ge=5, le=100),
    shape: Shape = 'slab',
    start_c: float = Query(5, ge=0, le=30),
    target_c: float = Query(54.5, ge=45, le=75),
    boost_c: float = Query(3, ge=0, le=10),
    sear_s: float = Query(45, ge=0, le=180),
    width_mm: float | None = Query(None, ge=20, le=400),
    length_mm: float | None = Query(None, ge=20, le=600),
    weight_g: float | None = Query(None, ge=50, le=5000),
    bone: Bone = 'none',
    bone_mm: float = Query(model.BONE_MM, ge=5, le=60),
    alpha: float | None = Query(None, ge=0.6, le=2.5, description='Diffusivity in 1e-7 m^2/s, from /sousvide/calibrate.'),
    h_bath: float | None = Query(None, ge=20, le=2000),
):
    return cached_plan(round(thickness_mm), shape, round(start_c * 2) / 2, round(target_c * 2) / 2,
                       round(boost_c * 2) / 2, round(sear_s / 15) * 15, rounded(width_mm, 5), rounded(length_mm, 5),
                       rounded(weight_g, 10), bone, round(bone_mm), rounded(alpha, 0.01), rounded(h_bath, 5))


class ProbeLog(BaseModel):
    """One cook: the steak as measured, the bath it sat in, and what the probe read."""
    thickness_mm: float = Field(ge=5, le=100)
    shape: Shape = 'slab'
    start_c: float = Field(ge=0, le=30)
    width_mm: float | None = Field(None, ge=20, le=400)
    length_mm: float | None = Field(None, ge=20, le=600)
    weight_g: float | None = Field(None, ge=50, le=5000)
    bone: Bone = 'none'
    bone_mm: float = Field(model.BONE_MM, ge=5, le=60)
    bath_c: float = Field(ge=40, le=90)
    # (minutes since the steak went in, core C). Ten hours bounds the fit's CPU.
    readings: list[tuple[float, float]] = Field(min_length=3, max_length=600)
    fit_h: bool = False


@router.post('/calibrate')
def calibrate_from_log(log: ProbeLog):
    """Fit alpha (and h when the log identifies it) to a probe log. Pass the result to /plan as alpha and h_bath."""
    if any(not 0 <= minute <= 600 or not -5 <= core <= 100 for minute, core in log.readings):
        raise HTTPException(422, 'Readings must be within 0 to 600 minutes and -5 to 100 C.')
    if max(core for _, core in log.readings) - min(core for _, core in log.readings) < 5:
        raise HTTPException(422, 'The core has to rise at least 5 C across the log to fit anything.')
    steak = measured(log.thickness_mm, log.shape, log.start_c, log.width_mm, log.length_mm, log.weight_g,
                     log.bone, log.bone_mm, None, None)
    out = calibrate.fit(steak, log.bath_c, log.readings, log.fit_h)
    return {**out, 'alpha': round(out['alpha'] * 1e7, 3)}  # in 1e-7 m^2/s, the unit /plan takes
