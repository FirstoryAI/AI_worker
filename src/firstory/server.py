"""
FastAPI 서버 — Spring 백엔드가 내부 HTTP로 부르는 AI API (API 스펙 v0.3).
  FIRSTORY_INTERNAL_TOKEN=local-test-token FIRSTORY_MOCK=true uv run uvicorn firstory.server:app --port 8000 --http h11
  (--http h11: Java HttpClient의 Upgrade: h2c 요청에서 기본 파서가 본문을 버린다. README 참고)

지금 있는 것: 인증(X-Internal-Token), 오류 형식, /health, /v1/safety/check(mock 모드만),
인터뷰(interview/start, interview/answer), 생성(generate, status, result), 검토(review), 재시도(retry).
"""
from __future__ import annotations

import logging
import secrets
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Literal, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langgraph.types import Command
from pydantic import BaseModel, Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import mock
from .config import config
from . import storage
from .graph import compile_graph
from .nodes.story import review_update
from .runs import Runs
from .schemas import Illustrations, SafetyResult, StoryInputContext

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
    global _graph, _runs
    _graph = compile_graph(config.checkpoint_db)
    _runs = Runs(config.checkpoint_db)
    if n := _runs.interrupt_running():
        log.warning("서버가 꺼질 때 돌던 실행 %d개를 FAILED로 바꿨습니다", n)
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
_runs: Optional[Runs] = None
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _acquire(thread_id: str) -> threading.Lock:
    """thread 잠금을 잡는다. 생성은 백그라운드 실행이 끝날 때 풀므로 잠금을 그대로 넘겨받는다."""
    with _locks_guard:
        lock = _locks.setdefault(thread_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise ApiError(409, "THREAD_BUSY", "이 thread는 다른 요청을 처리하고 있습니다")
    return lock


@contextmanager
def _thread_lock(thread_id: str):
    lock = _acquire(thread_id)
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


# ── 생성 (스펙 7-4 ~ 7-6) ────────────────────────────────────────────────

_STAGE = {"design_story": 1, "write_story": 2, "polish_story": 2,      # Spring GenerationStage와 같은 묶음
          "reading_guide": 3, "illustrate": 3, "illustrate_only": 3, "render": 4}
_PAUSED = {("interview_answer",): "INTERVIEWING", ("interview_step",): "INTERVIEWING", ("interview_finish",): "INTERVIEWING",
           ("confirm_generate",): "CONFIRMING", ("parent_review",): "REVIEWING"}


def _start_run(thread_id: str, lock: threading.Lock, run_id: UUID, run_no: int, inp, first_node: str,
               cost_start: int, checkpoint_id: Optional[str] = None) -> None:
    """그래프를 백그라운드에서 돌린다. 끝나거나 실패하면 ai_runs에 적고 thread 잠금을 푼다.
    checkpoint_id를 주면 그 체크포인트에서 갈라져 나간다 (이전 버전에서 다시 만들기, 스펙 8장)."""
    _runs.start(thread_id, run_no, first_node, cost_start)
    cfg = _cfg(thread_id, run_id, f"firstory-run-{run_no}")
    cfg["metadata"]["run_no"] = run_no
    if checkpoint_id:
        cfg["configurable"]["checkpoint_id"] = checkpoint_id

    def work():
        node: Optional[str] = first_node
        try:
            for ev in _graph.stream(inp, cfg, stream_mode="tasks"):
                if "result" not in ev and ev["name"] in _STAGE:   # 노드가 시작될 때 (끝날 때는 result가 붙는다)
                    node = ev["name"]
                    _runs.node(thread_id, node)
            _runs.done(thread_id)
        except Exception as e:  # noqa: BLE001 — 실패는 status로 알린다
            log.exception("생성 실패: thread_id=%s run_no=%s node=%s", thread_id, run_no, node)
            _runs.fail(thread_id, "GENERATION_FAILED", node, str(e)[:300])
        finally:
            lock.release()

    threading.Thread(target=work, name=f"run-{thread_id}", daemon=True).start()


class RunRequest(BaseModel):
    run_id: UUID
    run_no: int = Field(ge=1)
    output_prefix: str = Field(min_length=1)   # stories/{storyId}/runs/{runNo}/
    tone: Optional[Literal["plain", "warm", "undecided"]] = None
    context: Optional[StoryInputContext] = None   # generate만: 확인 화면에서 고친 지금 입력 전체
    summary: Optional[str] = None                 # generate만: 부모가 본(고쳤을 수 있는) '나누고 싶은 것'


@app.post("/v1/threads/{thread_id}/generate", status_code=202)
def generate(thread_id: str, body: RunRequest) -> dict:
    lock = _acquire(thread_id)
    try:
        snap = _graph.get_state(_cfg(thread_id))
        if not snap.values:
            raise ApiError(404, "THREAD_NOT_FOUND", "없는 thread입니다")
        if tuple(snap.next) != ("confirm_generate",):
            raise ApiError(409, "INVALID_STATE", "생성 전 확인에서 멈춰 있지 않습니다")
        try:
            storage.run_fields(body.output_prefix)
        except ValueError as e:
            raise ApiError(422, "VALIDATION_ERROR", f"output_prefix: {e}") from e
        resume = {"action": "generate", "output_prefix": body.output_prefix,
                  **({"tone": body.tone} if body.tone else {}),
                  **({"context": body.context.model_dump(mode="json")} if body.context else {}),
                  **({"summary": body.summary} if body.summary else {})}
        _start_run(thread_id, lock, body.run_id, body.run_no, Command(resume=resume), "design_story",
                   len(snap.values.get("cost", [])))
    except BaseException:
        lock.release()
        raise
    return {"accepted": True}


@app.get("/v1/threads/{thread_id}/status")
def status(thread_id: str) -> dict:
    snap = _graph.get_state(_cfg(thread_id))
    run = _runs.get(thread_id)
    if not snap.values and run is None:
        raise ApiError(404, "THREAD_NOT_FOUND", "없는 thread입니다")
    out = {"state": None, "run_no": run["run_no"] if run else None, "current_node": None, "stage": None,
           "error": None, "updated_at": run["updated_at"] if run else None}
    if run and run["state"] in ("RUNNING", "FAILED"):
        node = run["current_node"]
        out.update(state=run["state"], current_node=node, stage=_STAGE.get(node), error=run["error"])
    elif tuple(snap.next) in _PAUSED:
        out["state"] = _PAUSED[tuple(snap.next)]
    elif not snap.next:
        out["state"] = "COMPLETED"
    else:   # 생성 노드 앞에 멈춰 있는데 실행 기록이 없다 = 어디선가 끊겼다
        out.update(state="FAILED", current_node=snap.next[0], stage=_STAGE.get(snap.next[0]),
                   error={"code": "INTERRUPTED", "node": snap.next[0], "message": "실행 기록 없이 중간에 멈춰 있습니다"})
    return out


@app.get("/v1/threads/{thread_id}/result")
def result(thread_id: str) -> dict:
    snap = _graph.get_state(_cfg(thread_id))
    if not snap.values:
        raise ApiError(404, "THREAD_NOT_FOUND", "없는 thread입니다")
    run = _runs.get(thread_id)
    if (run and run["state"] == "RUNNING") or tuple(snap.next) != ("parent_review",):
        raise ApiError(409, "INVALID_STATE", "부모 검토에서 멈춰 있지 않습니다")
    v = snap.values
    story, ill = v["story"], v.get("illustrations") or Illustrations()
    roles = {c.name: c.role for c in story.characters}
    images = {pi.order: pi for pi in ill.pages if pi.status == "completed" and pi.path}
    costs = v.get("cost", [])[run["cost_start"] if run else 0:]   # 이번 실행 것만
    return {
        "run_no": run["run_no"] if run else None,
        "checkpoint_id": snap.config["configurable"]["checkpoint_id"],   # 이 버전에서 다시 만들 때 쓴다 (스펙 8장)
        "title": story.title,
        "design": v["story_design"].model_dump(mode="json") if v.get("story_design") else None,
        "character_sheets": [{"role": roles.get(name, "supporting"), "name": name, "path": key}
                             for name, key in ill.character_sheets.items()],
        "pages": [{"page_no": p.order, "text": p.text, "image_prompt": p.image_prompt,
                   "image_path": images[p.order].path if p.order in images else None,
                   "image_status": "done" if p.order in images else "failed"} for p in story.pages],
        "guide": v["guide"].model_dump(mode="json") if v.get("guide") else None,
        "cost": {"input_tokens": sum(c.input_tokens for c in costs), "output_tokens": sum(c.output_tokens for c in costs),
                 "image_count": sum(c.images for c in costs)},
        # TODO(G2): 완성 본문 위기 신호 판단. 만들기 전까지는 OK
        "safety": {"level": "OK", "category": None, "reason": None},
    }


# ── 검토·재시도 (스펙 7-7, 7-8) ───────────────────────────────────────────

_REGEN_FIRST_NODE = {"story": "design_story", "text": "write_story", "images": "illustrate_only"}


def _at(thread_id: str, snap) -> dict:
    """update_state에 넘길 그 체크포인트의 config (checkpoint_ns가 꼭 있어야 한다)."""
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": "",
                             "checkpoint_id": snap.config["configurable"]["checkpoint_id"]}}


