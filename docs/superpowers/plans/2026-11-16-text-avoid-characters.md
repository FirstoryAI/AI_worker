# 글 덩어리가 캐릭터를 가리지 않게 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 글 자리 찾기 AI 호출에서 캐릭터 칸을 받아, 글 덩어리가 그 칸(넉넉히 키운 것)에 걸치지 않게 놓고, 자리가 없으면 한 덩어리를 양쪽 면으로 나눈다.

**Architecture:** `layout:place` 답 맨 위에 `characters`를 더하고(모든 쪽, 눈금 그림), `settle`·`_search`·`_best_on`이 칸과 겹치는 자리를 버린다. `_arrange`는 합치기 다음에 코드로 한 덩어리를 둘로 나눠 양쪽 면을 찾고, 마지막 `calmest_pick`은 (겹친 넓이, 복잡도) 순으로 고른다. 의성어는 같은 맨 위 칸을 쓴다.

**Tech Stack:** Python 3, Pydantic, Pillow, numpy. 시험은 assert 스크립트 `evals/layout_run.py`, `evals/mock_run.py` (`uv run python ...`).

**Spec:** `docs/superpowers/specs/2026-11-16-text-avoid-characters-design.md`

## Global Constraints

- 결과 모양(`text_blocks`, `sound_word`)과 Spring·프론트는 바꾸지 않는다.
- AI 호출 수를 늘리지 않는다. 나누기는 AI를 다시 부르지 않는다.
- 칸은 % 단위(0~100). 픽셀로 온 칸·뒤집힌 칸은 그 칸만 버린다(`_sanitize_box` 그대로).
- `CHAR_PAD = 0.015` (캐릭터 칸을 사방으로 그림 폭의 1.5%씩 키움, 의성어에는 안 씀).
- 다시 그리기 상한 `MAX_REDRAWS = 2` 그대로.
- 로그에 글·그림 내용 남기지 않기(쪽 번호·개수만).
- 커밋 메시지 `<타입>: 설명 (#이슈)`, PR 제목 `<타입>(scope): 설명`, PR 본문 `Closes #이슈`.

## Review Focus

1. **AI가 그림 거의 전체를 칸으로 답함**(안긴 장면의 큰 칸) → 엄격한 자리는 없어도 `_arrange`는 늘 유효한 `text_blocks`를 돌려주고, 겹침이 가장 적은 곳에 둔다. → Task 5 시험
2. **다시 그린 그림에 이전 그림 칸이 남음** → 다시 그린 뒤에는 새 그림의 답 칸만 쓴다. → Task 5 시험
3. **긴 대사 한 줄이 여러 줄로 감긴 덩어리** → 따옴표 안에서 나누지 않는다(못 나누면 None). → Task 3 시험
4. **문단이 [본문 6줄] + [가이드 질문 1줄]처럼 한쪽으로 쏠림** → 문단 경계가 너무 쏠리면(큰 쪽이 전체 줄의 2/3 초과) 줄 경계에서 가운데로 나눈다(계획에서 정한 값). → Task 3 시험
5. **칸이 하나도 없는 답(mock·캐릭터 없는 장면·AI가 빈 목록)** → 자리는 복잡도만 본다. 단, 한 덩어리가 들어갈 곳이 없으면 칸이 없어도 둘로 나눈다(리뷰 뒤 판단, 다시 그리기를 아낌). → Task 2·5 시험

---

### Task 0: 이슈 만들기

- [ ] **Step 1:** AI_worker 저장소에 이슈 생성. 제목 `fix: 글 덩어리가 캐릭터를 가리지 않게 (자리 없으면 양쪽으로 나누기)`. 본문: 설계 문서 "왜 하나"·"정한 것" 요약 + 설계 경로. 번호를 이후 커밋·PR에 쓴다(아래 `#N`).
- [ ] **Step 2:** `git switch -c fix/text-avoid-characters` (main 최신에서).

