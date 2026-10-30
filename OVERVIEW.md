# FIRSTORY AI 파이프라인 — 백엔드 공유용 소개

> 레포: https://github.com/k1mg0eun/FIRSTORY_AI
> 2026-10-08 기준. 자세한 설계는 `ARCHITECTURE.md`, 실행법은 `README.md`.

## 한 줄로

부모가 아이 상황을 입력하면 → AI가 인터뷰로 고민을 구체화하고 → 간접화한 맞춤 동화(텍스트+그림)와 부모용 독서 가이드를 만들어서 → 부모가 검토·확정하는 흐름을 **로컬에서 끝까지 돌려볼 수 있는 프로토타입**.

서버·DB 없음. 터미널이나 Streamlit 뷰어로 돌리고, 결과는 `out/` 폴더에 쌓인다. 목적은 "동화가 얼마나 잘 나오는지"를 반복해서 보고 올리는 것.

## 스택

- **Python + LangGraph** — 플로우를 그래프로 선언. 인터뷰 루프, 사람 입력 대기(interrupt), 병렬 실행, 상태 저장·재개가 기본 제공
- **LangSmith** — 모든 LLM 호출이 자동 기록됨. "이 동화 왜 이렇게 나왔지?"를 노드별로 추적
- **OpenAI** — 텍스트 `gpt-5.5` / `gpt-5.4-mini`, 이미지 `gpt-image-2`
- **SQLite** — 그래프 상태 체크포인트 (`FIRSTORY_CHECKPOINT_DB`, 기본 `out/checkpoints.db`). 나중에 Postgres로 교체
- **Streamlit** — 입력↔출력 확인용 뷰어. 버리는 물건, 진짜 프론트 아님

## 흐름

```
form_input ─▶ interview(루프) ─▶ ⏸ 확인 ─▶ design_story ─▶ write_story ─▶ polish_story ─┬─▶ reading_guide ─┐
                                                                                       └─▶ illustrate    ─┴─▶ render ─▶ ⏸ parent_review
                                                                                                                             │
                                                 완료 → END  /  다시 만들기: 인물·이야기 → design_story, 글 → write_story, 그림만 → illustrate_only
```

| 노드 | 하는 일 | 모델 |
|---|---|---|
| `form_input` | 1차 폼 JSON 검증. 백엔드 사전조사 ①의 `StoryInputContext` 그대로 (pydantic) | – |
| `interview` | 비어 있는 필드(`concern`, `message_direction`)만 묻는다. 매 턴 **추출+질문 동시**, `missingFields`는 코드가 계산, 종료는 AI+코드 이중 확인. "모르겠다"→정리 질문 2회→`undecided`. 최대 5턴, skip 가능. 끝에 `summary` 한 문단 | mini |
| `confirm_generate` | 생성 전 확인. 인터뷰 요약·최종 Context를 보여주고 멈춤, 부모가 [만들기]를 누르면 생성 시작 (`auto_confirm`이면 안 멈춤) | – |
| `design_story` | 간접화 설계: 주인공(아이 관심사에서)·조연·세계·상황 재구성, 원인 1개(`problem_cause`), 주인공이 낸 해결 방법(`solution`), 부모가 바란 장면(`must_show`), 10쪽 줄거리 | 5.5 |
| `write_story` | 10페이지 텍스트 + 캐릭터 시트(주인공·조연 외형) + 페이지별 이미지 프롬프트. **교훈 선언 금지, 사건은 닫고 의미는 엶, 사람·가족 호칭 금지, 질문은 안 씀** | 5.5 |
| `polish_story` | 문장만 다듬기. 작가(이야기·구성)와 역할을 나눠 번역투·한 문장에 두 가지·꾸밈말을 아이 말로 고친다. 원문은 `03-draft.json` | 5.5 |
| `reading_guide` | Role B 독서 코치. 동화 속 질문 2~3개(`after_page`로 위치), 읽기 전 팁, 현실로 잇는 질문. 텍스트만 보므로 이미지와 **병렬** | 5.5 |
| `illustrate` | 캐릭터 시트 1장씩 생성 → 각 페이지는 그 장면에 나오는 캐릭터 시트만 참조 이미지로 넣어 병렬 생성 (동시 3장). 한 편에 12~13장 | image-2 |
| `illustrate_only` | 검토에서 "그림만 다시"를 골랐을 때만. 글은 두고 그림만 다시 | image-2 |
| `render` | 단계별 JSON + `book.html` | – |
| `parent_review` | 멈추고 사람 입력 대기. 완료 / 다시 쓰기(+피드백) / 캐릭터 바꾸기 / 그림만 다시. "다시 쓰기"는 가이드·그림도 다시 실행 | – |

