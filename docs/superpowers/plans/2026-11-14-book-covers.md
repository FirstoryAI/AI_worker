# 동화책 앞표지·뒤표지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 동화를 만들 때 앞표지(제목+주인공)와 뒤표지(글자 없음)를 쪽과 같은 1920×1088로 더 그리고, Spring이 버전에 저장해 미리보기·함께 읽기 응답의 `frontCoverUrl`, `backCoverUrl`과 그림 API로 내려준다.

**Architecture:** AI 워커 `illustrate._run`이 지금 정사각형 표지(`cover()`)와 같은 스레드 풀에서 뒤표지를 처음부터, 앞표지를 정사각형이 끝난 뒤(정사각형을 참고 그림으로) 그린다. 결과 API가 두 key를 더 주고, Spring은 `story_versions` 두 칸(V14)에 저장해 지금 `/cover`와 같은 방식으로 내려준다.

**Tech Stack:** Python 3.13, LangGraph, FastAPI, gpt-image-2 / Java 21, Spring Boot 4.1, Flyway.

**Spec:** `docs/superpowers/specs/2026-11-14-book-covers-design.md` (AI_worker 저장소). 실행하는 사람은 설계와 이 계획을 같이 읽는다.

## Global Constraints

- 앞·뒤표지 크기는 쪽과 같은 `config.image_size`(기본 `1920x1088`). 정사각형 표지(`config.cover_size`, 1024×1024)는 지금 그대로다.
- 앞표지 참고 그림 = 정사각형 표지 + 캐릭터 시트(정사각형이 없으면 캐릭터 시트만). 제목은 한글로 그림 위쪽에 `story.title` 그대로. 뒤표지는 글자 없음, 마지막 쪽 장면을 바탕으로 마무리하는 그림.
- 세 표지 모두 실패하면(정책 순화 `_draw` 뒤에도 예외) **한 번 더** 그리고, 그래도 실패하면 key는 None. 실행은 실패하지 않는다.
- 다시 만들 때: 앞표지는 정사각형을 새로 그릴 때만 새로. 뒤표지는 `only_pages is None`(전부)이거나 마지막 쪽(`story.pages[-1].order`)을 다시 그릴 때만 새로. 이전 key가 없으면(None) 그린다. 그 밖에는 이전 key 그대로.
- 비용 기록 node 이름: `illustrate:front_cover`, `illustrate:back_cover` (정사각형은 지금처럼 `illustrate:cover`).
- 결과 API 키: `front_cover_path`, `back_cover_path`. Spring 칸: `story_versions.front_cover_key`, `back_cover_key` (varchar(255), null 가능, `V14__version_book_covers.sql`). 그림 API: `/api/stories/{id}/versions/{versionId}/front-cover`, `/back-cover`. 응답 필드: `frontCoverUrl`, `backCoverUrl` (`BookResponse`, `PreviewResponse`), 없으면 null.
- 진짜 모델 호출은 사용자에게 비용을 말하고 물은 뒤에만 (한 편 약 900원). 결과는 그림 전부를 보여 주고 품질 판단은 사용자 몫.
- 이슈 먼저 → 브랜치 → PR(`Closes #N`), PR 제목 `<타입>(scope): 설명`, 합치기는 `gh pr merge --merge --delete-branch`. AI 저장소는 프롬프트와 코드를 커밋으로 나눌 필요 없음(지시문이 코드 안 함수다). AI 저장소 커밋 전 `LANGSMITH_TRACING=false OPENAI_API_KEY=가짜값 uv run python evals/mock_run.py`와 `evals/api_run.py` 통과. 백엔드는 `./gradlew build && git commit`(파이프 금지, macOS에서는 `sh ./gradlew`).
- 합치면 두 저장소 모두 EC2에 자동 배포된다. 어느 쪽이 먼저 나가도 깨지지 않는다.

## Review Focus

