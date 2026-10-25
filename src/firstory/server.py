"""
FastAPI 서버 — Spring 백엔드가 내부 HTTP로 부르는 AI API (API 스펙 v0.3).
  FIRSTORY_INTERNAL_TOKEN=local-test-token FIRSTORY_MOCK=true uv run uvicorn firstory.server:app --port 8000 --http h11
  (--http h11: Java HttpClient의 Upgrade: h2c 요청에서 기본 파서가 본문을 버린다. README 참고)

지금 있는 것: 인증(X-Internal-Token), 오류 형식, /health, /v1/safety/check(mock 모드만),
인터뷰(interview/start, interview/answer). 생성·결과·검토 API는 다음 단계에서 붙인다.
"""
from __future__ import annotations

import logging
import secrets
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Literal, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langgraph.types import Command
from pydantic import BaseModel, Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import mock
from .config import config
from .graph import compile_graph
from .schemas import SafetyResult, StoryInputContext

log = logging.getLogger("firstory.server")


# ── 오류 형식: { "error": { "code", "message" } } (스펙 6장) ──────────────

class ApiError(Exception):
    """핸들러에서 raise 하면 스펙 형식의 오류 응답이 된다. code 예: THREAD_NOT_FOUND, THREAD_BUSY, INVALID_STATE"""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


