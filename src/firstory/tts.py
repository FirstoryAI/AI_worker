"""ElevenLabs Text to Dialogue 호출. 표준 라이브러리 urllib만 쓴다 (새 의존성 없음)."""
from __future__ import annotations

import http.client
import json
import re
import threading
import urllib.error
import urllib.request
from typing import Callable, Optional

from .config import config

_URL = "https://api.elevenlabs.io/v1/text-to-dialogue?output_format=mp3_44100_128"
# 프로세스 전체에서 동시에 ElevenLabs에 걸린 요청 수 상한 (동화 여러 편이 같이 돌아도). override 경로는 잡지 않는다
_SEM = threading.BoundedSemaphore(max(1, config.tts_concurrency))
_CODE = re.compile(r"[A-Za-z0-9_.-]{1,60}")

_override: Optional[Callable[[list[dict]], bytes]] = None


def set_tts_override(fn: Optional[Callable[[list[dict]], bytes]]) -> None:
    """테스트 훅. 있으면 dialogue가 HTTP 대신 fn(inputs)를 부른다."""
    global _override
    _override = fn


class TtsError(Exception):
    """메시지는 짧은 코드만 (quota_exceeded, empty audio 등). 응답 본문은 동화 글을 되풀이할 수 있어 담지 않는다."""
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status   # HTTP 상태 코드. 네트워크·시간 초과·빈 응답이면 None


def enabled() -> bool:
    return _override is not None or bool(config.elevenlabs_api_key)


def error_code(raw: bytes) -> str:
    """오류 응답 본문에서 detail.status 또는 detail.code만 꺼낸다. 못 꺼내면 'http_error'."""
    try:
        detail = json.loads(raw).get("detail")
        if isinstance(detail, dict):
            code = detail.get("status") or detail.get("code")
            if isinstance(code, str) and _CODE.fullmatch(code):
                return code
    except Exception:
        pass
    return "http_error"


def _post(body: dict) -> bytes:
    req = urllib.request.Request(
        _URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"xi-api-key": config.elevenlabs_api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.tts_timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        raise TtsError(error_code(raw), status=e.code) from e
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:   # 읽다가 끊긴 것(IncompleteRead)도
        raise TtsError(str(e)[:100] or type(e).__name__, status=None) from e
    if not data:
        raise TtsError("empty audio", status=None)
    return data


def dialogue(inputs: list[dict], *, page: int) -> bytes:
    """inputs: [{"text": str, "voice_id": str}]. 한 쪽 분량의 mp3 바이트를 돌려준다."""
    if _override is not None:
        return _override(inputs)
    body = {"inputs": inputs, "model_id": config.tts_model, "language_code": "ko"}
    with _SEM:
        try:
            return _post(body)
        except TtsError as e:
            if e.status != 400:
                raise
            body.pop("language_code")   # 모델이 language_code를 받지 않으면 빼고 한 번 더
            return _post(body)
