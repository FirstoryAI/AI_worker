# 그림 위 글 배치 (textBlocks) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 쪽 그림마다 AI가 글을 1~2덩어리로 나누고, 그림을 보고 자리·글자색을 정해 `text_blocks`로 넘기고, Spring이 저장해 미리보기·책 응답의 `textBlocks`로 내려준다.

**Architecture:** AI 워커는 순수 계산(줄 나누기, 크기, 여백·띠·복잡도·읽는 순서, 자리 옮기기)을 `nodes/layout.py`에 모으고, LLM 호출 두 개(덩어리 나누기, 자리 찾기)를 같은 파일에 둔다. `illustrate._run`의 쪽 작업이 "나누기 → 크기 넣어 그리기 → 자리 찾기 → 코드 확인 → 합치기 → (최대 2쪽) 다시 그리기 → 기본 자리" 순서로 돌고, 결과는 `PageImage.text_blocks`에 붙는다. Spring은 `story_pages.text_blocks`(jsonb)에 저장하고 응답에 싣는다. 프론트는 이슈로 알린다.

**Tech Stack:** Python 3.13, LangGraph, FastAPI, OpenAI Responses API(`gpt-5.4-mini` 이미지 입력), Pillow, numpy / Java 21, Spring Boot 4.1, Flyway, Hibernate JSON.

**Spec:** `docs/superpowers/specs/2026-11-04-text-blocks-design.md` (AI_worker 저장소). 실행하는 사람은 설계와 이 계획을 같이 읽는다.

## Global Constraints

- 글자 크기는 그림 폭의 **1.5%**(1920 폭에서 29px)다. 줄 높이는 글자의 **1.55배**, 문단 사이는 **0.6줄**이다.
- 한 줄 최대 폭은 그림 폭의 **38%**다.
- 여백: 위·아래 **7%**, 좌우 **5%**, 접히는 선(x=50%)에서 **4%** 이상 떨어진다.
- 띠: 덩어리 위끝이 위에서 7~**20%** 안에 있거나, 아래끝이 아래에서 7~20% 안에 있어야 한다.
- 복잡도: 가우시안 흐림 3px 뒤 상자와 그 둘레 3%(그림 폭 기준)의 RGB 표준편차 평균이 **8 이하**여야 한다. 계산은 1/4로 줄인 그림에서 적분 영상으로 한다. 옮길 때 덩어리끼리는 그림 폭의 **2%** 이상 띄운다.
- 다시 그리기는 실행 한 번에 최대 **2쪽**이다. 마지막 기본 자리는 합친 한 덩어리를 `x 5, y 7, dark`에 둔다.
- 줄 나누기 정규식은 `(?<!\.)\.(?!\.)["”’]?\s+` 뒤에서 자른다. `**강조**`는 줄에 그대로 두고, 폭을 잴 때만 뺀다.
- 덩어리 나누기와 자리 찾기 모델은 `config.model_light`, reasoning `low`, structured output이다.
- 분량 규칙은 한 쪽 3~5줄이고, 대사 안 문장도 한 줄로 센다. 프롬프트 문장은 설계 1절에 적힌 그대로 쓴다.
- AI 저장소에서는 프롬프트와 코드를 커밋으로 나눈다. 백엔드는 `./gradlew build && git commit` 순서로, 빌드 명령에 파이프를 붙이지 않는다.
- 이슈 먼저 → 브랜치 → PR(`Closes #N`) 순서다. PR 제목은 `<타입>(scope): 설명`이다. 합치기는 Claude가 `gh pr merge --merge --delete-branch`로 한다.
- AI 결과를 보고할 때는 전문(그림 포함)을 보여 주고 품질 판단은 사용자에게 맡긴다. 그림 비용이 드는 확인은 하기 전에 비용을 말한다.

## Review Focus