1. **정사각형 표지가 실패했을 때 앞표지**는 캐릭터 시트만으로 그려져야 하고(참고 그림 수 = 캐릭터 수), 앞표지까지 None이 되면 안 된다. → Task 1 `front cover without square`
2. **배포 전에 만든 동화를 글 다시 만들기**(제목·장면 그대로)로 다시 만들면, 이전 실행에 앞·뒤표지가 없으므로 "전부 이전 것" 지름길(`illustrate()`의 early return)을 타지 말고 두 표지만 그려야 한다. → Task 1 `old run gets book covers`
3. **그림만 다시(일부 쪽)에 마지막 쪽이 없으면** 뒤표지와 앞표지 key가 이전 실행 것 그대로여야 한다. 마지막 쪽이 있으면 뒤표지만 새로. → Task 1 `partial redraw keeps covers`
4. **AI 결과에 두 키가 없는 옛 AI**(앞 배포 순서)와 **두 키가 null**인 결과도 Spring이 읽고 버전을 저장해야 하며, 응답 주소는 null, 그림 API는 404 `IMAGE_NOT_FOUND`. → Task 3 `옛_AI_결과에_앞뒤표지가_없어도_읽는다`, Task 4 `앞뒤표지가_없는_버전은_주소가_null이고_그림은_404`
5. **다른 동화 경로의 앞·뒤표지 key**(`stories/{다른id}/…`)는 지금 정사각형처럼 `INVALID_OUTPUT_PATH`로 거부돼야 한다. → Task 3 `앞뒤표지_key가_다른_동화_경로면_거부`

---

## 파일 지도

AI_worker (브랜치 `feat/book-covers`, 바탕화면 `Firstory_AI_pipeline`의 main에서)
- `src/firstory/schemas.py` — `Illustrations.front_cover`, `back_cover`
- `src/firstory/nodes/illustrate.py` — 지시문 `front_cover_prompt`, `back_cover_prompt`, `_run` 안 표지 작업, `illustrate()` 지름길 조건
- `src/firstory/server.py` — 결과에 두 키
- `src/firstory/nodes/render.py` — `book.html` 맨 앞·맨 뒤에 앞·뒤표지 (비교 화면용)
- `evals/mock_run.py` 6) 표지 절, `evals/api_run.py` `RESULT_KEYS`

Backend_Mainpage (브랜치 `feat/book-covers`)
- `src/main/resources/db/migration/V14__version_book_covers.sql`
- `global/ai/AiGenerationResult.java`, `global/ai/HttpAiClient.java`, `global/ai/FakeAiClient.java`
- `domain/generation/entity/StoryVersion.java`, `service/GenerationResultRecorder.java`, `service/StoryImageService.java`, `controller/StoryImageController.java`, `dto/StoryImageUrls.java`, `dto/PreviewResponse.java`
- `domain/reading/dto/BookResponse.java`
- 문서: `docs/FIRSTORY-AI-API-SPEC-v0.3.md`(결과 형식 `cover_path` 옆), `docs/frontend/screens.md`(미리보기·함께 읽기), CLAUDE.md(파일 저장소와 그림 API, key 형식)

---

### Task 0: 이슈

- [ ] **Step 1:** AI_worker에 이슈를 만든다. 제목 `동화책 앞표지·뒤표지 그리기 (Backend#61)`, 본문 문제/할 일 단답형(설계 링크, 결과 키 이름). 백엔드는 #61을 그대로 쓴다.

### Task 1: AI — 앞·뒤표지 그리기와 다시 만들기 규칙

**Files:**
- Modify: `src/firstory/schemas.py` (`Illustrations`, 358줄 근처)
- Modify: `src/firstory/nodes/illustrate.py` (`cover_prompt` 옆 186줄, `_run` 434~461줄, `illustrate()` 481줄)
- Test: `evals/mock_run.py` 6) 표지 절 (205~232줄)

**Interfaces:**
- Produces: `Illustrations.front_cover: Optional[str] = None`, `Illustrations.back_cover: Optional[str] = None`; `front_cover_prompt(story: StoryText, with_square: bool) -> str`(첫 줄 `"Wide front cover of a children's picture book."`), `back_cover_prompt(story: StoryText) -> str`(첫 줄 `"Back cover of a children's picture book."`). 저장 key `…/images/front-cover.{ext}`, `…/images/back-cover.{ext}`.

- [ ] **Step 1: mock_run 6) 절에 실패하는 확인을 더한다** (지금 `c1`, `same`, `retitled`, `failed`를 쓰는 자리)

