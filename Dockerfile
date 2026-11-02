# FIRSTORY AI 워커 이미지 (FastAPI). EC2 docker compose와 Railway에서 같이 쓴다.
#
#   docker build -t firstory-ai .
#   docker run -p 8000:8000 -e OPENAI_API_KEY=... -e FIRSTORY_INTERNAL_TOKEN=... -v firstory-ai:/data firstory-ai
#
# 환경 변수는 .env.example. 체크포인트(SQLite)는 /data/checkpoints.db라 /data에 볼륨을 붙인다.
# 볼륨이 없으면 다시 배포할 때 만들던 동화의 검토·다시 만들기가 끊긴다 (#38).
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# 의존성 층을 먼저 만들어 소스만 바뀌면 다시 받지 않게 한다. uv.lock 그대로 (--frozen)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src src
# 빌드하는 컴퓨터의 폴더 권한(예: 700)이 그대로 들어오면 아래 사용자가 못 읽는다
RUN chmod -R a+rX /app/src && uv sync --frozen --no-dev

# root가 아닌 사용자로 돈다. /data는 체크포인트, /app/out은 로컬 저장소일 때 결과물
RUN groupadd --system firstory && useradd --system --gid firstory firstory \
    && mkdir -p /data /app/out && chown -R firstory:firstory /data /app/out
USER firstory

ENV PATH="/app/.venv/bin:$PATH" \
    FIRSTORY_CHECKPOINT_DB=/data/checkpoints.db

EXPOSE 8000
# --http h11: 다른 클라이언트의 `Upgrade: h2c` 요청에서 기본 파서가 본문을 버린다.
# 워커 프로세스는 1개여야 한다 — thread 잠금과 실행 기록이 프로세스 메모리에 있다 (server.py)
CMD ["sh", "-c", "exec uvicorn firstory.server:app --host 0.0.0.0 --port ${PORT:-8000} --http h11 --workers 1"]
