# FIRSTORY AI 파이프라인 — 구조 설계

> Python + LangGraph + LangSmith
> 작성: 2026-10-02 · 상태: 초안 (어진·고은 회의 후 확정)
> 근거 문서: 기획안(9/23), 260929 회의록, 개발 사전조사, **백엔드 개발 사전 조사 내용(확정)**, 백엔드 1차 과제, 샘플 동화 3안
>
> 표기: 🔒 = 백엔드 사전조사에서 확정된 것 · 💡 = 이 문서의 제안 (회의에서 정할 것)

---

## 0. 이 문서가 답하려는 것

- 파이프라인이 **어떤 노드로, 어떤 순서로, 어떤 상태를 들고** 도는가
- 어디서 **사람(부모)이 개입**하고, 어디서 **멈췄다 재개**하는가
- 동화 품질을 **어떻게 측정하고 올릴** 것인가 — 이게 장기적으로 제일 중요
- 지금 결정할 것과 나중에 결정해도 되는 것

빨리 만드는 게 목표가 아니다. 동화와 가이드가 얼마나 잘 나오는지가 목표고, 그걸 **반복해서 재서 올릴 수 있는 구조**를 만드는 게 이 프로토타입의 일이다.

---

## 1. 왜 LangGraph인가

FIRSTORY 플로우는 직선이 아니다.

| 플로우 요소 | 기획 근거 | LangGraph 대응 |
|---|---|---|
| 인터뷰: 충분하면 넘어가고, 아니면 더 묻기 | 사전조사 2-3 "필요한 질문만 동적으로" | 조건부 엣지 + 루프 |
| 이미지 생성과 독서 가이드를 동시에 | 🔒 백엔드 사전조사 ④-1 | 병렬 브랜치 (fan-out / fan-in) |
| 부모 검토: 수정 / 재생성 / 완료 | 기획안 10 | `interrupt()` — human-in-the-loop |
| 생성 시점과 독서 시점 분리 | 기획안 14, 회의록 6 | checkpointer — 상태 저장 후 나중에 재개 |
| 같은 Context, 역할 프롬프트만 바꿔 호출 | 🔒 백엔드 사전조사 ③-1 | 노드 = 역할, Context는 state로 공유 |

이걸 if/while로 손으로 짜도 되지만, 그래프로 선언하면 **(a)** 플로우 변경이 노드 추가/엣지 수정으로 끝나고 **(b)** 상태 저장·재개가 공짜고 **(c)** LangSmith로 노드별 입출력이 전부 남는다. (c)가 품질 작업의 핵심이다.

**Python인 이유**: LangGraph는 Python이 본진이라 기능·평가 도구·예제가 앞선다. 메인 API 서버(Node 또는 Spring)와는 별도 서비스로 두면 언어가 달라도 안 꼬인다. → §9 참고.

---

## 2. 그래프

```
 form_input ──▶ interview_step ──ask──▶ interview_answer ──▶ interview_step … (max 5턴, skip 가능)
                      │ done
                      ▼
               interview_finish  (summary 한 문단)
                      │
                      ▼
             ⏸ confirm_generate  ← 생성 전 확인 (CRT-06). 요약·최종 Context 보여주고 [만들기]
                      │
                      ▼
          💡 design_story   ◀──────────────────────── regenerate: character / story
                      │
                      ▼
               write_story   ◀──────────────────────── regenerate: text (+피드백)
             (전체 텍스트 + characterSheet + imagePrompt)
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
  reading_guide (B)           illustrate              illustrate_only ◀── regenerate: images
  텍스트만, 질문 2~3개     sheet 1장 → 페이지 N장 병렬         │
         │                         │                        │
         └────────────┬────────────┘                        │
                      ▼                                     │
                   render  ◀────────────────────────────────┘
                      │
                      ▼
             ⏸ parent_review   ← 텍스트+이미지+가이드 완성 후 (기획안 STEP 5~6)
                      │
          approve ────┴──── regenerate(scope) → 위 화살표
             │
            END
```

