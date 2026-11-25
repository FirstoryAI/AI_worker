# Claude 작업 규칙

커밋·브랜치·PR 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)를 따른다.

## PR 올리기 전 code-simplifier 점검

브랜치 → PR로 가는 작업은 PR을 올리기 전에 반드시 아래 순서를 거친다. `main`에 바로 커밋하는 작은 변경은 건너뛴다.

1. `code-simplifier:code-simplifier` 에이전트를 부른다. 범위는 이번 브랜치에서 바뀐 코드만(`git diff main...HEAD`). 레포 전체를 고치지 않는다. 이 에이전트가 없으면(플러그인 미설치) 이 점검은 건너뛰고, PR 본문 "참고할 점"에 "code-simplifier 점검: 플러그인 없어서 건너뜀"이라고 적는다
2. 동작은 그대로 둔다. API 요청·응답, interrupt payload, 저장 경로, 출력은 바뀌면 안 된다
3. `src/firstory/prompts/*.md`(프롬프트)는 건드리지 않는다. 문구가 바뀌면 동화 출력이 바뀐다
4. 고친 게 있으면 `uv run python evals/mock_run.py`를 다시 돌리고, 통과해야 PR을 올린다
5. 정리한 내용은 기능 커밋과 나눠 `refactor: ...` 커밋으로 남기고, PR 본문 "참고할 점"에 한 줄로 적는다. 고칠 게 없었으면 "code-simplifier 점검: 고칠 것 없음"이라고 적는다
