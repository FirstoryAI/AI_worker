"""
S3 저장소 배선 확인 — FIRSTORY_STORAGE=s3일 때 storage.py가 버킷에 key 그대로 쓰고 읽는지. (uv run python evals/s3_storage_check.py)
botocore Stubber로 S3 응답을 흉내 낸다. AWS 호출 없음, 접근 키 필요 없음.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.update(FIRSTORY_STORAGE="s3", FIRSTORY_S3_BUCKET="test-bucket", FIRSTORY_S3_REGION="ap-northeast-2",
                  AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test", LANGSMITH_TRACING="false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from botocore.response import StreamingBody  # noqa: E402
from botocore.stub import Stubber  # noqa: E402

from firstory import storage  # noqa: E402

KEY = "stories/7/runs/1/images/page-01.png"
client = storage._s3()

with Stubber(client) as stub:
    stub.add_response("put_object", {}, {"Bucket": "test-bucket", "Key": KEY, "Body": b"png", "ContentType": "image/png"})
    stub.add_response("put_object", {}, {"Bucket": "test-bucket", "Key": "stories/7/runs/1/03-story.json",
                                         "Body": "{}".encode(), "ContentType": "application/json"})
    stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(b"png"), 3)}, {"Bucket": "test-bucket", "Key": KEY})
    stub.add_response("head_object", {}, {"Bucket": "test-bucket", "Key": KEY})
    stub.add_client_error("head_object", "404", http_status_code=404, expected_params={"Bucket": "test-bucket", "Key": KEY})
    stub.add_client_error("head_object", "403", http_status_code=403, expected_params={"Bucket": "test-bucket", "Key": KEY})

    assert storage.write_bytes(KEY, b"png") == KEY
    storage.write_text("stories/7/runs/1/03-story.json", "{}")
    assert storage.read_bytes(KEY) == b"png"
    assert storage.exists(KEY) is True
    assert storage.exists(KEY) is False          # 404 → 없음
    try:
        storage.exists(KEY)                      # 404가 아닌 오류(권한 등)는 그대로 올린다
        raise AssertionError("403이 삼켜졌습니다")
    except Exception as e:
        assert "403" in str(e), e
    stub.assert_no_pending_responses()

# 안전하지 않은 key는 S3를 부르기 전에 거부한다 (Spring StorageKeys와 같은 기준)
for bad in ["../etc/passwd", "/etc/passwd", "C:/x.png", "stories\\1\\a.png", "stories/1/../../x.png", ""]:
    with Stubber(client):                        # 응답을 넣지 않았으니 S3를 부르면 Stubber가 오류를 낸다
        for fn in (lambda: storage.write_bytes(bad, b"x"), lambda: storage.read_bytes(bad), lambda: storage.exists(bad)):
            try:
                fn()
                raise AssertionError(f"거부하지 않았습니다: {bad!r}")
            except ValueError:
                pass

print("s3_storage_check OK")
