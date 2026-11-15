# 의성어 나눠 두기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 별표 말(의성어·의태어)을 소리 근원(얼굴·물건) 옆에 1~2조각으로, 배경과 구별되는 색으로 놓아 `sound_word`로 내린다.

**Architecture:** AI(`layout:place` 호출)는 근원 종류·근원 칸·캐릭터 몸 칸만 답한다. 코드(`nodes/layout.py`)가 말을 나누고(`split_word`), 자리를 찾고(`place_word`), 색을 고른다(`pick_color`). Spring은 새 모양을 저장·검사해 `soundWord`로 내린다.

**Tech Stack:** Python 3 · Pydantic · Pillow/numpy (AI_worker), Java 21 · Spring Boot · Jackson 3 · Hibernate JSON (Backend_Mainpage)

**Spec:** `docs/superpowers/specs/2026-11-16-sound-word-split-design.md` (앞 설계 `2026-11-15-sound-word-design.md`)

## Global Constraints

- 나누기: 공백 뺀 글자 수가 정확히 4이고 앞 2글자 == 뒤 2글자일 때만 두 조각. 그 밖은 한 조각.
- 조각 글자 크기 = 그림 폭의 2.5% (`PIECE_RATIO = 0.025`), 상자 높이 = 글자 크기 × 1.2.
- 여백: 좌우 3%, 위·아래 4%, 접히는 선(x=50%)에서 2% (`SFX_EDGE_X, SFX_EDGE_Y, SFX_FOLD` 그대로). 글 덩어리와 `GAP`(2%). 근원과 조각 사이 1%. 탐색 반지름 그림 폭의 15% (`SFX_RADIUS` 그대로).
- 팔레트(순서가 동점 우선순위): `#7B4FD6`, `#F0661E`, `#E03E4E`, `#2D6BD9`, `#2A9D55`, `#FFFFFF`, `#4A4A4A`. WCAG 대비 3:1 이상 후보 중 CIELAB ΔE(CIE76) 최솟값이 가장 큰 색, 후보 없으면 대비 최솟값이 가장 큰 색. 두 조각 같은 색.
- 별표 말이 없는 쪽의 자리 찾기 호출(프롬프트·스키마)은 지금과 똑같다.
- `owner`·말·본문은 로그에 남기지 않는다(쪽 번호만). AI 응답·`sound_word`에 `owner`를 내리지 않는다.
- 옛 모양 `sound_word`는 바꿔 읽지 않는다. Spring은 읽지 못하면 `null`(500 금지).
- AI 저장소: 프롬프트와 코드는 커밋을 나눈다(`prompt:` / `feat:`). 커밋 전 `evals/mock_run.py` 통과.
- 백엔드: 빌드(`./gradlew build`) 통과 뒤 커밋. 적용된 마이그레이션은 고치지 않는다(이번엔 마이그레이션 없음).
- 이슈 먼저, PR 본문 `Closes #N`, PR 제목 `<타입>(scope): 설명`, 일반 merge 커밋.
- 배포 순서: Spring → AI → 프론트(이슈만).

## Review Focus

1. **물건을 캐릭터가 손에 들고 있을 때**(자동차가 몸 칸 안이나 바로 앞) — 조각은 물건 높이 양옆에 가야 하고 캐릭터 머리 옆으로 가면 안 된다. 놓을 곳이 없으면 `null`이 맞다. → Task 3 `test_object_in_front_of_body`.
2. **근원이 그림 가장자리나 접히는 선 가까이** — 거울 자리가 밖으로 나가면 대칭 탐색이 실패하고 한 조각으로 넘어가야 한다(한쪽만 놓으면 안 된다). → Task 3 `test_edge_falls_back_to_one_piece`.
3. **AI 칸이 이상함**(뒤집힘, 0~100 밖, `characters` 빈 목록, `source_box` 없음) — 칸만 버리거나 `null`, 예외로 쪽이 실패하면 안 된다. → Task 2 `_sanitize_word` 테스트, Task 3 `test_no_characters_still_places`.
4. **공백·강조가 섞인 말**(`데굴 데굴`) — 공백을 빼고 판단해 `["데굴","데굴"]`. → Task 1 테스트.
5. **어두운 밤 장면·중간 밝기 하늘색 벽** — 밤엔 `#F0661E`, 하늘색 벽(170,190,230)은 3:1을 넘는 색이 회색뿐이라 `#4A4A4A`. 실험에서 회색이 대부분이면 사용자에게 보고(기준 조정은 사용자 결정). → Task 1 테스트, Task 5 보고.

