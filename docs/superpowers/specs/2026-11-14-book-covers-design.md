# 동화책 앞표지·뒤표지 (설계, 2026-11-14)

관련: [Backend_Mainpage#61](https://github.com/FirstoryAI/Backend_Mainpage/issues/61) (프론트 팀원 요청)

## 왜
함께 읽기·미리보기에서 책 맨 앞에 앞표지, 맨 뒤에 뒤표지를 넣어 진짜 책처럼 보이게 한다.
지금 표지는 정사각형(1024×1024)이라, 펼친 두 쪽 크기(1920×1088)인 쪽 그림 사이에 넣을 수 없다.

## 정한 것 (사용자)
- 표지는 한 편에 **3장**: 정사각형(서재 카드용, 지금 그대로) + 앞표지 + 뒤표지
- 앞표지: 제목 글자 + 주인공, **정사각형 표지를 참고 그림으로 넣어 같은 장면을 가로로 넓혀 그린다** (카드 표지와 책 첫 장이 같은 그림처럼 보이게). 정사각형이 실패하면 캐릭터 시트만으로 따로 그린다
- 뒤표지: 이야기를 마무리하는 그림, 글자 없음 → **11/14 변경(AI_worker#90)**: 실제 그림책처럼 빈 바탕에 주인공 혼자 작게(인사하는 자세), 참고 그림은 주인공 시트 1장. 마지막 쪽 장면을 다시 그리면 10쪽과 겹쳐서
- 표지 그림이 실패하면 **AI가 그 그림만 바로 한 번 더** 그린다. 그래도 실패하면 null이고 동화는 정상 완성 (프론트는 표지 없이 1쪽부터)
- 샘플 동화 8편(#45)에는 지금 넣지 않는다
- `story_versions`에 칸 2개 추가 (ERD에는 팀원이 추가)
- 비용: 한 편에 약 55~85원 더 (그림 2장, 지금 한 편 약 600~850원). 이미지 모델은 지금 그대로 gpt-image-2 (Flare 비교는 따로)

## 방법 (고른 것: 2)
1. 앞표지를 정사각형 표지와 같은 지시문으로 따로 그리기 — 가장 단순하지만 카드 표지와 책 첫 장의 구도가 달라 다른 그림 두 장처럼 보인다
2. **정사각형 표지를 참고 그림으로 넣어 넓혀 그리기 (선택)** — 카드에서 본 표지가 책에서도 그대로. 정사각형을 기다리는 동안 쪽 그림을 그리므로 전체 시간은 1과 거의 같다. 참고 그림이 하나 늘어 장당 약 10원 더

## AI 워커 (`Firstory_AI_pipeline`)
- `Illustrations`에 `front_cover`, `back_cover` (key, 실패면 None)
- `illustrate.py`
  - 정사각형 `cover()`가 끝나면 앞표지 작업을 같은 풀에 넣는다. 참고 그림 = 정사각형 표지 + 캐릭터 시트. 정사각형이 없으면 캐릭터 시트만
  - 뒤표지는 처음부터 같은 풀에 넣는다. 참고 그림 = 캐릭터 시트, 장면 = 마지막 쪽 장면을 바탕으로 마무리하는 그림
  - 크기는 쪽과 같은 `IMAGE_SIZE`(1920×1088). 콘텐츠 정책에 막히면 지금처럼 장면을 순화해 다시(`_draw`)
  - 실패하면 한 번 더 그리고, 그래도 실패하면 None
- 다시 만들 때
  - 앞표지: 정사각형을 새로 그릴 때만 같이 새로 (처음부터 다시, 그림만 다시 전체, 제목이 바뀐 글 다시). 아니면 이전 key
  - 뒤표지: 처음부터 다시, 그림만 다시 전체일 때만 새로. 아니면 이전 key (#90부터 마지막 쪽과 상관없음)
  - 이전 버전에 앞·뒤표지가 없으면(배포 전 동화) 다시 만들 때 그린다
- 결과 API(`/result`)에 `front_cover_path`, `back_cover_path`. `mock.py`도 두 key를 만든다
- 비용 기록에 `illustrate:front_cover`, `illustrate:back_cover`
- **제 판단**: 실패 시 한 번 더 그리기는 정사각형 표지에도 같이 넣는다 (정사각형이 살아야 앞표지가 같은 그림이 된다)

## 백엔드 (`Backend_Mainpage`)
- `V14__version_book_covers.sql`: `story_versions.front_cover_key`, `back_cover_key` (varchar(255), null 가능)
- `HttpAiClient`가 두 key를 읽고 `AiGenerationResult`에 담는다. key 위치 검사(`stories/{storyId}/` 아래)에 두 key도 넣는다
- `GenerationResultRecorder`가 버전에 저장
- 그림 API: `GET /api/stories/{id}/versions/{versionId}/front-cover`, `/back-cover` (정사각형 `/cover`와 같은 확인·헤더). 없으면 404
- 응답: `BookResponse`, `PreviewResponse`에 `frontCoverUrl`, `backCoverUrl`. 없으면 null
- `FakeAiClient`도 1920×1088 PNG 두 장을 만든다
- 문서: AI 스펙(`docs/FIRSTORY-AI-API-SPEC-v0.3.md` 결과 형식), `docs/frontend/screens.md`(미리보기·함께 읽기), CLAUDE.md

## 배포
- 두 저장소 어느 쪽이 먼저 나가도 깨지지 않는다 (Spring은 키가 없으면 null, AI가 먼저면 Spring이 새 키를 무시)
- 둘 다 나간 뒤 새로 만든 동화부터 주소가 생긴다. 프론트(팀원)에 배포 시점을 알린다

## 확인
- AI: mock 테스트, 다시 만들기 규칙(앞·뒤표지 유지·새로) 단위 테스트
- 백엔드: `./gradlew build` (Flyway V14, 결과 저장, 그림 API, 응답 null·있음)
- 진짜 모델로 로컬에서 한 편 만들어 세 표지와 시간·비용을 보여 준다 (한 편 약 900원). 만들기 전에 다시 묻는다

## 빌더에게 맡긴 것
- 앞·뒤표지 지시문 문장 (위 방향 안에서)
- 테스트 이름과 나누기