1. **그림 생성이 실패한 쪽**(`status: failed`)은 `text_blocks`가 없어야 하고 결과 전체는 정상이어야 한다. → Task 3 테스트 `failed page has no blocks`
2. **글만 다시 만들기로 글은 바뀌었는데 장면이 같아 그림을 재사용한 쪽**은 옛 글의 덩어리를 쓰면 안 된다. 나누기와 자리를 다시 해야 한다. → Task 3 테스트 `text regen relayouts reused image`
3. **AI가 줄 번호를 빠뜨리거나 겹치거나 3덩어리로 준 경우**는 한 덩어리 한 문단이 된다. 대사 중간 끊김은 다시 붙인다. → Task 1 `normalize_chunks` 확인
4. **자리 찾기 AI가 좌표를 픽셀(100 초과)로 주거나 덩어리 수가 다르게 온 경우**는 % 변환하거나 기본 자리로 가고, 예외로 생성이 실패하면 안 된다. → Task 2 테스트 `place tolerates bad answers`
5. **Spring이 받은 `text_blocks`가 깨진 경우**(빈 줄, 색 다른 값, 0~100 밖, 0개·3개 이상)는 그 쪽만 `null`로 저장하고 동화 생성은 성공해야 한다. → Task 5 `PageTextBlockTest`, `HttpAiClientTest`

---

## 파일 지도

AI_worker (작업 폴더는 `origin/main`에서 새 worktree, 브랜치 `feat/text-blocks`)
- Create `src/firstory/nodes/layout.py`: 줄·덩어리·크기·자리 계산과 LLM 호출 두 개
- Create `src/firstory/prompts/text_chunks.md`, `src/firstory/prompts/text_place.md`
- Create `src/firstory/assets/fonts/MemomentKkukkukk.woff2`: 프론트 저장소 `src/assets/fonts/`에서 복사. 폭 계산용이고, 프론트가 이미 쓰는 글꼴이다
- Modify `src/firstory/schemas.py`: `TextBlock`, `TextChunking`, `BlockSpot`, `TextPlacement`, `PageImage.text_blocks`
- Modify `src/firstory/llm.py`: `structured_image`
- Modify `src/firstory/mock.py`: 두 스키마의 가짜 응답
- Modify `src/firstory/nodes/illustrate.py`: `_LAYOUT` 제거, `page_prompt` 레이아웃 인자, `_run` 쪽 작업, 재사용 쪽 다시 배치
- Modify `src/firstory/server.py`: 결과 `pages[].text_blocks`, `text_position` 도출
- Modify `src/firstory/prompts/write_story.md`, `polish_story.md`, `schemas.py` 쪽 글 설명: 분량 규칙
- Modify `pyproject.toml`: `pillow`, `numpy`를 명시 의존성으로(지금은 간접 의존)
- Create `evals/layout_run.py`: API 없이 `layout.py` 순수 함수 확인
- Modify `evals/mock_run.py`, `evals/api_run.py`

Backend_Mainpage (브랜치 `feat/text-blocks`)
- Create `src/main/resources/db/migration/V11__page_text_blocks.sql`
- Create `src/main/java/com/firstory/domain/generation/entity/PageTextBlock.java`
- Modify `domain/generation/entity/StoryPage.java`, `global/ai/AiGenerationResult.java`, `global/ai/HttpAiClient.java`, `domain/generation/service/GenerationResultRecorder.java`, `domain/generation/dto/PreviewResponse.java`, `domain/reading/dto/BookResponse.java`, `global/ai/FakeAiClient.java`
- Docs: `docs/FIRSTORY-AI-API-SPEC-v0.3.md`, `docs/frontend/screens.md`, `docs/frontend/fake-ai.md`
- Tests: `PageTextBlockTest`, `HttpAiClientTest`, 생성 통합 테스트

---

### Task 0: 이슈 세 개

**Files:** 없음 (GitHub)

- [ ] **Step 1:** AI_worker 이슈 「그림을 읽어 쪽마다 글 덩어리 자리·글자색 정하기 (text_blocks)」. 본문은 문제/원인/할 일 형식이고 설계 문서 링크를 넣는다. 라벨 `enhancement`.
- [ ] **Step 2:** Backend_Mainpage 이슈 「쪽마다 글 덩어리 배치(textBlocks) 저장하고 미리보기·책 응답에 싣기」. V11 칸과 응답 형식(설계 7절)을 적는다.
- [ ] **Step 3:** Frontend_MainPage 이슈 「쪽 글을 textBlocks 자리에 상자 없이 그리기 (데스크톱)」. 내용은 설계 8절 그대로다. 휴대폰은 새 그림에서 상자가 인물을 가릴 수 있다는 점을 꼭 적는다. 세 이슈는 서로 링크한다.

