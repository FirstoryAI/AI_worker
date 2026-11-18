"""
생성 동화의 형식을 AI Hub 유아 그림책(사회관계 51권) 분포와 나란히 본다. API 호출 없음.
  uv run python evals/story_form_check.py out/<실행 폴더> [...]

기준 수치는 evals/aihub_story_stats.py 결과(EVIDENCE.md §1)에서 숫자만 옮긴 것. 원문은 쓰지 않는다.
"실제 그림책이 이렇다"이지 "이래야 좋다"는 아니다 — 크게 벗어난 것만 눈여겨본다.
사람 등장·문체 예시 이름 복사처럼 규칙 위반은 따로 표시한다.
"""
from __future__ import annotations

import json
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from aihub_story_stats import _PLAIN, _POLITE, _QUOTE, _REDUP, _SENT  # noqa: E402

# 사회관계 유아 그림책 (median 또는 %). 출처: EVIDENCE.md §1
REF = {"어절/문장": 7.0, "문장/쪽": 3.0, "대사 쪽 %": 58.0, "의성어 쪽 %": 7.1, "지문 ~요 %": 72.9}

_HUMAN_KO = re.compile(r"사람|아저씨|아줌마")
# child/kid는 종 없이 쓰였을 때만 ("rabbit child"는 통과, "both children"은 걸림)
_HUMAN_EN = re.compile(r"(?<!no )\b(people|person|man|woman|boys?|girls?|human)\b"
                       r"|\b(?:the|a|an|both|two|three|other|some|small|little|young|of)\s+(?:kids?|child(?:ren)?)\b", re.I)


def check(run: Path) -> dict:
    story = json.loads((run / "03-story.json").read_text(encoding="utf-8"))
    pages = [p["text"].replace("**", "") for p in story["pages"]]  # 의성어 강조 표시 제거
    words, sents, polite, plain = [], [], 0, 0
    for t in pages:
        ss = [s.strip() for s in _SENT.findall(t) if s.strip()]
        sents.append(len(ss))
        words += [len(s.split()) for s in ss]
        for s in _SENT.findall(re.sub(r"[\"“][^\"”]*[\"”]", " ", t)):   # 지문만 (따옴표 대사 빼고)
            s = s.strip()
            polite += bool(_POLITE.search(s))
            plain += bool(_PLAIN.search(s))

    def pct(k: int) -> float:
        return round(100 * k / len(pages), 1)

    issues = []
    names = [c.get("name", "") for c in story.get("characters", [])]
    if "토리" in names or any("토리" in t for t in pages):
        issues.append("문체 예시 이름 '토리' 사용")
    ko = sorted({m for t in pages for m in _HUMAN_KO.findall(t)})
    en = sorted({m.lower() for p in story["pages"] for m in (x.group(0) for x in _HUMAN_EN.finditer(p.get("image_prompt", "")))})
    if ko or en:
        issues.append("사람 단어: " + ", ".join(ko + en))
    return {
        "제목": story["title"],
        "어절/문장": st.median(words) if words else 0,
        "문장/쪽": st.median(sents) if sents else 0,
        "대사 쪽 %": pct(sum(bool(_QUOTE.search(t)) for t in pages)),
        "의성어 쪽 %": pct(sum(bool(_REDUP.search(t)) for t in pages)),
        "지문 ~요 %": round(100 * polite / max(1, polite + plain), 1),
        "규칙 위반": "; ".join(issues) or "-",
    }


def main():
    rows = [(Path(a).name, check(Path(a))) for a in sys.argv[1:]]
    cols = list(REF) + ["규칙 위반"]
    print("| 실행 | 제목 | " + " | ".join(cols) + " |")
    print("|---" * (len(cols) + 2) + "|")
    print("| 그림책 기준 (사회관계) | | " + " | ".join(str(REF[c]) for c in REF) + " | |")
    for name, r in rows:
        print(f"| {name} | {r['제목']} | " + " | ".join(str(r[c]) for c in cols) + " |")


if __name__ == "__main__":
    main()
