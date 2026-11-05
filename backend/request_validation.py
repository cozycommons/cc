"""422 responses that never echo what the client sent.

FastAPI's default validation error includes each failing value under `input`
(for a missing field, the whole submitted body) and sometimes `ctx`. Several
routes take third-party passwords, cookies and SMS codes, so a malformed request
would send them straight back into logs, proxies and browser devtools. Only the
location, type and message are returned.
"""
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

SAFE_KEYS = ('type', 'loc', 'msg')


async def validation_error_without_input(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{key: error[key] for key in SAFE_KEYS if key in error} for error in exc.errors()]
    return JSONResponse(status_code=422, content={'detail': jsonable_encoder(errors)})


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_without_input)