### Task 1: 모든 쪽에서 캐릭터 칸 받기

**Files:**
- Modify: `src/firstory/schemas.py` (`TextPlacement`, `WordSpot`)
- Modify: `src/firstory/prompts/text_place.md`, `src/firstory/prompts/text_place_word.md`
- Modify: `src/firstory/nodes/layout.py` (`place_page`, `_sanitize_word`)
- Modify: `src/firstory/mock.py` (자리 답)
- Test: `evals/layout_run.py` ("자리 찾기 호출", "sound word" 부분)

**Interfaces:**
- Produces:
  - `TextPlacement.characters: list[CharacterBox]` (기본 빈 목록). `WordSpot`에서 `characters` 제거.
  - `Chars = list[tuple[str, tuple[float, float, float, float]]]` — (이름, % 칸 x0,y0,x1,y1)
  - `place_page(image, blocks, sfx=None, grid=True) -> tuple[list[dict], Chars, dict | None, list[CostEntry]]` — (자리, 캐릭터 칸, 의성어 답, 비용). 의성어 답 dict의 `"chars"`는 맨 위 칸과 같은 값.
  - `_sanitize_chars(chars) -> Chars`, `_sanitize_word(spot, chars: Chars) -> dict | None`

- [ ] **Step 1: 실패하는 시험 쓰기** (`evals/layout_run.py`)
  - 자리 찾기 호출: `TextPlacement(blocks=[...], characters=[CharacterBox(name="초코", box=ob(35,30,60,85))])` 답 → `place_page(img, [blk_a])` 결과 `[1] == [("초코", (35.0, 30.0, 60.0, 85.0))]`.
  - 뒤집힌 칸·0~100 밖 칸은 그 칸만 빠짐, `characters=[]`면 `[]`.
  - 기본(`grid=True`): `calls[0]["image"] != img` 이고 `"눈금" in calls[0]["system"]`, `"characters" in calls[0]["system"]`. `grid=False`면 그림 그대로.
  - 의성어 쪽: `TextPlacementWithWord(blocks=..., characters=[...], sound_word=WordSpot(owner, source_kind, source_box))` → `[2]["chars"] == [1]`.
  - 기존 시험의 `place_page(...)[0]`, `[1]` 인덱스와 `good`(WordSpot) 생성을 새 모양에 맞춘다. 의성어 준비가 터지는 경우(`with_grid` 예외)는 이제 눈금이 모든 쪽이라: 눈금 준비가 터지면 눈금 없이 원래 그림으로 묻는다(칸은 그래도 받음).
- [ ] **Step 2:** `uv run python evals/layout_run.py` → 새 assert에서 FAIL.
- [ ] **Step 3: 구현**
  - `text_place.md`: `{{grid}}` 자리와 "캐릭터 칸" 절 추가 — `text_place_word.md` 4번(모든 캐릭터, 머리·귀·팔·꼬리, 윤곽에 붙게, 안긴 캐릭터는 한 칸, 물건 든 캐릭터 포함)을 옮기고 "글이 이 칸을 피한다"는 문장. `text_place_word.md`는 1~3번만.
  - `place_page`: 눈금은 `grid`가 참이면 의성어와 상관없이 그린다(실패하면 원래 그림, 경고 로그). 스키마는 sfx 있으면 `TextPlacementWithWord`, 없으면 `TextPlacement`.
  - `mock.py`: 두 스키마 모두 `characters`를 맨 위에. 일반 쪽은 `[]`, 의성어 쪽은 지금 칸 `(58,30,74,88)`.
- [ ] **Step 4:** `uv run python evals/layout_run.py` → 끝까지 `split color ok`. `uv run python evals/mock_run.py` → `ALL OK` (이 단계에서 `_arrange`는 새 반환 모양만 풀어 쓰고 칸은 아직 안 씀).
- [ ] **Step 5:** 커밋 `feat: 글 자리 찾기 답에 캐릭터 칸을 모든 쪽에서 받기 (#N)`

