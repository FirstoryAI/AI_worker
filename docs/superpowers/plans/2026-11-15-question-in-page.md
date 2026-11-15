# 가이드 질문을 쪽 글 맨 밑에 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 독서 가이드 질문 문장(`guide.prompts[].text`)을 그 쪽(`after_page`) 그림 위 글(`text_blocks`)의 마지막 덩어리 맨 밑 새 문단으로 넣는다.

**Architecture:** 그래프 순서를 `polish_story → reading_guide → illustrate`로 바꿔 그림 전에 질문이 정해지게 한다. `illustrate`·`illustrate_only`가 `state["guide"]`에서 쪽별 질문 줄을 뽑아 `_run`에 넘기고, `_chunk`가 본문 덩어리를 나눈 뒤 질문 줄을 마지막 덩어리의 새 문단으로 붙인다. `_stale`은 본문 + 질문을 기준으로 견준다.

**Tech Stack:** Python, LangGraph, pydantic. 테스트는 `evals/mock_run.py`(assert 스크립트, `uv run python evals/mock_run.py`).

**Spec:** `docs/superpowers/specs/2026-11-15-question-in-page-design.md`

## Global Constraints

- 질문 문장은 가이드가 만든 `text` 그대로(장면 짚는 말 포함). 가이드 프롬프트·개수(기본 2, 최대 3)는 바꾸지 않는다.
- `story.pages[].text`(원고)는 바꾸지 않는다. 질문은 `text_blocks`에만.
- 질문 줄은 덩어리 나누기 AI(`chunk_page`)에 넘기지 않는다. 늘 마지막 덩어리의 **새 문단**, 맨 밑.
- 의성어 찾기(`_sfx`)에는 본문만 넘긴다(질문 말고).
- `safety_output`은 `polish_story` 뒤 나란히 그대로.
- 글 내용은 로그에 남기지 않는다(기존 규칙).
- 커밋 타입: `feat`/`fix`/`test`/`docs`, 메시지 끝에 `(#<이슈 번호>)`.

## Review Focus

1. 한 쪽에 질문이 둘(`after_page`가 같음) → 둘 다 순서대로 같은 마지막 문단에 들어가야 한다. (Task 1 테스트)
2. 덩어리가 2개로 나뉜 쪽 → 질문은 둘째(오른쪽) 덩어리 끝. `_arrange`가 한 덩어리로 합쳐도 마지막 문단 그대로. (Task 1 테스트)
3. 가이드가 없거나(`guide` None) 질문이 없는 쪽 → 지금과 똑같은 `text_blocks`. (Task 1 테스트)
4. 글 다시 만들기에서 가이드가 질문 쪽을 옮김(3쪽 → 4쪽) → 3·4쪽 모두 그림은 그대로, 글 자리만 다시. (Task 2 테스트)
5. `after_page`가 쪽 범위 밖(0, 11) → 무시하고 실행은 성공. (Task 1 테스트)

---

### Task 1: illustrate가 질문 줄을 마지막 문단으로 붙이기

**Files:**
- Modify: `src/firstory/nodes/illustrate.py` (`_stale` ~273, `_chunk` ~295, `_run`의 `work`·`relayout`·`stale` 목록, `illustrate` ~587, `illustrate_only`)
- Test: `evals/mock_run.py` (8장 끝에 `8-x` 새 절)

