from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import ROOT

_DB_PATH = ROOT / "state" / "openclaw.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS step_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              loop TEXT NOT NULL,
              step_id INTEGER NOT NULL,
              step_key TEXT NOT NULL,
              mode TEXT NOT NULL,         -- run | dry | verify
              status TEXT NOT NULL,        -- ok | failed | blocked
              started_at TEXT NOT NULL,
              finished_at TEXT,
              payload TEXT,                -- json
              error TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_step_runs_loop ON step_runs(loop, step_id);

            CREATE TABLE IF NOT EXISTS loop_state (
              loop TEXT PRIMARY KEY,
              cursor INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS kv (
              ns TEXT NOT NULL,
              k  TEXT NOT NULL,
              v  TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (ns, k)
            );
            """
        )


def record_run(loop: str, step_id: int, step_key: str, mode: str,
               status: str, payload: dict[str, Any] | None = None,
               error: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO step_runs(loop, step_id, step_key, mode, status, started_at, finished_at, payload, error)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (loop, step_id, step_key, mode, status, _now(), _now(),
             json.dumps(payload or {}, ensure_ascii=False), error),
        )
        return int(cur.lastrowid or 0)


def set_cursor(loop: str, step_id: int) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO loop_state(loop, cursor, updated_at) VALUES(?,?,?)
               ON CONFLICT(loop) DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at""",
            (loop, step_id, _now()),
        )


def get_cursor(loop: str) -> int:
    with _conn() as c:
        row = c.execute("SELECT cursor FROM loop_state WHERE loop=?", (loop,)).fetchone()
        return int(row["cursor"]) if row else 0


def kv_set(ns: str, k: str, v: Any) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO kv(ns,k,v,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(ns,k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at""",
            (ns, k, json.dumps(v, ensure_ascii=False), _now()),
        )


def kv_get(ns: str, k: str, default: Any = None) -> Any:
    with _conn() as c:
        row = c.execute("SELECT v FROM kv WHERE ns=? AND k=?", (ns, k)).fetchone()
        return json.loads(row["v"]) if row else default


def recent_runs(loop: str, limit: int = 20) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM step_runs WHERE loop=? ORDER BY id DESC LIMIT ?", (loop, limit)
        ).fetchall()
        return [dict(r) for r in rows]
