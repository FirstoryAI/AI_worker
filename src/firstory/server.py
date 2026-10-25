"""
FastAPI 서버 — Spring 백엔드가 내부 HTTP로 부르는 AI API (API 스펙 v0.3).
  FIRSTORY_INTERNAL_TOKEN=local-test-token FIRSTORY_MOCK=true uv run uvicorn firstory.server:app --port 8000

지금 있는 것: 인증(X-Internal-Token), 오류 형식, /health, /v1/safety/check(mock 모드만).
인터뷰·생성·결과·검토 API는 다음 단계에서 붙인다.
"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import mock
from .config import config
from .schemas import SafetyResult

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
