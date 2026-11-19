#!/usr/bin/env python3
"""A small, local-only full-text search engine for your documents."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("PRIVATE_SEARCH_DB", Path.home() / ".private-search-engine" / "index.sqlite3")).expanduser()
MAX_FILE_BYTES = 1_000_000
MAX_QUERY_CHARS = 200
MAX_RESULTS = 20
ALLOWED_SUFFIXES = {".txt", ".md"}


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def initialize(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                source_path TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(title, content, tokenize='unicode61')"
        )


def index_directory(directory: Path, db_path: Path = DB_PATH) -> tuple[int, int]:
    root = directory.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    initialize(db_path)
    indexed = skipped = 0
    seen: set[Path] = set()
    for candidate in root.rglob("*"):
        if candidate.suffix.lower() not in ALLOWED_SUFFIXES or not candidate.is_file():
            continue
        source = candidate.resolve()
        try:
            source.relative_to(root)
        except ValueError:
            skipped += 1
            continue
        if source in seen:
            continue
        seen.add(source)
        try:
            raw = source.read_bytes()
            if len(raw) > MAX_FILE_BYTES:
                skipped += 1
                continue
            content = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped += 1
            continue

        title = source.stem
        indexed_at = datetime.now(timezone.utc).isoformat()
        with connect(db_path) as conn:
            conn.execute(
                """INSERT INTO documents(title, source_path, content, indexed_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source_path) DO UPDATE SET
                       title=excluded.title, content=excluded.content, indexed_at=excluded.indexed_at""",
                (title, str(source), content, indexed_at),
            )
            document_id = conn.execute(
                "SELECT id FROM documents WHERE source_path = ?", (str(source),)
            ).fetchone()["id"]
            conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (document_id,))
            conn.execute(
                "INSERT INTO documents_fts(rowid, title, content) VALUES (?, ?, ?)",
                (document_id, title, content),
            )
        indexed += 1
    return indexed, skipped


def search_documents(query: str, db_path: Path = DB_PATH, limit: int = MAX_RESULTS) -> list[dict[str, str]]:
    query = query[:MAX_QUERY_CHARS]
    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    if not terms:
        return []
    # Quote each token to treat user input as terms, not FTS5 query syntax.
    match_query = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
    initialize(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT d.title, d.source_path,
                      snippet(documents_fts, 1, '', '', ' … ', 24) AS excerpt
               FROM documents_fts
               JOIN documents AS d ON d.id = documents_fts.rowid
               WHERE documents_fts MATCH ?
               ORDER BY bm25(documents_fts)
               LIMIT ?""",
            (match_query, min(max(limit, 1), MAX_RESULTS)),
        ).fetchall()
    return [
        {"title": row["title"], "source": Path(row["source_path"]).name, "excerpt": row["excerpt"]}
        for row in rows
    ]


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Private Search</title>
  <style>
    :root { font: 16px/1.5 system-ui, sans-serif; color-scheme: light dark; }
    body { max-width: 760px; margin: 10vh auto; padding: 0 1.25rem; }
    h1 { margin-bottom: .2rem; } .muted { color: #777; }
    form { display: flex; gap: .6rem; margin: 2rem 0 1rem; }
    input { flex: 1; min-width: 0; padding: .8rem; font: inherit; }
    button { padding: .7rem 1rem; font: inherit; cursor: pointer; }
    article { border-top: 1px solid #8886; padding: 1rem 0; }
    article h2 { font-size: 1.1rem; margin: 0; } article p { margin: .35rem 0; }
    #status { min-height: 1.5em; }
  </style>
</head>
<body>
  <h1>Private Search</h1>
  <p class="muted">Search your locally indexed text and Markdown files. Your documents stay on this device.</p>
  <form id="search-form">
    <input id="query" type="search" maxlength="200" placeholder="Search your documents…" autocomplete="off" required>
    <button type="submit">Search</button>
  </form>
  <p id="status" class="muted" aria-live="polite">Index a folder first: <code>python app.py index /path/to/documents</code></p>
  <section id="results" aria-label="Search results"></section>
  <script>
    const form = document.querySelector('#search-form');
    const input = document.querySelector('#query');
    const status = document.querySelector('#status');
    const results = document.querySelector('#results');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      status.textContent = 'Searching…';
      results.replaceChildren();
      try {
        const response = await fetch('/api/search', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: input.value })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Search failed');
        status.textContent = data.results.length ? `${data.results.length} result(s)` : 'No matches found.';
        for (const result of data.results) {
          const article = document.createElement('article');
          const heading = document.createElement('h2');
          const source = document.createElement('p');
          const excerpt = document.createElement('p');
          heading.textContent = result.title;
          source.className = 'muted'; source.textContent = result.source;
          excerpt.textContent = result.excerpt;
          article.append(heading, source, excerpt); results.append(article);
        }
      } catch (error) { status.textContent = error.message; }
    });
  </script>
</body>
</html>
"""


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "PrivateSearch/1.0"

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/health":
            self.send_json(200, {"status": "ok"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/search":
            self.send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4096:
                self.send_json(413, {"error": "Request body must be between 1 and 4096 bytes"})
                return
            payload = json.loads(self.rfile.read(length))
            query = payload.get("query") if isinstance(payload, dict) else None
            if not isinstance(query, str):
                self.send_json(400, {"error": "query must be a string"})
                return
            results = search_documents(query, DB_PATH)
            self.send_json(200, {"results": results})
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid JSON request"})
        except sqlite3.Error:
            self.send_json(500, {"error": "Search index is unavailable"})

    def log_message(self, fmt: str, *args) -> None:
        # Avoid writing search requests to logs.
        return


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("For privacy, the server only accepts loopback addresses.")
    initialize(DB_PATH)
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Private Search is running at http://{host}:{port} (index: {DB_PATH})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Private Search.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local-only search for text and Markdown documents.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    index_parser = subparsers.add_parser("index", help="Index .txt and .md files in a folder")
    index_parser.add_argument("directory", type=Path)
    serve_parser = subparsers.add_parser("serve", help="Start the private search web app")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.command == "index":
        indexed, skipped = index_directory(args.directory)
        print(f"Indexed {indexed} file(s); skipped {skipped}. Index: {DB_PATH}")
    else:
        serve(args.host, args.port)


if __name__ == "__main__":
    main()