**Interfaces:**
- Produces:
  - `_questions(guide: Optional[ReadingGuide]) -> dict[int, list[str]]` — 쪽 번호 → 질문 줄(`split_lines`로 나눈 것, 같은 쪽 질문이 여럿이면 `prompts` 순서대로 이어 붙임). guide가 None이면 `{}`.
  - `_chunk(order: int, text: str, costs: list[CostEntry], tail: list[str] = ()) -> list[Block]` — 본문만 덩어리로 나눈 뒤 `tail`이 있으면 `wrap_line`을 거친 줄들을 마지막 덩어리에 새 문단으로 붙인다. 본문 덩어리가 비면 `[[tail줄]]` 한 덩어리.
  - `_stale(p, pi: PageImage, tail: list[str] = ()) -> bool` — 견주는 글을 `split_lines(p.text) + tail`로.
  - `_run(..., questions: dict[int, list[str]] | None = None)` — `work`·`relayout`·`stale` 계산이 `questions.get(p.order, [])`를 `tail`로 쓴다. 이전 덩어리 재사용 조건(`not _stale(...)`)도 같은 tail.
  - `illustrate`·`illustrate_only`는 `_questions(state.get("guide"))`를 `_run`에 넘기고, `illustrate`의 "전부 이전 그대로" 빠른 길의 `relayout` 판단도 같은 tail로.

- [ ] **Step 1: 실패하는 테스트 쓰기** — `evals/mock_run.py` 8장 끝에 `# 8-x) 가이드 질문은 그 쪽 마지막 덩어리의 맨 밑 새 문단` 절. 기존 8장 헬퍼(`lines_of`, `joined`, `st`/`StoryText` 만들기, `il.set_image_override(mock.tiny_png)`)를 쓴다.

```python
from firstory.schemas import GuidePrompt, ReadingGuide, BeforeReading, AfterReading
def guide_of(*pairs):   # (after_page, text)
    return ReadingGuide(synopsis="s", prompts=[GuidePrompt(id=f"q{i}", after_page=a, text=t, purpose="empathy")
                        for i, (a, t) in enumerate(pairs)], before_reading=BeforeReading(intent="i", tips=["t"]),
                        after_reading=AfterReading(bridge_question="b"))
Q = "포포가 울었어요. 포포 마음은 어땠을까요?"
qs = il._questions(guide_of((2, Q), (2, "다음엔 어떻게 할까요?"), (0, "범위 밖?"), (99, "범위 밖?")))
assert qs[2] == ["포포가 울었어요.", "포포 마음은 어땠을까요?", "다음엔 어떻게 할까요?"], qs
assert il._questions(None) == {}
ill_q, _ = il._run(st_q, "stories/q/runs/1/images", questions=qs)          # st_q: 3쪽짜리 StoryText, 쪽마다 2~3줄
p2 = next(pi for pi in ill_q.pages if pi.order == 2)
assert p2.text_blocks[-1].paragraphs[-1] == qs[2], p2.text_blocks               # 마지막 덩어리의 마지막 문단 = 질문 줄
assert lines_of(p2) == joined(st_q.pages[1].text + "".join(qs[2]))              # 본문 다음 질문
assert all(Q[:5] not in "".join(l for b in pi.text_blocks for para in b.paragraphs for l in para)
           for pi in ill_q.pages if pi.order != 2)                               # 다른 쪽엔 없음
ill_none, _ = il._run(st_q, "stories/q/runs/2/images", questions={})
assert [pi.text_blocks for pi in ill_none.pages if pi.order != 2] == [pi.text_blocks for pi in ill_q.pages if pi.order != 2]
assert not il._stale(st_q.pages[1], p2, qs[2]) and il._stale(st_q.pages[1], p2, [])   # 질문까지 같아야 그대로
```

덩어리 2개인 경우: 덩어리 나누기 mock이 `[[[0]], [[1, 2]]]`를 돌려주게 override한 쪽에서도 `text_blocks[-1].paragraphs[-1] == 질문 줄`을 assert(합쳐진 경우도 마지막 문단).

- [ ] **Step 2: 실패 확인** — Run: `uv run python evals/mock_run.py` / Expected: `AttributeError: ... '_questions'`
- [ ] **Step 3: 위 Interfaces대로 구현** — `_sfx`에는 계속 `p.text`만. `relayout`도 `_chunk(..., tail)`.
- [ ] **Step 4: 통과 확인** — Run: `uv run python evals/mock_run.py` / Expected: 새 절 통과. 8-1(전체 실행)은 아직 그래프가 가이드를 그림과 나란히 돌려 질문이 안 들어가므로 그대로 통과해야 한다.
- [ ] **Step 5: 커밋** — `git commit -m "feat: 가이드 질문 줄을 쪽 글 마지막 문단으로 붙이기 (#100)"`

