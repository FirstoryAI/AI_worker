"""
결과물 저장소 (API 스펙 G3·G4). 파일은 모두 key(저장소 루트 기준 상대 경로)로 읽고 쓴다.
  key = 실행의 output_prefix + 파일 이름   예) stories/123/runs/2/images/page-03.png
  - 서버: Spring이 실행마다 새 output_prefix를 준다 → 다시 만들어도 이전 실행 파일이 남는다
  - CLI·뷰어: output_prefix가 없으면 form_input이 "<시각>_<이름>/"로 만든다 (예전 out/ 폴더와 같은 자리)
지금은 로컬 폴더(FIRSTORY_OUTPUT_ROOT, 없으면 out/). S3로 바꿀 때는 이 파일만 바꾼다.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from .config import config


def _check(key: str) -> str:
    """Spring LocalFileStorage와 같은 기준: 절대 경로, .., 역슬래시, : 가 있으면 거부."""
    if not key or key.startswith("/") or "\\" in key or ":" in key or ".." in PurePosixPath(key).parts:
        raise ValueError(f"쓸 수 없는 key: {key!r}")
    return key


def join(prefix: str, *names: str) -> str:
    return "/".join([prefix.rstrip("/"), *names])


def local_path(key: str) -> Path:
    """key의 로컬 파일 위치. 예전 실행이 state에 남긴 절대 경로는 그대로 돌려준다."""
    if Path(key).is_absolute():
        return Path(key)
    return config.output_root / _check(key)


def write_bytes(key: str, data: bytes) -> str:
    p = local_path(_check(key))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return key


def write_text(key: str, text: str) -> str:
    return write_bytes(key, text.encode("utf-8"))


def read_bytes(key: str) -> bytes:
    return local_path(key).read_bytes()


def exists(key: str) -> bool:
    return local_path(key).exists()


def run_fields(prefix: str) -> dict:
    """실행의 결과물 자리를 state에 넣을 때. run_dir은 CLI·뷰어가 보여 주는 로컬 폴더."""
    prefix = _check(prefix.rstrip("/") + "/")
    path = local_path(prefix)
    path.mkdir(parents=True, exist_ok=True)
    return {"output_prefix": prefix, "run_dir": str(path)}