### Task 1: 줄·덩어리·크기·자리 계산 (`layout.py` 순수 함수)

**Files:**
- Create: `src/firstory/nodes/layout.py`, `src/firstory/assets/fonts/MemomentKkukkukk.woff2`, `evals/layout_run.py`
- Modify: `pyproject.toml` (`uv add pillow numpy`)

**Interfaces:**
- Produces (모두 `firstory.nodes.layout`):
  - 상수 `W, H = 1920, 1088`, `FONT_RATIO = 0.015`, `LINE_H = 1.55`, `PARA_GAP = 0.6`, `MAX_LINE = 0.38`, `EDGE_Y, EDGE_X, FOLD, BAND = 7, 5, 4, 20`, `BUSY_LIMIT = 8.0`, `BUSY_PAD = 0.03`, `GAP = 0.02`, `MAX_REDRAWS = 2`, `DEFAULT_SPOT = (5.0, 7.0, "dark")`
  - `split_lines(text: str) -> list[str]`: 원래 `\n`과 마침표 기준으로 나눈다(설계 2절)
  - `text_width(line: str) -> float`: 1920 폭 기준 px. `**`를 빼고 Memoment 글꼴 29px로 잰다
  - `wrap_line(line: str) -> list[str]`: 38%(729.6px)를 넘으면 띄어쓰기에서 자른다
  - `normalize_chunks(n_lines: int, idx: list[list[list[int]]]) -> list[list[list[int]]]`: 순서대로 모든 줄을 한 번씩 쓰고 덩어리가 1~2개인지 확인하고, 아니면 `[[list(range(n))]]`. 따옴표가 열린 줄부터 닫히는 줄까지는 같은 문단으로 붙인다
  - `build_blocks(lines: list[str], idx) -> list[list[list[str]]]`: 덩어리 > 문단 > 줄(`wrap_line` 적용)
  - `merge(blocks) -> list[list[list[str]]]`: 한 덩어리로 합친다(문단 유지)
  - `block_size(block) -> tuple[float, float]`: (폭 px, 높이 px), 1920×1088 기준
  - `class Busy`: `Busy(image: bytes)`, `.at(x, y, w, h) -> float` (px 좌표, 1920×1088 기준. 그림 크기가 달라도 맞춰 줄인다)
  - `settle(busy: Busy, blocks, spots: list[dict]) -> list[dict] | None`: 설계 5절의 2~5단계(밀기, 띠, 복잡도, 읽는 순서, 옮기기). 각 dict는 `{"x": %, "y": %, "color"}`이고, 하나라도 자리가 없으면 `None`

- [ ] **Step 1: `evals/layout_run.py`에 실패하는 확인을 쓴다**

```python
assert split_lines('라라가 골랐어요. "어제 그 말 들으니 속상했어. 나는 같이 그리고 싶었어."') == [
    '라라가 골랐어요.', '"어제 그 말 들으니 속상했어.', '나는 같이 그리고 싶었어."']
assert split_lines('"알겠어…" 미나가 말했어요.') == ['"알겠어…" 미나가 말했어요.']
assert split_lines("하루가 **토닥토닥** 했어요.\n잘 자.") == ["하루가 **토닥토닥** 했어요.", "잘 자."]
assert all(text_width(l) <= W * MAX_LINE for l in wrap_line('"어제는 내 그림을 혼자 끝내고 싶었어. 라라가 싫어서 간 건 아니야."'))
lines = ['미나가 라라를 보았어요.', '"어제는 내 그림을 혼자 끝내고 싶었어.', '라라가 싫어서 간 건 아니야."', '라라는 꽃을 그렸어요.']
assert normalize_chunks(4, [[[0, 1], [2]], [[3]]]) == [[[0, 1, 2]], [[3]]]          # 대사 중간 문단 끊김 → 붙임
assert normalize_chunks(4, [[[0, 1]], [[2, 3]]]) == [[[0, 1, 2]], [[3]]]            # 대사 중간 덩어리 끊김 → 붙임
assert normalize_chunks(4, [[[0]], [[2, 3]]]) == [[[0, 1, 2, 3]]]                   # 줄 빠짐
assert normalize_chunks(4, [[[0]], [[1]], [[2, 3]]]) == [[[0, 1, 2, 3]]]            # 3덩어리
assert normalize_chunks(4, [[[1, 0]], [[2, 3]]]) == [[[0, 1, 2, 3]]]                # 순서 바뀜
w, h = block_size([["가나다"], ["라마"]]); assert h == (2 + 0.6) * 29 * 1.55
```

