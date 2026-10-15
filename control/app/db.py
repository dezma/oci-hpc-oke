from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any
import uuid

DB_PATH = Path(os.environ.get("HPC_CONTROL_DB", "/var/lib/oke-rdma-control/control.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              action TEXT NOT NULL,
              state TEXT NOT NULL,
              requested_at REAL NOT NULL,
              started_at REAL,
              finished_at REAL,
              lease_until REAL,
              confirmation TEXT NOT NULL DEFAULT '',
              result_json TEXT,
              error TEXT
            );
            CREATE INDEX IF NOT EXISTS jobs_state_idx ON jobs(state, requested_at);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT,
              at REAL NOT NULL,
              level TEXT NOT NULL,
              message TEXT NOT NULL,
              FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            """
        )


def enqueue(action: str, confirmation: str) -> dict[str, Any]:
    init_db()
    job_id = str(uuid.uuid4())
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO jobs(id,action,state,requested_at,confirmation) VALUES(?,?,?,?,?)",
            (job_id, action, "QUEUED", now, confirmation),
        )
        conn.execute(
            "INSERT INTO events(job_id,at,level,message) VALUES(?,?,?,?)",
            (job_id, now, "info", f"Queued action {action}"),
        )
    return get_job(job_id)


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    if data.get("result_json"):
        try:
            data["result"] = json.loads(data.pop("result_json"))
        except json.JSONDecodeError:
            data["result"] = {"raw": data.pop("result_json")}
    else:
        data.pop("result_json", None)
        data["result"] = None
    return data


def get_job(job_id: str) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        job = _row_to_job(row)
        events = conn.execute(
            "SELECT at,level,message FROM events WHERE job_id=? ORDER BY id", (job_id,)
        ).fetchall()
        job["events"] = [dict(x) for x in events]
        return job


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY requested_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_job(r) for r in rows]


def claim_next(lease_seconds: int = 300) -> dict[str, Any] | None:
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # Recover a worker lease that expired after a process/VM restart.
        conn.execute(
            "UPDATE jobs SET state='QUEUED', lease_until=NULL, error=NULL WHERE state='RUNNING' AND lease_until IS NOT NULL AND lease_until < ?",
            (now,),
        )
        row = conn.execute(
            "SELECT * FROM jobs WHERE state='QUEUED' ORDER BY requested_at LIMIT 1"
        ).fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        lease_until = now + lease_seconds
        conn.execute(
            "UPDATE jobs SET state='RUNNING', started_at=COALESCE(started_at,?), lease_until=? WHERE id=?",
            (now, lease_until, row["id"]),
        )
        conn.execute(
            "INSERT INTO events(job_id,at,level,message) VALUES(?,?,?,?)",
            (row["id"], now, "info", "Worker claimed job"),
        )
        conn.execute("COMMIT")
    return get_job(row["id"])


def heartbeat(job_id: str, lease_seconds: int = 300) -> None:
    with _connect() as conn:
        conn.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() + lease_seconds, job_id))


def event(job_id: str, message: str, level: str = "info") -> None:
    # Avoid unbounded logs and accidental terminal/control sequences in the UI.
    safe = "".join(ch for ch in message if ch == "\n" or ch == "\t" or ord(ch) >= 32)[:4000]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO events(job_id,at,level,message) VALUES(?,?,?,?)",
            (job_id, time.time(), level, safe),
        )


def complete(job_id: str, result: dict[str, Any]) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET state='SUCCEEDED', finished_at=?, lease_until=NULL, result_json=?, error=NULL WHERE id=?",
            (now, json.dumps(result), job_id),
        )
        conn.execute(
            "INSERT INTO events(job_id,at,level,message) VALUES(?,?,?,?)",
            (job_id, now, "info", "Job completed"),
        )


def fail(job_id: str, error: str) -> None:
    now = time.time()
    safe = str(error)[:4000]
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET state='FAILED', finished_at=?, lease_until=NULL, error=? WHERE id=?",
            (now, safe, job_id),
        )
        conn.execute(
            "INSERT INTO events(job_id,at,level,message) VALUES(?,?,?,?)",
            (job_id, now, "error", safe),
        )