### Task 2: 가이드를 그림 앞으로, 전체 흐름 테스트

**Files:**
- Modify: `src/firstory/graph.py` (docstring 그림, `polish_story` 간선, fan-in)
- Modify: `src/firstory/nodes/safety.py:4` docstring("reading_guide·illustrate와 나란히" → 순서에 맞게), `ARCHITECTURE.md` §2 그림
- Test: `evals/mock_run.py` 8-1, 8-4 근처

**Interfaces:**
- Consumes: Task 1의 `illustrate`가 `state["guide"]`를 읽음.
- Produces: 간선 `polish_story → reading_guide`, `reading_guide → illustrate`, `polish_story → safety_output`, fan-in `["safety_output", "illustrate"] → render`. `illustrate_only → render` 그대로.

- [ ] **Step 1: 실패하는 테스트로 고치기**
  - 8-1: `lines_of(pi) == joined(pg.text + 그 쪽 질문들)`로 바꾸고, mock 가이드의 질문 쪽(3·8쪽)은 `pi.text_blocks[-1].paragraphs[-1]`이 질문 줄인지 assert. 질문 없는 쪽은 지금처럼 `joined(pg.text)`.
  - 비용 순서: `r2["cost"]`에서 `reading_guide` 항목이 첫 `illustrate:` 항목보다 앞.
  - 새 절(Review Focus 4): 8-4처럼 글 다시 만들기를 돌리되 두 번째 가이드가 질문을 3쪽 → 4쪽으로 옮기게 `ReadingGuide` override. assert: 3·4쪽 `path` 그대로, 3쪽 마지막 문단에 질문 없음, 4쪽 마지막 문단이 질문, 새 비용에 `illustrate:page3`/`page4` 없음, `layout:place:page3`·`page4` 있음.
- [ ] **Step 2: 실패 확인** — Run: `uv run python evals/mock_run.py` / Expected: 8-1 assert 실패(질문 없음)
- [ ] **Step 3: `graph.py` 간선 바꾸기와 docstring·ARCHITECTURE.md 그림 고치기**
- [ ] **Step 4: 통과 확인** — Run: `uv run python evals/mock_run.py` / Expected: 끝까지 통과. 서버 배선 확인도: `uv run python evals/api_run.py` 통과(OpenAI 호출 없음)
- [ ] **Step 5: 커밋** — `git commit -m "feat: 가이드를 그림 앞으로 돌려 질문이 쪽 글에 들어가게 (#100)"`

### Task 3: 문서

**Files:**
- Modify: `Backend_Mainpage/docs/FIRSTORY-AI-API-SPEC-v0.3.md:330`(`text_blocks` 설명), `Backend_Mainpage/docs/frontend/screens.md:268`
- 문구: "질문이 있는 쪽(`prompts[].afterPage`)은 마지막 덩어리 맨 밑 문단이 그 질문(`prompts[].question`과 같은 글)이다. `text`(쪽 원고)에는 질문이 없다." screens.md에는 `textBlocks`가 `null`이거나 휴대폰 방식(`text` 사용)이면 질문이 쪽 글에 안 보인다는 한 줄.

- [ ] **Step 1: 두 문서 고치기**
- [ ] **Step 2: 백엔드 저장소에서 PR (AI 이슈를 본문에 링크)**

---

## 실행 뒤 (계획 밖, 사용자에게)
- 진짜 모델 한 편: 비용을 먼저 말하고 묻기. 볼 것: 질문 쪽 글이 6~7줄로 커져 그림을 가리는지, 앞 본문과 겹치는 말.