```python
# 처음: 세 표지 모두 이번 실행 key
assert c1.front_cover == "stories/c/runs/1/images/front-cover.png" and c1.back_cover == "stories/c/runs/1/images/back-cover.png"
assert [c.node for c in il.illustrate({"story": st, "output_prefix": "stories/c/runs/9/"})["cost"]].count("illustrate:front_cover") == 1
# 앞표지는 정사각형 + 시트를 참고 (refs 수 = 캐릭터 + 1)
seen = {}
def spy(prompt, refs):
    seen.setdefault(prompt.splitlines()[0], len(refs)); return mock.tiny_png(prompt, refs)
il.set_image_override(spy); il.illustrate({"story": st, "output_prefix": "stories/c/runs/8/"})
assert seen["Wide front cover of a children's picture book."] == len(st.characters) + 1
assert seen["Back cover of a children's picture book."] == len(st.characters)
il.set_image_override(mock.tiny_png)
# 제목·장면 그대로: 지름길, 표지 셋 다 이전 것 (same은 기존 확인 그대로)
# 제목만 바뀜: 정사각형·앞표지 새로, 뒤표지 이전
assert retitled["illustrations"].front_cover == "stories/c/runs/3/images/front-cover.png"
assert retitled["illustrations"].back_cover == c1.back_cover
assert sorted(c.node for c in retitled["cost"]) == ["illustrate:cover", "illustrate:front_cover"]
```

`retitled`의 기존 확인 `[c.node for c in retitled["cost"]] == ["illustrate:cover"]`는 위 줄로 바꾼다. 아래 세 확인도 이 절에 더한다(Review Focus 1~3).

```python
# front cover without square: 정사각형만 실패 → 앞표지는 시트만 참고해 그려짐, 정사각형은 두 번 시도
def no_square(prompt, refs):
    if prompt.startswith("Front cover"): raise RuntimeError("정사각형 실패 흉내")
    seen.setdefault(prompt.splitlines()[0], len(refs)); return mock.tiny_png(prompt, refs)
seen.clear(); il.set_image_override(no_square)
r = il.illustrate({"story": st, "output_prefix": "stories/c/runs/5/"})
assert r["illustrations"].cover is None and r["illustrations"].front_cover == "stories/c/runs/5/images/front-cover.png"
assert seen["Wide front cover of a children's picture book."] == len(st.characters)
# 실패 후 한 번 더: 두 번째에 성공하면 key가 있다
calls = {"n": 0}
def flaky_back(prompt, refs):
    if prompt.startswith("Back cover"):
        calls["n"] += 1
        if calls["n"] == 1: raise RuntimeError("한 번 실패")
    return mock.tiny_png(prompt, refs)
il.set_image_override(flaky_back)
assert il.illustrate({"story": st, "output_prefix": "stories/c/runs/6/"})["illustrations"].back_cover and calls["n"] == 2
il.set_image_override(mock.tiny_png)
# old run gets book covers: 앞·뒤표지 없는 이전 실행 + 글 다시(장면·제목 그대로) → 두 표지만
old = c1.model_copy(update={"front_cover": None, "back_cover": None})
o = il.illustrate({"story": st, "illustrations": old, "redraw_pages": [], "output_prefix": "stories/c/runs/7/"})
assert sorted(c.node for c in o["cost"]) == ["illustrate:back_cover", "illustrate:front_cover"]
assert o["illustrations"].cover == c1.cover and [p.path for p in o["illustrations"].pages] == [p.path for p in c1.pages]
# partial redraw keeps covers: 그림만 다시 1쪽 → 표지 셋 그대로 / 마지막 쪽(2) → 뒤표지만 새로
p1, _ = il._run(st, "stories/c/runs/10/images", only_pages={1}, prev=c1)
assert (p1.cover, p1.front_cover, p1.back_cover) == (c1.cover, c1.front_cover, c1.back_cover)
p2, costs2 = il._run(st, "stories/c/runs/11/images", only_pages={2}, prev=c1)
assert p2.back_cover == "stories/c/runs/11/images/back-cover.png" and p2.front_cover == c1.front_cover
```

기존 `no_cover`(정사각형 두 번 다 실패) 확인 뒤에 `failed.front_cover`가 있는지(시트만으로 그림)도 본다.

- [ ] **Step 2: 실패 확인**

Run: `LANGSMITH_TRACING=false OPENAI_API_KEY=가짜값 uv run python evals/mock_run.py`
Expected: 6) 절에서 `AttributeError: 'Illustrations' object has no attribute 'front_cover'` 또는 첫 assert 실패

