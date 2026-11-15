# 두 덩어리면 양쪽 면에 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 쪽 글이 2덩어리면 1번은 왼쪽 면, 2번은 오른쪽 면에 놓이게 한다.

**Architecture:** 자리 계산(`nodes/layout.py`)이 2덩어리일 때 덩어리마다 면을 고정해서 그 면 안에서만 찾는다. 그림·자리 프롬프트도 같은 면을 말한다. `_arrange`는 2덩어리일 때 합치기보다 다시 그리기를 먼저 하고, 면마다 가장 덜 복잡한 곳을 찾은 다음, 정말 놓을 곳이 없을 때만 합친다.

**Tech Stack:** Python 3, uv, Pillow·numpy. 확인은 pytest가 아니라 assert 스크립트 `evals/layout_run.py`, `evals/mock_run.py`로 한다.

**Spec:** `docs/superpowers/specs/2026-11-15-two-blocks-both-sides-design.md`

## Global Constraints

- 1덩어리 동작은 바꾸지 않는다: 자리 찾기 → 다시 그리기 → calmest → 기본 자리 순서, 면은 자유.
- 덩어리 나누기(`text_chunks.md`, `chunk_page`)는 건드리지 않는다.
- API, `TextBlock`·`text_blocks` 형식은 그대로 둔다. 프론트 변경은 없다.
- 다시 그리기 상한 `MAX_REDRAWS = 2`(실행당)는 그대로 둔다.
- 글·그림 내용은 로그에 남기지 않는다(기존 규칙).
- 작업은 `origin/main`에서 새 worktree를 만들어 한다. 메인 체크아웃 `Firstory_AI_pipeline`은 다른 세션이 `feat/sound-word`로 쓰고 있어서 브랜치를 바꾸면 안 된다.
- 이슈 먼저(형식: 문제 / 원인 / 할 일), 브랜치 `fix/two-blocks-both-sides`, PR 제목 `fix: 두 덩어리면 왼쪽·오른쪽 면에 하나씩`, 본문에 `Closes #95`.

## Review Focus

1. AI가 두 덩어리를 모두 오른쪽 면에 답한 경우 → 1번은 왼쪽 면으로 간다 (Task 1, 3-2).
2. 오른쪽 면 전체가 복잡하고 왼쪽 면만 조용한 경우 → settle은 None(반대 면으로 넘어가지 않음), calmest는 그래도 양쪽에 하나씩 둔다 (Task 1, 6-1).
3. 다시 그리기 상한을 다 쓴 2덩어리 쪽 → 합치지 않고 면마다 calmest로 둔다 (Task 2, 8-5).
4. 글을 다시 만들 때 그림은 그대로 두고 자리만 다시 하는 경로(`redraw` 없음, `illustrate.py:471`) → 2덩어리면 양쪽 calmest로 둔다 (Task 2, 8-7에서 redraw 없는 경우도 같은 분기를 지난다).
5. 1덩어리 쪽 → 지금과 똑같이 동작한다 (기존 1·2·6·7·8-8 사례가 그대로 통과).

---

### Task 1: 자리 계산이 2덩어리면 면을 고정

**Files:**
- Modify: `src/firstory/nodes/layout.py` (`_push` 248, `_search` 299, `calmest` 329, `settle` 347)
- Test: `evals/layout_run.py` (사례 3·3-2 고치기, 3-3·6-1 추가, 7-1에 면 확인 추가)

**Interfaces:**
- Produces: `side_of(i: int, n: int) -> int | None`: n == 2이면 i(0 = 왼쪽, 1 =오른쪽), 그 밖에는 None.
- Produces: `_push(x, y, bw, bh, page: int | None = None)`: page를 주면 그 면의 x 범위 안으로 민다.
- Produces: `_search(busy, near, bw, bh, placed, page: int | None = None)`: page를 주면 그 면에서만 찾는다.
- `settle(busy, blocks, spots)`, `calmest(busy, blocks)`는 시그니처를 그대로 두고 안에서 `side_of(i, len(blocks))`를 쓴다.