인터뷰를 세 노드로 쪼갠 이유: `interrupt()`는 재개할 때 그 노드를 처음부터 다시 실행한다. LLM 호출과 interrupt를 한 노드에 두면 답변 받을 때마다 LLM이 다시 돈다. 그래서 LLM은 `interview_step`, 멈춤은 `interview_answer`.

### 노드 요약

| 노드 | 역할 | 모델 등급 | 입력 → 출력 | 근거 |
|---|---|---|---|---|
| `form_input` | – | – | 1차 폼 JSON 검증 → `StoryInputContext` (parent 비어 있음) | 🔒 ① |
| `interview` | **Role A · 인터뷰어** | light | Context + 대화 이력 + `missingFields` + `remaining` → `InterviewTurnResult` | 🔒 ② |
| `confirm_generate` | – | – | `interrupt()`. 인터뷰 요약·최종 Context를 보여주고 부모가 확인하면 생성 시작. 재개 값 `{action: "generate", tone}`. `auto_confirm`이면 안 멈춤 | 화면 CRT-06 |
| `design_story` | 💡 작가(설계) | main | Context + summary → 간접화 설정 (주인공·세계·상황 재구성, 질문 씨앗) | 기획안 9 |
| `write_story` | **동화 생성기** | main | Context + summary (+설계, +피드백) → 전체 텍스트 + `characterSheet` + 페이지별 `imagePrompt` | 🔒 ④-1 |
| `parent_review` | – | – | `interrupt()`. 텍스트+이미지+가이드 **완성 후** 부모가 확인. 완료 / 재생성(scope) | 기획안 10, STEP 5 |
| `reading_guide` | **Role B · 독서 코치** | main | Context + summary + 페이지 텍스트 → `ReadingGuide` (synopsis·prompts·before·after). **이미지 안 봄, illustrate와 병렬** | 🔒 ③ |
| `illustrate` | – | image | characterSheet → 시트 1장 → 페이지 N장 병렬, 페이지 단위 실패 처리 | 🔒 ④ |
| `render` | – | – | 단계별 JSON + book.html. 재생성 후에도 다시 돈다 | 🔒 ⑤ |

- **동화 속 질문은 B가 만든다.** 작가가 쓰지 않는다. `guide.prompts[]`에 `afterPage`로만 페이지와 연결 → 질문 수·위치를 바꿔도 `pages`는 안 건드린다. 🔒 ⑤-1
- `design_story`는 확정안에 없는 노드다. "실제 상황을 그대로 재현하지 않고 간접화한다"(기획안 9)를 별도 단계로 뺀 것. `write_story` 안에 접을 수도 있다. → §11
- **검수(`verify_story`)는 지금 안 넣는다.** 검수 기준이 사람 평가(§6-3)에서 나온 뒤에 추가할 항목. 그 전까지 쓰기는 1회.

---

## 3. State

그래프를 흐르는 상태. 모든 노드가 읽고, 일부만 쓴다. LangSmith에 노드별로 전부 남는다.

```python
class PipelineState(TypedDict):
    # 🔒 입력 Context — 1차 폼 + 인터뷰가 함께 채움
    context: StoryInputContext          # situation / child / moment / parent
    # 🔒 인터뷰
    interview_turns: list[Turn]         # (question, answer, contextUpdate)
    interview_done_by: Literal["sufficient", "max_turns", "user_skip"] | None
    interview_summary: str | None       # A가 끝에 쓰는 한 문단 — 생성기와 B가 둘 다 읽음
    # 💡 설계
    story_design: StoryDesign | None    # 간접화 설정
    # 생성
    story: StoryText | None             # title, pages[].text, characterSheet, pages[].imagePrompt
    writer_feedback: str | None         # 부모 피드백 → 작가에게 (뷰어 [다시 쓰기])
    # 검토
    review_action: Literal["approve", "edit", "regenerate"] | None
    regenerate_scope: Literal["character", "story", "text", "images"] | None  # 💡 뭐가 싫은지
    review_feedback: str | None         # 자유 서술. "토끼 말고 공룡으로" / "3p 엄마 말이 설명조"
    # 산출물
    guide: ReadingGuide | None          # 🔒 synopsis / prompts / beforeReading / afterReading
    illustrations: Illustrations | None # 🔒 pages[].image.{url,status}
    # 메타
    status: StoryStatus                 # 🔒 requested → generating_text → generating_images → completed | failed
    cost: CostLog                       # 노드별 토큰·시간·이미지 수
```

