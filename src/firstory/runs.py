"""
생성 실행 상태 (API 스펙 7-5). 생성은 백그라운드에서 돌아서, 지금 어느 노드인지와 실패를 따로 적어 둔다.
서버를 다시 띄워도 남도록 체크포인트 DB 안의 작은 테이블(ai_runs)에. thread마다 마지막 실행 하나만 둔다.
  RUNNING  백그라운드 실행 중        DONE  끝남 (멈춘 자리는 그래프 state로 본다)
  FAILED   예외 또는 서버 재시작으로 끊김
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Runs:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS ai_runs (
                thread_id TEXT PRIMARY KEY, run_no INTEGER, state TEXT NOT NULL, current_node TEXT,
                error TEXT, cost_start INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)""")

    def _write(self, sql: str, *args) -> None:
        with self._lock, self._conn:
            self._conn.execute(sql, args)

    def start(self, thread_id: str, run_no: int, node: str, cost_start: int) -> None:
        self._write("""INSERT INTO ai_runs (thread_id, run_no, state, current_node, error, cost_start, updated_at)
                       VALUES (?, ?, 'RUNNING', ?, NULL, ?, ?)
                       ON CONFLICT(thread_id) DO UPDATE SET run_no = excluded.run_no, state = 'RUNNING',
                         current_node = excluded.current_node, error = NULL, cost_start = excluded.cost_start,
                         updated_at = excluded.updated_at""", thread_id, run_no, node, cost_start, _now())

    def node(self, thread_id: str, node: Optional[str]) -> None:
        self._write("UPDATE ai_runs SET current_node = ?, updated_at = ? WHERE thread_id = ?", node, _now(), thread_id)

    def done(self, thread_id: str) -> None:
        self._write("UPDATE ai_runs SET state = 'DONE', current_node = NULL, updated_at = ? WHERE thread_id = ?",
                    _now(), thread_id)

    def fail(self, thread_id: str, code: str, node: Optional[str], message: str) -> None:
        error = json.dumps({"code": code, "node": node, "message": message}, ensure_ascii=False)
        self._write("UPDATE ai_runs SET state = 'FAILED', error = ?, updated_at = ? WHERE thread_id = ?",
                    error, _now(), thread_id)

    def get(self, thread_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM ai_runs WHERE thread_id = ?", (thread_id,)).fetchone()
        if row is None:
            return None
        run = dict(row)
        run["error"] = json.loads(run["error"]) if run["error"] else None
        return run

    def interrupt_running(self) -> int:
        """서버가 꺼질 때 돌던 실행은 이어 갈 수 없으므로 FAILED로. 서버 시작할 때 부른다."""
        error = json.dumps({"code": "SERVER_RESTARTED", "node": None, "message": "AI 서버가 다시 시작돼 실행이 끊겼습니다"},
                           ensure_ascii=False)
        with self._lock, self._conn:
            return self._conn.execute("UPDATE ai_runs SET state = 'FAILED', error = ?, updated_at = ? WHERE state = 'RUNNING'",
                                      (error, _now())).rowcount
