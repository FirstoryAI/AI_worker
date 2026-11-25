"""ElevenLabs Text to Dialogue 호출. 표준 라이브러리 urllib만 쓴다 (새 의존성 없음)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

from .config import config

_URL = "https://api.elevenlabs.io/v1/text-to-dialogue?output_format=mp3_44100_128"
_TIMEOUT = 120   # 초

_override: Optional[Callable[[list[dict]], bytes]] = None


def set_tts_override(fn: Optional[Callable[[list[dict]], bytes]]) -> None:
    """테스트 훅. 있으면 dialogue가 HTTP 대신 fn(inputs)를 부른다."""
    global _override
    _override = fn


class TtsError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status   # HTTP 상태 코드. 네트워크·시간 초과면 None


def enabled() -> bool:
    return _override is not None or bool(config.elevenlabs_api_key)


def _post(body: dict) -> bytes:
    req = urllib.request.Request(
        _URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"xi-api-key": config.elevenlabs_api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise TtsError((detail or str(e))[:300], status=e.code) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TtsError(str(e)[:300], status=None) from e


def dialogue(inputs: list[dict], *, page: int) -> bytes:
    """inputs: [{"text": str, "voice_id": str}]. 한 쪽 분량의 mp3 바이트를 돌려준다."""
    if _override is not None:
        return _override(inputs)
    body = {"inputs": inputs, "model_id": config.tts_model, "language_code": "ko"}
    try:
        return _post(body)
    except TtsError as e:
        if e.status != 400:
            raise
        body.pop("language_code")   # 모델이 language_code를 받지 않으면 빼고 한 번 더
        return _post(body)
