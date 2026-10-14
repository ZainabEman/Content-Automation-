"""The registry database (PRD D1): state/registry.db, numbered migrations, backups, transactions.

stdlib sqlite3, no ORM. The connection runs in autocommit mode and every write goes through
transaction(): commit on success, roll back on any error; a nested call becomes a savepoint, so
a helper's writes join its caller's transaction. Before a migration upgrades an existing
database, a copy goes to state/backups/registry-<UTC timestamp>.db (a new, empty database has
nothing to copy). Timestamps are UTC ISO strings ending in Z, so they sort as text.
"""

import itertools
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB_PATH = Path("state/registry.db")  # git-ignored
BACKUP_DIR = "backups"  # next to the database: state/backups/


class RegistryError(RuntimeError):
    """A registry rule was broken; the message says what to do."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


# Fixed small enums get a CHECK; statuses and kinds are checked in statuses.py and items.py
# (one source of truth). Events have no foreign key and cannot be changed or deleted.
SCHEMA_1 = """
CREATE TABLE id_counter (
    name TEXT PRIMARY KEY,
    next_value INTEGER NOT NULL CHECK (next_value >= 1)
);
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    number INTEGER NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    platforms TEXT NOT NULL DEFAULT '[]',
    parent_id TEXT REFERENCES items (id),
    planned_date TEXT,
    source_refs TEXT NOT NULL DEFAULT '[]',
    package_path TEXT,
    current_version INTEGER NOT NULL DEFAULT 1,
    approved_version INTEGER,
    idea_status TEXT NOT NULL,
    generation_status TEXT NOT NULL,
    review_status TEXT NOT NULL,
    upload_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE aliases (
    alias TEXT PRIMARY KEY COLLATE NOCASE,
    item_id TEXT NOT NULL REFERENCES items (id),
    created_at TEXT NOT NULL
);
CREATE INDEX aliases_item ON aliases (item_id);
CREATE TABLE versions (
    item_id TEXT NOT NULL REFERENCES items (id),
    version INTEGER NOT NULL CHECK (version >= 1),
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    feedback TEXT,
    package_path TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'approved', 'superseded')),
    PRIMARY KEY (item_id, version)
);
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items (id),
    version INTEGER NOT NULL,
    gate TEXT NOT NULL CHECK (gate IN ('idea', 'review')),
    action TEXT NOT NULL CHECK (action IN ('approve', 'reject', 'revise')),
    text TEXT,
    actor TEXT NOT NULL CHECK (actor IN ('user', 'system')),
    created_at TEXT NOT NULL
);
CREATE INDEX decisions_item ON decisions (item_id);
CREATE TABLE authorizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_ids TEXT NOT NULL,
    job_types TEXT NOT NULL,
    provider TEXT NOT NULL,
    unit TEXT NOT NULL CHECK (unit IN ('usd', 'credits')),
    max_amount REAL NOT NULL CHECK (max_amount >= 0),
    spent REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed', 'exceeded')),
    actor TEXT NOT NULL CHECK (actor IN ('user', 'system')),
    command TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items (id),
    version INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    inputs TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    estimate REAL,
    actual REAL,
    unit TEXT CHECK (unit IN ('usd', 'credits')),
    authorization_id INTEGER REFERENCES authorizations (id),
    result_path TEXT,
    error TEXT,
    timeout_seconds INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX jobs_key ON jobs (idempotency_key);
CREATE INDEX jobs_item ON jobs (item_id);
CREATE TABLE publications (
    item_id TEXT NOT NULL REFERENCES items (id),
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    url TEXT,
    published_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (item_id, platform)
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('user', 'system')),
    command TEXT,
    item_id TEXT,
    version INTEGER,
    type TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX events_item ON events (item_id);
CREATE INDEX events_created ON events (created_at);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
"""

# The deliverable an item was made for (PRD §14 D-1: one item per package and deliverable).
SCHEMA_2 = "ALTER TABLE items ADD COLUMN deliverable TEXT;"

# Jobs (§14 D-5, D-6): item-less jobs (`ca image`, `ca video`), cancelled, base_key + redo_n
# (a deliberate redo is a new job), a rejected result (person or set check, carousel check).
# Authorizations grouped by their dry run (D-4); the upload provider of an item (D-16).
SCHEMA_3 = """
CREATE TABLE jobs_v3 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT REFERENCES items (id),
    version INTEGER,
    job_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    base_key TEXT NOT NULL,
    redo_n INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL,
    inputs TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    estimate REAL,
    actual REAL,
    unit TEXT CHECK (unit IN ('usd', 'credits')),
    authorization_id INTEGER REFERENCES authorizations (id),
    result_path TEXT,
    error TEXT,
    rejected_at TEXT,
    reject_reason TEXT,
    timeout_seconds INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);
