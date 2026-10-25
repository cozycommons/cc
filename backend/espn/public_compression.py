"""Compress public snapshots without buffering other API responses."""

from starlette.middleware.gzip import GZipMiddleware


class PublicPredictionsCompression:
    def __init__(self, app):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=1000, compresslevel=5)

    async def __call__(self, scope, receive, send):
        handler = self.compressed if (
            scope["type"] == "http"
            and scope["path"] == "/espn/public/predictions/latest"
        ) else self.app
        await handler(scope, receive, send)