---

## AI_worker

### Task 1: 나누기·조각 크기·색 고르기 (순수 함수)

**Files:**
- Modify: `src/firstory/nodes/layout.py` (의성어 절, `SFX_RATIO`·`word_size` 근처)
- Test: `evals/layout_run.py` (의성어 절, 419행 근처)

**Interfaces:**
- Produces:
  - `PIECE_RATIO = 0.025`, `PALETTE: list[tuple[str, tuple[int, int, int]]]` (Global Constraints 순서)
  - `split_word(word: str) -> list[str]`
  - `piece_size(text: str) -> tuple[float, float]` — px(1920×1088): `(text_width(text) * PIECE_RATIO / FONT_RATIO, W * PIECE_RATIO * SFX_LINE_H)`
  - `contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float` — WCAG, 기존 `luminance` 사용
  - `delta_e(a, b) -> float` — CIE76 (sRGB → XYZ D65 → Lab, 직접 구현, 새 패키지 없음)
  - `pick_color(busy: Busy, boxes: list[tuple[float, float, float, float]]) -> str` — px 상자 `(x, y, w, h)`, 배경은 `busy.mean_rgb(x - pad, y - pad, w + 2pad, h + 2pad)`, `pad = W * BUSY_PAD`

- [ ] **Step 0: 이슈 만들기와 브랜치** — `gh issue create`(AI_worker, 제목 "의성어를 소리 근원 옆에 나눠 두고 색을 정하기", 본문에 설계 링크), Backend_Mainpage에도 이슈("soundWord를 조각 목록·색 코드로"). `git switch -c feat/sound-word-split` (최신 main에서).
- [ ] **Step 1: 실패하는 테스트**

```python
assert split_word("데굴데굴") == ["데굴", "데굴"]
assert split_word("두근두근") == ["두근", "두근"]
assert split_word("데굴 데굴") == ["데굴", "데굴"]
for w in ("우당탕탕", "와르르르", "엉엉", "꼬르륵", "콩닥콩닥콩닥", "톡"):
    assert split_word(w) == [w], w
pw, ph = piece_size("데굴")
assert abs(pw - text_width("데굴") * 0.025 / FONT_RATIO) < 1e-6 and abs(ph - W * 0.025 * 1.2) < 1e-6
assert round(contrast((255, 255, 255), (0, 0, 0)), 1) == 21.0
assert delta_e((255, 255, 255), (255, 255, 255)) == 0
def solid(rgb):   # 한 색 그림
    buf = io.BytesIO(); Image.new("RGB", (W, H), rgb).save(buf, "PNG"); return Busy(buf.getvalue())
box = [(800.0, 400.0, 100.0, 60.0)]
assert pick_color(solid((255, 255, 255)), box) == "#7B4FD6"
assert pick_color(solid((32, 32, 32)), box) == "#F0661E"
assert pick_color(solid((240, 225, 190)), box) == "#7B4FD6"
assert pick_color(solid((170, 190, 230)), box) == "#4A4A4A"
assert pick_color(solid((255, 255, 255)), box * 2) == "#7B4FD6"   # 두 조각 = 같은 한 색
```