그리고 `Busy`/`settle`을 위한 합성 그림 확인을 쓴다. 1920×1088 흰 배경의 왼쪽 위(x 5~45%, y 7~40%)에 4px 간격 줄무늬를 그린 그림에서는 이렇다.
- `settle`이 AI 자리 `{"x": 6, "y": 8}`을 줄무늬 밖 띠 안으로 옮긴다
- AI 자리가 띠 밖(`y 45`)이면 띠로 옮긴다
- 덩어리 2를 덩어리 1보다 먼저 오는 자리(덩어리 1이 오른쪽 면, 2가 왼쪽 면)에 주면 읽는 순서를 지키는 자리로 옮긴다
- 픽셀 답(`x 1037`)은 %로 바꾼다
- 그림 전체가 줄무늬면 `None`

- [ ] **Step 2:** `uv run python evals/layout_run.py` → ImportError로 실패하는 것을 확인한다.
- [ ] **Step 3:** `layout.py`에 위 함수를 구현한다.
  - 복잡도는 `Image.resize((W//4, H//4)).filter(GaussianBlur(0.75))` 뒤 채널별 적분 영상(합, 제곱합)으로 표준편차를 구하고 평균을 낸다.
  - 옮기기는 같은 면을 먼저, 다음에 반대쪽 면을 8px 격자로 본다. 점수는 `std + 0.01 × 원래 자리와의 px 거리`이고, 기준 이하인 자리 중 가장 낮은 점수를 고른다.
  - 읽는 순서는 (면 번호, y) 사전순이다. 왼쪽 면=0, 오른쪽 면=1이고, 면은 덩어리 가운데 x로 정한다.
  - 글꼴 경로는 `Path(__file__).parents[1] / "assets/fonts/MemomentKkukkukk.woff2"`다.
- [ ] **Step 4:** `uv run python evals/layout_run.py` → `layout ok`
- [ ] **Step 5:** 커밋 `feat: 글 덩어리 줄 나누기·크기·자리 계산 (layout)`

### Task 2: 스키마, 이미지 입력 LLM, 덩어리 나누기·자리 찾기 호출

**Files:**
- Modify: `src/firstory/schemas.py`, `src/firstory/llm.py`, `src/firstory/mock.py`, `src/firstory/nodes/layout.py`
- Create: `src/firstory/prompts/text_chunks.md`, `src/firstory/prompts/text_place.md`
- Test: `evals/layout_run.py` (LLM은 `llm.set_structured_override`로 가짜)

