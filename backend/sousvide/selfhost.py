"""Run the sous vide planner at home: the page, the planner and the probe bridge on one port.

The public site plans cooks; a home server can also hear the kitchen's devices,
which the public site never can (they are on the home network). Build the page
to call its own origin, then serve it from here:

    cd frontend && VITE_API_URL=dice-sandbox:same-origin VITE_SUPABASE_URL=dice-sandbox:same-origin \\
        VITE_SUPABASE_ANON_KEY=selfhost npm run build
    cd backend && python -m sousvide.selfhost --dist ../frontend/dist

See docs/cozy-sous-vide.md, "Self-hosting", for posting probe readings.
"""
import argparse
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from . import bridge, routes

# Tells the page it is served next to a bridge, so it offers the home thermometer.
BRIDGE_META = '<meta name="sousvide-bridge" content="1">'


def create_app(dist: Path) -> FastAPI:
    dist = dist.resolve()
    index = (dist / 'index.html').read_text()
    if '</head>' not in index:
        raise ValueError(f'{dist / "index.html"} is not a built page')
    page = index.replace('</head>', f'{BRIDGE_META}</head>', 1)

    app = FastAPI(title='Cozy sous vide, self-hosted', docs_url=None, redoc_url=None)
    app.include_router(routes.router, prefix='/sousvide')
    app.include_router(bridge.router, prefix='/sousvide')

    @app.get('/{path:path}', include_in_schema=False)
    def static(path: str):
        """A built file if there is one, otherwise the page, which routes itself."""
        if path.startswith('sousvide/'):
            raise HTTPException(404)
        target = (dist / path).resolve()
        if path and target.is_file() and target.is_relative_to(dist) and target.name != 'index.html':
            return FileResponse(target)
        return HTMLResponse(page)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dist', type=Path, required=True, help='the built frontend (frontend/dist)')
    parser.add_argument('--host', default='127.0.0.1',
                        help='127.0.0.1 by default; put it behind `tailscale serve` rather than opening it to the LAN')
    parser.add_argument('--port', type=int, default=8790)
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(create_app(args.dist), host=args.host, port=args.port)


if __name__ == '__main__':
    main()
