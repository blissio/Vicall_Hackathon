"""SQLite persistence and one-time imports of legacy workspace JSON files."""
import json
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path
from datetime import datetime, timezone


@contextmanager
def connect(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "workspace.sqlite3", timeout=30)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS documents(name TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS organizations(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY, business_id TEXT NOT NULL, body TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS contacts_business ON contacts(business_id);
        CREATE TABLE IF NOT EXISTS saved_searches(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews(business_id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    try:
        with db:
            yield db
    finally:
        db.close()


def load_document(path, default=None):
    """SQLite is authoritative; existing JSON is imported once, never deleted."""
    path = Path(path)
    with connect(path.parent) as db:
        row = db.execute("SELECT body FROM documents WHERE name=?", (path.name,)).fetchone()
        if row:
            return json.loads(row[0])
        if not path.exists():
            return default
        value = json.loads(path.read_text(encoding="utf-8"))
        db.execute("INSERT INTO documents VALUES (?,?)", (path.name, json.dumps(value)))
        return value


def save_document(path, value):
    path = Path(path)
    body = json.dumps(value, ensure_ascii=False, indent=2)
    # Keep the old file format as a compatibility export. The SQL transaction
    # commits only after the export succeeds; reads use SQL after migration.
    with connect(path.parent) as db:
        db.execute("INSERT OR REPLACE INTO documents VALUES (?,?)", (path.name, body))
        temporary = path.with_suffix(".tmp")
        temporary.write_text(body, encoding="utf-8")
        temporary.replace(path)


def backup(directory, destination):
    with connect(directory) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)


def stamp():
    return datetime.now(timezone.utc).isoformat()