**Interfaces:**
- Consumes: Task 1의 `split_lines`, `normalize_chunks`, `build_blocks`, `block_size`
- Produces:
  - `schemas.TextBlock(paragraphs: list[list[str]], x: float, y: float, color: Literal["dark", "light"])`
  - `schemas.TextChunking(blocks: list[list[list[int]]])`
  - `schemas.BlockSpot(x: float, y: float, color: Literal["dark", "light"])`, `schemas.TextPlacement(blocks: list[BlockSpot])`
  - `schemas.PageImage.text_blocks: Optional[list[TextBlock]] = None`
  - `llm.structured_image(*, node, model, schema, system, user, image: bytes, reasoning=None) -> tuple[T, CostEntry]`. Responses API `input_image`(data URL, `detail: "high"`)를 쓴다. override가 있으면 `image=`도 함께 넘긴다(`mock.fake_structured`에 `image=None` 인자 추가)
  - `layout.chunk_page(text: str) -> tuple[list[str], list[list[list[str]]], list[CostEntry]]`: (줄, 덩어리, 비용). 줄이 하나면 LLM을 부르지 않는다
  - `layout.place_page(image: bytes, blocks) -> tuple[list[dict], list[CostEntry]]`: AI 답을 % dict 목록으로 준다. 개수가 다르거나 예외가 나면 빈 목록을 준다(호출한 쪽이 기본 자리로 간다)

- [ ] **Step 1:** `layout_run.py`에 확인을 더한다.
  - 가짜 LLM이 `TextChunking(blocks=[[[0, 1]], [[2]]])`을 주면 `chunk_page`의 덩어리가 원문 줄 그대로다(글자 비교).
  - 가짜 자리 답 `x=1037` 같은 픽셀 값과 개수가 다른 답, 예외에 대해 `place_page`가 예외 없이 `[]` 또는 보정된 값을 준다(`place tolerates bad answers`).
  - 텍스트가 1줄이면 LLM 호출 0번이다.
- [ ] **Step 2:** 실행 → 실패 확인
- [ ] **Step 3:** 구현한다.
  - `text_chunks.md`: 시안 문구 그대로 쓴다. "아래는 그림책 한 쪽의 글을 줄 번호와 함께 적은 것이다… 1덩어리… 2덩어리… 줄 번호로만 답한다." `{{lines}}` 자리를 둔다.
  - `text_place.md`: 시안 문구에 여백·띠·읽는 순서 조건과 덩어리 크기(`{{sizes}}`)를 넣는다.
  - mock은 덩어리를 `[[[0..n-1]]]`로, 자리를 `x 5, y 7, dark`로 준다.
- [ ] **Step 4:** `uv run python evals/layout_run.py` → `layout ok`
- [ ] **Step 5:** 커밋 두 개
  - `prompt: 글 덩어리 나누기·자리 찾기 프롬프트` (md 두 개)
  - `feat: 덩어리 나누기·자리 찾기 호출과 스키마` (나머지)

### Task 3: 쪽 그림 작업에 배치 넣기, 결과에 싣기

**Files:**
- Modify: `src/firstory/nodes/illustrate.py`, `src/firstory/server.py`
- Test: `evals/mock_run.py`, `evals/api_run.py`

**Interfaces:**
- Consumes: Task 1·2 전부
- Produces:
  - `illustrate.layout_prompt(sizes: list[tuple[float, float]], where: Optional[list[str]] = None) -> str`. `where`는 다시 그릴 때 덩어리별 `"left top"`처럼 쓴다
  - `illustrate.page_prompt(story, page_chars, image_prompt, sizes, request=None, where=None) -> str`. `text_position` 인자와 `_LAYOUT`은 없앤다
  - `PageImage.text_blocks` 채우기
  - 결과 `pages[]`에 `"text_blocks": [TextBlock.model_dump()] | None`
  - 결과 `pages[].text_position`은 첫 덩어리의 y+높이/2가 50% 미만이면 `"top"`, 아니면 `"bottom"`이다. 덩어리가 없으면 작가 값

- [ ] **Step 1:** 실패하는 테스트를 쓴다.
  - `mock_run.py`: 첫 생성 뒤 그림이 있는 모든 쪽의 `text_blocks`가 1~2개이고, 각 줄을 이으면 원문과 같다.
  - `failed page has no blocks`: 5쪽만 그림이 실패하도록 override하면 그 쪽만 `text_blocks is None`이다.
  - `text regen relayouts reused image`: 글 다시 만들기에서 mock 작가가 1쪽 글만 바꾸고 장면이 같으면, 1쪽 그림 key는 그대로이고 `text_blocks`의 글은 새 글이다.
  - 자리를 못 찾으면(가짜 복잡도 그림 전부 줄무늬) 다시 그리기는 실행당 2쪽까지이고, 나머지는 기본 자리다(이미지 override 호출 수로 확인).
  - `api_run.py`: `/result`의 `pages[].text_blocks` 모양 `{paragraphs, x, y, color}`
