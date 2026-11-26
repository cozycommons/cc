"""/sousvide: cook times for a steak in a water bath, classic against two shortcuts.

A plan costs about half a second of CPU (model.py runs a few hundred heat-conduction
solves), so inputs are rounded to steps a cook can actually set and plans are
cached per process.
"""
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Query

from . import model

router = APIRouter()


@lru_cache(maxsize=256)
def cached_plan(thickness_mm: float, shape: str, start_c: float, target_c: float,
                boost_c: float, sear_s: float) -> dict:
    return model.plan(model.Steak(thickness_mm, shape, start_c), target_c, boost_c, model.Finish(sear_s))


@router.get('/plan')
def plan(
    thickness_mm: float = Query(38, ge=5, le=100),
    shape: Literal['slab', 'cylinder'] = 'slab',
    start_c: float = Query(5, ge=0, le=30),
    target_c: float = Query(54.5, ge=45, le=75),
    boost_c: float = Query(3, ge=0, le=10),
    sear_s: float = Query(45, ge=0, le=180),
):
    return cached_plan(round(thickness_mm), shape, round(start_c * 2) / 2, round(target_c * 2) / 2,
                       round(boost_c * 2) / 2, round(sear_s / 15) * 15)
