# FIRSTORY AI 파이프라인 프로토타입

Python + LangGraph + LangSmith. 구조는 `ARCHITECTURE.md`.

## 설치

```bash
uv sync                            # uv 없으면: pip install uv  (또는 brew install uv)
cp .env.example .env               # OPENAI_API_KEY, LANGSMITH_API_KEY 넣기
uv run python -m firstory.models   # 계정에서 쓸 수 있는 모델 이름 확인 → .env 반영
```

## 실행

```bash
# 뷰어 (이걸로 보는 게 제일 편함)
uv run streamlit run viewer/app.py

# CLI
uv run firstory datasets/inputs/donggeul.json --auto          # 스크립트 답변 + 자동 완료
uv run firstory datasets/inputs/donggeul.json                 # 인터뷰·검토 직접
uv run firstory datasets/inputs/donggeul.json --skip-images   # 텍스트만 (저렴)
uv run firstory datasets/inputs/donggeul.json --strategy arc,engine   # 프롬프트 전략 켜기
uv run firstory --resume <thread_id>                          # 멈춘 곳부터

# 프롬프트 실험 — 같은 인터뷰로 전략만 바꿔 동화(텍스트)를 뽑고 채점해 나란히 (뷰어 맨 위 '프롬프트 실험'과 같은 일)
uv run python evals/prompt_lab.py out/<기준 실행 폴더>
uv run python evals/prompt_lab.py datasets/inputs/byeol.json --presets base engine motif   # 기준 실행부터 만든다

# API 없이 배선만 확인 (mock)
uv run python evals/mock_run.py

# FastAPI 서버 — Spring 백엔드가 부르는 내부 API. 모든 요청에 X-Internal-Token 헤더
FIRSTORY_INTERNAL_TOKEN=local-test-token FIRSTORY_MOCK=true uv run uvicorn firstory.server:app --port 8000 --http h11
uv run python evals/api_run.py                                # 서버 배선 확인 (인증, 오류 형식, mock)
uv run python evals/safety_eval.py                            # 위기 신호 판단 품질 (진짜 OpenAI, 사례 31개)
uv run python evals/s3_storage_check.py                       # S3 저장소 배선 확인 (AWS 호출 없음)
```

결과물은 `FIRSTORY_OUTPUT_ROOT`(없으면 `out/`) 아래 실행의 `output_prefix`(Spring이 실행마다 주는 `stories/{id}/runs/{n}/`)에 쓴다. 그림만 다시 그리면 안 바뀐 쪽과 캐릭터 시트는 이전 실행의 파일을 그대로 가리킨다 (`src/firstory/storage.py`). 글 다시 만들기도 장면(그림 지시·등장인물)이 바뀐 쪽만 새로 그리고 나머지는 같은 방식이다 (`redraw_pages`). CLI·뷰어는 `output_prefix`가 없어 예전처럼 `out/<타임스탬프>_<이름>/`이다.

Spring과 서버가 다른 컴퓨터면(Railway, EC2 등) 폴더를 같이 쓸 수 없어 S3에 둔다. `FIRSTORY_STORAGE=s3`, `FIRSTORY_S3_BUCKET`(Spring `STORAGE_S3_BUCKET`과 같은 버킷), `FIRSTORY_S3_REGION`(기본 `ap-northeast-2`). 접근 키는 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`(EC2는 IAM 역할). key가 그대로 객체 key라 Spring이 같은 key로 읽는다. 버킷을 공개하지 않는다. S3 모드에서도 체크포인트(`out/checkpoints.db`)는 로컬이다. CLI·뷰어는 로컬(`local`, 기본)로 쓴다.

`--http h11`: Spring(Java HttpClient)이 `Upgrade: h2c` 헤더를 붙여 보내는데, uvicorn 기본 파서(httptools)는 이때 본문을 버려 422가 난다. h11 파서는 헤더를 무시하고 본문을 받는다.

위기 신호(G2)는 `src/firstory/nodes/safety.py` 하나가 판단한다. `/v1/safety/check`(폼, 인터뷰 답변, 다시 만들기 메모)와 완성 본문(`safety_output` 노드, `/result`의 `safety`)이 같은 프롬프트(`prompts/safety_check.md`)를 쓴다. 판단만 하고, 횟수를 세고 막는 건 Spring이 한다.

`FIRSTORY_MOCK=true`면 OpenAI를 부르지 않고 가짜 응답으로 돈다 (`src/firstory/mock.py`). 위기 신호는 글에 `[[SENSITIVE]]`·`[[REVISE]]`·`[[CRISIS]]`가 있으면 그 level, 없으면 `OK`.

실행마다 `out/<타임스탬프>/`에 `00-context.json … 05-illustrations.json`, `images/`, `book.html`, `99-cost.json`이 남고,
그래프 상태는 `out/checkpoints.db`(SQLite)에 저장됨. LangSmith 켜져 있으면 smith.langchain.com 프로젝트 `firstory-pipeline`에 트레이스가 올라감.

## 흐름

```
form_input → interview(루프) → ⏸ confirm_generate → design_story → write_story → polish_story → [reading_guide ∥ safety_output ∥ illustrate] → render → ⏸ parent_review
                                                                                                                               │
                                                            approve → END   /   regenerate(scope) → design_story | write_story | illustrate_only
```

- 자동으로 도는 건 쓰기 1회. 재생성·그림 재시도는 뷰어/CLI 버튼으로 사람이.
- 검수(verify) 없음 — 사람 평가에서 기준 나오면 추가.

## 만질 곳

| 뭘 바꾸고 싶은가 | 어디 |
|---|---|
| AI가 하는 말·방식 | `src/firstory/prompts/*.md` — `{{변수}}`는 코드가 채움 |
| 프롬프트 전략 (실험용으로 켜고 끄는 블록) | `prompts/strategies/*.md`, 상황별 흐름 `prompts/arcs/<카테고리>.md`, 채점 `prompts/story_judge.md` — 실험 결과는 `out/lab/` |
| 입력 필드·enum, 출력 구조 | `src/firstory/schemas.py` (백엔드 사전조사 확정안) — `description`도 모델에게 전달됨 |
| 테스트 상황 | `datasets/inputs/*.json` — `scripted_answers`는 `--auto` 때 인터뷰 답변 |
| 페이지 수, 인터뷰 턴, 질문 수 | `src/firstory/config.py` |
| 모델 ID, 이미지 품질 | `.env` |

## 비용 감각

`99-cost.json` / 뷰어 "비용" 탭. 텍스트는 수십 원, 이미지 9장이 거의 전부. `IMAGE_QUALITY=low`로 내리면 크게 줄어듦.
