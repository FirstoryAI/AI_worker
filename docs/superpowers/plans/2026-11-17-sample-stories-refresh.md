# 홈 샘플 동화 8편 의성어·글 배치 최신화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 샘플 동화 8편(80쪽)의 `textBlocks`·`soundWord`를 지금 파이프라인 기준으로 다시 잡고, 사용자가 고른 쪽만 다시 그려 지금 폴더 양식으로 넘긴다.

**Architecture:** 먼저 파이프라인에 AI#113(조용한 자리면 다시 그리지 않기)을 넣는다. 그다음 `evals/sample_refresh.py` 하나가 세 단계를 맡는다: `place`(80쪽 자리 찾기 + 미리보기), `redraw`(고른 쪽만 그림 수정 + 다시 배치), `export`(최종 폴더). 단계 사이 결과는 `out/sample-refresh-1117/result.json`에 둔다.

**Tech Stack:** Python 3 / uv, `firstory.nodes.layout`·`illustrate`, OpenAI(gpt-5.4-mini 자리 찾기, gpt-image-2.5-flare 그림 수정), Pillow.

**Spec:** `docs/superpowers/specs/2026-11-17-sample-stories-refresh-design.md`

## Global Constraints

- 원본 `~/Desktop/FIRSTORY/샘플동화/`는 export 전까지 건드리지 않는다. export 때 먼저 `~/Desktop/FIRSTORY/샘플동화-1106/`으로 통째로 복사한다(이미 있으면 덮지 않음)
- 바뀌는 것은 쪽의 `textBlocks`·`soundWord`, 그리고 다시 그린 쪽의 `page-NN.webp`뿐이다. `cardId`·`cardTitle`·`title`·`cover`·`pageCount`·`text`·`image`·`textPosition`과 `cover.webp`는 그대로
- 앞·뒤표지와 대화 가이드 질문은 넣지 않는다
- 출력 모양은 Spring `BookResponse.Page`와 같게 한다: `textBlocks[{paragraphs, x, y, color: "DARK"|"LIGHT"}]`, `soundWord {text, color: "#RRGGBB", pieces[{text, x, y, side: "LEFT"|"RIGHT"|"CENTER"}]}` 또는 `null`. `owner`는 내보내지 않는다
- 글자 크기 `FONT_RATIO` 0.0235, 의성어 `PIECE_RATIO` 0.025는 layout.py 값을 그대로 쓴다(복사하지 않는다)
- `REDRAW_BUSY = 14.0`
- 비용: place 80번 약 400원(사용자 승인). redraw는 쪽 수가 정해지면 장수 × 약 40원을 사용자에게 말하고 승인받은 뒤 돌린다
- 로그·커밋·PR에 동화 글은 넣지 않는다(쪽 번호·숫자만)
- 사용자에게 하는 말은 전부 한글

## Review Focus

1. **줄 감기 되돌리기**: 옛 `paragraphs`는 1.5% 크기로 감은 줄이다. 그대로 다시 감으면 줄이 잘게 끊긴다 → 문장으로 다시 이은 뒤 감아야 한다. 강조 안에서 잘려 생긴 `a**` / `**b`를 이을 때 `****`가 남지 않아야 한다 (Task 2 `unwrap` 테스트)
2. **글 손실**: 새 `textBlocks`의 글을 이으면 옛 글과 같아야 한다(공백·`**`를 빼고 비교). 덩어리 나누기·합치기에서 줄이 사라지면 안 된다 (Task 2 `same_text` 검사, Task 4 export 검사)
3. **의성어 빠짐**: `**말**`이 있는데 `soundWord`가 null인 쪽을 미리보기와 요약 숫자에 꼭 표시한다. 조용히 null이면 안 된다 (Task 2)
4. **다시 그린 그림 크기**: 그림 수정 결과가 1920×1088이 아니면 그 쪽은 실패로 두고 옛 그림을 쓴다(자리 계산은 W·H 기준) (Task 3)
5. **보존**: export 뒤 바뀌면 안 되는 칸이 하나라도 다르면 실패한다. `샘플동화-1106`이 이미 있으면 다시 복사하지 않는다(두 번 돌려도 원본이 덮이지 않음) (Task 4)

