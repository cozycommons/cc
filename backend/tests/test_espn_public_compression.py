from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from espn.public_compression import PublicPredictionsCompression


def test_public_snapshots_negotiate_compression_and_keep_cache_headers():
    payload = {"matchups": ["snapshot data" * 1000]}

    async def snapshot(request):
        return JSONResponse(payload, headers={"Cache-Control": "public, max-age=300"})

    app = Starlette(routes=[
        Route("/espn/public/predictions/latest", snapshot),
        Route("/other", snapshot),
    ])
    app.add_middleware(PublicPredictionsCompression)
    with TestClient(app) as client:
        compressed = client.get("/espn/public/predictions/latest", headers={"Accept-Encoding": "gzip"})
        assert compressed.json() == payload
        assert compressed.headers["content-encoding"] == "gzip"
        assert int(compressed.headers["content-length"]) < 1000
        assert compressed.headers["vary"] == "Accept-Encoding"
        assert compressed.headers["cache-control"] == "public, max-age=300"
        plain = client.get("/espn/public/predictions/latest", headers={"Accept-Encoding": "identity"})
        assert plain.json() == payload
        assert "content-encoding" not in plain.headers
        assert "content-encoding" not in client.get("/other").headers