- [ ] **Step 2: 실패 확인** — `uv run python evals/layout_run.py` → `ImportError`(split_word 없음).
- [ ] **Step 3: 구현** — 위 시그니처 그대로 `layout.py`에. `split_word`는 `w = word.replace(" ", "")`로 판단해 나눈 조각도 공백 없이.
- [ ] **Step 4: 통과 확인** — `uv run python evals/layout_run.py` → 마지막까지 `... ok`, 예외 없음.
- [ ] **Step 5: 커밋** — `feat: 의성어 나누기와 배경 대비 색 고르기 (#N)`

### Task 2: AI 답 모양 (스키마·정리·프롬프트·mock)

**Files:**
- Modify: `src/firstory/schemas.py` (`OwnerBox`, `WordSpot`, `SoundWord` 347~374행)
- Modify: `src/firstory/nodes/layout.py` (`_sanitize_word`, `_sanitize_box`, `place_page`)
- Modify: `src/firstory/prompts/text_place_word.md`
- Modify: `src/firstory/mock.py:64-65`
- Test: `evals/layout_run.py`

**Interfaces:**
- Produces (schemas.py):
  - `CharacterBox(BaseModel)`: `name: str`, `box: OwnerBox`
  - `WordSpot(BaseModel)`: `owner: str`, `source_kind: Literal["face", "object"]`, `source_box: OwnerBox`, `characters: list[CharacterBox]` (`x`, `y`, `owner_box` 삭제). Field 설명은 설계 2절 문장.
  - `SoundPiece(BaseModel)`: `text: str`, `x: float`, `y: float`, `side: Literal["left", "right", "center"]`
  - `SoundWord(BaseModel)`: `text: str`, `color: str`, `pieces: list[SoundPiece]`, `owner: Optional[str] = None`
- Produces (layout.py): `_sanitize_word(spot) -> dict | None` →
  `{"owner": str, "kind": "face"|"object", "source": (x0, y0, x1, y1) %, "chars": [(name, (x0, y0, x1, y1) %)]}`. `source_box`가 `_sanitize_box`로 None이면 전체 None, 이상한 캐릭터 칸은 그 칸만 뺀다, `kind`가 두 값이 아니면 None.
- `place_page(image, blocks, sfx, grid)`는 그대로 `(spots, word_dict|None, costs)`. 프롬프트에 `size`를 더 넘기지 않는다.

- [ ] **Step 1: 실패하는 테스트** (`layout_run.py`의 기존 `_sanitize_word`·`WordSpot(... x=, y=, owner_box=)` 테스트를 바꾼다)

```python
ob = lambda *v: OwnerBox(x0=v[0], y0=v[1], x1=v[2], y1=v[3])
good = WordSpot(owner="초코", source_kind="object", source_box=ob(40, 70, 48, 78),
                characters=[CharacterBox(name="초코", box=ob(35, 30, 60, 85)), CharacterBox(name="모아", box=ob(10, 30, 30, 85))])
s = _sanitize_word(good)
assert s == {"owner": "초코", "kind": "object", "source": (40.0, 70.0, 48.0, 78.0),
             "chars": [("초코", (35.0, 30.0, 60.0, 85.0)), ("모아", (10.0, 30.0, 30.0, 85.0))]}, s
bad_char = good.model_copy(update={"characters": [CharacterBox.model_construct(name="x", box=ob(60, 10, 50, 20))]})
assert _sanitize_word(bad_char)["chars"] == []
assert _sanitize_word(good.model_copy(update={"source_box": ob(50, 10, 40, 20)})) is None
assert _sanitize_word(WordSpot.model_construct(owner="a", source_kind="hand", source_box=ob(1, 1, 2, 2), characters=[])) is None
# 프롬프트: 별표 말 있는 쪽에 근원 규칙·데굴데굴 예시, 크기 안내 없음
calls.clear(); llm.set_structured_override(fake_with(TextPlacementWithWord(blocks=[BlockSpot(x=6, y=8, color="dark")], sound_word=good)))
place_page(img_bytes,   # img_bytes = 이 파일의 기존 합성 그림 PNG 바이트 [[["라라가 웃었어요."]]], SfxAsk(word="데굴데굴", text="초코는 자동차를 **데굴데굴** 굴렸어요.", cast=[("초코", "hedgehog")]))
sysmsg = calls[0]["system"]
assert "source_kind" in sysmsg and "자동차" in sysmsg and "말 크기" not in sysmsg and "{{" not in sysmsg
```