---

### Task 1: AI#113 다시 그리기 문턱 (파이프라인, PR)

**Files:**
- Modify: `src/firstory/nodes/layout.py` (상수 줄 근처, `MAX_REDRAWS` 옆)
- Modify: `src/firstory/nodes/illustrate.py:427-436` (`_arrange`의 `if got is None and redraw:` 앞)
- Modify: `docs/superpowers/specs/2026-11-04-text-blocks-design.md` (다시 그리기 절)
- Test: `evals/mock_run.py` ("avoid characters ok" 블록 안)

**Interfaces:**
- Produces: `layout.REDRAW_BUSY: float = 14.0`. `_arrange`는 처음 그림으로 자리를 못 찾았을 때 `calmest_pick(cur, blocks, avoid)`를 먼저 보고, `_cost`가 `(0, ≤ REDRAW_BUSY)`이면 그 덩어리·자리를 쓰고 `redraw`를 부르지 않는다. 시그니처는 그대로

- [ ] **Step 1: 브랜치** — 최신 main에서 `git switch -c fix/redraw-threshold`
- [ ] **Step 2: 실패하는 테스트** — `evals/mock_run.py`에 `faint_png(diff: int) -> bytes`를 넣는다(흰 바탕에 `(255-diff,)*3` 세로 줄무늬, `striped_png`와 같은 간격). 테스트:

```python
# #113: 자리 기준(8)은 넘지만 문턱(14) 이하이고 몸 겹침이 없으면 다시 그리지 않는다
faint = faint_png(FAINT_DIFF)
assert layout.BUSY_LIMIT < layout._score(layout.Busy(faint), 100, 80, *layout.block_size(b7[0])) <= layout.REDRAW_BUSY
llm.set_structured_override(chars_seq([]))
redraws.clear()
tbs_, _ = il._arrange(1, faint, b7, [], redraw_to(white_png))
assert redraws == [] and tbs_, tbs_
# 문턱을 넘으면 지금처럼 다시 그린다
redraws.clear()
tbs_, _ = il._arrange(1, faint_png(LOUD_DIFF), b7, [], redraw_to(white_png))
assert len(redraws) == 1, redraws
```

`FAINT_DIFF`·`LOUD_DIFF`는 첫 assert(그리고 LOUD는 `> REDRAW_BUSY`)가 맞도록 고른다. 기존 "나눠도 안 들어가면 다시 그리기"(`chars_seq([(0, 15, 100, 100)])`) 테스트는 몸 겹침 때문에 그대로 다시 그려야 한다(손대지 않음).

- [ ] **Step 3: 실패 확인** — `uv run python evals/mock_run.py` → 새 assert에서 `redraws == []` 실패
- [ ] **Step 4: 구현** — `REDRAW_BUSY` 추가. `_arrange`에서 `if got is None and redraw:` 앞에 calmest 확인. 쓰면 `log.info("쪽 %d: 다시 그리지 않고 조용한 자리(복잡도 %.1f)", order, worst)`. `_cost`·`calmest_pick`은 illustrate에서 layout을 import하는 기존 방식으로 가져온다
- [ ] **Step 5: 통과 확인** — `uv run python evals/mock_run.py`와 `uv run python evals/layout_run.py` 모두 끝까지(ALL OK / 예외 없음)
- [ ] **Step 6: replay로 숫자 확인** — `uv run python evals/text_avoid_lab.py --replay text-avoid-1116b --out text-avoid-1117-113 ../샘플동화/tantrum ../샘플동화/friend` → 요약의 "다시 그리기 필요"가 15 → 9 근처(0원). 숫자를 PR 본문에 적는다
- [ ] **Step 7: 설계 문서** — text-blocks 설계의 다시 그리기 절에 문턱 한 문단. 이 계획과 샘플 설계 문서도 같은 PR에 넣는다
- [ ] **Step 8: 커밋·PR·합치기** — `fix(layout): 조용한 자리가 있으면 다시 그리지 않기`, 본문 `Closes #113` + replay 숫자. 사용자 지침대로 Claude가 합친다(EC2 자동 배포). 합친 뒤 main으로 돌아와 `git pull`

