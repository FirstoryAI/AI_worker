"""
결과물 저장소 (API 스펙 G3·G4). 파일은 모두 key(저장소 루트 기준 상대 경로)로 읽고 쓴다.
  key = 실행의 output_prefix + 파일 이름   예) stories/123/runs/2/images/page-03.png
  - 서버: Spring이 실행마다 새 output_prefix를 준다 → 다시 만들어도 이전 실행 파일이 남는다
  - CLI·뷰어: output_prefix가 없으면 form_input이 "<시각>_<이름>/"로 만든다 (예전 out/ 폴더와 같은 자리)
FIRSTORY_STORAGE로 고른다 (Spring STORAGE_TYPE과 같게 맞춘다).
  - local(기본): 로컬 폴더 FIRSTORY_OUTPUT_ROOT (없으면 out/). Spring과 같은 컴퓨터에서 같은 폴더를 볼 때
  - s3: FIRSTORY_S3_BUCKET 버킷에 key 그대로. Spring이 같은 버킷에서 읽는다 (서버가 서로 다른 컴퓨터일 때)
local_path는 로컬 폴더 기준이라 CLI·뷰어용이다. 서버 흐름은 write_*·read_bytes·exists만 쓴다.
"""
from __future__ import annotations

import functools
import mimetypes
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


@functools.cache
def _s3():
    if not config.s3_bucket:
        raise RuntimeError("FIRSTORY_STORAGE=s3면 FIRSTORY_S3_BUCKET이 필요합니다")
    import boto3   # local에서는 부르지 않는다
    return boto3.client("s3", region_name=config.s3_region)


def _use_s3() -> bool:
    return config.storage == "s3"


def write_bytes(key: str, data: bytes) -> str:
    _check(key)
    if _use_s3():
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        _s3().put_object(Bucket=config.s3_bucket, Key=key, Body=data, ContentType=content_type)
        return key
    p = local_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return key


def write_text(key: str, text: str) -> str:
    return write_bytes(key, text.encode("utf-8"))


def read_bytes(key: str) -> bytes:
    if _use_s3():
        return _s3().get_object(Bucket=config.s3_bucket, Key=_check(key))["Body"].read()
    return local_path(key).read_bytes()


def exists(key: str) -> bool:
    if _use_s3():
        from botocore.exceptions import ClientError
        try:
            _s3().head_object(Bucket=config.s3_bucket, Key=_check(key))
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
    return local_path(key).exists()


def run_fields(prefix: str) -> dict:
    """실행의 결과물 자리를 state에 넣을 때. run_dir은 CLI·뷰어가 보여 주는 로컬 폴더."""
    prefix = _check(prefix.rstrip("/") + "/")
    return {"output_prefix": prefix, "run_dir": str(local_path(prefix))}   # 폴더는 처음 쓸 때 생긴다