INSERT INTO jobs_v3 (id, item_id, version, job_type, provider, base_key, redo_n,
    idempotency_key, inputs, status, attempts, max_attempts, estimate, actual, unit,
    authorization_id, result_path, error, timeout_seconds, created_at, started_at, finished_at,
    updated_at)
SELECT id, item_id, version, job_type, provider, idempotency_key, 0, idempotency_key, inputs,
    status, attempts, max_attempts, estimate, actual, unit, authorization_id, result_path, error,
    timeout_seconds, created_at, started_at, finished_at, updated_at FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_v3 RENAME TO jobs;
CREATE INDEX jobs_key ON jobs (idempotency_key);
CREATE INDEX jobs_base ON jobs (base_key);
CREATE INDEX jobs_item ON jobs (item_id);
ALTER TABLE authorizations ADD COLUMN dryrun_id TEXT;
ALTER TABLE authorizations ADD COLUMN closed_at TEXT;
ALTER TABLE authorizations ADD COLUMN note TEXT;
CREATE INDEX authorizations_dryrun ON authorizations (dryrun_id);
ALTER TABLE items ADD COLUMN upload_provider TEXT;
"""

# The last text the app wrote to a view file (the calendar CSVs): the hand-edit guard (D10).
SCHEMA_4 = """
CREATE TABLE written_files (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    content TEXT NOT NULL,
    written_at TEXT NOT NULL
);
"""

# The last value written to each workflow cell of the Content Tracker (D-15).
SCHEMA_5 = """
CREATE TABLE tracker_cells (
    row_key TEXT NOT NULL,
    column_name TEXT NOT NULL,
    written TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (row_key, column_name)
);
"""

# Phase 5 (P5-D1, D4, D5, D9, D10, D11): idea details, sources (SRC-####), idea <-> source
# links and labelled claims (CL-####).
SCHEMA_6 = """
CREATE TABLE ideas (
    item_id TEXT PRIMARY KEY REFERENCES items (id),
    pillar TEXT,
    score INTEGER,
    score_parts TEXT NOT NULL DEFAULT '{}',
    flags TEXT NOT NULL DEFAULT '[]',
    original_text TEXT,
    assumptions TEXT NOT NULL DEFAULT '[]',
    duplicate_of TEXT REFERENCES items (id),
    updated_at TEXT NOT NULL
);
CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    number INTEGER NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('newsletter', 'article', 'web', 'manual')),
    url TEXT,
    original_url TEXT,
    title TEXT,
    publisher TEXT,
    language TEXT,
    published_at TEXT,
    fetched_at TEXT,
    purpose TEXT,
    trust TEXT NOT NULL DEFAULT 'unknown' CHECK (trust IN ('primary', 'secondary', 'unknown')),
    text_path TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX sources_url ON sources (url);
CREATE INDEX sources_original ON sources (original_url);
CREATE TABLE idea_sources (
    item_id TEXT NOT NULL REFERENCES items (id),
    source_id TEXT NOT NULL REFERENCES sources (id),
    role TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (item_id, source_id)
);
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    number INTEGER NOT NULL UNIQUE,
    item_id TEXT NOT NULL REFERENCES items (id),
    text TEXT NOT NULL,
    label TEXT NOT NULL CHECK (label IN ('fact', 'opinion', 'speculation')),
    status TEXT NOT NULL CHECK (status IN ('verified', 'unverified', 'disputed', 'outdated')),
    source_refs TEXT NOT NULL DEFAULT '[]',
    counter_refs TEXT NOT NULL DEFAULT '[]',
    reason TEXT,
    checked_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX claims_item ON claims (item_id);
"""

SCHEMA_7 = """
CREATE TABLE artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items (id),
    version INTEGER NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('script', 'brief', 'copy')),
    path TEXT NOT NULL,
    check_result TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX artifacts_item ON artifacts (item_id, version);