- [ ] **Step 3: 구현**
  - `schemas.py`: 두 칸 추가, 주석 "1920×1088, 앞표지는 제목 포함 / 뒤표지는 글자 없음. 못 그렸으면 None".
  - `illustrate.py` 지시문: `front_cover_prompt`는 `cover_prompt`의 캐릭터 참조 줄·스타일·제목 줄을 같이 쓰고, `with_square`면 "Reference 1 is the square cover of this same book: keep its scene, composition, characters and title lettering, and extend it to a wide 16:9 cover by widening the background left and right."를 넣는다(참고 그림 순서: 정사각형 먼저, 그다음 시트). `back_cover_prompt`는 캐릭터 참조 줄, 마지막 쪽 `image_prompt`를 "Last scene of the story (for mood)", "A calm closing illustration that wraps up the story", 스타일, "No text, no title, no borders."로.
  - `_run`: 표지 하나 그리기를 `_cover_job(name, prompt_fn, refs, size)`로 묶고 실패하면 한 번 더(정사각형 `cover()`도 이걸 쓴다). 뒤표지는 정사각형과 함께 처음에 `ex.submit`. 앞표지는 정사각형 future의 결과를 받은 뒤 `ex.submit`(정사각형을 다시 그리지 않으면 이전 정사각형 key의 바이트를 `storage.read_bytes`로 읽어 참고). 다시 그리기 조건은 Global Constraints 대로: `redraw_front = redraw_cover or not ill.front_cover`, `redraw_back = only_pages is None or last_order in only_pages or not ill.back_cover`.
  - `illustrate()` 지름길(481줄) 조건에 `and prev.front_cover and prev.back_cover`를 더한다.

- [ ] **Step 4: 통과 확인** — Step 2 명령, Expected: 끝까지 돌고 `cover ok` 출력

- [ ] **Step 5: 커밋** `feat: 앞표지·뒤표지를 쪽 크기로 그리고 다시 만들 때 필요한 것만 다시 (#<AI 이슈>)`

### Task 2: AI — 결과 API와 book.html

**Files:**
- Modify: `src/firstory/server.py:411`, `src/firstory/nodes/render.py:49-57`
- Test: `evals/api_run.py:280, 336, 460, 583`

**Interfaces:**
- Consumes: Task 1의 `Illustrations.front_cover`, `back_cover`
- Produces: 결과 JSON `front_cover_path`, `back_cover_path` (없으면 null)

- [ ] **Step 1: api_run 확인을 더한다**: `RESULT_KEYS`에 두 키, 336줄 옆에 `res["front_cover_path"] == f"{prefix}images/front-cover.png" and storage.exists(...)`, 뒤표지도 같게. 460줄(일부 쪽 그림만 다시) 옆에 `v2["front_cover_path"] == v1["front_cover_path"]`, 마지막 쪽이 대상이 아니면 `v2["back_cover_path"] == v1["back_cover_path"]`. 583줄(제목 그대로 글 다시) 옆에 두 키도 재사용.
- [ ] **Step 2: 실패 확인** — `LANGSMITH_TRACING=false OPENAI_API_KEY=가짜값 uv run python evals/api_run.py`, Expected: `set(res) == RESULT_KEYS` 실패
- [ ] **Step 3: 구현** — `server.py` 결과에 `"front_cover_path": ill.front_cover, "back_cover_path": ill.back_cover`(주석: 쪽 크기, 못 그렸으면 null). `render.py`는 앞표지가 있으면 표지 슬라이드 다음에 `<section class="slide">`로 앞표지, 마지막 쪽 뒤에 뒤표지 (16:9, 기존 `.slide img` 스타일).
- [ ] **Step 4: 통과 확인** — Step 2 명령과 `evals/mock_run.py` 둘 다 끝까지
- [ ] **Step 5: 커밋** `feat: 결과에 front_cover_path·back_cover_path, book.html에 앞·뒤표지 (#<AI 이슈>)` → 설계·계획 문서도 같은 브랜치에 `docs:` 커밋 → PR(`Closes #<AI 이슈>`, 템플릿 합니다체) → 합치기

### Task 3: 백엔드 — 저장 칸과 결과 읽기

