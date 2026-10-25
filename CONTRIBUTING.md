# 커밋 규칙

[이 글](https://velog.io/@shin6403/Git-git-%EC%BB%A4%EB%B0%8B-%EC%BB%A8%EB%B2%A4%EC%85%98-%EC%84%A4%EC%A0%95%ED%95%98%EA%B8%B0) 기준 + AI 프로젝트용 타입 2개 추가.

## 형식

```
<type>: <제목>

<본문>  (선택)

<꼬리말>  (선택)
```

- **제목** 50자 이내, 마침표·특수기호 없이. 한국어 OK. "무엇을 했다"가 바로 보이게
- **본문** 한 줄 72자. 무엇을·왜. 어떻게는 코드가 말해줌
- **꼬리말** `Resolves #12`, `Ref #7`

## type

| type | 언제 | 예 |
|---|---|---|
| `feat` | 새 기능 — 노드 추가, 뷰어 기능, 스키마 필드 | `feat: 조연 캐릭터 시트 추가` |
| `fix` | 버그 수정 | `fix: gpt-image-2에서 input_fidelity 제거` |
| `prompt` | **프롬프트 수정** — 코드는 그대로, 출력이 바뀜. `src/firstory/prompts/*.md` | `prompt: 독서 가이드 질문 기본 2개로 제한` |
| `data` | **입력 케이스·PM 샘플** 추가/수정. `datasets/` | `data: 태권도 과자 케이스 추가` |
| `docs` | 문서만 | `docs: OVERVIEW 비용 수치 갱신` |
| `refactor` | 구조 변경, 동작 동일 | `refactor: 인터뷰 노드 3개로 분리` |
| `test` | 테스트·평가 스크립트. `evals/` | `test: mock_run에 조연 시트 검증 추가` |
| `chore` | 패키지·설정·모델 ID | `chore: MODEL_MAIN을 gpt-5.5로` |
| `style` | 포맷팅 | |

`prompt`를 따로 둔 이유: "언제부터 동화 톤이 바뀌었지?" 할 때 `git log --grep '^prompt'`로 바로 찾기 위해서. 프롬프트와 코드를 같이 고쳤으면 커밋을 나눈다.

## 템플릿 걸기 (클론 후 한 번)

```bash
git config commit.template .gitmessage.txt
```

이후 `git commit` (옵션 없이) 치면 템플릿이 열림. `-m`으로 바로 써도 됨.

## 브랜치

- `main` — 돌아가는 상태 유지. 커밋 전에 `evals/mock_run.py`가 통과해야 함
- 브랜치는 최신 `main`에서 딴다. 이름은 `<타입>/<짧은-설명>`
  - 타입은 커밋 타입과 같게: `feat`, `fix`, `prompt`, `data`, `docs`, `refactor`, `test`, `chore`
  - 설명은 영어 소문자·숫자·하이픈만: `feat/supporting-character-sheet`, `prompt/guide-question-count`
  - 한글은 쓰지 않는다. 주소에서 `%EC%AA%BD…`처럼 인코딩되고, 일부 도구에서 깨지고, 터미널에서 치기 불편하다
- 열린 PR의 브랜치 이름은 바꾸지 않는다. GitHub는 head 브랜치 이름을 바꾸면 그 PR을 닫는다

언제 PR로 올리나:

| 변경 | 방식 |
|---|---|
| 백엔드가 기대는 것 — API 요청·응답, interrupt payload·재개 값, 결과물 저장 경로, 쪽수 | 브랜치 → PR |
| 크고 커밋이 여러 개인 작업 — FastAPI API, 새 노드 | 브랜치 → PR |
| 이 저장소 안에서만 끝나는 작은 변경 — 프롬프트 조정, 문서 오타, 테스트 추가 | `main`에 바로 커밋 |

애매하면 PR. 백엔드 저장소(`Backend_Mainpage`)와 API 스펙(`docs/FIRSTORY-AI-API-SPEC-v0.3.md`, 백엔드 저장소에 있음)을 바꿀 때도 PR.

PR:
- 본문은 `.github/pull_request_template.md` 틀(무엇을 바꿨나 / 참고할 점 / 확인 방법), 합니다체. 그 PR의 변경만 쓴다
- 합칠 때는 일반 merge 커밋 — squash하지 않는다 (프롬프트·코드 커밋을 나눠 둔 게 남게)
- 확인을 기다리며 오래 열어 두지 않는다. 합친 뒤 백엔드 쪽에서 고칠 게 생기면 노션 "백엔드 작업목록"에 항목으로 적는다