### 핵심 스키마 — 🔒 백엔드 사전조사 ①③⑤ 그대로 (pydantic으로 옮김)

- **`StoryInputContext`** = `situation` + `child` + `moment` + `parent`
  - `situation.category` enum 8종 (+custom), `timing: past|upcoming`, `description` ≤30자 — 필수
  - `child.ageMonths` int — 필수. gender / traits / interests — 선택 (개인화용)
  - `moment.reactions[]`, `moment.emotions[]` (`unknown` 허용) — **선택** (upcoming이면 못 채움)
  - `parent.response / concern / message / messageDirection` — 전부 인터뷰가 채움. `messageDirection` enum 6종, `undecided` 포함
  - 생성용 vs 개인화용: 없으면 동화 **내용**이 바뀌면 생성용, **묘사**만 바뀌면 개인화용
- **`InterviewTurnResult`** = `contextUpdate` + `status: ask|sufficient` + `nextQuestion` + `reason`
- **`StoryText`** — title, pages[].text, `characterSheet`(주인공 묘사 한 문단), pages[].`imagePrompt`
- **`ReadingGuide`** — `prompts[]{afterPage, text, purpose: empathy|predict|perspective|connect, parentHint}` + `beforeReading{intent, tips[]}` + `afterReading{bridgeQuestion, ifUndecided}`
- **`StoryResult`** — 프론트에 주는 최종 구조. `pages[]{order, text, image{url,status}}` + `guide` + `status/progress`

### 💡 제안 스키마

- **`StoryDesign`** — 주인공(이름·종·특징, 아이 관심사에서), 세계, 실제 상황을 한 걸음 떨어뜨린 재구성, `valuesToHonor`(결론으로 주입하지 않을 가치). 간접화 거리는 실험 축(§5-4).
- **`Verify`** — (나중) 사람 평가에서 나온 기준으로 만든다. 지금은 없음.

---

## 4. 인터뷰 — 🔒 확정안 요약

종료 조건 4요소 **채택**: `상황 맥락 + 아이 반응/감정 + 부모 고민 + 전달 방향`

| 4요소 | 필드 | 충족 |
|---|---|---|
| 상황 맥락 | `situation.*` | 1차 폼에서 이미 |
| 아이 반응/감정 | `moment.*` | 1차 폼. `emotions == ["unknown"]`이면 1회 보완 시도, 그래도 모르면 통과 |
| 부모 고민 | `parent.concern` | 인터뷰. "딱히 없다"도 유효 |
| 전달 방향 | `parent.messageDirection` | 인터뷰. `undecided`도 유효 |

→ **실제로 인터뷰가 채워야 하는 건 `concern`과 `messageDirection` 둘.** 명확한 부모는 1~2턴이면 끝.

구현 규칙:
- 매 턴 AI가 **질문과 필드 추출을 동시에** (`contextUpdate` + `nextQuestion`). 따로 하면 호출 두 배.
- `missingFields`는 **서버(노드 코드)가 계산**해서 프롬프트에 넣는다. AI 판단에만 맡기면 채워진 걸 또 묻는다.
- 종료 판단도 AI 말만 믿지 않고 코드가 `concern`·`messageDirection` 채워졌는지 **이중 확인**.
- "모르겠다" → 바로 `undecided`로 확정하지 않고 **정리 질문 최대 2회** (MessageDirection 후보 중 상황에 맞는 2~3개를 선택지처럼). 그래도 모르면 `undecided` + `concern`에 부모 말 그대로 → 생성 프롬프트에서 주인공의 행동을 "한 번 해 봤다" 수준에 두고 어느 쪽이 옳은지 드러내지 않음.
- 최대 **5턴**. 넘으면 `undecided`로 강제 종료. 부모가 언제든 "이만 만들어주세요" → `user_skip`.
- 질문마다 **답변 카드(`choices`) 2~4개**를 같은 호출에서 만든다. 부모가 누르면 그 문장이 답변으로 간다. 노드가 빈 카드·겹치는 카드를 빼고 4개까지 남겨 interrupt 값과 FastAPI 인터뷰 응답에 싣는다.
- 끝날 때 `interview_summary` 한 문단 — "이 부모는 ~를 걱정하고 ~를 전하고 싶어한다". 구조화 필드에 빠지는 뉘앙스를 담는다. 생성기와 B가 둘 다 읽는다.

