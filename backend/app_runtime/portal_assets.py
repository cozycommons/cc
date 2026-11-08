"""Public, bundled branding for the Apps portal."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()
FAVICON = Path(__file__).with_name("static") / "favicon.svg"


@router.api_route("/favicon.svg", methods=["GET", "HEAD"])
def favicon():
    return FileResponse(FAVICON, media_type="image/svg+xml")