- [ ] **Step 0: 준비**
  기존 확인을 먼저 돌려 지금 통과하는지 본다: `uv run python evals/layout_run.py`, `uv run python evals/mock_run.py`.
  GitHub `FirstoryAI/AI_worker`에 이슈를 만든다(문제: 2덩어리가 한 면에 몰림, 11/14 「분홍 길을 그린 날」 10쪽 중 8쪽이 한 면 / 원인: 같은 면 먼저 찾기, 합치기 먼저 / 할 일: 스펙 요약).
  worktree를 만든다: `git worktree add ../Firstory_AI_pipeline-sides -b fix/two-blocks-both-sides origin/main`.
  스펙(`docs/superpowers/specs/2026-11-15-two-blocks-both-sides-design.md`)과 이 계획 파일을 메인 체크아웃에서 worktree로 옮긴다(메인에서는 추적되지 않는 파일). 그리고 `docs: 두 덩어리면 양쪽 면에 설계와 계획 (#95)`으로 커밋한다.

- [ ] **Step 1: 실패하는 확인 쓰기** (`evals/layout_run.py`. 합성 그림 `busy`는 왼쪽 위 x 5~45%, y 7~40%만 줄무늬)
  - 3) 1번 AI 자리 오른쪽 위 `(55,8)`, 2번 왼쪽 아래 `(8,70)` → `page(out[0], bw) == 0`, `page(out[1], bw2) == 1`, 둘 다 `check_one`. 기존의 `out[0] == {"x": 55.0, ...}` 확인은 지운다.
  - 3-2) `(55,8)`, `(55,12)` → 지금 간격 확인에 더해 `page(out[0], bw) == 0 and page(out[1], bw2) == 1`.
  - 3-3) 새 사례: 둘 다 왼쪽 아래 `(8,70)`, `(8,80)` → `out[0]`은 `{"x": 8.0, "y": 70.0, "color": "dark"}` 그대로, `page(out[1], bw2) == 1`.
  - 6-1) 새 사례: `right_full = Busy(png(stripes((50, 0, 100, 100))))` → `settle(right_full, [blk, blk2], [{"x":8,"y":70,...},{"x":55,"y":75,...}]) is None`. 그리고 `out = calmest(right_full, [blk, blk2])`일 때 `page(out[0], bw) == 0 and page(out[1], bw2) == 1`.
  - 7-1) `calmest(dark_bg, [blk, blk2])` 결과에 `page(out[0], bw) == 0 and page(out[1], bw2) == 1` 추가.
  - `side_of`: `side_of(0, 2) == 0`, `side_of(1, 2) == 1`, `side_of(0, 1) is None`, `side_of(2, 3) is None`.

- [ ] **Step 2: 실패 확인**
  Run: `uv run python evals/layout_run.py`
  Expected: `side_of` import에서 ImportError(또는 3)에서 AssertionError).

- [ ] **Step 3: 구현** (`src/firstory/nodes/layout.py`)
  - `side_of`를 위 Interfaces대로 만든다. 상수를 두지 말고 `n == 2`로 판단한다(3덩어리 이상은 `normalize_chunks`가 막는다).
  - `_push`: page가 주어지면 `_page(x, bw)` 대신 그 page로 `_x_range`를 쓴다.
  - `_search`: page가 주어지면 `(page,)`만 돌고, 아니면 지금처럼 같은 면 다음에 반대 면을 본다.
  - `settle`: 덩어리 i마다 `side = side_of(i, len(blocks))`를 구해 `_push(..., side)`와 `_search(..., side)`에 넘긴다.
  - `calmest`: `_best_on`의 pages를 `(side,)`로, side가 None이면 `(0, 1)`로 준다.
  - docstring에 "2덩어리면 1번 왼쪽 면, 2번 오른쪽 면에서만"을 한 줄 더한다.

- [ ] **Step 4: 통과 확인**
  Run: `uv run python evals/layout_run.py`
  Expected: `layout ok`, `calmest ok`, `stale ok`가 출력되고 끝난다.

- [ ] **Step 5: 커밋**
  `git commit -am "fix: 두 덩어리면 자리 계산을 왼쪽·오른쪽 면에 고정 (#95)"`

### Task 2: 프롬프트와 `_arrange` 순서

**Files:**
- Modify: `src/firstory/nodes/illustrate.py` (`layout_prompt` 161, `_arrange` 314)
- Modify: `src/firstory/prompts/text_place.md`
- Test: `evals/mock_run.py` (8-5·8-6·8-7)

**Interfaces:**
- Consumes: Task 1의 `side_of`, `settle`, `calmest`(2덩어리면 면 고정).
- `layout_prompt(sizes, where=None)`, `_arrange(order, image, blocks, costs, redraw=None)`의 시그니처는 그대로 둔다.