LangGraph에서: `interview` 노드가 `interrupt({question, turn, choices})`로 멈추고, 답변이 들어오면 재개 → `contextUpdate` 병합 → 조건부 엣지가 `sufficient / max_turns / user_skip` 판정.

---

## 5. 사람이 개입하는 지점

LangGraph `interrupt()`를 쓴다. 그래프가 멈추고 상태가 checkpointer에 저장되고, 외부에서 값을 넣어주면 그 자리에서 재개된다.

| 지점 | 무엇을 기다리나 | 프로토타입에서 | MVP에서 |
|---|---|---|---|
| `interview` 각 턴 | 부모 답변 (또는 skip) | CLI 입력 / 스크립트 자동 답변 | 프론트 채팅 UI |
| `parent_review` | 수정/재생성/완료 | 뷰어 버튼 (다시 쓰기 / 캐릭터 바꾸기 / 그림만 다시 / 완료) | 알림 → 재진입 → 검토 화면 |

**checkpointer**: 프로토타입은 SQLite(`langgraph-checkpoint-sqlite`) — 파일 하나, 서버 없음. MVP는 Postgres. 같은 인터페이스라 교체만 하면 된다. 이게 "생성 요청 → 이탈 → 알림 → 재진입" UX를 받쳐주는 부분이고, 🔒 ④-5의 "비동기 작업 + 상태 조회" 구조와 맞물린다.

`thread_id` = 동화 1권 (= `storyId`). 부모가 며칠 뒤에 돌아와도 같은 thread로 이어간다.

### 💡 재생성은 "뭐가 싫은지"를 받아서 거기로 되돌린다

자동으로 도는 건 쓰기 1회. 그 뒤는 `parent_review`에서 멈춰 있고, **뷰어 버튼으로 사람이** 아래 중 하나를 시킨다. 자동 재작성·재생성·재시도는 없다.

"재생성" 버튼 하나로 처음부터 다시 뽑지 않는다. 의도를 받아서 필요한 노드만 다시 돈다 — 비용도 그만큼만.

| 부모가 싫은 것 | `regenerate_scope` | 되돌아갈 곳 | 다시 도는 것 |
|---|---|---|---|
| 캐릭터 (토끼 말고 다른 거) | `character` | `design_story` | 간접화 → 동화 → 가이드 → 그림 전부 |
| 이야기 흐름·상황 재구성 | `story` | `design_story` | 위와 같음 |
| 문장·표현 (특정 페이지) | `text` + feedback | `write_story` | 동화 → 가이드 → 바뀐 페이지 그림만 |
| 그림 화풍·특정 페이지 | `images` | `illustrate` | 그림만 |
| 그냥 다른 걸 보고 싶음 | `story`, feedback 없음 | `write_story` | 동화 → 가이드 → 그림 |

이게 `design_story`를 별도 노드로 두는 이유 중 하나다 — 캐릭터·세계·상황 재구성이 `write_story` 안에 접혀 있으면 "캐릭터만 바꿔줘"를 받을 자리가 없다. 프로토타입은 CLI 번호 선택, MVP는 디자인이 버튼으로 푼다. 세부 갈래는 나중에 더해도 엣지 추가로 끝난다.

---

## 6. 품질 — 측정하고 올리는 루프

이 프로젝트에서 가장 오래 할 일. 구조는 처음부터 깔아둔다.

### 6-1. 트레이싱 (LangSmith)
- 모든 실행이 프로젝트 `firstory-pipeline`에 노드별로 남는다. 프롬프트·입력·출력·토큰·지연.
- "이 동화 왜 이렇게 나왔지?" → 트레이스 열어서 인터뷰 summary가 이상한지, write가 이상한지, 가이드가 놓쳤는지 바로 본다.
- 프롬프트는 레포 `prompts/`에 두고 커밋으로 관리. PM이 PR로 고치는 게 리뷰하기 쉽다.