### Task 2: 글이 캐릭터 칸을 피하게

**Files:**
- Modify: `src/firstory/nodes/layout.py` (`settle`, `_search`, `_best_on`, 새 함수)
- Test: `evals/layout_run.py` (settle 부분 뒤)

**Interfaces:**
- Consumes: `Chars` (Task 1)
- Produces:
  - `CHAR_PAD = 0.015`
  - `Rect = tuple[float, float, float, float]` (px x0, y0, x1, y1)
  - `blockers(chars: Chars) -> list[Rect]` — % 칸 → px, 사방 `W * CHAR_PAD`
  - `_overlap(x, y, bw, bh, avoid: list[Rect]) -> float` — 덩어리와 칸들이 겹친 넓이 합(px²)
  - `settle(busy, blocks, spots, avoid: list[Rect] = ()) -> list[dict] | None`
  - `_search(..., page=None, avoid=())`, `_best_on(..., move_cost=MOVE_COST, avoid=(), strict=True)` — strict면 겹치는 자리는 버림, 아니면 점수에 `OVERLAP_COST * _overlap(...)` 더함 (`OVERLAP_COST = 1.0`/px², 복잡도 최대값보다 늘 크게 지배)

- [ ] **Step 1: 실패하는 시험 쓰기**
  - 흰 그림 `white`, 덩어리 `blk_a`. AI 자리 (6%, 8%)에 캐릭터 칸 `("a", (4, 5, 30, 60))` → `settle(white, [blk_a], [{"x":6,"y":8,"color":"dark"}], blockers(chars))` 결과 덩어리 사각형이 `blockers` 어느 것과도 안 겹침.
  - `blockers([("a",(10,10,20,20))])[0] == (10/100*W - W*0.015, 10/100*H - W*0.015, 20/100*W + W*0.015, 20/100*H + W*0.015)`.
  - `avoid=()`면 기존 settle 시험 결과와 같다(기존 assert 그대로 통과).
  - 2덩어리: 왼쪽 면 위 띠 전체를 덮는 칸이 있으면 1번은 왼쪽 아래 띠로(면 고정 #95 유지).
- [ ] **Step 2:** `uv run python evals/layout_run.py` → FAIL.
- [ ] **Step 3: 구현** — `settle`의 `ok`에 `_overlap(...) == 0` 추가, `_search`·`_best_on`에 `avoid` 전달.
- [ ] **Step 4:** `uv run python evals/layout_run.py` → 끝까지 통과.
- [ ] **Step 5:** 커밋 `fix: 글 덩어리가 캐릭터 칸에 걸치는 자리를 버리기 (#N)`

### Task 3: 한 덩어리를 둘로 나누기

**Files:**
- Modify: `src/firstory/nodes/layout.py` (새 함수 `split_block`)
- Test: `evals/layout_run.py` (덩어리 정리 부분 뒤)

**Interfaces:**
- Produces: `split_block(block: Block) -> list[Block] | None` — 두 덩어리(읽는 순서, 문단·줄 그대로) 또는 나눌 수 없으면 None.

규칙(계획에서 정함):
1. 문단 경계 중 앞쪽 줄 수가 전체 줄 수의 절반에 가장 가까운 곳. 같으면 뒤쪽 경계(앞 덩어리가 작지 않게).
2. 그 경계에서 큰 쪽이 전체 줄의 2/3를 넘거나 문단이 하나면 → 줄 경계 중 가운데에 가장 가까운 곳(같으면 뒤쪽). 그 경계에서 끊기는 문단은 두 문단으로 갈림. 경계 앞까지 이어 붙인 글이 `_quote_open`이면 그 경계는 안 됨.
3. 줄이 하나거나 쓸 경계가 없으면 None.

- [ ] **Step 1: 실패하는 시험 쓰기**
  - `split_block([["a.","b."],["c.","d."]]) == [[["a.","b."]],[["c.","d."]]]`
  - `split_block([["a.","b.","c.","d."]]) == [[["a.","b."]],[["c.","d."]]]`
  - `split_block([["a.","b.","c."]]) == [[["a.","b."]],[["c."]]]` (같으면 뒤쪽)
  - 쏠림: `split_block([["1.","2.","3.","4.","5.","6."],["질문?"]])` → `[[["1.","2.","3.","4."]],[["5.","6."],["질문?"]]]`
  - 대사: `split_block([['"가나다', '라마바."']]) is None`, `split_block([['가.', '"나다', '라마."']]) == [[['가.']],[['"나다','라마."']]]`
  - `split_block([["한 줄."]]) is None`
  - 어떤 결과든 `merge(out) == [가른 문단들]`이고 줄 순서·글자가 그대로.
- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** `split_block` 구현.
- [ ] **Step 4:** `uv run python evals/layout_run.py` → 통과.
- [ ] **Step 5:** 커밋 `feat: 자리 없는 한 덩어리를 둘로 나누는 규칙 (#N)`

### Task 4: 마지막 안전판이 겹침을 먼저 보기

**Files:**
- Modify: `src/firstory/nodes/layout.py` (`calmest`, `_worst`, `calmest_pick`)
- Test: `evals/layout_run.py` (calmest 부분)

**Interfaces:**
- Consumes: `_best_on(..., avoid, strict=False)` (Task 2), `split_block` (Task 3)
- Produces:
  - `calmest(busy, blocks, avoid=()) -> list[dict] | None`
  - `calmest_pick(busy, blocks, avoid=()) -> tuple[list[Block], list[dict]] | None` — 후보: 받은 덩어리 그대로, 2덩어리면 합친 것, 1덩어리면 `split_block` 한 것. 점수 `(겹친 넓이 합, 가장 복잡한 자리 복잡도)`가 가장 작은 것. 같으면 지금 규칙(2덩어리는 나눈 쪽, 1덩어리는 그대로).

- [ ] **Step 1: 실패하는 시험 쓰기**
  - 어디에 두든 칸에 걸치는 흰 그림(칸이 왼쪽 면 전체 + 오른쪽 면 위 띠): `calmest_pick` 자리의 겹친 넓이가, 같은 그림에서 `avoid=()`로 고른 자리의 겹친 넓이보다 작거나 같다.
  - 1덩어리 7줄, 칸 `[("a",(0,35,50,100)), ("b",(50,40,100,100))]`, 흰 그림 → 나눈 두 덩어리가 뽑히고 겹친 넓이 0.
  - `avoid=()`면 기존 calmest 시험 그대로 통과.
- [ ] **Step 2:** FAIL 확인.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** `uv run python evals/layout_run.py` → 통과.
- [ ] **Step 5:** 커밋 `fix: 자리가 없을 때 캐릭터와 가장 적게 겹치는 곳에 두기 (#N)`

### Task 5: `_arrange`에 이어 붙이기

**Files:**
- Modify: `src/firstory/nodes/illustrate.py` (`_arrange`)
- Test: `evals/mock_run.py` ("의성어 자리" 부분 근처, 새 소절 `8-14`)

**Interfaces:**
- Consumes: Task 1~4 전부
- 순서: AI 자리 → 칸 피한 다른 자리 → (2덩어리면) 합치기 → (원래 1덩어리면) `split_block` 후 `settle(busy, parts, [], avoid)` → 다시 그리기 → 새 그림에서 위를 다시 → `calmest_pick(cur, blocks, avoid)`.
- `avoid`는 그림마다 그 그림에 대한 **첫 답**의 칸(`blockers`). 다시 그리면 비우고 새 그림 답으로. 칸이 비면 경고 로그(쪽 번호만) 후 `avoid=()`.
- 의성어: `last_word`의 칸은 그 답의 맨 위 칸(Task 1에서 이미 채움). `place_word` 그대로.

- [ ] **Step 1: 실패하는 시험 쓰기** (`evals/mock_run.py`)
  - 나누기: 흰 그림, 1덩어리 7줄(한 문단), 답 칸 `[("a",(0,35,50,100)), ("b",(50,40,100,100))]` → 7줄 덩어리는 어느 위 띠에 놓아도 칸에 닿음. `_arrange` 결과 덩어리 2개, 1번 x < 50·2번 x ≥ 50, 둘 다 `_overlap == 0`, `redraw` 호출 0회.
  - 다시 그리기로 넘어감: 칸 `("a",(0,0,100,100))`이 아닌 `("a",(0,15,100,100))`(위 띠만 조금 빔, 나눠도 안 들어감) → `redraw` 호출 1회.
  - Review Focus 1: 칸이 그림 전체 `(0,0,100,100)`, redraw도 같은 답 → 결과 덩어리 수 ≥ 1, 자리 0~100 안, 예외 없음.
  - Review Focus 2: 첫 그림 답은 칸이 오른쪽 면 전체, 다시 그린 그림 답은 칸 없음 → 다시 그린 뒤 자리는 오른쪽에 놓여도 됨(이전 칸을 안 씀).
  - Review Focus 5: 칸 `[]`면 Task 5 전 결과와 같음(기존 mock_run assert 그대로 통과).
  - 기존 `place_schemas` assert는 그대로 두되 눈금이 모든 쪽에 들어가도 통과하는지 확인.
- [ ] **Step 2:** `uv run python evals/mock_run.py` → FAIL.
- [ ] **Step 3:** `_arrange` 구현.
- [ ] **Step 4:** `uv run python evals/layout_run.py`, `uv run python evals/mock_run.py` → 둘 다 통과(`ALL OK`). `uv run python evals/api_run.py`도 mock으로 통과.
- [ ] **Step 5:** 커밋 `fix: 글 자리에서 캐릭터 칸을 피하고 자리가 없으면 양쪽으로 나누기 (#N)`

### Task 6: 진짜 그림 작은 실험 (사용자에게 비용 묻고)

**Files:**
- Create: `evals/text_avoid_lab.py` (그림 폴더들 → 쪽마다 지금 방식/새 방식 자리, 칸 그린 비교 HTML)
- 결과: `out/text-avoid-1116-*/index.html`, 미리보기 `.claude/launch.json`에 `text-avoid`(포트 8769)

- [ ] **Step 1:** 사용자에게 묻기: 예시 동화(미루·가온) 번호 + 기존 `out/` 그림 몇 쪽, 합쳐 약 15~20쪽, `gpt-5.4-mini` 이미지 호출 쪽당 1번, 약 100원 어림. 승인 전엔 돌리지 않는다.
- [ ] **Step 2:** 실행, HTML로 보여 주기. 셀 것: 칸과 겹친 쪽 수(전/후), 나눈 쪽 수, 다시 그리기가 필요했을 쪽 수, 칸이 틀리게 잡힌 쪽.
- [ ] **Step 3:** 결과로 `CHAR_PAD`·2/3 기준 조정이 필요하면 고치고 `layout_run`·`mock_run` 다시. 커밋 `test: 글 캐릭터 피하기 실험 스크립트 (#N)`

### Task 7: 마무리

- [ ] **Step 1:** 전체 브랜치 새 리뷰어 검토, 반영.
- [ ] **Step 2:** 설계·계획 문서 커밋 포함, PR 생성 — 제목 `fix(layout): 글 덩어리가 캐릭터를 가리지 않게`, 본문 `Closes #N`, 실험 결과 요약.
- [ ] **Step 3:** 합치기 전 서버 `generation_runs`에 진행 중 실행이 없는지 확인 → main 합침(EC2 자동 배포) → AI health 200 확인.
- [ ] **Step 4:** `~/Desktop/FIRSTORY/NEXT-STEPS.md`에 항목 추가(남은 것: 이미 만든 동화는 그대로, 진짜 모델 한 편).
