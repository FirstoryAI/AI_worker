"""
FastAPI 서버 배선 확인 — 인증, 오류 형식, /health, mock /safety/check. (uv run python evals/api_run.py)
서버를 띄우지 않고 TestClient로 부른다. OpenAI 호출 없음.
"""
from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

os.environ.update(FIRSTORY_MOCK="true", FIRSTORY_INTERNAL_TOKEN="test-token", LANGSMITH_TRACING="false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from firstory import server  # noqa: E402

H = {"X-Internal-Token": "test-token"}


def err(res, status, code):
    assert res.status_code == status, (res.status_code, res.text)
    body = res.json()
    assert set(body) == {"error"} and body["error"]["code"] == code and body["error"]["message"], body


@server.app.get("/_boom")   # 처리 못 한 예외가 INTERNAL_ERROR 형식으로 나가는지 보려는 테스트용 경로
def _boom():
    raise ValueError("boom")


with TestClient(server.app, raise_server_exceptions=False) as c:
    # ── 인증 ──
    err(c.get("/health"), 401, "UNAUTHORIZED")
    err(c.get("/health", headers={"X-Internal-Token": "wrong"}), 401, "UNAUTHORIZED")
    err(c.post("/v1/safety/check", json={"source": "form", "texts": ["a"]}), 401, "UNAUTHORIZED")

    # ── /health ──
    r = c.get("/health", headers=H)
    assert r.status_code == 200 and r.json() == {"status": "ok", "mock": True}, r.text

    # ── mock /safety/check: 표시가 있으면 그 level, 여러 개면 더 심각한 쪽 ──
    def level(*texts, **extra):
        r = c.post("/v1/safety/check", headers=H, json={"source": "form", "texts": list(texts), **extra})
        assert r.status_code == 200, r.text
        s = r.json()["safety"]
        assert set(s) == {"level", "category", "reason"}, s
        return s["level"]

    assert level("어린이집에서 친구가 밀쳐서 넘어졌어요.") == "OK"
    assert level("할머니가 돌아가셨어요 [[SENSITIVE]]") == "SENSITIVE"
    assert level("[[REVISE]] 혼내 주고 싶어요") == "REVISE"
    assert level("괜찮아요", "[[CRISIS]]") == "CRISIS"
    assert level("[[REVISE]] [[CRISIS]] [[SENSITIVE]]") == "CRISIS"
    assert level("그때 울었대요", source="interview_answer", context={"question": "아이는 어땠나요?"}) == "OK"

    # ── 오류 형식 ──
    err(c.post("/v1/safety/check", headers=H, json={"source": "form"}), 422, "VALIDATION_ERROR")
    err(c.post("/v1/safety/check", headers=H, json={"source": "chat", "texts": ["a"]}), 422, "VALIDATION_ERROR")
    err(c.post("/v1/safety/check", headers=H, json={"source": "form", "texts": []}), 422, "VALIDATION_ERROR")
    err(c.get("/v1/없는-경로", headers=H), 404, "NOT_FOUND")
    err(c.get("/v1/safety/check", headers=H), 405, "METHOD_NOT_ALLOWED")
    err(c.get("/_boom", headers=H), 500, "INTERNAL_ERROR")
print("auth / health / safety mock / errors ok")

# ── mock이 아니면: /health는 mock false, /safety/check는 아직 501 ──
real = server.config
server.config = dataclasses.replace(real, mock=False)
with TestClient(server.app) as c:
    assert c.get("/health", headers=H).json() == {"status": "ok", "mock": False}
    err(c.post("/v1/safety/check", headers=H, json={"source": "form", "texts": ["a"]}), 501, "NOT_IMPLEMENTED")

# ── 토큰 설정이 비어 있으면 시작하지 않는다 ──
server.config = dataclasses.replace(real, internal_token="")
try:
    with TestClient(server.app):
        raise AssertionError("토큰 없이 시작됨")
except RuntimeError as e:
    assert "FIRSTORY_INTERNAL_TOKEN" in str(e)
server.config = real
print("real mode / startup ok")

print("\nALL OK")