### Task 2: `sample_refresh.py place` — 80쪽 다시 배치 + 미리보기

**Files:**
- Create: `evals/sample_refresh.py`
- Create: `evals/sample_refresh_check.py` (순수 함수 assert, API 없음)

**Interfaces:**
- Consumes: Task 1의 `_arrange`(main). `layout.split_lines`, `wrap_line`, `sound_words`, `SfxAsk`, `_SENTENCE_STOP`, `illustrate._arrange`
- Produces:
  - `unwrap(para: list[str]) -> list[str]` — 감긴 줄을 문장으로 다시 잇는다. 줄이 `_SENTENCE_STOP`으로 끝나면 문장 끝. 이을 때는 공백 하나로, 이어 붙인 자리의 `** **`는 공백 하나로 바꾼다
  - `rewrap(blocks: list[list[list[str]]]) -> list[list[list[str]]]` — 문단마다 `unwrap` 뒤 `wrap_line`
  - `same_text(a_blocks, b_blocks) -> bool` — 공백·`**`를 빼고 이은 글이 같은지
  - `to_front(tbs: list[TextBlock], sw: SoundWord | None) -> tuple[list[dict], dict | None]` — 색·side 대문자, x·y 소수 1자리, `owner` 뺌
  - `result.json`: `{"cards": {cardId: {"pages": {"<pageNo>": {"textBlocks": [...], "soundWord": {...}|null, "needsRedraw": [where…]|null, "word": "말"|null, "image": "원본 경로", "redrawn": false}}}}}`
  - CLI: `uv run python evals/sample_refresh.py place [--mock] [--limit N] [--cards a,b]` → `out/sample-refresh-1117/result.json`, `index.html`

- [ ] **Step 1: 실패하는 테스트** — `evals/sample_refresh_check.py`:

```python
assert unwrap(["토끼 라니는 옷바구니", "옆에 앉아 있었어요.", "아침이에요."]) == ["토끼 라니는 옷바구니 옆에 앉아 있었어요.", "아침이에요."]
assert unwrap(["미루가 **훌쩍**", "**훌쩍** 울었어요."]) == ["미루가 **훌쩍 훌쩍** 울었어요."]   # 강조 안에서 잘린 줄
assert unwrap(['"같이 놀자."', "가온이 웃었어요."]) == ['"같이 놀자."', "가온이 웃었어요."]          # 따옴표로 끝난 문장
assert all(text_width(l) <= W * MAX_LINE or " " not in l for b in rewrap(old) for p in b for l in p)
assert same_text(old, rewrap(old))
tb, sw = to_front([TextBlock(paragraphs=[["가."]], x=10.04, y=8.0, color="dark")],
                  SoundWord(text="훌쩍훌쩍", color="#AA3300", owner="미루",
                            pieces=[SoundPiece(text="훌쩍", x=30.0, y=40.0, side="left"), SoundPiece(text="훌쩍", x=60.0, y=40.0, side="right")]))
assert tb == [{"paragraphs": [["가."]], "x": 10.0, "y": 8.0, "color": "DARK"}]
assert "owner" not in sw and [p["side"] for p in sw["pieces"]] == ["LEFT", "RIGHT"]
assert to_front([], None)[1] is None
```

(`old`는 tantrum 1쪽 `textBlocks`의 `paragraphs`를 파일에서 읽는다.) 두 번째 줄의 기대값은 원래 글이 `**훌쩍 훌쩍**`이었는지 `**훌쩍훌쩍**`이었는지 샘플에서 확인해 맞춘다. 원칙은 "원래 본문 `text`와 같게"다.