- [ ] **Step 2: 실패 확인** — `uv run python evals/layout_run.py` → `ImportError: CharacterBox` 또는 스키마 검증 실패.
- [ ] **Step 3: 스키마·정리 구현** — 위 Interfaces 그대로. `place_page`의 `prompt("text_place_word", ...)`에서 `size=` 인자를 뺀다.
- [ ] **Step 4: 프롬프트 다시 쓰기** — `text_place_word.md`: AI는 자리를 고르지 않고 `owner`, `source_kind`, `source_box`, `characters`를 답한다. 설계 2절의 근원 고르기 4가지(목소리·표정 → 얼굴, 물건 → 물건, 몸 움직임 → 얼굴, 화면 밖 → 반응하는 캐릭터 얼굴), 칸은 윤곽에 붙게, 안은 캐릭터는 한 칸, 물건을 든 캐릭터도 `characters`에, 예시 "초코는 자동차를 데굴데굴 굴렸어요 → owner 자동차, source_kind object, source_box는 자동차". `{{size}}` 자리 삭제.
- [ ] **Step 5: mock** — `mock.py`: `sound_word=WordSpot(owner="mock", source_kind="face", source_box=OwnerBox(x0=62, y0=30, x1=70, y1=42), characters=[CharacterBox(name="mock", box=OwnerBox(x0=58, y0=30, x1=74, y1=88))])`.
- [ ] **Step 6: 통과 확인** — `uv run python evals/layout_run.py` 위 테스트 통과. 옛 모양(`x`, `y`, `owner_box`)을 쓰는 기존 `settle_word`·`WordSpot` 테스트(419~540행 근처)는 이 Task에서 지운다(Task 3이 새 테스트로 대신한다). `settle_word`·`illustrate`는 Task 3·4까지 옛 dict를 기대하므로 **브랜치 안에서는 Task 4 전까지 `mock_run.py`가 깨질 수 있다**. main에 합치기 전(Task 4 끝)에는 반드시 통과.
- [ ] **Step 7: 커밋 두 개** — `prompt: 의성어 근원 칸과 캐릭터 칸을 답하게 (#N)`(프롬프트만), `feat: 의성어 AI 답을 근원·캐릭터 칸으로 (#N)`(나머지).

### Task 3: 조각 놓기 `place_word`

**Files:**
- Modify: `src/firstory/nodes/layout.py` (`settle_word`, `_word_ok`, `word_size`, `SFX_RATIO` 삭제·대체)
- Test: `evals/layout_run.py` (기존 `settle_word`·`word_size` 테스트 삭제, 아래로 대체)

**Interfaces:**
- Consumes: Task 1 `split_word`, `piece_size`, `pick_color`; Task 2 `_sanitize_word` dict, `SoundWord`, `SoundPiece`
- Produces: `place_word(busy: Busy, word: str, spot: dict | None, blocks: list[TextBlock]) -> SoundWord | None`
  (`spot`은 `_sanitize_word` 결과. `pieces`의 x, y는 조각 가운데 %, 소수 한 자리. 두 조각이면 `side` left/right, 한 조각이면 center.)
- Produces: `_closer_to_source(pt: tuple[float, float], source: tuple[float, float, float, float], others: list[tuple[float, float, float, float]]) -> bool` — px, 칸은 `(x0, y0, x1, y1)`, 점–사각형 거리로 `dist(source) < min(dist(others))`(others가 비면 True)

자리 규칙(설계 3절, 모두 px, `g = W * 0.01`, `(x0, y0, x1, y1)` = 근원 칸, 조각 크기 `(pw, ph)`):

