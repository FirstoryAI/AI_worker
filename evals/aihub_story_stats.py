"""
AI Hub '생성형AI 동화 줄거리 생성 데이터'(dataSetSn=71696) 유아 라벨링 데이터 → 집계 통계.
(python evals/aihub_story_stats.py <라벨링데이터 폴더> [--out stats.json])

출력은 숫자뿐이다. 원문(srcText)·라벨 문자열은 찍지 않는다 — 약관상 원문은 로컬 밖으로 내보내지 않는다.
데이터는 저장소 밖에 둔다. 출처: 한국지능정보사회진흥원(NIA) AI Hub.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

ELEMENTS = ["character", "setting", "action", "feeling", "causalRelationship", "outcomeResolution", "prediction"]
BINS = 8  # 우리 동화가 8페이지 — 책 진행도를 8구간으로 환산

_SENT = re.compile(r"[^.!?…]+[.!?…]+[\"”’']?")
_QUOTE = re.compile(r"[\"“”]")
_REDUP = re.compile(r"([가-힣]{2})\1")            # 콩닥콩닥, 살랑살랑 — 의성어·의태어 근사치
_POLITE = re.compile(r"(요|죠)[.!?…]*[\"”’']?$")   # ~어요/~지요
_PLAIN = re.compile(r"다[.!?…]*[\"”’']?$")         # ~다
_DIALOGUE = re.compile(r"[\"“][^\"”]*[\"”]")


def _q(a: list[float]) -> dict | None:
    if not a:
        return None
    a = sorted(a)

    def pick(p: float) -> float:
        return a[min(len(a) - 1, int(p * len(a)))]

    return {"n": len(a), "p10": pick(.1), "median": st.median(a), "mean": round(st.mean(a), 2), "p90": pick(.9)}


def _pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def _has(v) -> bool:
    return bool(v and str(v).strip())


def _ending(sent: str) -> str:
    if _POLITE.search(sent):
        return "polite(~요)"
    if _PLAIN.search(sent):
        return "plain(~다)"
    return "other"


def _summary_items(ps) -> list:
    """plotSummaryInfo는 목록일 때도, 하나짜리 dict일 때도 있다."""
    if isinstance(ps, list):
        return ps
    if isinstance(ps, dict):
        return [ps]
    return []


def analyze(books: list[dict]) -> dict:
    n_books = len(books)
    paras_per_book, sents_per_para, words_per_para, words_per_sent = [], [], [], []
    book_has = Counter()                      # 요소가 한 번이라도 나오는 책
    para_has = Counter()                      # 요소가 붙은 단락
    first_pos = defaultdict(list)             # 요소 첫 등장 위치 (0~1)
    by_bin = defaultdict(lambda: [0] * BINS)  # 구간별 요소 등장 단락 수
    bin_total = [0] * BINS
    outcome_in_last, outcome_final_para = 0, 0
    elems_per_para = []
    n_para = quote_para = redup_para = question_para = 0
    sent_end = Counter()
    narr_sents = 0
    summary_meta = defaultdict(Counter)

    for b in books:
        paras = b.get("paragraphInfo") or []
        paras_per_book.append(len(paras))
        seen = set()
        for i, p in enumerate(paras):
            n_para += 1
            pos = i / max(1, len(paras) - 1)
            k = min(BINS - 1, int(pos * BINS))
            bin_total[k] += 1
            present = [e for e in ELEMENTS if _has(p.get(e))]
            elems_per_para.append(len(present))
            for e in present:
                para_has[e] += 1
                by_bin[e][k] += 1
                if e not in seen:
                    seen.add(e)
                    first_pos[e].append(pos)
            s, w = p.get("srcSentenceEA"), p.get("srcWordEA")
            if isinstance(s, int) and s > 0:
                sents_per_para.append(s)
                if isinstance(w, int):
                    words_per_para.append(w)
                    words_per_sent.append(w / s)
            text = p.get("srcText") or ""
            if _QUOTE.search(text):
                quote_para += 1
            if _REDUP.search(text):
                redup_para += 1
            if "?" in text:
                question_para += 1
            narration = _DIALOGUE.sub(" ", text)  # 대사 빼고 지문만
            for sent in _SENT.findall(narration):
                narr_sents += 1
                sent_end[_ending(sent.strip())] += 1
            for item in _summary_items(p.get("plotSummaryInfo")):
                for f in ("classification", "readAge", "form"):
                    summary_meta[f][str(item.get(f))] += 1
        for e in seen:
            book_has[e] += 1
        tail = paras[int(len(paras) * 0.75):]
        if any(_has(p.get("outcomeResolution")) for p in tail):
            outcome_in_last += 1
        if paras and _has(paras[-1].get("outcomeResolution")):
            outcome_final_para += 1

    return {
        "books": n_books,
        "paragraphs": n_para,
        "paragraphs_per_book": _q(paras_per_book),
        "sentences_per_paragraph": _q(sents_per_para),
        "words_per_paragraph": _q(words_per_para),
        "words_per_sentence": _q([round(x, 2) for x in words_per_sent]),
        "elements": {
            e: {
                "books_with_pct": _pct(book_has[e], n_books),
                "paragraphs_with_pct": _pct(para_has[e], n_para),
                "first_appearance_pos": _q([round(x, 3) for x in first_pos[e]]),
                f"share_by_{BINS}bins_pct": [_pct(by_bin[e][k], bin_total[k]) for k in range(BINS)],
            }
            for e in ELEMENTS
        },
        "elements_per_paragraph": _q(elems_per_para),
        "outcome": {
            "books_with_outcome_in_last_quarter_pct": _pct(outcome_in_last, n_books),
            "books_with_outcome_in_final_paragraph_pct": _pct(outcome_final_para, n_books),
        },
        "style": {
            "paragraphs_with_dialogue_pct": _pct(quote_para, n_para),
            "paragraphs_with_reduplication_pct": _pct(redup_para, n_para),
            "paragraphs_with_question_mark_pct": _pct(question_para, n_para),
            "narration_sentence_endings_pct": {k: _pct(v, narr_sents) for k, v in sent_end.most_common()},
        },
        "summary_meta": {f: dict(c.most_common(8)) for f, c in summary_meta.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", type=Path, help="압축 푼 02.라벨링데이터 폴더 (TL_*_유아/ 들이 있는 곳)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    groups: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(args.data_dir.rglob("*.json")):
        topic = f.relative_to(args.data_dir).parts[0]
        topic = re.sub(r"^[TV]L_\d+T_|_\d+S_.*$", "", topic)
        groups[topic].append(json.loads(f.read_text(encoding="utf-8")))

    result = {"all": analyze([b for g in groups.values() for b in g])}
    result.update({topic: analyze(books) for topic, books in groups.items()})
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
