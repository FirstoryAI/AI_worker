"""
FastAPI 서버 배선 확인 — 인증, 오류 형식, /health, /safety/check, 인터뷰, 생성, 검토·재시도, 완성 본문 위기 신호. (uv run python evals/api_run.py)
서버를 띄우지 않고 TestClient로 부른다. OpenAI 호출 없음.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

os.environ.update(FIRSTORY_MOCK="true", FIRSTORY_INTERNAL_TOKEN="test-token", LANGSMITH_TRACING="false",
                  FIRSTORY_OUTPUT_ROOT=tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from firstory import llm, mock, server, storage  # noqa: E402
from firstory.config import config  # noqa: E402
from firstory.nodes import safety  # noqa: E402
from firstory.schemas import (  # noqa: E402
    InterviewTurnResult, ParentUpdate, SafetyJudgement, SafetyResult, StoryPage, StoryRevision,
)

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
    revise = c.post("/v1/safety/check", headers=H, json={"source": "form", "texts": ["[[REVISE]]"]}).json()["safety"]
    assert revise["category"] == "other" and revise["reason"], revise   # REVISE·CRISIS에는 category와 부모용 문장

    # 판단 프롬프트에 글의 종류와 직전 질문이 들어간다 (글은 user로)
    seen = {}

    def capture(**kw):
        seen.update(kw)
        return mock.fake_structured(**kw)

    llm.set_structured_override(capture)
    level("문 앞에서 울었어요", source="interview_answer", context={"question": "아이는 어땠나요?"})
    assert seen["node"] == "safety_check" and seen["user"] == "문 앞에서 울었어요"
    assert "인터뷰 질문에 한 답" in seen["system"] and "아이는 어땠나요?" in seen["system"]
    mock.enable()

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
    assert q1 == {"type": "question", "turn": 1, "question": "당시에 어떻게 반응해주셨어요?",
                  "choices": ["꼭 안아 줬어요", "괜찮다고 말해 줬어요", "뭐라고 할지 몰라 가만히 있었어요"],
                  "context_update": None}, q1
    assert server._graph.get_state(server._cfg(tid)).values["tone"] == "warm"
    q2 = ok(answer(tid, {"answer": "안아 줬어요"}))
    assert q2["type"] == "question" and q2["turn"] == 2, q2
    assert q2["context_update"] == {"parent": {"response": "안아줌", "concern": "뭐라고 말할지 모르겠음"}}, q2
    # 빈 카드·겹치는 카드를 빼고 4개까지
    assert q2["choices"] == ["마음을 먼저 다독이고 싶어요", "친구 입장도 생각해 보게 하고 싶어요", "잘 모르겠어요", "둘 다요"], q2
    done = ok(answer(tid, {"answer": "마음을 먼저 받아 주고 싶어요"}))
    assert set(done) == {"type", "summary", "end_reason", "context"} and done["type"] == "confirm", done
    assert done["end_reason"] == "sufficient"
    assert done["summary"] == "속상했던 마음을 먼저 알아주고 싶어요. 친구를 나쁘게 말하지는 않고 싶어요."   # 부모용 문장
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

    # AI가 질문 없이 ask만 주면 기본 질문을 묻고, 그 질문과 상관없는 카드는 버린다
    def no_question(**kw):
        if kw["schema"] is InterviewTurnResult:
            return InterviewTurnResult(context_update=ParentUpdate(), status="ask", choices=["엉뚱한 카드"], reason="질문 빠짐")
        return mock.fake_structured(**kw)

    llm.set_structured_override(no_question)
    fallback = ok(start(str(uuid.uuid4())))
    assert fallback["question"].startswith("아이에게 이번 일로") and fallback["choices"] == [], fallback
    mock.enable()
print("interview ok")

# ── 생성·상태·결과 (스펙 7-4 ~ 7-6) ──
RESULT_KEYS = {"run_no", "checkpoint_id", "title", "design", "character_sheets", "pages", "guide", "cost", "safety"}


def run_body(run_no=1, prefix=None, **extra):
    return {"run_id": str(uuid.uuid4()), "run_no": run_no,
            "output_prefix": prefix or f"stories/{uuid.uuid4().hex[:6]}/runs/{run_no}/", "tone": None} | extra


with TestClient(server.app, raise_server_exceptions=False) as c:
    def to_confirm():
        tid = str(uuid.uuid4())
        assert c.post(f"/v1/threads/{tid}/interview/start", headers=H,
                      json={"run_id": str(uuid.uuid4()), "context": CONTEXT, "tone": None}).status_code == 200
        for a in ("안아 줬어요", "마음을 먼저 받아 주고 싶어요"):
            r = c.post(f"/v1/threads/{tid}/interview/answer", headers=H, json={"answer": a})
        assert r.json()["type"] == "confirm", r.text
        return tid

    def status(tid):
        r = c.get(f"/v1/threads/{tid}/status", headers=H)
        assert r.status_code == 200, r.text
        return r.json()

    def wait(tid, until, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            st = status(tid)
            if st["state"] in until:
                return st
            time.sleep(0.05)
        raise AssertionError(f"{until}까지 안 감: {status(tid)}")

    # 끝까지: CONFIRMING → 202 → RUNNING → REVIEWING → result
    tid = to_confirm()
    assert status(tid)["state"] == "CONFIRMING"
    err(c.get(f"/v1/threads/{tid}/result", headers=H), 409, "INVALID_STATE")
    prefix = "stories/12/runs/1/"
    r = c.post(f"/v1/threads/{tid}/generate", headers=H, json=run_body(prefix=prefix, tone="warm"))
    assert r.status_code == 202 and r.json() == {"accepted": True}, r.text
    st = wait(tid, {"REVIEWING", "FAILED"})
    assert st["state"] == "REVIEWING" and st["run_no"] == 1 and st["error"] is None, st
    res = c.get(f"/v1/threads/{tid}/result", headers=H).json()
    assert set(res) == RESULT_KEYS, res.keys()
    assert res["run_no"] == 1 and res["checkpoint_id"] and res["title"] == "포포와 비어 있는 자리"
    assert [p["page_no"] for p in res["pages"]] == list(range(1, config.page_count + 1))
    assert all(p["image_status"] == "done" and p["image_path"] == f"{prefix}images/page-{p['page_no']:02d}.png"
               and storage.exists(p["image_path"]) for p in res["pages"]), res["pages"][0]
    assert {(s["role"], s["name"]) for s in res["character_sheets"]} == {("protagonist", "포포"), ("supporting", "엄마곰")}
    assert all(s["path"].startswith(f"{prefix}images/sheet-") and storage.exists(s["path"]) for s in res["character_sheets"])
    assert set(res["guide"]) == {"prompts", "before_reading", "after_reading"} and res["guide"]["prompts"][0]["after_page"] == 3
    assert res["cost"]["image_count"] == config.page_count + 2 and res["cost"]["input_tokens"] == 0, res["cost"]
    assert res["safety"] == {"level": "OK", "category": None, "reason": None}
    assert server._graph.get_state(server._cfg(tid)).values["tone"] == "warm"
    err(c.post(f"/v1/threads/{tid}/generate", headers=H, json=run_body()), 409, "INVALID_STATE")

    # 확인 화면에서 고친 입력과 '나누고 싶은 것'이 생성에 반영된다
    tid_e = to_confirm()
    edited = json.loads(json.dumps(CONTEXT))
    edited["situation"]["description"] = "놀이터에서 친구가 그네를 안 비켜 줬어요"
    edited["child"]["age_months"] = 70
    edited["moment"]["emotions"] = ["angry"]
    edited["parent"]["message"] = "기다리면 차례가 온다고 말해 주고 싶어요"
    new_summary = "차례를 기다리는 게 어렵다는 마음을 알아주고 싶어요."
    r = c.post(f"/v1/threads/{tid_e}/generate", headers=H, json=run_body(context=edited, summary=new_summary))
    assert r.status_code == 202, r.text
    assert wait(tid_e, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    v = server._graph.get_state(server._cfg(tid_e)).values
    assert v["context"].situation.description == edited["situation"]["description"]
    assert v["context"].child.age_months == 70 and v["context"].moment.emotions == ["angry"]
    assert v["context"].parent.message == edited["parent"]["message"]
    assert v["context"].parent.message_direction == "comfort_first"   # 인터뷰가 채운 칸은 그대로
    assert v["interview_parent_summary"] == new_summary and new_summary in v["interview_summary"]
    assert v["interview_summary"].startswith("이 부모는")   # 원래 정리는 남고 고친 문장을 덧붙인다

    # 상황을 안 고쳤으면 인터뷰가 가진 moment를 지키고, 요약을 안 고쳤으면 정리도 그대로
    tid_k = to_confirm()
    before = server._graph.get_state(server._cfg(tid_k)).values
    same = json.loads(json.dumps(CONTEXT))
    same["moment"]["emotions"] = ["excited"]   # Spring 폼 값이 인터뷰 결과와 달라도
    r = c.post(f"/v1/threads/{tid_k}/generate", headers=H,
               json=run_body(context=same, summary=before["interview_parent_summary"]))
    assert r.status_code == 202, r.text
    assert wait(tid_k, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    v = server._graph.get_state(server._cfg(tid_k)).values
    assert v["context"].moment == before["context"].moment and v["interview_summary"] == before["interview_summary"]

    # 형식 오류, 없는 thread
    tid2 = to_confirm()
    err(c.post(f"/v1/threads/{tid2}/generate", headers=H, json=run_body(prefix="../outside/")), 422, "VALIDATION_ERROR")
    err(c.post(f"/v1/threads/{tid2}/generate", headers=H, json=run_body(run_no=0)), 422, "VALIDATION_ERROR")
    err(c.post(f"/v1/threads/{uuid.uuid4()}/generate", headers=H, json=run_body()), 404, "THREAD_NOT_FOUND")
    err(c.get(f"/v1/threads/{uuid.uuid4()}/status", headers=H), 404, "THREAD_NOT_FOUND")
    assert status(tid2)["state"] == "CONFIRMING"   # 거절된 요청은 아무것도 바꾸지 않는다

    # 진행 중: 설계에서 붙잡아 두고 RUNNING·THREAD_BUSY 확인
    gate = threading.Event()

    def held(**kw):
        if kw["node"] == "design_story":
            gate.wait(10)
        return mock.fake_structured(**kw)

    llm.set_structured_override(held)
    assert c.post(f"/v1/threads/{tid2}/generate", headers=H, json=run_body()).status_code == 202
    st = status(tid2)
    assert st["state"] == "RUNNING" and st["current_node"] == "design_story" and st["stage"] == 1, st
    err(c.post(f"/v1/threads/{tid2}/generate", headers=H, json=run_body()), 409, "THREAD_BUSY")
    err(c.post(f"/v1/threads/{tid2}/interview/answer", headers=H, json={"answer": "a"}), 409, "THREAD_BUSY")
    err(c.get(f"/v1/threads/{tid2}/result", headers=H), 409, "INVALID_STATE")
    gate.set()
    assert wait(tid2, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    mock.enable()

    # 실패: 글 쓰기에서 예외 → FAILED, error에 code·node. 잠금은 풀린다
    tid3 = to_confirm()

    def broken(**kw):
        if kw["node"] == "write_story":
            raise RuntimeError("OpenAI 장애 흉내")
        return mock.fake_structured(**kw)

    llm.set_structured_override(broken)
    assert c.post(f"/v1/threads/{tid3}/generate", headers=H, json=run_body()).status_code == 202
    st = wait(tid3, {"FAILED", "REVIEWING"})
    assert st["state"] == "FAILED" and st["error"]["code"] == "GENERATION_FAILED", st
    assert st["error"]["node"] == "write_story" and st["stage"] == 2, st
    err(c.get(f"/v1/threads/{tid3}/result", headers=H), 409, "INVALID_STATE")
    err(c.post(f"/v1/threads/{tid3}/generate", headers=H, json=run_body()), 409, "INVALID_STATE")   # 잠금은 풀렸다
    mock.enable()

    # 서버가 꺼질 때 돌던 실행: 다시 띄우면 FAILED(SERVER_RESTARTED)
    tid4 = to_confirm()
    server._runs.start(tid4, 1, "illustrate", 0)
with TestClient(server.app, raise_server_exceptions=False) as c:
    st = c.get(f"/v1/threads/{tid4}/status", headers=H).json()
    assert st["state"] == "FAILED" and st["error"]["code"] == "SERVER_RESTARTED", st
    assert c.get(f"/v1/threads/{tid}/status", headers=H).json()["state"] == "REVIEWING"   # 끝난 실행은 그대로
print("generation ok")

# ── 검토·재시도 (스펙 7-7, 7-8, 8장 버전 갈래) ──
with TestClient(server.app, raise_server_exceptions=False) as c:
    def review(t, **body):
        return c.post(f"/v1/threads/{t}/review", headers=H, json=body)

    def result(t):
        r = c.get(f"/v1/threads/{t}/result", headers=H)
        assert r.status_code == 200, r.text
        return r.json()

    def regen(scope, run_no, base, **extra):
        return {"action": "regenerate", "scope": scope, "pages": [], "feedback": None, "base_checkpoint_id": base,
                "run_id": str(uuid.uuid4()), "run_no": run_no, "output_prefix": f"stories/12/runs/{run_no}/"} | extra

    def accepted(r):
        assert r.status_code == 202 and r.json() == {"accepted": True}, r.text

    def page_paths(res):
        return {p["page_no"]: p["image_path"] for p in res["pages"]}

    # v1(생성 테스트의 tid, runs/1)에서 그림만 다시 3쪽 → v2(runs/2): 3쪽만 새로, 나머지 쪽·시트는 v1 key
    v1 = result(tid)
    accepted(review(tid, **regen("images", 2, v1["checkpoint_id"], pages=[3])))
    assert wait(tid, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    v2 = result(tid)
    assert v2["run_no"] == 2 and v2["checkpoint_id"] != v1["checkpoint_id"]
    assert page_paths(v2)[3] == "stories/12/runs/2/images/page-03.png"
    assert all(path == f"stories/12/runs/1/images/page-{n:02d}.png" for n, path in page_paths(v2).items() if n != 3)
    assert v2["character_sheets"] == v1["character_sheets"] and v2["cost"]["image_count"] == 1, v2["cost"]

    # v1로 되돌려 글 다시 → v3(runs/3)는 v1에서 갈라진다. v2 체크포인트도 그대로 남는다
    # mock 작가는 1쪽만 고쳐 그 쪽 장면이 바뀐다 → 1쪽만 runs/3에 새로 그리고 나머지 쪽·시트는 v1 key
    accepted(review(tid, **regen("text", 3, v1["checkpoint_id"], feedback="더 짧게")))
    assert wait(tid, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    v3 = result(tid)
    assert v3["run_no"] == 3 and page_paths(v3)[1] == "stories/12/runs/3/images/page-01.png"
    assert all(path == page_paths(v1)[n] for n, path in page_paths(v3).items() if n != 1)
    assert v3["character_sheets"] == v1["character_sheets"] and v3["cost"]["image_count"] == 1, v3["cost"]
    assert server._graph.get_state(server._cfg(tid)).values["review_feedback"] == "더 짧게"
    kept = server._graph.get_state({"configurable": {"thread_id": tid, "checkpoint_id": v2["checkpoint_id"]}})
    assert {pi.order: pi.path for pi in kept.values["illustrations"].pages}[3] == "stories/12/runs/2/images/page-03.png"
    assert storage.exists("stories/12/runs/2/images/page-03.png") and storage.exists("stories/12/runs/1/images/page-03.png")

    # 이야기·인물 다시 (지금 버전에서) → v4
    accepted(review(tid, **regen("story", 4, None, feedback="토끼 말고 공룡으로")))
    assert wait(tid, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    assert result(tid)["run_no"] == 4

    # 형식 오류, 없는 thread, 없는 체크포인트
    err(review(tid, action="regenerate", scope="text"), 422, "VALIDATION_ERROR")
    err(review(tid, **regen("text", 5, None, pages=[2])), 422, "VALIDATION_ERROR")
    err(review(tid, **regen("pictures", 5, None)), 422, "VALIDATION_ERROR")
    err(review(tid, action="publish"), 422, "VALIDATION_ERROR")
    err(review(tid, **regen("images", 5, None, output_prefix="../outside/")), 422, "VALIDATION_ERROR")
    err(review(tid, **regen("images", 5, "no-such-checkpoint")), 409, "INVALID_STATE")
    err(review(str(uuid.uuid4()), action="approve"), 404, "THREAD_NOT_FOUND")
    assert status(tid)["state"] == "REVIEWING"   # 거절된 요청은 아무것도 바꾸지 않는다

    # 다시 만드는 중에는 같은 thread의 요청이 THREAD_BUSY
    gate = threading.Event()

    def held(**kw):
        if kw["node"] == "write_story":
            gate.wait(10)
        return mock.fake_structured(**kw)

    llm.set_structured_override(held)
    accepted(review(tid, **regen("text", 5, None)))
    st = status(tid)
    assert st["state"] == "RUNNING" and st["current_node"] == "write_story" and st["run_no"] == 5, st
    err(review(tid, action="approve"), 409, "THREAD_BUSY")
    gate.set()
    assert wait(tid, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    mock.enable()

    # 확정
    r = review(tid, action="approve")
    assert r.status_code == 200 and r.json() == {"state": "COMPLETED"}, r.text
    assert status(tid)["state"] == "COMPLETED"
    err(review(tid, action="approve"), 409, "INVALID_STATE")
    err(c.get(f"/v1/threads/{tid}/result", headers=H), 409, "INVALID_STATE")

    # 재시도: 글 쓰기에서 실패한 실행을 새 output_prefix로 다시
    tid5 = to_confirm()

    def broken_once(**kw):
        if kw["node"] == "write_story":
            raise RuntimeError("OpenAI 장애 흉내")
        return mock.fake_structured(**kw)

    llm.set_structured_override(broken_once)
    accepted(c.post(f"/v1/threads/{tid5}/generate", headers=H, json=run_body(prefix="stories/55/runs/1/")))
    assert wait(tid5, {"FAILED", "REVIEWING"})["state"] == "FAILED"
    mock.enable()
    err(c.post(f"/v1/threads/{tid}/retry", headers=H, json=run_body(run_no=9)), 409, "INVALID_STATE")   # 실패한 적 없음
    err(c.post(f"/v1/threads/{uuid.uuid4()}/retry", headers=H, json=run_body()), 404, "THREAD_NOT_FOUND")
    accepted(c.post(f"/v1/threads/{tid5}/retry", headers=H, json=run_body(run_no=2, prefix="stories/55/runs/2/")))
    st = wait(tid5, {"REVIEWING", "FAILED"})
    assert st["state"] == "REVIEWING" and st["run_no"] == 2 and st["error"] is None, st
    retried = result(tid5)
    assert retried["run_no"] == 2 and all(path.startswith("stories/55/runs/2/images/") for path in page_paths(retried).values())
    assert not storage.exists("stories/55/runs/1/images/page-01.png")   # 실패한 실행은 그림 전에 멈췄다
    err(c.post(f"/v1/threads/{tid5}/retry", headers=H, json=run_body(run_no=3)), 409, "INVALID_STATE")
print("review / retry ok")

# ── 글 다시 만들기: 작가는 메모 때문에 고친 쪽만 돌려주고, 나머지 쪽은 이전 원고 그대로. 다듬기는 메모를 받고 고친 쪽만 ──
polish_systems, writer_calls = [], []
revised_pages = {"value": [6], "same_scene": False}


def rewrite_page6(**kw):
    if kw["node"] == "write_story" and kw["schema"] is StoryRevision:
        writer_calls.append(kw["system"])
        same = revised_pages["same_scene"]   # True면 글만 고치고 장면(그림 지시·등장인물)은 mock 첫 원고와 같게
        return StoryRevision(reason="test", pages=[StoryPage(order=n, text=f"{n}쪽. 포포는 깜짝 놀랐어요.",
                                                             characters_in_scene=["포포"] + (["엄마곰"] if same and n % 2 == 0 else []),
                                                             image_prompt=f"scene {n}" if same else f"scene {n} revised")
                                                   for n in revised_pages["value"]])
    if kw["node"] == "polish_story":
        polish_systems.append(kw["system"])
    return mock.fake_structured(**kw)


with TestClient(server.app, raise_server_exceptions=False) as c:
    llm.set_structured_override(rewrite_page6)   # 시작할 때 mock.enable()이 덮어쓰므로 그 뒤에
    tid8 = to_confirm()
    accepted(c.post(f"/v1/threads/{tid8}/generate", headers=H, json=run_body()))
    assert wait(tid8, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    first = result(tid8)
    assert not writer_calls   # 첫 생성은 원고 전체 (StoryText)
    assert len(polish_systems) == 1 and "부모 요청" not in polish_systems[0]
    assert len(re.findall(r'"order": \d+', polish_systems[0])) == config.page_count   # 첫 생성은 전부 다듬는다
    accepted(review(tid8, **regen("text", 2, first["checkpoint_id"], feedback="6쪽은 놀랐다는 마음이 드러나게",
                                  output_prefix="stories/78/runs/2/")))
    assert wait(tid8, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    second = result(tid8)
    assert len(writer_calls) == 1 and "6쪽은 놀랐다는 마음이 드러나게" in writer_calls[0] and "## 기존 원고" in writer_calls[0]
    assert len(polish_systems) == 2 and "6쪽은 놀랐다는 마음이 드러나게" in polish_systems[1]
    assert re.findall(r'"order": (\d+)', polish_systems[1]) == ["6"], polish_systems[1][-300:]   # 다시 쓴 쪽만
    unchanged = [(p["text"], p["image_prompt"]) for p in first["pages"] if p["page_no"] != 6]
    assert [(p["text"], p["image_prompt"]) for p in second["pages"] if p["page_no"] != 6] == unchanged   # 글·그림 지시 그대로
    assert next(p for p in second["pages"] if p["page_no"] == 6)["image_prompt"] == "scene 6 revised"
    assert second["title"] == first["title"]
    # 장면이 바뀐 6쪽만 새로 그리고, 나머지 쪽과 캐릭터 시트는 v1 그림 그대로
    assert page_paths(second)[6] == "stories/78/runs/2/images/page-06.png"
    assert all(path == page_paths(first)[n] for n, path in page_paths(second).items() if n != 6)
    assert second["character_sheets"] == first["character_sheets"] and second["cost"]["image_count"] == 1, second["cost"]
    after = server._graph.get_state(server._cfg(tid8)).values
    assert after.get("revision_feedback") is None and after.get("revision_base") is None   # 다음 실행에 남지 않는다
    assert after.get("redraw_pages") is None

    # 글만 고치고 장면은 그대로면 그림을 하나도 다시 그리지 않는다
    revised_pages.update(value=[3], same_scene=True)
    accepted(review(tid8, **regen("text", 3, second["checkpoint_id"], feedback="3쪽 말투만", output_prefix="stories/78/runs/3/")))
    assert wait(tid8, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    third = result(tid8)
    draft3 = server._graph.get_state(server._cfg(tid8)).values["story_draft"]
    assert {pg.order: pg.text for pg in draft3.pages}[3] == "3쪽. 포포는 깜짝 놀랐어요."   # 작가는 3쪽 글을 고쳤다
    assert page_paths(third) == page_paths(second) and third["cost"]["image_count"] == 0, third["cost"]

    # 작가가 없는 쪽을 돌려주면 실패 (부모는 다시 시도할 수 있다). 앞선 버전은 그대로
    revised_pages.update(value=[99], same_scene=False)
    accepted(review(tid8, **regen("text", 4, third["checkpoint_id"], feedback="더 짧게", output_prefix="stories/78/runs/4/")))
    assert wait(tid8, {"REVIEWING", "FAILED"})["state"] == "FAILED"
    mock.enable()
print("text regen keeps other pages ok")

# ── 완성 본문 위기 신호 (스펙 4장): result의 safety. 그림만 다시는 글이 그대로라 지난 판단을 쓴다 ──
judged = []


def unsafe_output(**kw):
    if kw["node"] == "safety_output":
        judged.append(kw["user"])
        return SafetyJudgement(basis="test", level="REVISE", category=None, reason=" ")
    return mock.fake_structured(**kw)


with TestClient(server.app, raise_server_exceptions=False) as c:
    llm.set_structured_override(unsafe_output)   # 시작할 때 mock.enable()이 덮어쓰므로 그 뒤에
    tid7 = to_confirm()
    accepted(c.post(f"/v1/threads/{tid7}/generate", headers=H, json=run_body()))
    assert wait(tid7, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    out = result(tid7)
    assert out["safety"] == {"level": "REVISE", "category": "other", "reason": safety._FALLBACK_REASON["REVISE"]}, out["safety"]
    assert len(judged) == 1 and judged[0].startswith("제목: ") and "\n1쪽: " in judged[0], judged
    accepted(review(tid7, **regen("images", 2, out["checkpoint_id"], pages=[2])))
    assert wait(tid7, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    assert result(tid7)["safety"]["level"] == "REVISE" and len(judged) == 1   # 그림만 다시: 다시 판단하지 않음
    accepted(review(tid7, **regen("text", 3, result(tid7)["checkpoint_id"])))
    assert wait(tid7, {"REVIEWING", "FAILED"})["state"] == "REVIEWING"
    assert len(judged) == 2   # 글 다시: 새 본문을 다시 판단
    mock.enable()

# 정리 규칙: 완성 본문에는 SENSITIVE가 없고, category는 REVISE·CRISIS에만
j = SafetyJudgement(basis="t", level="SENSITIVE", category="other", reason="무거운 주제예요")
assert safety._tidy("output", j) == SafetyResult(level="OK")
assert safety._tidy("form", j) == SafetyResult(level="SENSITIVE", category=None, reason="무거운 주제예요")
assert safety._tidy("form", SafetyJudgement(basis="t", level="OK", category="other", reason="x")) == SafetyResult(level="OK")
print("output safety ok")

# ── mock이 아니면: /health는 mock false, /safety/check는 판단 노드로 (여기서는 LLM 대신 가짜 응답) ──
real = server.config
server.config = dataclasses.replace(real, mock=False)
with TestClient(server.app) as c:
    assert c.get("/health", headers=H).json() == {"status": "ok", "mock": False}
    r = c.post("/v1/safety/check", headers=H, json={"source": "form", "texts": ["a"]})
    assert r.status_code == 200 and r.json()["safety"]["level"] == "OK", r.text

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
