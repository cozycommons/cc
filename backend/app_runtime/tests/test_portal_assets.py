from pathlib import Path
from xml.etree import ElementTree

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app_runtime.portal_assets import FAVICON, router


def test_portal_favicon_reuses_canonical_branding():
    canonical = Path(__file__).resolve().parents[3] / "frontend/public/favicon.svg"
    assert FAVICON.read_bytes() == canonical.read_bytes()
    assert ElementTree.fromstring(FAVICON.read_bytes()).tag == "{http://www.w3.org/2000/svg}svg"


def test_portal_favicon_is_public_and_has_svg_content_type():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, base_url="https://apps.example.test", follow_redirects=False) as client:
        response = client.get("/favicon.svg")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/svg+xml"
        assert response.content == FAVICON.read_bytes()
        assert "location" not in response.headers
        assert "set-cookie" not in response.headers
        head = client.head("/favicon.svg")
        assert head.status_code == 200
        assert head.headers["content-type"] == "image/svg+xml"
        assert head.content == b""
