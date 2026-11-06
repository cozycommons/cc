"""Small synthetic trip app used by the local prototype demonstration."""

import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import sqlite3
from pathlib import Path


DATA = Path("/workspace/data")
DATA.mkdir(exist_ok=True)
DATABASE = DATA / "trip.sqlite3"


def notes():
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, note text NOT NULL)"
        )
        return conn.execute("SELECT note FROM notes ORDER BY id").fetchall()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/headers":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"authorization": self.headers.get("Authorization")}
                ).encode()
            )
            return
        rows = "".join("<li>" + html.escape(row[0]) + "</li>" for row in notes())
        label = "Experiment" if os.environ.get("PUBLIC_DEMO") else "Weekend trip"
        body = f"""<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>{label}</title>
<style>body{{font:17px system-ui;color:#30382f;background:#f5f3eb;max-width:720px;margin:64px auto;padding:0 24px}}small{{color:#64705e}}h1{{font-size:40px;letter-spacing:-1px}}section{{background:#fffdf8;border:1px solid #dddacb;border-radius:16px;padding:24px;margin:24px 0}}input,button{{font:inherit;padding:10px;border:1px solid #bbc4b4;border-radius:8px}}button{{background:#365b43;color:white}}li{{margin:12px 0}}</style></head>
<body><small>COZY COMMONS · SYNTHETIC DEMO</small><h1>{label}</h1><p>A shared plan you and your agents can change.</p>
<section><h2>Saturday</h2><p>10:00 · Meet for coffee</p><p>12:00 · Walk by the river</p><p>18:00 · Dinner together</p></section>
<section><h2>Group notes</h2><ul>{rows or "<li>No notes yet</li>"}</ul>"""
        if not os.environ.get("PUBLIC_DEMO"):
            body += '<form method="post"><label for="note">Add a note</label><p><input id="note" name="note" required maxlength="500"> <button>Add</button></p></form>'
        body += "</section></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if os.environ.get("PUBLIC_DEMO") or not 0 < length <= 4096:
            self.send_error(403)
            return
        note = (
            parse_qs(self.rfile.read(length).decode())
            .get("note", [""])[0]
            .strip()[:500]
        )
        if note:
            with sqlite3.connect(DATABASE) as conn:
                conn.execute("INSERT INTO notes (note) VALUES (?)", (note,))
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


notes()
ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Handler).serve_forever()
