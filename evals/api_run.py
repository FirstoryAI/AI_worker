"""
FastAPI 서버 배선 확인 — 인증, 오류 형식, /health, mock /safety/check, 인터뷰. (uv run python evals/api_run.py)
서버를 띄우지 않고 TestClient로 부른다. OpenAI 호출 없음.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

os.environ.update(FIRSTORY_MOCK="true", FIRSTORY_INTERNAL_TOKEN="test-token", LANGSMITH_TRACING="false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from firstory import llm, mock, server  # noqa: E402

H = {"X-Internal-Token": "test-token"}
server.config = dataclasses.replace(server.config, checkpoint_db=Path(tempfile.mkdtemp()) / "checkpoints.db")

# Spring이 보내는 모양: AiContextMapper가 만든 StoryInputContext (parent는 비어 있음)
CONTEXT = json.loads((Path(__file__).resolve().parents[1] / "datasets/inputs/donggeul.json").read_text(encoding="utf-8"))
for k in ("_note", "scripted_answers"):
    CONTEXT.pop(k, None)
CONTEXT["parent"] = {"response": None, "concern": None, "message": None, "message_direction": None}


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

# ── 인터뷰 (스펙 7-2, 7-3) ──
with TestClient(server.app, raise_server_exceptions=False) as c:
    def start(tid, **body):
        return c.post(f"/v1/threads/{tid}/interview/start", headers=H,
                      json={"run_id": str(uuid.uuid4()), "context": CONTEXT, "tone": None} | body)

    def answer(tid, body):
        return c.post(f"/v1/threads/{tid}/interview/answer", headers=H, json=body)

    def ok(res):
        assert res.status_code == 200, (res.status_code, res.text)
        return res.json()

    tid = str(uuid.uuid4())
    q1 = ok(start(tid, tone="warm"))
    assert q1 == {"type": "question", "turn": 1, "question": "당시에 어떻게 반응해주셨어요?", "context_update": None}, q1
    assert server._graph.get_state(server._cfg(tid)).values["tone"] == "warm"
    q2 = ok(answer(tid, {"answer": "안아 줬어요"}))
    assert q2["type"] == "question" and q2["turn"] == 2, q2
    assert q2["context_update"] == {"parent": {"response": "안아줌", "concern": "뭐라고 말할지 모르겠음"}}, q2
    done = ok(answer(tid, {"answer": "마음을 먼저 받아 주고 싶어요"}))
    assert set(done) == {"type", "summary", "end_reason", "context"} and done["type"] == "confirm", done
    assert done["end_reason"] == "sufficient" and done["summary"]
    assert done["context"]["parent"]["message_direction"] == "comfort_first"
    assert done["context"]["situation"] == CONTEXT["situation"] | {"custom_category": None}   # 빈 칸도 null로 채워 돌려준다
    assert server._graph.get_state(server._cfg(tid)).next == ("confirm_generate",)

    # 멈춤 지점과 맞지 않는 요청, 없는 thread
    err(answer(tid, {"answer": "또"}), 409, "INVALID_STATE")
    err(start(tid), 409, "INVALID_STATE")
    err(answer(str(uuid.uuid4()), {"answer": "a"}), 404, "THREAD_NOT_FOUND")

    # skip → 생성 전 확인 (end_reason user_skip)
    tid2 = str(uuid.uuid4())
    assert ok(start(tid2))["turn"] == 1
    skipped = ok(answer(tid2, {"skip": True}))
    assert skipped["type"] == "confirm" and skipped["end_reason"] == "user_skip", skipped
    assert skipped["context"]["parent"]["message_direction"] == "undecided"

    # 형식 오류
    bad = dict(CONTEXT)
    bad.pop("situation")
    err(start(str(uuid.uuid4()), context=bad), 422, "VALIDATION_ERROR")
    err(start(str(uuid.uuid4()), run_id="not-uuid"), 422, "VALIDATION_ERROR")
    for body in ({}, {"answer": "a", "skip": True}, {"answer": ""}, {"skip": False}):
        err(answer(tid2, body), 422, "VALIDATION_ERROR")

    # 같은 thread를 처리하는 중이면 THREAD_BUSY
    tid3 = str(uuid.uuid4())
    with server._thread_lock(tid3):
        err(start(tid3), 409, "THREAD_BUSY")
    assert ok(start(tid3))["turn"] == 1   # 끝나면 다시 받는다

    # LLM이 중간에 실패해도 Spring이 같은 요청을 다시 보내면 이어진다 (답변이 두 번 쌓이지 않는다)
    fail_once = {"interview": True}

    def flaky(**kw):
        if kw["node"] == "interview" and fail_once.pop("interview", False):
            raise RuntimeError("OpenAI 장애 흉내")
        return mock.fake_structured(**kw)

    llm.set_structured_override(flaky)
    err(answer(tid3, {"answer": "안아 줬어요"}), 500, "INTERNAL_ERROR")
    assert server._graph.get_state(server._cfg(tid3)).next == ("interview_step",)
    retried = ok(answer(tid3, {"answer": "안아 줬어요"}))
    assert retried["type"] == "question" and retried["turn"] == 2, retried
    assert len(server._graph.get_state(server._cfg(tid3)).values["interview_turns"]) == 1
    mock.enable()
print("interview ok")

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
