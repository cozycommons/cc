"""Compress public snapshots without buffering other API responses."""

from starlette.middleware.gzip import GZipMiddleware


# Large public JSON bodies worth gzip; Cozy Bikes' live map payload is ~200 KB raw.
COMPRESSED_PATHS = frozenset({"/espn/public/predictions/latest", "/bikes/live"})


class PublicPredictionsCompression:
    def __init__(self, app):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=1000, compresslevel=5)

    async def __call__(self, scope, receive, send):
        handler = self.compressed if (
            scope["type"] == "http"
            and scope["path"] in COMPRESSED_PATHS
        ) else self.app
        await handler(scope, receive, send)