- [ ] **Step 2:** `LANGSMITH_TRACING=false OPENAI_API_KEY=가짜값 uv run python evals/mock_run.py` → 실패 확인
- [ ] **Step 3:** 구현한다.
  - `_run.work(p)`가 이 순서로 돈다: `chunk_page` → `page_prompt(sizes)`로 그리기 → `place_page` → `Busy` → `settle` → 실패하면 `merge`해서 `place_page`·`settle` → 그래도 실패하고 실행 다시 그리기 횟수(`threading.Lock`으로 세는 `_run` 지역 카운터)가 2 미만이면 `where`를 넣어 다시 그리기(같은 key에 덮어씀) → 그래도 실패하면 `DEFAULT_SPOT`에 합친 한 덩어리.
  - 그리지 않은 쪽(`only_pages` 밖, 이전 key 재사용)은 이전 `text_blocks`의 줄을 이은 글이 지금 `split_lines(p.text)`와 다를 때만 저장소에서 그림을 읽어 나누기·자리를 다시 한다.
  - 비용 엔트리 노드 이름은 `layout:chunk:page{n}`, `layout:place:page{n}`이다.
  - 쪽 줄 수가 5를 넘으면 경고 로그만 남긴다(본문 X, 쪽 번호와 줄 수만).
- [ ] **Step 4:** mock_run·api_run → `ALL OK`
- [ ] **Step 5:** 커밋 `feat: 쪽 그림마다 글 덩어리 자리를 정해 결과에 싣기 (text_blocks)`

### Task 4: 분량 규칙 (프롬프트)

**Files:** Modify `src/firstory/prompts/write_story.md`, `src/firstory/prompts/polish_story.md`, `src/firstory/schemas.py`(`StoryPage.text` 설명)

- [ ] **Step 1:** 설계 1절의 문장으로 바꾼다. 11/4 시험 diff와 같다.
  - write_story 27·33줄
  - polish 26줄
  - schemas 설명 "3~5줄(마침표마다 한 줄, 대사 안 문장도 센다)"
- [ ] **Step 2:** mock_run·api_run → `ALL OK`
- [ ] **Step 3:** 커밋 두 개
  - `prompt: 쪽 분량을 문장이 아니라 줄(마침표, 대사 안 문장 포함) 3~5줄로`
  - `fix: 쪽 글 설명을 줄 기준으로` (schemas)
- [ ] **Step 4: 진짜 모델 확인 (사용자에게 비용을 먼저 말한다: 그림 약 11~13장, 한 편 약 $0.5~1)**
  - 동화 한 편(`datasets/inputs/donggeul.json`)을 끝까지 만든다.
  - 쪽별 줄 수, 덩어리, 자리, 복잡도, 옮김·합침·다시 그리기 여부를 표로 남긴다.
  - 10쪽 그림에 글을 얹은 시안을 Memoment 글꼴로 만들어 전부 보여 준다.
  - 품질 판단은 사용자에게 맡긴다.
- [ ] **Step 5:** AI PR을 연다. `feat(illustrate): 그림을 읽어 쪽마다 글 덩어리 자리·글자색 정하기`, `Closes #<Task 0 AI 이슈>`. 합치는 건 Task 6 Spring 배포 뒤다.

### Task 5: Spring 저장과 응답 (Backend_Mainpage)

**Files:**
- Create: `src/main/resources/db/migration/V11__page_text_blocks.sql`, `domain/generation/entity/PageTextBlock.java`, `src/test/java/com/firstory/domain/generation/entity/PageTextBlockTest.java`
- Modify: `StoryPage`, `AiGenerationResult.Page`, `HttpAiClient.PageBody`(+변환), `GenerationResultRecorder`(`StoryPage.create` 인자), `PreviewResponse.Page`, `BookResponse.Page`, `FakeAiClient`(쪽마다 고정 `textBlocks`, `textPosition`과 맞게), 문서 3개
- Test: `HttpAiClientTest`(키 구조), 생성 통합 테스트(미리보기·책 응답에 `textBlocks`), `PageTextBlockTest`