_HTTP_CODES = {401: "UNAUTHORIZED", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def _register_errors(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return _error(e.status, e.code, e.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        detail = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
        return _error(422, "VALIDATION_ERROR", detail)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        return _error(e.status_code, _HTTP_CODES.get(e.status_code, "HTTP_ERROR"), str(e.detail))

    @app.exception_handler(Exception)
    async def internal_error(_: Request, e: Exception):
        log.exception("처리 못 한 오류")
        return _error(500, "INTERNAL_ERROR", "AI 서버 내부 오류")


# ── 인증: 모든 요청에 X-Internal-Token (스펙 2장) ─────────────────────────

def check_token(request: Request) -> None:
    sent = request.headers.get("X-Internal-Token", "")
    if not secrets.compare_digest(sent.encode(), config.internal_token.encode()):
        raise ApiError(401, "UNAUTHORIZED", "X-Internal-Token이 없거나 다릅니다")


# ── 앱 ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_: FastAPI):
    if not config.internal_token:
        raise RuntimeError("FIRSTORY_INTERNAL_TOKEN이 비어 있습니다. Spring과 같은 값을 넣어 주세요.")
    if config.mock:
        mock.enable()
        log.warning("mock 모드: OpenAI를 부르지 않습니다")
    global _graph
    _graph = compile_graph(config.checkpoint_db)
    yield


app = FastAPI(title="FIRSTORY AI", version="0.3", lifespan=lifespan, dependencies=[Depends(check_token)])
_register_errors(app)


@app.get("/health")
def health():
    return {"status": "ok", "mock": config.mock}


class SafetyCheckRequest(BaseModel):
    source: Literal["form", "interview_answer", "regen_feedback"]
    texts: list[str] = Field(min_length=1)
    context: Optional[dict] = None   # interview_answer일 때 {"question": 직전 질문}


@app.post("/v1/safety/check")
def safety_check(body: SafetyCheckRequest) -> dict[str, SafetyResult]:
    if not config.mock:
        raise ApiError(501, "NOT_IMPLEMENTED", "위기 신호 판단(G2)은 아직 없습니다. 지금은 FIRSTORY_MOCK=true에서만 동작합니다")
    return {"safety": mock.fake_safety(body.texts)}


# ── 그래프 실행: thread 하나에 동시에 하나만 (스펙 6장) ──────────────────────

_graph = None
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def _thread_lock(thread_id: str):
    with _locks_guard:
        lock = _locks.setdefault(thread_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise ApiError(409, "THREAD_BUSY", "이 thread는 다른 요청을 처리하고 있습니다")
    try:
        yield
    finally:
        lock.release()


def _cfg(thread_id: str, run_id: Optional[UUID] = None, run_name: Optional[str] = None) -> dict:
    """LangSmith에서 Spring의 run_id·thread_id로 찾을 수 있게 (스펙 10장)."""
    cfg: dict = {"configurable": {"thread_id": thread_id}, "metadata": {"thread_id": thread_id}}
    if run_id:
        cfg["run_id"] = run_id
    if run_name:
        cfg["run_name"] = run_name
    return cfg


# LLM 호출이 중간에 실패하면 그래프는 그 노드 앞에 멈춰 있다. Spring이 같은 요청을 다시 보내면 거기서 잇는다
_INTERVIEW_HALFWAY = {("interview_step",), ("interview_finish",)}


def _changed(before: BaseModel, after: BaseModel) -> dict:
    a, b = after.model_dump(mode="json"), before.model_dump(mode="json")
    return {k: v for k, v in a.items() if v is not None and v != b.get(k)}


def _interview_reply(before: StoryInputContext, result: dict) -> dict:
    """멈춘 자리를 스펙 7-3 응답으로. question이면 이번 턴에 AI가 채운 칸(context_update)도 함께."""
    if "__interrupt__" not in result:
        raise ApiError(500, "INTERNAL_ERROR", "인터뷰가 멈추지 않고 끝났습니다")
    pause = result["__interrupt__"][0].value
    if pause["type"] == "interview":
        after = result["context"]
        update = {name: diff for name, diff in (("parent", _changed(before.parent, after.parent)),
                                                ("moment", _changed(before.moment, after.moment))) if diff}
        return {"type": "question", "turn": pause["turn"], "question": pause["question"],
                "context_update": update or None}
    if pause["type"] == "confirm":
        return {"type": "confirm", "summary": pause["summary"], "end_reason": pause["end_reason"],
                "context": StoryInputContext.model_validate(pause["context"]).model_dump(mode="json")}
    raise ApiError(500, "INTERNAL_ERROR", f"인터뷰 중 예상하지 못한 멈춤: {pause['type']}")


class InterviewStartRequest(BaseModel):
    run_id: UUID
    context: StoryInputContext
    tone: Optional[Literal["plain", "warm", "undecided"]] = None


@app.post("/v1/threads/{thread_id}/interview/start")
def interview_start(thread_id: str, body: InterviewStartRequest) -> dict:
    with _thread_lock(thread_id):
        cfg = _cfg(thread_id, body.run_id, "firstory-interview")
        snap = _graph.get_state(cfg)
        if snap.values:
            if snap.next not in _INTERVIEW_HALFWAY:
                raise ApiError(409, "INVALID_STATE", "이미 인터뷰를 시작한 thread입니다")
            return _interview_reply(snap.values["context"], _graph.invoke(None, _cfg(thread_id)))
        result = _graph.invoke({
            "context": body.context, "tone": body.tone, "run_name": "api",
            "auto_answers": [], "auto_confirm": False, "auto_approve": False, "skip_images": False,
        }, cfg)
        return _interview_reply(body.context, result)


class InterviewAnswerRequest(BaseModel):
    answer: Optional[str] = Field(None, min_length=1)
    skip: bool = False

    @model_validator(mode="after")
    def _one(self):
        if self.skip == (self.answer is not None):
            raise ValueError("answer와 skip 중 하나만 보내 주세요")
        return self


@app.post("/v1/threads/{thread_id}/interview/answer")
def interview_answer(thread_id: str, body: InterviewAnswerRequest) -> dict:
    with _thread_lock(thread_id):
        cfg = _cfg(thread_id)
        snap = _graph.get_state(cfg)
        if not snap.values:
            raise ApiError(404, "THREAD_NOT_FOUND", "없는 thread입니다")
        before = snap.values["context"]
        if snap.next in _INTERVIEW_HALFWAY:   # 지난번 답변은 이미 받았다. 실패한 노드부터 잇는다
            return _interview_reply(before, _graph.invoke(None, cfg))
        if snap.next != ("interview_answer",):
            raise ApiError(409, "INVALID_STATE", "인터뷰 질문에서 멈춰 있지 않습니다")
        return _interview_reply(before, _graph.invoke(Command(resume="skip" if body.skip else body.answer), cfg))