| | 시작 자리(조각 가운데) | 탐색 |
|---|---|---|
| face 두 조각 | 왼쪽 `(x0 - g - pw/2, y0)`, 오른쪽 `(x1 + g + pw/2, y0)` | 두 조각 같이: 왼쪽 `−dx`, 오른쪽 `+dx`, 둘 다 `−dy` (`dx, dy ≥ 0`, GRID 보폭, `hypot ≤ SFX_RADIUS·W`, 가까운 순) |
| face 한 조각 | `((x0+x1)/2, y0 - g - ph/2)` | 시작에서 가까운 순, 조각 아래끝 `≤ y1` |
| object 두 조각 | 왼쪽 `(x0 - g - pw/2, (y0+y1)/2)`, 오른쪽 거울 | face 두 조각과 같되 조각 가운데 `y ≥ y0 - ph` |
| object 한 조각 | `((x0+x1)/2, y0 - g - ph/2)` → 다음 후보로 양옆 같은 높이 | 시작에서 가까운 순, 조각 가운데 `y ≥ y0 - ph` |

검사(모든 조각): 여백·접히는 선·글 덩어리 `GAP`(기존 `_word_ok`의 검사), 모든 `chars` 칸과 겹침 없음, 두 조각끼리 겹침 없음, **근원 가까움**: 조각 가운데에서 근원 칸까지 거리 < 다른 캐릭터 칸까지 거리(점–사각형 거리). 근원이 face면 근원 칸 가운데를 품은 캐릭터 칸은 "다른 캐릭터"에서 뺀다. object면 빼지 않는다. 두 조각 실패 → 원래 말 한 조각 → 실패 → `None`.

- [ ] **Step 1: 실패하는 테스트** (흰 그림 `white`, 글 덩어리 `tb = [TextBlock(paragraphs=[["가"]], x=5, y=7, color="dark")]`)

```python
face = {"owner": "모아", "kind": "face", "source": (20.0, 35.0, 30.0, 50.0), "chars": [("모아", (15.0, 30.0, 35.0, 90.0))]}
sw = place_word(white, "데굴데굴", face, tb)
l, r = sw.pieces
assert [p.text for p in sw.pieces] == ["데굴", "데굴"] and (l.side, r.side) == ("left", "right")
assert l.x < 15 and r.x > 35 and l.y == r.y and l.y <= 35          # 캐릭터 칸 바깥, 대칭, 얼굴 위끝 이하
assert abs((20 - l.x) - (r.x - 30)) < 0.2                          # 근원 기준 거울 대칭
assert sw.color == "#7B4FD6" and sw.text == "데굴데굴"
one = place_word(white, "엉엉", face, tb)
assert [p.side for p in one.pieces] == ["center"] and one.pieces[0].y < 30   # 몸 칸 위
assert [p.text for p in place_word(white, "우당탕탕", face, tb).pieces] == ["우당탕탕"]

def test_object_in_front_of_body():
    car = {"owner": "자동차", "kind": "object", "source": (55.0, 75.0, 62.0, 82.0),
           "chars": [("초코", (52.0, 35.0, 72.0, 88.0)), ("모아", (15.0, 30.0, 35.0, 90.0))]}
    sw = place_word(white, "데굴데굴", car, tb)
    assert sw is None or all(p.y >= 75 - 3 for p in sw.pieces), sw   # 머리 옆(위쪽)으로 가지 않는다
test_object_in_front_of_body()
car_free = {"owner": "자동차", "kind": "object", "source": (60.0, 75.0, 66.0, 82.0), "chars": [("초코", (75.0, 35.0, 92.0, 88.0))]}
sw = place_word(white, "데굴데굴", car_free, tb)
assert sw and abs(sw.pieces[0].y - 78.5) < 3 and abs(sw.pieces[1].y - 78.5) < 3   # 물건 높이 양옆

def test_edge_falls_back_to_one_piece():
    edge = {"owner": "a", "kind": "face", "source": (2.0, 30.0, 10.0, 45.0), "chars": [("a", (1.0, 28.0, 12.0, 90.0))]}
    sw = place_word(white, "데굴데굴", edge, [])
    assert sw is None or [p.side for p in sw.pieces] == ["center"]
test_edge_falls_back_to_one_piece()

def test_no_characters_still_places():
    sw = place_word(white, "엉엉", {"owner": "a", "kind": "face", "source": (60.0, 30.0, 70.0, 45.0), "chars": []}, [])
    assert sw and len(sw.pieces) == 1
test_no_characters_still_places()
# 근원 가까움 (px 칸): 다른 캐릭터 칸이 더 가까우면 False
assert _closer_to_source((100.0, 100.0), (120.0, 90.0, 140.0, 110.0), [(50.0, 50.0, 95.0, 95.0)]) is False
assert _closer_to_source((100.0, 100.0), (105.0, 90.0, 140.0, 110.0), [(50.0, 50.0, 80.0, 80.0)]) is True
assert _closer_to_source((100.0, 100.0), (105.0, 90.0, 140.0, 110.0), []) is True
assert place_word(white, "엉엉", None, tb) is None
```