- [ ] **Step 2: 실패 확인** — `uv run python evals/sample_refresh_check.py` → ImportError
- [ ] **Step 3: 구현** — 위 함수들과 `place`. 쪽마다 `blocks = rewrap(옛 paragraphs)`, `words = sound_words(text)`, `sfx = SfxAsk(word=words[0], text=text, cast=[]) if words else None`, `il._arrange(pageNo, image_bytes, blocks, costs, redraw=lambda bl, where: wanted.append(where) or None, sfx=sfx)`. 다시 그리기를 원하면 `needsRedraw=where`, 결과는 그 뒤 calmest 자리. `same_text`가 거짓이면 예외로 멈춘다. `--mock`은 `llm.set_structured_override(mock.fake_structured)`(`FIRSTORY_MOCK`은 스크립트에서 안 먹음)
- [ ] **Step 4: 미리보기** — `index.html`. 쪽마다 옛 배치 / 새 배치를 나란히(`text_avoid_lab.py`의 CSS·`blocks_html`을 import해서 다시 씀, `font.woff2` 복사). 쪽 머리에 표시 3개: `자리 없음 → 조용한 곳`(needsRedraw), `의성어 빠짐`(word 있고 soundWord null), `의성어 있음`. 맨 위 요약: 쪽 수, 자리 없음 수, 의성어 있음/빠짐 수, 토큰. 쪽마다 체크박스 `card:page`. 고른 목록을 복사하는 버튼(텍스트 상자에 `tantrum:3,friend:7` 꼴)
- [ ] **Step 5: 확인** — `sample_refresh_check.py` 통과. `place --mock` → 80쪽, 예외 없음, 요약의 "의성어 있음+빠짐"이 40
- [ ] **Step 6: 진짜 모델 작게** — `place --cards tantrum --limit 3`(약 15원) → 미리보기 눈으로 확인
- [ ] **Step 7: 진짜 모델 전체** — `place`(80번, 약 400원). `.claude/launch.json`에 `sample-refresh`(out 폴더, 새 포트) 추가 후 열어서 확인, 사용자에게 링크와 요약 숫자
- [ ] **Step 8: 커밋** — `test: 샘플 동화 다시 배치 스크립트 (#45)` (main에 바로, evals만)

### Task 3: `sample_refresh.py redraw` — 고른 쪽만 다시 그리기

**Files:**
- Modify: `evals/sample_refresh.py`
- Modify: `evals/sample_refresh_check.py`

**Interfaces:**
- Consumes: Task 2의 `result.json`, `rewrap`, `to_front`. `illustrate._edit(prompt, refs) -> (bytes, tin, tout)`, `illustrate.layout_prompt(sizes, where)`, `layout.block_size`
- Produces:
  - `redraw_prompt(sizes: list[tuple[float, float]], where: list[str]) -> str` — "첨부한 그림책 한 쪽을 다시 그린다: 같은 장면·같은 인물(종·색·옷·생김새)·같은 화풍, 구도는 최대한 그대로" + `layout_prompt(sizes, where)`
  - CLI: `redraw --pages tantrum:3,friend:7 [--mock]` → `out/sample-refresh-1117/img/<card>-page-NN.webp`, 그 쪽 `result.json`을 새 자리로 바꾸고 `redrawn: true`, 미리보기 다시 만들기

- [ ] **Step 1: 실패하는 테스트**

```python
p = redraw_prompt([(700.0, 300.0)], ["left top"])
assert "same characters" in p and "toward the left top" in p
```