- [ ] **Step 1: 실패하는 확인 쓰기** (`evals/mock_run.py`)
  - 8-5 (`two_blocks` + `all_busy`): 다시 그리기 수 확인(`5 + MAX_REDRAWS`, `[1,1,1,2,2]`)은 그대로 둔다. 쪽마다 `len(pi.text_blocks) == 2`이어야 하고, 1번 블록은 `x < 50`인 왼쪽, 2번은 `x >= 50`인 오른쪽이어야 한다. 기대 자리는 `layout.calmest(calm_busy, [tb.paragraphs for tb in pi.text_blocks])`와 같아야 한다. `places`는 `1 not in places`(합치지 않음)이어야 한다. "합쳐진 한 덩어리" 확인은 지운다.
  - 8-6: `sizes2 = [layout.block_size(b) for b in layout.build_blocks(["가나다.", "라마바."], [[[0]], [[1]]])]`일 때 `"first one within the left half" in il.layout_prompt(sizes2)`와 `"second one within the right half" in il.layout_prompt(sizes2)`. 1덩어리 프롬프트에는 `"first one within the left half"`가 없어야 한다.
  - 8-7을 새 규칙으로 바꾼다. `settle`은 지금처럼 2덩어리면 None을 돌려주도록 흉내 낸다. 다시 그리기 프롬프트를 모은다(`sent`).
    결과: `places == [2, 2]`(처음 그림, 다시 그린 그림. 합치기 없음), `page_calls["x"] == 2`, 다시 그린 프롬프트에 `"left top"`과 `"right top"`이 둘 다 들어 있음.
    `len(m.text_blocks) == 2`이고 1번은 `x < 50`, 2번은 `x >= 50`. `lines_of(m) == joined(...)`는 그대로.

- [ ] **Step 2: 실패 확인**
  Run: `uv run python evals/mock_run.py`
  Expected: 8-5에서 AssertionError(아직 합쳐서 1덩어리).

- [ ] **Step 3: 구현**
  - `layout_prompt`: 지금 문장 `"each within the left half or the right half (not across the vertical center). "`를 `len(sizes) == 2`일 때만 아래 문장으로 바꾼다.
    `"the first one within the left half and the second one within the right half (not across the vertical center). "`
    1덩어리 문장은 그대로 둔다.
  - `_arrange`: `len(blocks) == 2`이면 첫 `fit`이 실패해도 합치지 않고 바로 `redraw(blocks, ["left top", "right top"])`를 한다.
    그다음 `calmest(cur, blocks)`를 하고, None이면 그때 `merge`해서 `calmest`를 한다.
    1덩어리 흐름(합치기 분기는 원래 `len(blocks) > 1`에서만 탐)과 `where`(`_side` 사용)는 그대로 둔다.
    docstring의 순서 설명을 고친다.
  - `prompts/text_place.md` 조건:
    - "접히는 선" 줄 다음에 이 줄을 넣는다. `- 덩어리가 2개면 1번은 왼쪽 면, 2번은 오른쪽 면에 둔다. 두 덩어리를 같은 면에 위·아래로 두지 않는다.`
    - 읽는 순서 줄을 이렇게 바꾼다. `- 위 번호 순서대로 답한다.`

- [ ] **Step 4: 통과 확인**
  Run: `uv run python evals/mock_run.py && uv run python evals/layout_run.py`
  Expected: 둘 다 끝까지 오류 없이 돈다(`layout ok` … 그리고 mock_run의 마지막 출력).

- [ ] **Step 5: 커밋**
  `git commit -am "fix: 두 덩어리면 그림·자리 프롬프트도 양쪽 면, 합치기 전에 다시 그리기 (#95)"`

### Task 3: PR과 진짜 모델 확인

- [ ] **Step 1:** 브랜치를 푸시하고 PR을 만든다. 제목 `fix: 두 덩어리면 왼쪽·오른쪽 면에 하나씩`, 본문에 바뀐 것과 영향(다시 그리기가 늘 수 있음), `Closes #95`.
- [ ] **Step 2:** 진짜 모델로 한 편(그림 10장 + 다시 그리기 최대 2장)을 만들기 전에 사용자에게 비용을 말하고 묻는다. 허락하면 돌려서 2덩어리 쪽이 모두 양쪽인지, 다시 그리기가 몇 번인지 세고, 결과는 앱처럼 보이는 HTML(`book.html`)로 보여 준다.
- [ ] **Step 3:** 확인이 끝나면 PR을 합친다(`gh pr merge --merge --delete-branch`). 그다음 worktree를 정리하고 NEXT-STEPS.md에 한 줄 적는다. EC2 배포는 main에 합치면 자동인지 확인해서 알린다.