"""

SCHEMA_8 = """
CREATE TABLE decisions_v8 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items (id),
    version INTEGER NOT NULL,
    gate TEXT NOT NULL CHECK (gate IN ('idea', 'review')),
    action TEXT NOT NULL CHECK (action IN ('approve', 'reject', 'revise')),
    text TEXT,
    actor TEXT NOT NULL CHECK (actor IN ('user', 'system', 'migration')),
    created_at TEXT NOT NULL
);
INSERT INTO decisions_v8 SELECT id, item_id, version, gate, action, text, actor, created_at
    FROM decisions;
DROP TABLE decisions;
ALTER TABLE decisions_v8 RENAME TO decisions;
CREATE INDEX decisions_item ON decisions (item_id);
CREATE TABLE events_v8 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('user', 'system', 'migration')),
    command TEXT,
    item_id TEXT,
    version INTEGER,
    type TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}'
);
INSERT INTO events_v8 SELECT id, created_at, actor, command, item_id, version, type, details
    FROM events;
DROP TABLE events;
ALTER TABLE events_v8 RENAME TO events;
CREATE INDEX events_item ON events (item_id);
CREATE INDEX events_created ON events (created_at);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
"""

SCHEMA_9 = """
ALTER TABLE items ADD COLUMN production_status TEXT NOT NULL DEFAULT 'not_started';
CREATE TABLE artifacts_v9 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items (id),
    version INTEGER NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('script', 'brief', 'copy', 'recording', 'edit', 'final',
                                       'thumbnail', 'audio', 'handoff')),
    path TEXT NOT NULL,
    check_result TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
INSERT INTO artifacts_v9 SELECT id, item_id, version, type, path, check_result, created_at
    FROM artifacts;
DROP TABLE artifacts;
ALTER TABLE artifacts_v9 RENAME TO artifacts;
CREATE INDEX artifacts_item ON artifacts (item_id, version);
"""

MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "registry core", SCHEMA_1),
    Migration(2, "item deliverable", SCHEMA_2),
    Migration(3, "jobs, redo and authorization groups", SCHEMA_3),
    Migration(4, "written view files", SCHEMA_4),
    Migration(5, "tracker last-written cells", SCHEMA_5),
    Migration(6, "ideas, sources and claims", SCHEMA_6),
    Migration(7, "script and brief artifacts", SCHEMA_7),
    Migration(8, "migration actor", SCHEMA_8),
    Migration(9, "production status and media artifacts", SCHEMA_9),
)

_SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""
_savepoints = itertools.count(1)


@dataclass(frozen=True)
class MigrationResult:
    applied: tuple[Migration, ...]
    backup: Path | None  # the copy made before the first migration ran


def now() -> str:
    """The current UTC time as ISO text (2026-10-13T09:30:00.123456Z)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (or create) the database file: autocommit mode, rows by name, foreign keys on."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, autocommit=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One transaction: commit on success, roll back on any error (nested: a savepoint)."""
    if conn.in_transaction:
        name = f"sp_{next(_savepoints)}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        conn.execute(f"RELEASE {name}")
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute(_SCHEMA_TABLE)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def backup(conn: sqlite3.Connection, path: Path) -> Path:
    """Copy the database to <db folder>/backups/registry-<UTC timestamp>.db; return the copy."""
    folder = path.parent / BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = folder / f"registry-{stamp}.db"
    for number in itertools.count(2):
        if not target.exists():
            break
        target = folder / f"registry-{stamp}-{number}.db"
    with closing(sqlite3.connect(target)) as copy:
        conn.backup(copy)
    return target


def migrate(
    conn: sqlite3.Connection, path: Path, migrations: Sequence[Migration] = MIGRATIONS
) -> MigrationResult:
    """Apply every migration newer than the database, each in its own transaction."""
    numbers = [migration.version for migration in migrations]
    if numbers != list(range(1, len(numbers) + 1)):
        raise RegistryError(f"Migrations must be numbered 1..n in order, got {numbers}.")
    current = schema_version(conn)
    if current > len(migrations):
        raise RegistryError(
            f"{path} is at schema {current}, newer than this code ({len(migrations)}): "
            "update the code before using this database."
        )
    pending = tuple(migrations[current:])
    if not pending:
        return MigrationResult((), None)
    saved = backup(conn, path) if current else None
    for migration in pending:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, now()),
            )
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    return MigrationResult(pending, saved)