- [ ] **Step 2: 실패 확인** — `uv run python evals/sample_refresh_check.py` → NameError
- [ ] **Step 3: 구현** — 고른 쪽마다: 원본 그림을 참고로 `_edit(redraw_prompt(...), [("page.webp", 원본)])`. `where`는 result의 `needsRedraw`, 없으면(사용자가 자리 있는 쪽을 골랐으면) 덩어리 수로 `["left top", "right top"][:n]`. 결과 크기가 (1920, 1088)이 아니면 경고하고 그 쪽은 옛 그림·옛 결과 그대로. 맞으면 `_arrange(..., redraw=None, sfx)`로 다시 배치. 한 장 실패가 나머지를 막지 않는다. `--mock`은 `il.set_image_override`로 흰 1920×1088
- [ ] **Step 4: 확인** — check 통과. `redraw --mock --pages tantrum:1` → 그 쪽만 바뀌고 `redrawn: true`
- [ ] **Step 5: 사용자 확인 받기** — 사용자가 고른 쪽 수 × 약 40원을 말하고 승인받는다
- [ ] **Step 6: 진짜 모델** — 승인된 쪽만 `redraw`. 미리보기에서 옛 그림/새 그림을 비교하고, 인물 생김새가 달라진 쪽은 사용자에게 알린다(그 쪽은 옛 그림으로 되돌릴지 사용자가 정함: result에서 `redrawn`을 false로 돌리는 `--revert card:page`)
- [ ] **Step 7: 커밋** — `test: 샘플 동화 고른 쪽 다시 그리기 (#45)`

### Task 4: `sample_refresh.py export` — 최종 폴더

**Files:**
- Modify: `evals/sample_refresh.py`
- Modify: `evals/sample_refresh_check.py`

**Interfaces:**
- Consumes: `result.json`, 원본 `샘플동화/`
- Produces: `export_story(old: dict, pages: dict) -> dict`(새 story.json), `check_story(old: dict, new: dict) -> list[str]`(문제 목록, 비면 통과). CLI `export` → `샘플동화-1106/`(없을 때만 복사), `샘플동화/<card>/story.json` 다시 씀, 다시 그린 쪽 `page-NN.webp` 바꿈, `~/Desktop/FIRSTORY/샘플동화_1117.zip`

- [ ] **Step 1: 실패하는 테스트** — `check_story`:

```python
new = export_story(old, pages)
assert check_story(old, new) == []
bad = json.loads(json.dumps(new)); bad["pages"][0]["text"] += "!"
assert any("text" in m for m in check_story(old, bad))
bad = json.loads(json.dumps(new)); bad["pages"][0]["soundWord"] = {"text": "콩", "color": "red", "pieces": []}
assert check_story(old, bad)
```

`check_story`가 보는 것: 바뀌면 안 되는 칸 같음, 쪽마다 `textBlocks` 1개 이상이고 x·y 0~100, `same_text(옛, 새)`, `soundWord`는 null이거나 (색 `#RRGGBB`, 조각 1~2개, side 대문자 셋 중 하나, 조각을 이으면 `text`의 공백 뺀 것, `text`가 그 쪽 `sound_words(text)[0]`)

- [ ] **Step 2: 실패 확인** — check → NameError
- [ ] **Step 3: 구현** — `export`. `check_story`가 하나라도 문제를 내면 아무것도 쓰지 않고 멈춘다. 쓰기 순서: `샘플동화-1106` 복사(없을 때만) → story.json·그림 → zip
- [ ] **Step 4: 확인** — check 통과. `export` 뒤 `diff -rq 샘플동화-1106 샘플동화`에 story.json 8개와 다시 그린 webp만 나온다. 두 번 돌려도 `샘플동화-1106`이 그대로(수정 시각 같음)
- [ ] **Step 5: 화면 확인(사용자가 원하면)** — 프론트 저장소 `src/assets/sample-stories/`에 복사해 로컬 `StoryReader`로 2편 열어 글 잘림·의성어 위치 확인. 프론트 저장소에는 커밋하지 않고, 확인 뒤 `git checkout -- src/assets/sample-stories`로 되돌린다(프론트는 팀원 몫)
- [ ] **Step 6: 기록** — 커밋 `test: 샘플 동화 내보내기 (#45)`. `NEXT-STEPS.md`의 샘플 동화 줄 갱신(zip 위치, 다시 그린 쪽 수, 비용). Backend#45에 짧은 댓글(숫자만). 사용자에게 zip 경로를 알리고 카톡 전달을 부탁