**Files:**
- Create: `src/main/resources/db/migration/V14__version_book_covers.sql`
- Modify: `StoryVersion.java`(칸 2개, `create` 인자 2개 뒤에 추가), `AiGenerationResult.java`(`coverPath` 뒤에 `frontCoverPath`, `backCoverPath`, `fileKeys()`에 포함), `HttpAiClient.java:368`(`@JsonProperty("front_cover_path")`, `"back_cover_path"`), `GenerationResultRecorder.java:114`, `FakeAiClient.java:480-503`, `support/Fixtures.java`, `support/StoryStates.java`, `ReadingIntegrationTest.java:135,174`(생성자 인자)
- Test: `HttpAiClientTest`, `FlywayMigrationTest`, `GenerationIntegrationTest`

**Interfaces:**
- Produces: `StoryVersion.getFrontCoverKey()`, `getBackCoverKey()`; `StoryVersion.create(..., String coverKey, String frontCoverKey, String backCoverKey)`; `AiGenerationResult(int runNo, String checkpointId, String title, Map design, String coverPath, String frontCoverPath, String backCoverPath, List<CharacterSheet> ..., ...)`

- [ ] **Step 1: 테스트를 쓴다**
  - `FlywayMigrationTest.V14_버전에_앞뒤표지_칸이_있다()` — `information_schema.columns`에 `story_versions.front_cover_key`, `back_cover_key`가 `character varying`, nullable `YES` (V8 테스트와 같은 방식)
  - `HttpAiClientTest.결과의_앞뒤표지_key를_읽는다()` — 응답 JSON에 `"front_cover_path": "stories/1/runs/1/images/front-cover.webp"`, `"back_cover_path": "stories/1/runs/1/images/back-cover.webp"` → `result.frontCoverPath()`, `backCoverPath()`가 그 값
  - `HttpAiClientTest.옛_AI_결과에_앞뒤표지가_없어도_읽는다()` — 두 키 없는 JSON → 둘 다 null
  - `GenerationIntegrationTest.앞뒤표지_key가_다른_동화_경로면_거부()` — 기존 정사각형 표지 경로 거부 테스트와 같은 방식(`misdirectOutput` 또는 결과 직접 기록)으로 `front_cover_path`가 `stories/{다른id}/…`면 실행 FAILED `INVALID_OUTPUT_PATH`
  - `GenerationIntegrationTest`의 그림만 다시 일부 쪽 테스트(287줄)에 `frontCoverKey(v2) == frontCoverKey(v1)`, `backCoverKey(v2) == backCoverKey(v1)` (가짜 AI 대상 쪽에 마지막 쪽이 없다)
- [ ] **Step 2: 실패 확인** — `sh ./gradlew test --tests '*FlywayMigrationTest' --tests '*HttpAiClientTest' --tests '*GenerationIntegrationTest'`, Expected: 컴파일 실패(없는 메서드)
- [ ] **Step 3: 구현** — V14 첫 줄 주석 "동화책 앞표지·뒤표지 (쪽과 같은 1920×1088, #61)", `ALTER TABLE story_versions ADD COLUMN front_cover_key varchar(255), ADD COLUMN back_cover_key varchar(255);`. `FakeAiClient`는 `png(color, 1920, 1088)`로 `images/front-cover.png`, `images/back-cover.png`를 쓰고, 일부 쪽 그림만 다시(`base != null && targets != null`)면 앞표지는 `base` 것, 뒤표지는 `targets`에 마지막 쪽이 있을 때만 새로. `Cost`의 그림 수 `pageCount + 2` → `pageCount + 4`(쪽 + 시트 + 표지 3).
- [ ] **Step 4: 통과 확인** — Step 2 명령, Expected: BUILD SUCCESSFUL
- [ ] **Step 5: 커밋** `sh ./gradlew build && git commit -m "feat(generation): AI 결과의 앞·뒤표지 key를 버전에 저장 (#61)"`

### Task 4: 백엔드 — 그림 API와 응답 주소, 문서