class ReviewRequest(BaseModel):
    action: Literal["approve", "regenerate"]
    scope: Optional[Literal["story", "text", "images"]] = None
    pages: list[int] = []                       # images일 때 다시 그릴 쪽. 비면 전부
    feedback: Optional[str] = None              # 부모 메모 (Spring이 위기 신호를 먼저 검사한다)
    base_checkpoint_id: Optional[str] = None    # 이 버전에서 다시 만든다. 없으면 지금 상태에서
    run_id: Optional[UUID] = None
    run_no: Optional[int] = Field(None, ge=1)
    output_prefix: Optional[str] = None

    @model_validator(mode="after")
    def _regenerate_fields(self):
        if self.action == "regenerate" and not (self.scope and self.run_id and self.run_no and self.output_prefix):
            raise ValueError("regenerate에는 scope, run_id, run_no, output_prefix가 필요합니다")
        if self.pages and self.scope != "images":
            raise ValueError("pages는 scope가 images일 때만 보낼 수 있습니다")
        return self


def _check_prefix(prefix: str) -> None:
    try:
        storage.run_fields(prefix)
    except ValueError as e:
        raise ApiError(422, "VALIDATION_ERROR", f"output_prefix: {e}") from e


@app.post("/v1/threads/{thread_id}/review")
def review(thread_id: str, body: ReviewRequest, response: Response) -> dict:
    lock = _acquire(thread_id)
    handed_off = False   # 백그라운드 실행에 잠금을 넘겼으면 여기서 풀지 않는다
    try:
        if not _graph.get_state(_cfg(thread_id)).values:
            raise ApiError(404, "THREAD_NOT_FOUND", "없는 thread입니다")
        cfg = _cfg(thread_id)
        if body.base_checkpoint_id:
            cfg["configurable"]["checkpoint_id"] = body.base_checkpoint_id
        snap = _graph.get_state(cfg)
        if tuple(snap.next) != ("parent_review",):
            raise ApiError(409, "INVALID_STATE", "부모 검토에서 멈춰 있지 않습니다 (없는 checkpoint_id일 수도 있습니다)")
        # 멈춘 interrupt를 Command(resume)로 풀지 않고, parent_review가 이 값을 돌려준 것으로 새 체크포인트를 만든다.
        # 한 번 재개한 체크포인트를 다시 재개하면 LangGraph가 처음 재개 값을 다시 써서 (이전 버전에서 다시 만들기가
        # 그 전 다시 만들기를 되풀이한다), 이렇게 해야 이전 버전에서 새 갈래가 나온다
        if body.action == "approve":
            _graph.invoke(None, _graph.update_state(_at(thread_id, snap), review_update({"action": "approve"}),
                                                    as_node="parent_review"))
            return {"state": "COMPLETED"}
        _check_prefix(body.output_prefix)
        # 그림만 다시는 쪽 번호를 "3,5"로 (illustrate_only가 feedback에서 쪽 번호를 읽는다)
        feedback = ",".join(map(str, body.pages)) if body.scope == "images" else body.feedback
        branch = _graph.update_state(_at(thread_id, snap), review_update({
            "action": "regenerate", "scope": body.scope, "feedback": feedback, "output_prefix": body.output_prefix,
        }), as_node="parent_review")
        _start_run(thread_id, lock, body.run_id, body.run_no, None, _REGEN_FIRST_NODE[body.scope],
                   len(snap.values.get("cost", [])), branch["configurable"]["checkpoint_id"])
        handed_off = True
        response.status_code = 202
        return {"accepted": True}
    finally:
        if not handed_off:
            lock.release()


@app.post("/v1/threads/{thread_id}/retry", status_code=202)
def retry(thread_id: str, body: RunRequest) -> dict:
    """FAILED에서 마지막 체크포인트부터 다시. 이번 실행의 결과물은 새 output_prefix 아래에."""
    lock = _acquire(thread_id)
    handed_off = False
    try:
        cfg = _cfg(thread_id)
        snap = _graph.get_state(cfg)
        if not snap.values:
            raise ApiError(404, "THREAD_NOT_FOUND", "없는 thread입니다")
        if status(thread_id)["state"] != "FAILED":
            raise ApiError(409, "INVALID_STATE", "실패한 실행이 없습니다")
        _check_prefix(body.output_prefix)
        _graph.update_state(cfg, storage.run_fields(body.output_prefix))   # 멈춘 자리(next)는 그대로
        _start_run(thread_id, lock, body.run_id, body.run_no, None, snap.next[0], len(snap.values.get("cost", [])))
        handed_off = True
        return {"accepted": True}
    finally:
        if not handed_off:
            lock.release()
