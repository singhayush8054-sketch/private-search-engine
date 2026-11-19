# Private Search

A small, local-first search engine for your own text and Markdown documents. It uses Python's standard library and SQLite FTS5: no hosted service, telemetry, external API, or third-party dependency.

## Requirements

- Python 3.10+
- A Python build with SQLite FTS5 enabled (usually included)

## Quick start

```bash
# Index .txt and .md files under a folder (subfolders are included)
python app.py index ~/Documents/notes

# Start the web interface, then open http://127.0.0.1:8000
python app.py serve
```

Re-run the `index` command after adding or editing files. Documents larger than 1 MB, files that aren't valid UTF-8, and formats other than `.txt` and `.md` are skipped.

By default, the SQLite index is stored at `~/.private-search-engine/index.sqlite3`, outside this repository. Set `PRIVATE_SEARCH_DB` to choose another index location:

```bash
PRIVATE_SEARCH_DB=/path/to/index.sqlite3 python app.py index ./documents
PRIVATE_SEARCH_DB=/path/to/index.sqlite3 python app.py serve
```

## Privacy and security

- The server binds to loopback (`127.0.0.1`) only and refuses non-loopback hosts.
- Search terms and document contents are not sent to any external service.
- Search requests are not written to the application log; the UI uses safe text rendering.
- The index stores document contents locally in SQLite. Protect your user account and index file accordingly.
- This is a local personal tool, not an authenticated multi-user service. Do not expose it through a public interface or reverse proxy.

## Development

```bash
python -m unittest discover -s tests -v
```

Only `.txt` and `.md` are supported in this initial version. PDF, Office documents, OCR, and automatic file watching are not included.