**Files:**
- Modify: `StoryImageUrls.java`(`frontCover(storyId, versionId)`, `backCover(...)`), `StoryImageService.java`(`frontCover`, `backCover`, `cover`와 같은 확인), `StoryImageController.java`(`@GetMapping("/front-cover")`, `"/back-cover"`, `@Operation` 한국어 요약 "앞표지", "뒤표지", 설명 "쪽과 같은 1920×1088. 없는 버전이면 IMAGE_NOT_FOUND"), `PreviewResponse.java`, `BookResponse.java`(필드 `frontCoverUrl`, `backCoverUrl`, 기존 `coverUrl` 뒤), 문서 3곳
- Test: `GenerationIntegrationTest`, `ReadingIntegrationTest`

**Interfaces:**
- Consumes: Task 3의 `getFrontCoverKey()`, `getBackCoverKey()`
- Produces: 응답 `frontCoverUrl` = `/api/stories/{id}/versions/{versionId}/front-cover` 또는 null, `backCoverUrl` 같은 방식

- [ ] **Step 1: 테스트를 쓴다**
  - `미리보기는_10쪽이고_주소에_파일_key나_경로가_없다`(160줄)에 `$.frontCoverUrl` = `storyUrl(id) + "/versions/" + versionId + "/front-cover"`, `$.backCoverUrl`도 같게. 같은 테스트 끝(정사각형 1024 확인 옆)에 `/front-cover`, `/back-cover`가 200, `image/png`, `nosniff`, 1920×1088
  - `GenerationIntegrationTest.앞뒤표지가_없는_버전은_주소가_null이고_그림은_404()` — `UPDATE story_versions SET front_cover_key = NULL, back_cover_key = NULL` 뒤 미리보기 두 필드 null, 두 그림 API 404 `IMAGE_NOT_FOUND`
  - 그림 API 404 테스트(`그림_API는_내_동화의_버전과_쪽이_아니면_404`)에 다른 회원·다른 버전의 `/front-cover`, `/back-cover`
  - `ReadingIntegrationTest`의 `/book` 응답 확인에 `$.frontCoverUrl`, `$.backCoverUrl` 주소
- [ ] **Step 2: 실패 확인** — `sh ./gradlew test --tests '*GenerationIntegrationTest' --tests '*ReadingIntegrationTest' --tests '*OpenApiDocsTest'`, Expected: 새 필드 없음으로 실패
- [ ] **Step 3: 구현과 문서**
  - 응답 record 주석: "앞표지(쪽과 같은 크기, 제목 포함). 없으면(이전 버전, 표지 실패) null", "뒤표지(글자 없음). 없으면 null"
  - `docs/FIRSTORY-AI-API-SPEC-v0.3.md` 결과 예시(308줄)와 설명(324줄 옆)에 두 키와 다시 만들기 규칙(Global Constraints 그대로), 파일 트리(403줄)에 `front-cover.webp`, `back-cover.webp`
  - `docs/frontend/screens.md` 미리보기(255줄)·함께 읽기(361줄) 표에 두 필드, "null이면 표지 없이 1쪽부터"
  - CLAUDE.md "파일 저장소와 그림 API"의 key 형식과 그림 API 목록에 두 가지
- [ ] **Step 4: 통과 확인** — `sh ./gradlew build`, Expected: BUILD SUCCESSFUL
- [ ] **Step 5: 커밋·PR·합치기** — `sh ./gradlew build && git commit -m "feat(generation): 앞·뒤표지 그림 API와 미리보기·책 응답 주소 (#61)"` → PR `feat(generation): 동화책 앞표지·뒤표지 저장하고 그림 API와 응답 주소로 내려주기`(`Closes #61`) → 합치기 → EC2 배포 확인

### Task 5: 진짜 모델로 한 편 확인 (사용자에게 묻고)

- [ ] **Step 1:** 사용자에게 "로컬에서 진짜 모델로 한 편, 약 900원" 묻는다. 예면 Spring(local, `AI_MODE=http`) + AI 워커(진짜 모델)로 한 편 만든다.
- [ ] **Step 2:** 정사각형·앞표지·뒤표지 세 장과 쪽 10장, 첫 생성 시간, `99-cost.json`의 `illustrate:front_cover`·`back_cover` 토큰과 금액을 그대로 보여 준다(앱 화면처럼 보이는 HTML, 판단은 사용자).
- [ ] **Step 3:** 프론트 팀원 알림 문구(배포됨, 새 필드, null이면 표지 없이)를 사용자에게 준다. NEXT-STEPS.md 갱신.