### 6-2. 데이터셋
- `datasets/inputs/` — 1차 폼 + 스크립트 답변. 처음엔 샘플 동화 3안의 상황 3개(친구 관계 / 등원 거부 / 추상적 질문) + upcoming 케이스 2개.
- `datasets/samples/` — PM이 수동으로 쓴 샘플 동화 (기준선). 블라인드 비교 대상.
- 잘 나온 실행은 LangSmith 데이터셋에 추가 → 회귀 테스트.

### 6-3. 평가자
세 겹으로. 단, **순서는 사람이 먼저다.** 기준을 미리 세우지 않는다 — 첫 10~20권을 뽑아서 PM·백엔드가 같이 보고 "좋다/별로다 + 이유 한 줄"을 적는다. 거기서 반복되는 불만이 rubric이 된다. 아래 2번 LLM 판정은 그 뒤에, 사람이 본 결과를 정답지로 삼아 일치율을 확인하고 나서 자동화한다.

1. **규칙** — 페이지 수, 질문 수(2~3)·`afterPage` 범위, 금지 패턴(아이 이름·실제 장소 노출), 글자 수, `undecided`일 때 질문이 열린 질문인지. 코드로.
2. **LLM 판정 (rubric)** — 사람 평가에서 나온 기준으로. 초기 후보: 교훈 주입 / 간접화 거리 / 연령 어휘 / 질문의 성격 / 캐릭터 일관 / 가이드 대화문의 구체성 — 실제 항목은 사람 평가 결과로 바꾼다.
3. **사람** — 최종 기준. PM 블라인드 비교 (수동 샘플 vs 생성물). 캐릭터 일관성은 자동 지표가 보조일 뿐, 사람 눈이 결정한다. 지원서 기준: 생성 성공률 80%, 캐릭터 일관 8/10.

`evals/run.py`로 데이터셋 전체를 돌리고 LangSmith에 결과를 올린다. 프롬프트를 바꾸면 이걸 돌려서 전후 비교.

### 6-4. 실험 축
처음 몇 주 동안 바꿔볼 것들. 하나씩, 데이터셋으로 비교.
- 작가 프롬프트: 구조(기승전결 템플릿) 유무, 예시 동화 포함 유무 (발표 피드백: "프롬프트 많이 먹일수록 못해질 수 있음" — 실제로 재보자)
- 모델 등급: write를 main vs light — 품질 차이가 비용 차이만큼 나는지
- 💡 `design_story` 분리 vs `write_story`에 포함
- 간접화 거리: 상황을 얼마나 바꿀지 (너무 멀면 자기 얘기로 못 느끼고, 가까우면 방어적)
- 질문 2개 vs 3개, `purpose` 조합

---

## 7. 일러스트 — 🔒 ④ 그대로

1. `write_story`가 `characterSheet`(주인공 외형 한 문단) + 페이지별 `imagePrompt`를 함께 낸다. 텍스트를 **전체** 먼저 생성해야 외형·배경·화풍이 전 페이지에서 일관된다.
2. 캐릭터 시트 이미지 1장 생성
3. 그걸 **참조 이미지**로 넣고 페이지별 삽화 병렬. 동시 3~5장씩 끊어서 (rate limit). 페이지 프롬프트에 `characterSheet` 공통 주입.
4. 한두 장 실패해도 나머지는 살리고 `pages[].image.status`로 페이지 단위 표시. 자동 재시도 없음 — 뷰어의 [재시도] 버튼으로 그 페이지만.

| 후보 | 참조 방식 | 메모 |
|---|---|---|
| OpenAI gpt-image-2 | `images.edit` + 참조 이미지, `input_fidelity=high` | 지금 키 있음. 먼저 이걸로 |
| Gemini 3.1 Flash Image | 참조 이미지 최대 4장 | 비교 테스트 대상 |

`reading_guide`는 이미지를 안 보니까 **여기와 동시에 돈다** (④-1). 텍스트+가이드가 나오는 시점에 "읽기 시작 가능", 이미지는 도착하는 대로 — 이 UX는 디자인 결정 사항.