인터뷰는 실제로 `interview_step`(LLM) → `interview_answer`(interrupt) → … 세 노드로 쪼개져 있음. interrupt는 재개할 때 노드를 처음부터 다시 실행하므로 LLM 호출과 같은 노드에 두면 답변마다 LLM이 다시 돈다.

## 지금까지 확인된 것

- 별·동글·물음 3개 입력 end-to-end 성공 (10/7). 10쪽 동화 + 그림 + 독서 가이드
- **캐릭터 일관성**: 인물마다 기준 그림(시트) → 10쪽 전부 같은 캐릭터로 나옴
- **부모가 바란 장면**: 부모가 "소리 질러서 미안"이라고 하면 곁의 어른이 큰 소리를 내고 사과하는 장면이 들어감 (`must_show`)
- **소요 시간**: 한 편 약 3분 반 (글 단계 약 1분 30초~1분 45초, 그림 단계 약 1분 40초~1분 50초). 인터뷰 자동 답변, 3편 동시 실행 기준
- **비용**: 한 편 약 $0.45~0.6 (1,400원 환율 기준 약 600~850원). **텍스트가 절반**(약 $0.26~0.30, 대부분 `design_story`·`write_story`의 gpt-5.5 출력), 그림 12~13장 약 $0.17~0.31 (화질 low). `99-cost.json` 토큰 × OpenAI 공식 단가, 캐시 할인 미반영
- **위기 신호(G2)**: 부모 글과 완성 본문을 OK·SENSITIVE·REVISE·CRISIS로 판단 (`nodes/safety.py`). 평가 사례 31개 모두 맞음 (10/26, `evals/safety_eval.py`)
- **아직 안 한 것**: 생성 후 검수 노드, 독서 가이드 성향 맞춤, 독서 후 회고 저장, 캐릭터 시트 재사용

## 코드 어디에 뭐가

```
src/firstory/
  graph.py          노드·엣지. 플로우 바꿀 땐 여기
  state.py          그래프를 흐르는 상태 (TypedDict)
  schemas.py        pydantic. 입력 Context, 인터뷰 결과, 동화, 가이드. description이 모델에게 그대로 간다
  llm.py            structured() 하나로 모든 텍스트 호출. 벤더 바꿀 땐 여기만
  nodes/            노드별 함수
  prompts/*.md      역할별 프롬프트. {{변수}}는 코드가 채움. PM도 고칠 수 있게 분리
  prompts/strategies/, arcs/   켜고 끄는 프롬프트 전략 블록 (schemas.Strategy)
  lab.py            프롬프트 실험: 같은 인터뷰로 전략별 텍스트 생성 + 채점 → out/lab/
  cli.py            터미널 실행
viewer/app.py       Streamlit (맨 위 '프롬프트 실험' 화면은 viewer/lab_view.py)
evals/prompt_lab.py 프롬프트 실험 CLI
datasets/inputs/    테스트 입력 5개 (scripted_answers = 자동 인터뷰 답변)
datasets/samples/   사람이 쓴 기준 동화 (PM 샘플 + 기준선 lumi·popo)
evals/mock_run.py   API 없이 배선 확인
out/<시각>_<샘플>/  00-context … 05-illustrations.json, images/, book.html, 99-cost.json
```

## 돌려보기

```bash
git clone https://github.com/k1mg0eun/FIRSTORY_AI.git && cd FIRSTORY_AI
uv sync                            # uv 없으면 curl -LsSf https://astral.sh/uv/install.sh | sh
cp .env.example .env               # OPENAI_API_KEY, LANGSMITH_API_KEY
uv run python evals/mock_run.py    # 키 없이 배선 확인
uv run streamlit run viewer/app.py # 뷰어
```

## 같이 정할 것

- `design_story`를 별도 노드로 둘지 `write_story`에 접을지 — 지금은 분리 유지 (글만 다시 쓸 때 설계를 재사용하고, 어디서 망가졌는지 보기 쉬움)
- `polish_story`를 뺄지 mini로 내릴지 — 바꾸는 게 단어 몇 개 수준이고 한 편에 약 $0.03
- 쪽 수를 이야기마다 10~15쪽으로 바꿀지 (그림 비용·시간 늘어남)
- 사람 등장인물로 비교해 볼지 (지금은 동물만, 가족 호칭 금지)
- 평가: AI 채점 점수와 실제로 읽은 품질이 어긋난 사례가 있음 → 사람이 직접 읽고 비교하는 게 먼저
