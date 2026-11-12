"""SQLite persistence for conversations and opt-outs.

SQLite is deliberate: one small VPS per region handles a few dozen clients, and
the file is easy to back up and inspect during a client support call.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id     TEXT NOT NULL,
    caller        TEXT NOT NULL,
    source        TEXT NOT NULL,          -- missed_call | after_hours_call | web_form
    status        TEXT NOT NULL,          -- qualifying | complete | stale | opted_out
    answers       TEXT NOT NULL DEFAULT '{}',
    transcript    TEXT NOT NULL DEFAULT '[]',
    caller_name   TEXT,
    emergency     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    first_text_at TEXT,
    first_reply_at TEXT,
    updated_at    TEXT NOT NULL,
    lead_sent_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_conv_active ON conversations (client_id, caller, status);

CREATE TABLE IF NOT EXISTS opt_outs (
    client_id  TEXT NOT NULL,
    phone      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (client_id, phone)
);
"""


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


@dataclass
class Conversation:
    id: int
    client_id: str
    caller: str
    source: str
    status: str
    answers: dict = field(default_factory=dict)
    transcript: list = field(default_factory=list)
    caller_name: str | None = None
    emergency: bool = False
    created_at: str = ""
    first_text_at: str | None = None
    first_reply_at: str | None = None
    updated_at: str = ""
    lead_sent_at: str | None = None

    @property
    def caller_turns(self) -> int:
        return sum(1 for m in self.transcript if m["role"] == "caller")


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    # conversations -----------------------------------------------------

    def _row(self, row: sqlite3.Row | None) -> Conversation | None:
        if row is None:
            return None
        d = dict(row)
        d["answers"] = json.loads(d["answers"])
        d["transcript"] = json.loads(d["transcript"])
        d["emergency"] = bool(d["emergency"])
        return Conversation(**d)

    def create(self, client_id: str, caller: str, source: str) -> Conversation:
        now = utcnow().isoformat()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO conversations (client_id, caller, source, status, created_at, updated_at)"
                " VALUES (?, ?, ?, 'qualifying', ?, ?)",
                (client_id, caller, source, now, now),
            )
            self._db.commit()
        return self.get(cur.lastrowid)

    def get(self, conv_id: int) -> Conversation | None:
        row = self._db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        return self._row(row)

    def active_for(self, client_id: str, caller: str) -> Conversation | None:
        row = self._db.execute(
            "SELECT * FROM conversations WHERE client_id = ? AND caller = ? AND status = 'qualifying'"
            " ORDER BY id DESC LIMIT 1",
            (client_id, caller),
        ).fetchone()
        return self._row(row)

    def recent_for(self, client_id: str, caller: str, minutes: int) -> Conversation | None:
        cutoff = (utcnow() - timedelta(minutes=minutes)).isoformat()
        row = self._db.execute(
            "SELECT * FROM conversations WHERE client_id = ? AND caller = ? AND created_at >= ?"
            " ORDER BY id DESC LIMIT 1",
            (client_id, caller, cutoff),
        ).fetchone()
        return self._row(row)

    def count_since(self, client_id: str, minutes: int) -> int:
        cutoff = (utcnow() - timedelta(minutes=minutes)).isoformat()
        row = self._db.execute(
            "SELECT COUNT(*) FROM conversations WHERE client_id = ? AND created_at >= ?", (client_id, cutoff)
        ).fetchone()
        return row[0]

    def save(self, conv: Conversation) -> None:
        conv.updated_at = utcnow().isoformat()
        with self._lock:
            self._db.execute(
                "UPDATE conversations SET status=?, answers=?, transcript=?, caller_name=?, emergency=?,"
                " first_text_at=?, first_reply_at=?, updated_at=?, lead_sent_at=? WHERE id=?",
                (
                    conv.status,
                    json.dumps(conv.answers),
                    json.dumps(conv.transcript),
                    conv.caller_name,
                    int(conv.emergency),
                    conv.first_text_at,
                    conv.first_reply_at,
                    conv.updated_at,
                    conv.lead_sent_at,
                    conv.id,
                ),
            )
            self._db.commit()

    def stale(self, minutes: int) -> list[Conversation]:
        cutoff = (utcnow() - timedelta(minutes=minutes)).isoformat()
        rows = self._db.execute(
            "SELECT * FROM conversations WHERE status = 'qualifying' AND updated_at < ?", (cutoff,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def all_for(self, client_id: str) -> list[Conversation]:
        rows = self._db.execute(
            "SELECT * FROM conversations WHERE client_id = ? ORDER BY id", (client_id,)
        ).fetchall()
        return [self._row(r) for r in rows]

    # opt-outs ----------------------------------------------------------

    def opt_out(self, client_id: str, phone: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO opt_outs (client_id, phone, created_at) VALUES (?, ?, ?)",
                (client_id, phone, utcnow().isoformat()),
            )
            self._db.execute(
                "UPDATE conversations SET status='opted_out' WHERE client_id=? AND caller=? AND status='qualifying'",
                (client_id, phone),
            )
            self._db.commit()

    def opt_in(self, client_id: str, phone: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM opt_outs WHERE client_id=? AND phone=?", (client_id, phone))
            self._db.commit()

    def is_opted_out(self, client_id: str, phone: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM opt_outs WHERE client_id=? AND phone=?", (client_id, phone)
        ).fetchone()
        return row is not None