---

## 8. 모델·비용

| 용도 | 등급 | 메모 |
|---|---|---|
| interview | light | 판단 위주. 싼 모델로 충분한지 §6으로 확인 |
| design_story, write_story, reading_guide | main | 품질이 걸린 곳 |
| illustrate | image | 비용의 대부분 |

- 권당 변동비 목표 850원(지원서) — **PM 쪽 가정값**이지 실측이 아니다. 텍스트는 수십 원, 이미지 9장이 $0.3~1.0. medium 품질이면 근처거나 넘고, low면 밑. 재작성·재생성·이미지 재시도는 별도.
- `cost` 상태에 노드별 토큰·시간·이미지 수를 남긴다. 첫 10권 돌리면 실제 숫자가 나온다. 발표 피드백 "비용 최적화가 제일 중요".
- 모델 ID는 설정 파일 한 곳. LLM 호출은 `llm.py` 한 군데로 모아서 벤더 교체 가능하게.
- 한 권 예상 시간 1~2.5분, 병목은 이미지 (🔒 ④-3). 실측은 ⑥ 테스트 첫 항목.

---

## 9. 디렉토리

```
firstory_pipeline/
  pyproject.toml
  .env.example              OPENAI_API_KEY, LANGSMITH_API_KEY, 모델 ID
  README.md
  ARCHITECTURE.md           ← 이 문서

  src/firstory/
    graph.py                StateGraph 정의, 엣지, 병렬 브랜치, 컴파일
    state.py                PipelineState
    schemas.py              pydantic: StoryInputContext, InterviewTurnResult, StoryText,
                            ReadingGuide, StoryResult (🔒) + StoryDesign (💡)
    llm.py                  structured output 호출 한 곳. 모델 등급 → ID 매핑
    config.py
    nodes/
      form_input.py
      interview.py          missingFields 계산, 이중 확인, interrupt()
      design_story.py       💡
      write_story.py
      parent_review.py      interrupt()
      reading_guide.py
      illustrate.py
      render.py
    prompts/                *.md — PM이 고치는 곳. {{var}} 치환
      _persona.md
      interview.md  design_story.md  write_story.md  reading_guide.md
    cli.py                  로컬 실행: 인터뷰·검토를 터미널로

  viewer/
    app.py                  Streamlit 한 페이지. 왼쪽 입력 → [실행] → 오른쪽 단계별 출력
                            (인터뷰 로그 / Context+summary / 동화 페이지+그림+질문 / 가이드 / 비용)
                            인터뷰는 scripted answers로 자동. 검토 단계 버튼: [다시 쓰기(+피드백)]
                            [캐릭터 바꾸기] [이 그림만 다시] [실패 재시도] [완료] → parent_review 재개.
                            누를 때마다 비용 누적 표시. 지난 실행은 checkpointer에서 불러온다.
                            버리는 물건 — 진짜 프론트는 FE가 만든다.

  datasets/
    inputs/*.json           1차 폼 + 스크립트 답변
    samples/*.md             PM 수동 샘플
  evals/
    rules.py                규칙 평가
    judge.py                LLM rubric 판정
    run.py                  데이터셋 전체 실행 → LangSmith
  out/                      실행별 산출물 (gitignore)
```

---

## 10. 서버와의 관계 (나중)

프로토타입은 CLI + 뷰어. MVP가 되면 🔒 ④-5 구조:

```
[프론트] ── HTTPS ──▶ [API 서버: Node or Spring] ──▶ [AI 파이프라인 서비스: Python/LangGraph]
                            │                              │
                           [DB]                        [checkpointer: Postgres]
                                                           │
                                                       [LLM / 이미지 API]

POST /stories                → { storyId, status: "requested" }  즉시 반환, 백그라운드 실행
POST /stories/:id/answer     → 인터뷰 답변 전달 (interrupt 재개)
POST /stories/:id/review     → 검토 결과 전달 (interrupt 재개)
GET  /stories/:id/progress   → StoryProgress
GET  /stories/:id            → StoryResult
```

