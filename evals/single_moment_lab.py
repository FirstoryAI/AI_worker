"""
한 쪽 그림에 장면이 두 개 그려지는 문제 실험 (#110): 저장된 지시문 그대로 한 쪽을 고치기 전·후 그림 지시로 여러 장 그려 HTML로 비교한다.

  uv run python evals/single_moment_lab.py <실행 폴더> <쪽 번호> [--old N] [--new N] [--out 이름]

실행 폴더: 03-story.json, 05-illustrations.json(text_blocks), 시트 그림(sheet-*.webp, images/ 아래 또는 바로 아래).
'고치기 전'은 지금 지시에서 #110이 더한 문장만 뺀 것이다. 원고(image_prompt)는 둘 다 저장된 그대로(나쁜 지시문)라 그림 지시만의 효과를 본다.
그림 한 장에 약 40원(쪽 그림, 시트 첨부).
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstory.nodes import illustrate as il  # noqa: E402
from firstory.nodes.layout import block_size  # noqa: E402
from firstory.schemas import StoryText  # noqa: E402

BOTH_NEW = ("the second one within the right half (not across the vertical center); "
            "both are just empty parts of the same single scene, not two separate pages. ")
BOTH_OLD = "the second one within the right half (not across the vertical center). "


def old_prompt(new: str, chars) -> str:
    single = il.single_moment(chars)
    assert single in new, "지금 지시가 #110 문장을 안 가짐"
    return new.replace(single + "\n", "").replace(BOTH_NEW, BOTH_OLD)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("page", type=int)
    ap.add_argument("--old", type=int, default=1)
    ap.add_argument("--new", type=int, default=3)
    ap.add_argument("--out", default="single-moment")
    a = ap.parse_args()

    story = StoryText.model_validate_json((a.src / "03-story.json").read_text(encoding="utf-8"))
    ill = json.loads((a.src / "05-illustrations.json").read_text(encoding="utf-8"))
    p = next(x for x in story.pages if x.order == a.page)
    pi = next(x for x in ill["pages"] if x["order"] == a.page)
    blocks = [tb["paragraphs"] for tb in pi["text_blocks"]]
    by_name = {c.name: c for c in story.characters}
    chars = [by_name[n] for n in p.characters_in_scene if n in by_name]
    sheets = {unicodedata.normalize("NFC", f.name): f for f in [*a.src.glob("sheet-*.webp"), *a.src.glob("images/sheet-*.webp"), *a.src.glob("*sheet-*.webp")]}
    refs = []
    for c in chars:
        f = next(v for k, v in sheets.items() if unicodedata.normalize("NFC", c.name) in k)
        refs.append((f"{il._safe(c.name)}.png", il._ref(f.read_bytes())))

    new = il.page_prompt(story, chars, p.image_prompt, [block_size(b) for b in blocks])
    prompts = {"old": old_prompt(new, chars), "new": new}
    out = ROOT / "out" / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompts.json").write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")

    jobs = [("old", i) for i in range(a.old)] + [("new", i) for i in range(a.new)]

    def draw(job):
        kind, i = job
        img, tin, tout = il._edit(prompts[kind], refs)
        name = f"{kind}-{i + 1}.{il._ext(img)}"
        (out / name).write_bytes(img)
        print(f"{name}: 입력 {tin} 출력 {tout}", flush=True)
        return kind, name

    with ThreadPoolExecutor(len(jobs)) as ex:
        done = list(ex.map(draw, jobs))

    rows = "".join(
        f"<h2>{'고치기 전' if k == 'old' else '고친 뒤'}</h2>" + "".join(f'<img src="{n}">' for kk, n in done if kk == k)
        for k in ("old", "new"))
    (out / "index.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>한 순간 실험</title><style>body{{font-family:sans-serif;margin:16px}}"
        f"img{{width:48%;margin:4px}}pre{{white-space:pre-wrap;background:#f4f4f4;padding:8px}}</style>"
        f"<h1>{html.escape(story.title)} {a.page}쪽</h1><pre>{html.escape(p.image_prompt)}</pre>{rows}", encoding="utf-8")
    print(out / "index.html")


if __name__ == "__main__":
    main()