**Interfaces:**
- Consumes: AI 결과 `pages[].text_blocks` (Task 3 형식)
- Produces:
  - `record PageTextBlock(List<List<String>> paragraphs, double x, double y, TextColor color)`
  - `enum TextColor { DARK, LIGHT }`: `AiValue` 규칙대로, AI 값은 소문자
  - `static List<PageTextBlock> PageTextBlock.validated(List<PageTextBlock> raw)`: 1~2개, x·y 0~100, 문단·줄이 비지 않음, 색 있음. 아니면 `null`
  - `StoryPage.textBlocks`: `@JdbcTypeCode(SqlTypes.JSON) @Column(name = "text_blocks", columnDefinition = "jsonb")`, null 허용
  - 응답 `Page`의 `List<PageTextBlock> textBlocks`(`@Schema` 예시는 설계 6절 JSON)

- [ ] **Step 1:** 실패하는 테스트를 쓴다.
  - `PageTextBlockTest`
    - 정상 2개는 그대로 통과한다.
    - 0개, 3개, x=120, 빈 줄, color null이면 `validated(...) == null`이다.
  - `HttpAiClientTest`
    - `text_blocks` 있는 응답과 없는 응답(옛 AI)을 둘 다 변환한다. `color: "light"`는 `LIGHT`가 된다.
    - 깨진 값이면 그 쪽만 null이다.
  - 통합 테스트
    - 가짜 AI로 만든 동화의 미리보기·책 응답 쪽마다 `textBlocks`가 있다.
    - 옛 데이터(`text_blocks` null)는 `textBlocks: null`이다.
- [ ] **Step 2:** `export JAVA_HOME=$(/usr/libexec/java_home -v 21) && sh ./gradlew test` → 실패 확인
- [ ] **Step 3:** 구현한다.
  - `V11__page_text_blocks.sql`: `ALTER TABLE story_pages ADD COLUMN text_blocks jsonb;` 주석 한 줄을 단다.
  - 깨진 값은 `log.warn`에 thread_id와 쪽 번호만 남긴다.
  - `FakeAiClient` 고정값: 1쪽 `[{paragraphs: [[첫 줄]], x 5, y 7, DARK}]`. test 프로필 기본 동작(다른 값)은 바꾸지 않는다.
  - 문서
    - AI 스펙 결과 예시에 `text_blocks`를 넣는다.
    - `screens.md` 미리보기·함께 읽기에 `textBlocks` 그리는 법을 넣는다(설계 8절 요약).
    - `fake-ai.md`에 고정값을 적는다.
- [ ] **Step 4:** `sh ./gradlew build` → BUILD SUCCESSFUL
- [ ] **Step 5:** 커밋 `feat(generation): 쪽 글 덩어리 배치(textBlocks) 저장하고 응답에 싣기`하고 PR `Closes #<Task 0 백엔드 이슈>`를 연다.

### Task 6: 배포와 마무리

- [ ] **Step 1:** 백엔드 PR을 합친다. 자동 배포 성공(`backend ok`)과 V11 적용을 Actions 로그에서 확인한다.
- [ ] **Step 2:** AI PR을 합친다. 자동 배포 성공(`ai ok`)을 확인한다.
- [ ] **Step 3:** 개발 서버(`https://api.firstoryofficial.com`)에서 동화 하나를 만들고 미리보기 응답(`GET /api/stories/{id}/preview`)에 `textBlocks`가 오는지 본다. 그림 비용이 드니 먼저 말한다.
- [ ] **Step 4:** NEXT-STEPS.md를 고친다.
  - 할 일: ERD에 `story_pages.text_blocks` 추가(사용자), 프론트 이슈 링크, 데모 중 `EC2_DEPLOY_ENABLED=false`
  - 작업 worktree와 로컬 브랜치를 정리한다.