- API 서버는 인증·결제·라이브러리·알림을 맡고, 파이프라인 서비스에는 `thread_id`(= storyId)로 위 다섯 가지만 한다.
- LangGraph Platform(또는 자체 FastAPI 래퍼)이 이 인터페이스를 거의 그대로 제공한다.
- 알림은 폴링 + 서비스 내 알림으로 시작, 웹 푸시는 iOS 제약으로 보류 (🔒 ⑤-2).
- **지금 Python으로 가도 메인 서버 언어와 무관**하다.

---

## 11. 결정 사항

### 🔒 확정 (백엔드 사전조사)
- 입력 스키마 `StoryInputContext` (enum 포함), 필수 4개, `moment` 선택
- 인터뷰: 4요소 종료 조건, 추출+질문 동시, missingFields 서버 계산, "모르겠다" 정리 질문 2회, 최대 5턴, user_skip, summary
- A/B는 같은 Context 공유 + 역할 프롬프트 분리
- 질문은 B가 생성, `guide.prompts[]` + `afterPage`, 기본 2 최대 3, `undecided`면 열린 질문만
- 텍스트 전체 → 이미지 병렬 + 가이드 병렬, `characterSheet` 공통 주입
- 상태 5개 + 이미지 진행률, 비동기 작업 구조

### 지금 정할 것
- [ ] Python + LangGraph + LangSmith로 간다 ← 이 문서의 전제
- [ ] 텍스트 모델 벤더 (OpenAI 키 있음 → 일단 OpenAI, 평가 루프 생기면 비교)
- [ ] 이미지 모델 1차 선택 (gpt-image-2 → Gemini 비교는 §6 루프에서)
- [ ] 프롬프트 관리: 레포 `prompts/` + PR

### 💡 백엔드끼리 정할 것
- [ ] `design_story`(간접화 설계)를 별도 노드로 둘지 `write_story`에 접을지 — 둘 다 돌려보고 비교 (§6-4)
- [x] 검수(`verify_story`) → **지금 안 넣음.** 사람 평가(§6-3)에서 기준 나오면 추가
- [x] 재생성 → **`regenerate_scope`로 받아서 해당 노드로 되돌림** (§5). 세부 갈래는 실험하면서 조정
- [x] 한 번 실행 범위 → **자동은 쓰기 1회.** 재작성·재생성·이미지 재시도는 전부 **뷰어 버튼으로 사람이 시킴** (§5 표대로 해당 노드로 되돌림). 비용은 누를 때마다 누적 표시

### 회의에서 정할 것 (회의록 열린 질문)
- [ ] 줄거리 제안/수정 단계 유지? → 노드 하나 추가/제거로 끝나니 **둘 다 돌려보고 데이터로**
- [ ] 일러스트가 MVP 핵심? → 텍스트만으로 PSF 검증 가능한지
- [x] 입력 필드 근거 리서치 → **일단 🔒 스키마로 파이프라인 만들고, 실험하면서 수정** (10/27 리서치 결과는 enum 값 조정으로 반영)

### 나중에
- 검수 노드 `verify_story`: 사람 평가에서 반복되는 문제가 보이면 그 기준으로. 작가와 다른 호출, 불합격 시 피드백 들고 재작성
- checkpointer SQLite → Postgres
- 알림 연동 지점: `parent_review` interrupt 직전

---

## 12. 첫 2주

1. 그래프 뼈대 + 🔒 스키마(pydantic) + 프롬프트 (기존 TS 초안의 프롬프트 이식, 확정안에 맞게 수정)
2. CLI로 동글이 케이스 end-to-end, LangSmith에 트레이스 남는지 확인 → `viewer/app.py`로 입력↔출력 눈으로 확인
3. 데이터셋 5케이스로 10~20권 뽑기 → **PM·백엔드가 같이 보는 자리 한 번** (좋다/별로다 + 이유). 여기서 rubric이 나온다
4. 그 rubric으로 규칙 평가 + LLM 판정 → `evals/run.py`. 사람 평가와 일치율 확인
5. 실험 축(§6-4) 중 2개 돌려서 전후 비교 — `design_story` 유무가 첫 번째

여기까지 되면 "품질을 올릴 수 있는 상태"다. 그 다음부터가 진짜 작업.
