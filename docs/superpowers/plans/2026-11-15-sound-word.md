# 의성어·의태어를 인물 옆에 띄우기 (soundWord) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 본문에 `**별표**` 말이 있는 쪽마다 AI 워커가 그 말을 그림 위 어디(소리 주인 옆)에 띄울지 정해 `pages[].sound_word`로 주고, Spring이 저장해 미리보기·책 응답의 `soundWord`로 내려준다.

**Architecture:** 별표 말이 있는 쪽만 글 자리 찾기 호출(`layout.place_page`)에 의성어 단락(`prompts/text_place_word.md`)과 의성어 칸이 있는 스키마(`TextPlacementWithWord`)를 쓴다. 글 자리가 최종으로 정해진 뒤 `layout.settle_word`가 말 상자를 검사하고 밀어 `SoundWord`를 만들고, `PageImage.sound_word`에 저장한다. Spring은 `story_pages.sound_word jsonb`(V16)에 `text_blocks`와 같은 방식으로 저장한다.

**Tech Stack:** Python 3.13, LangGraph, FastAPI, Pillow / Java 21, Spring Boot 4, Flyway, PostgreSQL jsonb.

**Spec:** `docs/superpowers/specs/2026-11-15-sound-word-design.md` (AI_worker). 이슈 [AI#92](https://github.com/FirstoryAI/AI_worker/issues/92), [Backend#69](https://github.com/FirstoryAI/Backend_Mainpage/issues/69). 실행하는 사람은 설계와 이 계획을 같이 읽는다.

## Global Constraints

- 별표 말이 **없는** 쪽의 자리 찾기 호출은 지금과 글자 하나 다르지 않다: system은 `prompt("text_place", sizes=…)` 그대로, user 문장 그대로, schema `TextPlacement` 그대로.
- 본문 글, 작가·다듬기 프롬프트, 별표 빈도는 바꾸지 않는다.
- 말 기준 크기: 글자 = 그림 폭의 **3.5%**(`SFX_RATIO = 0.035`), 줄 높이 1.2배, 글꼴은 본문과 같은 `MemomentKkukkukk`. 여백: 좌우 **3%**, 위·아래 **4%**, 접히는 선에서 **2%**, 글 덩어리와 `GAP`(그림 폭 2%). 밀기 반지름 그림 폭의 **15%**. 격자는 기존 `GRID`(8px).
- `x`, `y`는 말의 **가운데**, 그림 폭·높이 대비 %(소수 한 자리). 색은 `text_color`처럼 바탕 밝기로(`dark` | `light`), AI가 고르지 않는다.
- 소리 주인이 그림에 없으면 반응하는 인물 옆. `null`은 코드가 놓을 곳을 못 찾았을 때, 별표 말이 없을 때, 그림이 없거나 실패했을 때, AI 답이 없거나 이상할 때만.
- 별표 말이 둘 이상이면 첫 번째만. 로그에는 쪽 번호와 개수만. 글·말·`owner`(아이 이름일 수 있음)는 로그에 남기지 않는다.
- 결과 API 쪽 키 `sound_word`: `{"text", "x", "y", "color"}` 또는 `null`(`owner`는 내리지 않는다). Spring 응답 필드 `soundWord`: `{text, x, y, color: "DARK" | "LIGHT"}` 또는 `null`. Spring 칸 `story_pages.sound_word jsonb NULL`(`V16__page_sound_word.sql`).
- 진짜 모델 호출은 비용을 말하고 사용자에게 물은 뒤에만. 결과는 전문(그림 전부)을 보여 주고 품질 판단은 사용자 몫.
- AI 저장소 커밋 전 `LANGSMITH_TRACING=false OPENAI_API_KEY=가짜값 uv run python evals/layout_run.py`, `evals/mock_run.py`, `evals/api_run.py` 통과. 프롬프트(`.md`)와 코드는 커밋을 나눈다. 백엔드는 `sh ./gradlew build`가 통과한 뒤 `git commit`(파이프 금지).
- PR 제목 `<타입>(scope): 설명`, 본문 `Closes #N`, 합치기 `gh pr merge --merge --delete-branch`. 합치면 EC2에 자동 배포되므로 **Spring PR을 먼저** 합친다. 프론트 코드는 건드리지 않는다.

## Review Focus

1. **덩어리를 합쳐 다시 묻거나 글 자리 때문에 다시 그린 쪽**에서는 말 자리가 마지막 그림에 대한 마지막 답에서 와야 한다. 다시 그린 뒤 새 그림으로 답을 못 받았으면 처음 그림의 자리를 쓰지 말고 `null`이어야 한다. → Task 3 `redraw drops stale word spot`
2. **AI 답의 말 자리가 글 덩어리 위나 접히는 선 위**에 있으면, 밀려나서 덩어리와 2% 이상 떨어지고 선에서 2% 이상 떨어져야 한다. 반지름 15% 안에 그런 곳이 없으면 `null`이어야 한다. → Task 1 `settle_word pushes off block / fold`, `settle_word gives up`
3. **AI가 픽셀로 답하거나 NaN·음수**를 주면 `_sanitize_spots`처럼 %로 바꾸거나 `null`이어야 한다. 생성이 실패하면 안 된다. → Task 1 `word spot sanitize`
4. **옛 AI 결과(`sound_word` 키 없음)와 이상한 값**(빈 말, 0~100 밖, 색이 다른 값)을 받아도 Spring이 버전을 저장해야 한다. 그 쪽만 `soundWord: null`이어야 한다. → Task 5 `옛_AI_결과에_sound_word가_없어도_읽는다`, `PageSoundWordTest`
5. **글만 다시 만들어 그림은 그대로인 쪽**(relayout)도 새 글의 별표 말로 자리를 다시 찾아야 한다. 아무것도 다시 하지 않은 쪽은 이전 `sound_word`를 그대로 가져야 한다. → Task 3 `relayout re-places word`, `untouched page keeps word`

---

## 파일 지도

AI_worker (브랜치 `feat/sound-word`, 이미 있음. 설계 커밋 `18390ef`)
- `src/firstory/schemas.py` — `WordSpot`, `TextPlacementWithWord`, `SoundWord`, `PageImage.sound_word`
- `src/firstory/prompts/text_place_word.md` — 새 의성어 단락
- `src/firstory/nodes/layout.py` — 말 꺼내기·크기·묻기·검사(`sound_words`, `short_look`, `SfxAsk`, `word_size`, `place_page`, `settle_word`)
- `src/firstory/nodes/illustrate.py` — `_arrange`, `work`, `relayout`
- `src/firstory/server.py` — 결과 `sound_word`
- `src/firstory/mock.py` — `TextPlacementWithWord` 답, 다듬기 mock 글에 별표 말
- `evals/layout_run.py`, `evals/mock_run.py`, `evals/api_run.py`, 새 `evals/sound_word_lab.py`

Backend_Mainpage (브랜치 `feat/sound-word`, main에서)
- `src/main/resources/db/migration/V16__page_sound_word.sql`
- `domain/generation/entity/PageSoundWord.java`(새), `StoryPage.java`
- `global/ai/AiGenerationResult.java`, `HttpAiClient.java`, `FakeAiClient.java`
- `domain/generation/service/GenerationResultRecorder.java`, `dto/PreviewResponse.java`, `domain/reading/dto/BookResponse.java`
- 문서 `docs/FIRSTORY-AI-API-SPEC-v0.3.md`, `docs/frontend/screens.md`, `docs/frontend/fake-ai.md`

---

### Task 1: AI — 말 꺼내기, 묻기, 검사 (순수 함수 + 프롬프트)

**Files:**
- Modify: `src/firstory/schemas.py` (`BlockSpot`·`TextPlacement` 옆, 336~345줄; `PageImage` 347줄)
- Create: `src/firstory/prompts/text_place_word.md`
- Modify: `src/firstory/nodes/layout.py` (상수 23~42줄, `_sanitize_spots`·`place_page` 395~442줄, 새 함수는 `text_color` 뒤)
- Modify: `src/firstory/mock.py:63` 근처, `src/firstory/nodes/illustrate.py` (`fit()` 한 줄)
- Test: `evals/layout_run.py` (자리 찾기 호출 절 280줄 근처, 끝에 새 절 `# ── 의성어 ──`)

**Interfaces:**
- Produces (schemas):
  - `class WordSpot(BaseModel): owner: str; x: float; y: float` — `owner` 설명 "이 소리·움직임을 내는(그림에 없으면 반응하는) 인물·물건 이름", x·y 설명 "말 가운데, 그림 폭/높이 대비 %(0~100)"
  - `class TextPlacementWithWord(TextPlacement): sound_word: WordSpot` (필수 칸)
  - `class SoundWord(BaseModel): text: str; x: float; y: float; color: Literal["dark", "light"]; owner: Optional[str] = None`
  - `PageImage.sound_word: Optional[SoundWord] = None`
- Produces (layout):
  - `SFX_RATIO = 0.035`, `SFX_LINE_H = 1.2`, `SFX_EDGE_X, SFX_EDGE_Y, SFX_FOLD = 3, 4, 2`, `SFX_RADIUS = 0.15`
  - `sound_words(text: str) -> list[str]` — `**…**` 안의 말을 나온 순서대로, 별표 없이, 앞뒤 공백 없이
  - `short_look(visual_description: str) -> str` — 첫 문장(`. ` 앞)만, 120자 넘으면 120자에서 자름
  - `@dataclass class SfxAsk: word: str; text: str; cast: list[tuple[str, str]]` (이름, `short_look`)
  - `word_size(word: str) -> tuple[float, float]` — px. 가로 = `text_width(word) * SFX_RATIO / FONT_RATIO`, 세로 = `W * SFX_RATIO * SFX_LINE_H`
  - `place_page(image: bytes, blocks: list[Block], sfx: Optional[SfxAsk] = None) -> tuple[list[dict], Optional[dict], list[CostEntry]]` — 둘째 값은 `{"x": %, "y": %, "owner": str}` 또는 None. `sfx`가 None이면 첫째·셋째 값과 호출이 지금과 같고 둘째는 None
  - `settle_word(busy: Busy, word: str, spot: Optional[dict], blocks: list[TextBlock]) -> Optional[SoundWord]`

- [ ] **Step 1: 실패하는 테스트를 `evals/layout_run.py`에 쓴다**

```python
# ── 의성어 ──
assert sound_words("미루가 **훌쩍훌쩍** 울었어요.") == ["훌쩍훌쩍"]
assert sound_words("**톡** 치고 **냠냠**") == ["톡", "냠냠"]
assert sound_words("별표 없음.") == []
assert short_look("A small white rabbit with long ears. Wears a yellow apron.") == "A small white rabbit with long ears"
assert len(short_look("x" * 300)) == 120
ww, wh = word_size("훌쩍")
assert abs(ww - text_width("훌쩍") * 0.035 / 0.015) < 1e-6 and abs(wh - W * 0.035 * 1.2) < 1e-6

# place_page: 별표 없는 쪽은 지금 호출 그대로 (Global Constraints 1)
calls.clear()
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")])))
spots, wspot, costs = place_page(img, [blk_a])
assert wspot is None and calls[0]["schema"] is TextPlacement and "의성어" not in calls[0]["system"]
sys0, user0 = calls[0]["system"], calls[0]["user"]

# 별표 있는 쪽: 의성어 단락 + 의성어 스키마
ask = SfxAsk(word="훌쩍훌쩍", text="미루가 **훌쩍훌쩍** 울었어요.", cast=[("미루", "A small white rabbit")])
calls.clear()
llm.set_structured_override(fake_with(TextPlacementWithWord(blocks=[BlockSpot(x=6, y=8, color="dark")],
                                                            sound_word=WordSpot(owner="미루", x=62.5, y=31))))
spots, wspot, costs = place_page(img, [blk_a], ask)
assert wspot == {"x": 62.5, "y": 31.0, "owner": "미루"}
assert calls[0]["schema"] is TextPlacementWithWord
assert all(s in calls[0]["system"] for s in ("훌쩍훌쩍", "미루", "A small white rabbit")) and "{{" not in calls[0]["system"]
assert calls[0]["system"].startswith(sys0) and calls[0]["user"].startswith(user0)   # 지금 지시 뒤에 붙일 뿐

# word spot sanitize: 픽셀 → %, NaN·음수 → None
def wplaced(x, y):
    llm.set_structured_override(fake_with(TextPlacementWithWord.model_construct(
        blocks=[BlockSpot(x=6, y=8, color="dark")], sound_word=WordSpot.model_construct(owner="미루", x=x, y=y))))
    return place_page(img, [blk_a], ask)[1]
assert wplaced(1200, 300) == {"x": 1200 / W * 100, "y": 300 / H * 100, "owner": "미루"}
assert wplaced(float("nan"), 30) is None and wplaced(-5, 30) is None
llm.set_structured_override(fake_with(RuntimeError("boom")))
assert place_page(img, [blk_a], ask)[:2] == ([], None)

# settle_word (흰 바탕 그림 `png(stripes(None))`, 덩어리 하나는 왼쪽 위)
white = Busy(png(stripes(None)))
tb = [TextBlock(paragraphs=blk_a, x=5.0, y=7.0, color="dark")]
ok = settle_word(white, "훌쩍훌쩍", {"x": 75.0, "y": 40.0, "owner": "미루"}, tb)
assert ok == SoundWord(text="훌쩍훌쩍", x=75.0, y=40.0, color="dark", owner="미루")   # 조건을 지키면 그대로, 흰 바탕 → dark
# settle_word pushes off block: 덩어리 위에 놓인 말은 밀려나 2% 이상 떨어진다
on_block = settle_word(white, "훌쩍훌쩍", {"x": 10.0, "y": 9.0, "owner": "미루"}, tb)
assert on_block is not None and word_box_gap_ok(on_block, tb)   # 테스트 도우미: 말 상자와 덩어리 상자 간격 ≥ W*GAP
# settle_word pushes off fold: 접히는 선 위의 말은 선에서 2% 이상
on_fold = settle_word(white, "훌쩍훌쩍", {"x": 50.0, "y": 40.0, "owner": "미루"}, [])
ww, _ = word_size("훌쩍훌쩍")
assert on_fold is not None and (on_fold.x / 100 * W + ww / 2 <= W * 0.48 + 1 or on_fold.x / 100 * W - ww / 2 >= W * 0.52 - 1)
# settle_word gives up: 반지름 15% 안이 모두 덩어리면 None
wall = [TextBlock(paragraphs=[["가" * 12]] * 14, x=5.0, y=7.0, color="dark")]   # 왼쪽 면을 거의 덮는 덩어리
assert settle_word(white, "훌쩍훌쩍", {"x": 20.0, "y": 40.0, "owner": "미루"}, wall) is None
assert settle_word(white, "훌쩍훌쩍", None, tb) is None
# 어두운 바탕 → light (stripes 대신 검정 그림)
dark = Busy(png(Image.new("RGB", (W, H), (20, 20, 30))))
assert settle_word(dark, "훌쩍", {"x": 75.0, "y": 40.0, "owner": "미루"}, []).color == "light"
```

`word_box_gap_ok`는 이 절 안에 쓰는 테스트 도우미다. 말 상자(가운데±`word_size`/2)와 각 덩어리 상자(`x,y` %→px, `block_size`) 사이가 `W * GAP` 이상인지 본다. `wall`이 실제로 반지름 안을 다 덮지 않으면 덩어리 크기를 늘려 맞춘다. 단언 뜻("15% 안에 놓을 곳이 없으면 None")은 바꾸지 않는다.

- [ ] **Step 2: 실패 확인** — `LANGSMITH_TRACING=false OPENAI_API_KEY=가짜값 uv run python evals/layout_run.py` → `ImportError`(`sound_words` 등 없음).

- [ ] **Step 3: 스키마** — Interfaces대로 `schemas.py`에 더한다.

- [ ] **Step 4: 프롬프트 `text_place_word.md`** — 변수 `{{word}}`, `{{text}}`, `{{cast}}`(줄마다 `- 이름: 외형`), `{{size}}`(`가로 약 n%, 세로 약 m%`). 담을 것:
  - 이 쪽 본문에 의성어·의태어 "{{word}}"가 있고, 그림 위에 크게 띄울 자리를 함께 찾는다.
  - 그 소리·움직임을 내는 인물(또는 물건) 바로 옆(머리 위나 옆 빈 곳)에 둔다.
  - 그 주인이 그림에 없으면(화면 밖 소리, 장면 전체의 소리) 그 소리를 듣거나 반응하는 인물 옆에 둔다. 비워 두지 않는다.
  - 얼굴·눈·손을 덮지 않는다. 위에서 정한 글 덩어리 자리와 겹치지 않는다. 접히는 선(x=50%)을 넘지 않는다.
  - 답: `sound_word`에 `owner`(이름), `x`, `y` = 말의 **가운데**, % 단위.
  - 본문과 인물 목록 아래에 붙인다.

  `text_place.md`는 고치지 않는다.

- [ ] **Step 5: `layout.py`**
  - 상수, `sound_words`(정규식 `\*\*(.+?)\*\*`, `render._SFX`와 같은 것), `short_look`, `SfxAsk`, `word_size`를 더한다.
  - `place_page`에 `sfx`를 더한다. `sfx`가 있으면 system = 지금 system + `"\n\n"` + `prompt("text_place_word", word=…, text=…, cast=…, size=…)`, user = 지금 문장 + `" 의성어 자리도 답하세요."`, schema = `TextPlacementWithWord`. 덩어리 답은 지금처럼 `_sanitize_spots`로 정리한다.
  - 말 답은 새 `_sanitize_word(spot) -> Optional[dict]`로 정리한다. 숫자가 아니거나 유한하지 않거나 음수면 None. 100을 넘는 값은 축마다 `W`·`H`로 나눠 %로 바꾼다.
  - 반환을 3개로 바꾼다. `evals/layout_run.py`의 기존 `place_page` 호출(280줄, `placed()` 도우미)도 `[0]`·언팩으로 맞춘다. `illustrate._arrange`의 `fit()`도 `spots, _, pcosts = place_page(img, bl)`로 맞춘다. 연결은 Task 3에서 하고, 여기서는 생성 흐름이 지금처럼 돌게만 한다.
  - `settle_word`:
    - 말 상자 = 가운데 ± `word_size/2`.
    - 조건: 상자가 좌우 `SFX_EDGE_X`%·위아래 `SFX_EDGE_Y`% 안에 들고, 상자가 `[W/2 - SFX_FOLD%, W/2 + SFX_FOLD%]`와 겹치지 않고, 모든 덩어리 상자(`block_size(b.paragraphs)`)와 `W*GAP` 이상 떨어진다.
    - AI 자리가 조건을 지키면 그대로 쓴다. 아니면 AI 자리를 중심으로 반지름 `W*SFX_RADIUS` 안의 `GRID` 격자점 중 조건을 지키고 가장 가까운 점을 쓴다. 없으면 None.
    - 색은 `text_color(busy, 상자)`.
    - x·y는 `round(…, 1)`.
- [ ] **Step 6: `mock.py`** — `schema is TextPlacementWithWord`를 `TextPlacement` 분기보다 **먼저** 본다. 덩어리는 같은 규칙으로 만들고, `sound_word=WordSpot(owner="mock", x=75, y=40)`을 더한다.
- [ ] **Step 7: 통과 확인** — `evals/layout_run.py` 통과, `evals/mock_run.py`·`evals/api_run.py` 통과(아직 연결 전이라 그대로여야 한다).
- [ ] **Step 8: 커밋** — 프롬프트와 코드를 나눈다.

```bash
git add src/firstory/prompts/text_place_word.md && git commit -m "prompt: 의성어 자리 찾기 단락 (#92)"
git add src/firstory/schemas.py src/firstory/nodes/layout.py src/firstory/nodes/illustrate.py src/firstory/mock.py evals/layout_run.py && git commit -m "feat: 의성어 말 꺼내기·자리 묻기·검사 함수 (#92)"
```

### Task 2: 작은 실험 (관문) — 사용자 확인 전 Task 3 금지

**Files:**
- Create: `evals/sound_word_lab.py`

**Interfaces:**
- Consumes: Task 1의 `sound_words`, `short_look`, `SfxAsk`, `place_page`, `settle_word`, `Busy`, `settle`, `build_blocks`/기존 덩어리, `TextBlock`

- [ ] **Step 1: 스크립트** — `uv run python evals/sound_word_lab.py [--grid] <입력>...`. 입력은 둘이다.
  - 실행 폴더 `out/20261114-195743_donggeul`(`03-story.json`, `05-illustrations.json`의 `text_blocks`, 쪽 그림, 인물 시트 설명)
  - 샘플 `~/Desktop/FIRSTORY/노란접시가좋았어_에셋`(`story.json`, `pages/page-NN/page-NN.webp`; 인물은 스크립트에 `미루: small white rabbit, protagonist`, `가온 선생님: big brown bear teacher`로 적는다. 덩어리는 `_chunk`와 같은 방법 대신 한 덩어리 `build_blocks(split_lines→wrap_line)`로)
  - 별표 말이 있는 쪽만 진짜 `place_page(img, blocks, ask)`를 부른다(덩어리는 기존 `text_blocks`의 문단을 그대로). 그다음 `settle(busy, blocks, spots)`로 새 글 자리를, `settle_word`로 말 자리를 낸다.
  - `out/sound-word-lab-1115.html` 한 장에 쪽마다 두 칸을 둔다. **왼쪽**은 기존 `text_blocks` 자리, **오른쪽**은 새 글 자리 + 말이다. 말은 3.5cqw 굵게, AI 원래 점은 작은 빨간 점, 밀린 뒤 자리는 말 자체로 그린다. `owner`, 비용, 시간을 쪽마다 적는다.
  - `--grid`면 자리 찾기 그림에 10% 눈금(반투명 선 + 숫자)을 그려서 보낸다. 같은 화면에 "눈금" 표시를 단다.
- [ ] **Step 2: 비용 묻기** — 사용자에게 "별표 말 있는 쪽 약 10쪽, 한 쪽 약 $0.003, 합계 약 50원"을 말하고 허락을 받는다.
- [ ] **Step 3: 실행** — `LANGSMITH_TRACING=false uv run python evals/sound_word_lab.py out/20261114-195743_donggeul ~/Desktop/FIRSTORY/노란접시가좋았어_에셋`. 끝나면 HTML을 미리보기로 열어 **모든 쪽**을 보여 준다. 판단은 사용자가 한다.
- [ ] **Step 4: 갈림길**(사용자 답에 따라)
  - **좋음** → 커밋(`test: 의성어 자리 실험 스크립트 (#92)`), Task 3.
  - **말 자리가 어긋남** → 비용을 다시 말하고 `--grid`로 같은 쪽을 한 번 더 돌린다. 나으면 Task 3 Step 3b(눈금)를 넣는다.
  - **글 자리가 눈에 띄게 나빠짐** → Task 3에서 의성어만 묻는 호출을 따로 둔다(Step 3c). 실험 스크립트에 `--separate`를 더해 같은 쪽으로 확인한다.
  - 결과와 사용자 선택을 이슈 #92에 댓글로 남긴다.

### Task 3: AI — 생성 흐름에 연결

**Files:**
- Modify: `src/firstory/nodes/illustrate.py` (`_arrange` 313~357줄, `work` 425~457줄, `relayout` 461~473줄)
- Modify: `src/firstory/server.py:379-420` (`_text_blocks` 옆)
- Modify: `src/firstory/mock.py:83` (다듬기 mock 글)
- Test: `evals/mock_run.py`, `evals/api_run.py`

**Interfaces:**
- Consumes: Task 1 전부.
- Produces: `_arrange(order, image, blocks, costs, redraw=None, sfx: Optional[SfxAsk] = None) -> tuple[list[TextBlock], Optional[SoundWord]]`; 결과 쪽 키 `sound_word`.

- [ ] **Step 1: 실패하는 테스트**
  - `mock.py` 다듬기 mock 글을 홀수 쪽만 `f"{i}쪽. 포포는 **깡충** 뛰었어요."`로 바꾼다(짝수 쪽은 그대로). 이 때문에 깨지는 기존 글 비교 단언은 별표를 포함하도록 고친다.
  - `evals/mock_run.py`에 단언을 더한다.
    - 첫 생성: 홀수 쪽 `sound_word.text == "깡충"`, `0 <= x, y <= 100`, `color in ("dark","light")`. 짝수 쪽은 `sound_word is None`.
    - 짝수 쪽 `layout:place` 호출의 schema가 `TextPlacement`이고, 홀수 쪽은 `TextPlacementWithWord`인지 본다(override 기록).
    - `untouched page keeps word`: 그림만 다시(1쪽만) 뒤 3쪽 `sound_word`가 이전과 같다.
    - `relayout re-places word`: 글 다시 만들기로 2쪽(짝수) 글에 `**쿵**`이 생기면, 그림은 이전 key 그대로이고 `sound_word.text == "쿵"`이다. StoryRevision mock을 그 시험에서만 덮어쓴다.
    - `redraw drops stale word spot`: `_arrange`를 직접 부른다. 첫 그림 자리 찾기는 실패하도록(덩어리가 모두 기준을 넘는 줄무늬 그림), `redraw`는 다른 그림을 돌려주게 한다. 새 그림 호출은 예외를 내도록 override한다. 결과 말이 `None`이어야 한다.
  - `evals/api_run.py`: 쪽 키에 `sound_word`를 더한다. 값이 None이거나 `set == {"text","x","y","color"}`인지(owner 없음) 본다.
- [ ] **Step 2: 실패 확인** — `evals/mock_run.py` → `KeyError`/단언 실패.
- [ ] **Step 3: 구현**
  - `_arrange`: `fit()`이 `place_page(img, bl, sfx)`의 말 답을 `last_word = (그 그림의 Busy, spot)`으로 기억한다. 합쳐 다시 물으면 덮어쓴다. `redraw`로 그림이 바뀌면 `fit` 전에 `last_word = None`으로 한다.
  - 글 자리가 최종으로 정해진 뒤(기본 자리 포함) `sfx`가 있고 `cur`가 있으며 `last_word`가 `cur`의 것일 때만 `settle_word(cur, sfx.word, spot, 최종 TextBlock들)`을 부른다. 아니면 None. 말 단계의 예외는 잡아서 None과 경고 로그(쪽 번호와 예외 이름만)를 남긴다.
  - `work`, `relayout`: `words = sound_words(p.text)`. 둘 이상이면 `log.warning("쪽 %d: 의성어 %d개 → 첫 번째만", order, len(words))`. 있으면 `SfxAsk(words[0], p.text, [(c.name, short_look(c.visual_description)) for c in chars])`를 만든다. `relayout`은 `p.characters_in_scene`으로 `chars`를 같은 방식(없으면 주인공)으로 만든다. 결과를 `PageImage(..., sound_word=sw)` / `model_copy(update={"text_blocks": tbs, "sound_word": sw})`에 넣는다.
  - `server.py`: `"sound_word": _sound_word(images.get(p.order))` → `{"text","x","y","color"}` 또는 None.
  - **3b(Task 2에서 눈금을 고른 경우만)**: `place_page`가 `sfx`가 있을 때만 그림에 Task 2와 같은 눈금을 그려 보낸다(`_with_grid(image) -> bytes`). 별표 없는 쪽 그림은 그대로 보낸다.
  - **3c(Task 2에서 따로 묻기를 고른 경우만)**: `place_page`는 `sfx` 없이 지금 그대로 둔다. 새 `place_word(image, sfx, blocks: list[TextBlock]) -> tuple[Optional[dict], list[CostEntry]]`를 만들어, 최종 글 자리를 프롬프트에 알려 주고 부른다(node `layout:word:page{n}`).
- [ ] **Step 4: 통과 확인** — `layout_run.py`, `mock_run.py`, `api_run.py` 모두 통과.
- [ ] **Step 5: 커밋** — `feat: 의성어 자리를 쪽 결과 sound_word로 (#92)`.

### Task 4: AI — 문서와 PR (합치기는 Task 6 뒤)

- [ ] **Step 1:** `docs/FIRSTORY-AI-API-SPEC-v0.3.md`는 untracked 사본이다. AI 저장소에서 결과 형식을 적는 곳(`ARCHITECTURE.md` 또는 `README.md`의 결과 키 표, `text_blocks`가 적힌 곳)에 `sound_word`를 더한다. 커밋 `docs: 결과 sound_word (#92)`.
- [ ] **Step 2:** 푸시하고 PR을 연다. 제목 `feat: 의성어·의태어를 인물 옆에 띄울 자리 (sound_word)`, 본문 `Closes #92`, 실험 HTML 결과 요약과 사용자 선택을 담는다. **Spring PR(Task 6)이 합쳐질 때까지 합치지 않는다.**

### Task 5: Spring — 저장과 응답

**Files:**
- Create: `src/main/resources/db/migration/V16__page_sound_word.sql`, `src/main/java/com/firstory/domain/generation/entity/PageSoundWord.java`, `src/test/java/com/firstory/domain/generation/entity/PageSoundWordTest.java`
- Modify: `StoryPage.java`, `AiGenerationResult.java:38-41`, `HttpAiClient.java:385-472`, `GenerationResultRecorder.java:145`, `PreviewResponse.java:37-42`, `BookResponse.java:31-`, `FakeAiClient.java`
- Test: `PageSoundWordTest`, `HttpAiClientTest`, `GenerationIntegrationTest`, `ReadingIntegrationTest`, `FlywayMigrationTest`, `FakeAiClientTest`

**Interfaces:**
- Produces: `public record PageSoundWord(String text, double x, double y, TextColor color)`, `static PageSoundWord validated(PageSoundWord raw)`(빈 말·공백, x·y 0~100 밖·NaN, 색 null → null). `toString`에 말을 넣지 않는다(`PageTextBlock`처럼). `StoryPage.soundWord`(jsonb, `copyTo`에 포함). 응답 필드 `soundWord`.

- [ ] **Step 1: 실패하는 테스트**
  - `PageSoundWordTest`: `정상_값은_그대로_통과한다`, `경계값_0과_100도_통과한다`, `빈_말이나_공백이면_null`, `좌표가_0에서_100_밖이거나_NaN이면_null`, `색이_없으면_null`, `toString에_말이_없다`.
  - `HttpAiClientTest`:
    - `sound_word를_읽는다` — `{"text":"훌쩍훌쩍","x":62.5,"y":31.0,"color":"dark"}` → `PageSoundWord("훌쩍훌쩍",62.5,31.0,DARK)`
    - `옛_AI_결과에_sound_word가_없어도_읽는다` → null
    - `sound_word_색이_다른_값이면_그_쪽만_null`
  - `FlywayMigrationTest`: `story_pages.sound_word`가 있고, null 가능이고, `jsonb`인지 본다(`text_blocks` 단언과 같은 모양).
  - `GenerationIntegrationTest`·`ReadingIntegrationTest`: 미리보기·`/book` 쪽마다 `soundWord`가 FakeAi 고정값이거나 null이다. 그림만 다시 만든 새 버전에서도 안 바뀐 쪽의 `soundWord`가 복사된다.
- [ ] **Step 2: 실패 확인** — `sh ./gradlew test` → 컴파일 실패.
- [ ] **Step 3: 구현**
  - V16: `-- V16: 쪽의 의성어·의태어를 그림 위 어디에 띄울지 AI가 정한 자리(sound_word, {text, x, y, color}). 옛 쪽·별표 말 없는 쪽은 null.` + `ALTER TABLE story_pages ADD COLUMN sound_word jsonb;`
  - `StoryPage`는 `textBlocks`와 같은 방식으로 한다(`@JdbcTypeCode(SqlTypes.JSON)`, 생성자·`create`·`copyTo`). `create` 호출부를 모두 맞춘다.
  - `HttpAiClient`의 `PageBody`에 `@JsonProperty("sound_word") JsonNode soundWord`를 더한다. `soundWord(threadId, page)`는 형식이 어긋나면 `log.warn("sound_word 형식이 맞지 않아 뺐어요: thread_id={}, page_no={}", …)` 후 null이다.
  - `AiGenerationResult` 쪽 record에 `PageSoundWord soundWord`, `GenerationResultRecorder`가 `StoryPage.create(…, soundWord)`로 넘긴다.
  - `PreviewResponse`·`BookResponse` 쪽 record에 `@Schema(example = SOUND_WORD_EXAMPLE) PageSoundWord soundWord`를 더한다. javadoc은 "의성어·의태어 자리. 말 가운데 x·y %. 옛 동화·별표 말 없는 쪽·그림 실패 쪽은 null". 색은 기존 `TextColor`대로 `DARK|LIGHT`로 직렬화된다.
  - `FakeAiClient`: 홀수 쪽에 `new PageSoundWord("깡충", 75.0, 40.0, TextColor.DARK)`, 짝수 쪽은 null. 이 고정값이 샘플 글에 실제 별표 말로 없으면 `FakeAiClient`의 홀수 쪽 글에도 `**깡충**`을 넣는다. test 프로필 기본 흐름(쪽 수·상태)은 바꾸지 않는다.
  - 문서 3곳에 `textBlocks` 설명 옆으로 `soundWord`를 더한다. 프론트용 `screens.md`에는 "`left:x%; top:y%; transform:translate(-50%,-50%)`, 글자 크기 약 3.5cqw(±20%), 본문 굵게는 그대로, null이면 안 띄움"을 적는다.
- [ ] **Step 4: 통과 확인** — `sh ./gradlew build` 성공.
- [ ] **Step 5: 커밋** — `feat(story): 쪽마다 의성어 자리 soundWord 저장하고 응답에 (#69)`.

### Task 6: 배포 순서대로 합치기와 정리

- [ ] **Step 1:** Spring 브랜치를 푸시하고 PR을 연다. 제목 `feat(story): 쪽마다 의성어 자리(soundWord) 저장하고 내려주기`, 본문 `Closes #69`. 검사가 통과하면 `gh pr merge --merge --delete-branch`로 합치고 EC2 배포 성공(health 200)을 확인한다.
- [ ] **Step 2:** 그다음 AI PR(Task 4)이 검사를 통과하면 합치고 배포를 확인한다.
- [ ] **Step 3:** 진짜 모델 한 편 확인(약 800~900원)은 사용자에게 묻고, 허락하면 한 편을 만들어 모든 쪽 화면을 보여 준다.
- [ ] **Step 4:** 프론트 이슈를 만들지 사용자에게 묻는다. 만들게 되면 Task 5 `screens.md`의 그리는 방법을 그대로 옮긴다.
- [ ] **Step 5:** `~/Desktop/FIRSTORY/NEXT-STEPS.md`에 결과를 적는다. 남은 것은 ERD에 `story_pages.sound_word` 칸 추가(저장소 밖, 사용자·팀원), 팀원에게 배포 알리기, 프론트 붙이기다.