- [ ] **Step 2: 실패 확인** — `uv run python evals/layout_run.py` → `ImportError: place_word`.
- [ ] **Step 3: 구현** — 표의 규칙 그대로. `settle_word`, `_word_ok`, `word_size`, `SFX_RATIO`, `SFX_LINE_H`가 다른 곳에서 안 쓰이면 지운다(`SFX_LINE_H`는 `piece_size`가 쓴다면 둔다). 색은 마지막에 `pick_color(busy, 조각 px 상자들)`.
- [ ] **Step 4: 통과 확인** — `uv run python evals/layout_run.py` → `sound word ok`까지.
- [ ] **Step 5: 커밋** — `feat: 의성어 조각을 근원 옆에 대칭으로 놓기 (#N)`

### Task 4: 연결 (쪽 결과·API·실험 스크립트)

**Files:**
- Modify: `src/firstory/nodes/illustrate.py:410-414` (`settle_word` → `place_word`), import 줄 24~25
- Modify: `src/firstory/server.py:379-382` (`_sound_word`)
- Modify: `evals/sound_word_lab.py` (조각·색·근원 칸·캐릭터 칸 그리기)
- Test: `evals/mock_run.py:946-1040`, `evals/api_run.py:341-347`

**Interfaces:**
- Consumes: Task 3 `place_word`
- Produces: 결과 API `pages[].sound_word = {"text", "color", "pieces": [{"text", "x", "y", "side"}]}` 또는 `null` (`owner` 제외)

- [ ] **Step 1: 테스트 바꾸기** — `mock_run.py` 965~966행:

```python
assert pi.sound_word and pi.sound_word.text == "깡충" and pi.sound_word.color.startswith("#") and len(pi.sound_word.color) == 7, pi
assert 1 <= len(pi.sound_word.pieces) <= 2 and all(0 <= p.x <= 100 and 0 <= p.y <= 100 for p in pi.sound_word.pieces)
```
  994~1017행의 `mock.WordSpot(owner=..., owner_box=..., x=, y=)`는 Task 2 모양으로(`source_kind="face"`, `source_box`, `characters`). `api_run.py` 341행 근처:

```python
sw = p["sound_word"]
if sw:
    assert set(sw) == {"text", "color", "pieces"} and sw["color"].startswith("#")
    assert all(set(q) == {"text", "x", "y", "side"} for q in sw["pieces"])
    assert "".join(q["text"] for q in sw["pieces"]) == sw["text"].replace(" ", "")
```
- [ ] **Step 2: 실패 확인** — `LANGSMITH_TRACING=false OPENAI_API_KEY=가짜값 uv run python evals/mock_run.py` → `settle_word` import 오류 또는 단언 실패.
- [ ] **Step 3: 구현** — `_arrange`에서 `place_word(cur, sfx.word, last_word[1], tbs)`. `_sound_word`: `sw.model_dump(include={"text", "color", "pieces"})`. `sound_word_lab.py`: `settle_word` → `place_word`, 조각마다 `<span class="sw" style="left:..;top:..;color:{sw.color}">`, 근원 칸(빨강)·캐릭터 칸(파랑) 테두리, 메타에 `source_kind`·`owner`·토큰. 글자 크기 CSS `{PIECE_RATIO * 100:g}cqw`.
- [ ] **Step 4: 통과 확인** — `mock_run.py` → `ALL OK`. `api_run.py`(mock 서버로, 파일 머리 주석의 실행법대로) → 통과. `layout_run.py` 다시 → 통과.
- [ ] **Step 5: 커밋** — `feat: 쪽 결과 sound_word를 조각 목록과 색으로 (#N)`

### Task 5: 작은 실험 (관문, 사용자 확인)

**Files:** 없음(출력 `out/sound-word-split-1116/`)

- [ ] **Step 1: 사용자에게 묻기** — "이미 그린 그림 약 10쪽(11/15 실험과 같은 입력)으로 새 자리 찾기만 진짜 모델로 돌림, 약 50원(한 장 약 $0.003)". 답을 받은 뒤에만.
- [ ] **Step 2: 실행** — `uv run python evals/sound_word_lab.py --grid --out sound-word-split-1116 <11/15 실험 입력들>`.
- [ ] **Step 3: 보고** — HTML 경로, 쪽마다 결과 전부(잘라 내지 않음), 놓인 조각 수/`null` 수, 고른 색 분포(회색이 대부분이면 Review Focus 5로 보고), 쪽당 입력·출력 토큰과 비용. 좋은지는 사용자가 정한다. 칸이 커서 조각이 멀면 프롬프트 고쳐 같은 크기로 한 번 더(다시 묻고).
- [ ] **Step 4: 사용자 승인 후 PR** — `gh pr create --title "feat(layout): 의성어를 소리 근원 옆에 나눠 두고 색 정하기"`, 본문 템플릿(무엇을/참고할 점/확인 방법), `Closes #N`. **합치기는 Task 7에서**(Spring 먼저).

## Backend_Mainpage

### Task 6: `soundWord` 조각·색 모양

**Files:**
- Modify: `src/main/java/com/firstory/domain/generation/entity/PageSoundWord.java`
- Create: `src/main/java/com/firstory/domain/generation/entity/PieceSide.java`
- Modify: `src/main/java/com/firstory/domain/generation/entity/StoryPage.java` (`getSoundWord`)
- Modify: `src/main/java/com/firstory/global/ai/HttpAiClient.java:410-426`
- Modify: `src/main/java/com/firstory/global/ai/FakeAiClient.java:530-533`
- Modify: `PreviewResponse.java:33` (`SOUND_WORD_EXAMPLE`), `BookResponse.java` 주석
- Modify: `docs/FIRSTORY-AI-API-SPEC-v0.3.md`, `docs/frontend/screens.md`, `docs/frontend/fake-ai.md`
- Test: `PageSoundWordTest`, `HttpAiClientTest`, `ReadingIntegrationTest`, `GenerationIntegrationTest`, `FakeAiClientTest`

**Interfaces:**
- Produces:
  - `enum PieceSide { LEFT, RIGHT, CENTER; static PieceSide fromAi(String v) }` (소문자 받음, 모르면 null)
  - `@JsonIgnoreProperties(ignoreUnknown = true) record PageSoundWord(String text, String color, List<Piece> pieces)`, 안에 `record Piece(String text, double x, double y, PieceSide side)`
  - `static PageSoundWord validated(PageSoundWord raw)` — null이면: text 빔, color가 `^#[0-9A-Fa-f]{6}$` 아님, pieces null·0개·3개 이상, 조각 text 빔, x·y 0~100 밖(NaN 포함), side null, 조각 text를 이은 것 ≠ `text`에서 공백 뺀 것. `toString`에 말을 넣지 않는다.
  - `StoryPage.getSoundWord()` → `PageSoundWord.validated(soundWord)` (옛 모양 행은 `pieces == null`이라 null)
- 응답: `{"text":"데굴데굴","color":"#E03E4E","pieces":[{"text":"데굴","x":18.2,"y":46.0,"side":"LEFT"},{"text":"데굴","x":37.9,"y":46.0,"side":"RIGHT"}]}`

- [ ] **Step 0: 브랜치** — Backend_Mainpage 최신 main에서 `git switch -c feat/sound-word-pieces`.
- [ ] **Step 1: 실패하는 테스트**
  - `PageSoundWordTest`: 위 응답 예시는 그대로 통과. 색 `"red"` → null, 조각 3개 → null, 조각 이음 불일치(`"데굴"`+`"구르"`) → null, x=101 → null, side null → null. 한 조각 `{"엉엉", CENTER}` 통과.
  - `HttpAiClientTest`: `sound_word` = `{"text":"데굴데굴","color":"#E03E4E","pieces":[{"text":"데굴","x":18.2,"y":46.0,"side":"left"},{"text":"데굴","x":37.9,"y":46.0,"side":"right"}]}` → 위 record. 옛 모양 `{"text":"훌쩍","x":62.5,"y":31.0,"color":"dark"}` → null(경고 로그). 없음 → null.
  - `ReadingIntegrationTest`: 새 모양 저장 → `$.pages[0].soundWord.pieces[1].side == "RIGHT"`, `.color == "#E03E4E"`. **옛 모양 jsonb를 SQL로 직접 넣은 쪽 → `$.pages[1].soundWord`가 null이고 응답 200.**
  - `FakeAiClientTest`/`GenerationIntegrationTest`: 별표 말 `**깡충깡충**` 쪽 → 두 조각, 색 `#7B4FD6`.
- [ ] **Step 2: 실패 확인** — `./gradlew test` → 컴파일 오류(새 생성자).
- [ ] **Step 3: 구현** — Interfaces 그대로. `HttpAiClient.soundWord`는 JsonNode에서 새 모양을 읽어 `validated`. `FakeAiClient`: 반복 4글자면 `(30.0, 40.0, LEFT)`·`(45.0, 40.0, RIGHT)`, 아니면 `(75.0, 40.0, CENTER)`, 색 `#7B4FD6`.
- [ ] **Step 4: 통과 확인** — `./gradlew build` → `BUILD SUCCESSFUL`.
- [ ] **Step 5: 문서** — 세 문서의 `sound_word`/`soundWord` 모양을 새 모양으로, 크기 2.5cqw, `side` 뜻, 색은 서버가 배경 대비로 고름.
- [ ] **Step 6: 커밋·PR** — `feat: soundWord를 조각 목록과 색 코드로 (#M)`, PR 제목 `feat(reading): soundWord를 조각 목록과 색 코드로`, `Closes #M`.

## 내보내기

### Task 7: 합치기·배포·알리기

- [ ] **Step 1: Spring 먼저** — Backend PR 합치기(일반 merge) → EC2 배포 워크플로 `success` 확인(`gh run watch`).
- [ ] **Step 2: AI** — Task 5 승인을 받은 AI PR 합치기 → 배포 `success` 확인.
- [ ] **Step 3: 프론트 알림** — Frontend_MainPage #155에 댓글: 새 모양 JSON 예시, 조각마다 `left/top + translate(-50%,-50%)`, 글자 크기 `2.5cqw`(±20%), 색은 `color` 그대로(외곽선은 얇게, 선택), `side` LEFT/RIGHT 기울기 방향, null이면 안 띄움.
- [ ] **Step 4: NEXT-STEPS.md** — 맨 위 "다음 할 일"에 이슈·PR·커밋, 실험 결과 경로, 남은 것(진짜 모델 한 편 확인은 비용 묻고, 프론트 #155).
