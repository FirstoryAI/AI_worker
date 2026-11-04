"""
같은 원고·같은 그림 지시문으로 화풍(style_guide)만 바꿔 다시 그려 나란히 본다.
  uv run python evals/compare_style.py out/<실행 폴더> [out/<실행 폴더> ...]

전: 원고에 저장된 style_guide, 후: prompts/write_story.md의 지금 문장. 둘 다 지금 코드로 새로 그린다 (시트부터).
결과: <폴더>__style-before/images/, <폴더>__style-after/images/, out/compare-style-<이름>.jpg (왼쪽 전, 오른쪽 후)
분당 이미지 한도(429)에 걸린 그림은 잠시 쉬었다가 그 쪽만 다시 그린다.
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firstory.config import config  # noqa: E402
from firstory.nodes import illustrate as ill  # noqa: E402
from firstory.schemas import StoryText  # noqa: E402

PROMPT = Path(__file__).resolve().parents[1] / "src/firstory/prompts/write_story.md"


def new_style() -> str:
    m = re.search(r"`style_guide`[^\n]*\n\s*\"([^\"]+)\"", PROMPT.read_text(encoding="utf-8"))
    return m.group(1)


def draw(story: StoryText, out: Path) -> int:
    key = out.resolve().relative_to(config.output_root.resolve()).as_posix()   # 기준 폴더가 결과물 루트 아래여야 한다
    result, costs = ill._run(story, key)
    made = sum(c.images for c in costs)
    for _ in range(6):
        failed = {p.order for p in result.pages if p.status != "completed"}
        if not failed and result.cover:
            break
        time.sleep(65)
        result, costs = ill._run(story, key, only_pages=failed, prev=result)
        made += sum(c.images for c in costs)
    return made


def sheet(a_img: Path, b_img: Path, dest: Path):
    names = ["cover"] + sorted({p.stem for p in b_img.glob("page-*")})
    W, G, H = 768, 12, 36
    rows = []
    for name in names:
        pair = [next(iter(sorted(d.glob(f"{name}.*"))), None) for d in (a_img, b_img)]
        size = Image.open(pair[1] or pair[0]).size if any(pair) else (W, W)
        rows.append((name, pair, round(W * size[1] / size[0])))
    im = Image.new("RGB", (2 * W + 3 * G, sum(h + H + G for *_, h in rows) + G), "white")
    d = ImageDraw.Draw(im)
    y = G
    for name, pair, h in rows:
        for c, (f, label) in enumerate(zip(pair, ("before", "after"))):
            x = G + c * (W + G)
            d.text((x + 4, y + 10), f"{label}  {name}", fill="black")
            if f:
                im.paste(Image.open(f).convert("RGB").resize((W, h), Image.LANCZOS), (x, y + H))
            else:
                d.text((x + 4, y + H + 20), "(none)", fill="gray")
        y += h + H + G
    im.save(dest, quality=88)


def main():
    after = new_style()
    for a_dir in map(Path, sys.argv[1:]):
        story = StoryText(**json.loads((a_dir / "03-story.json").read_text(encoding="utf-8")))
        if story.style_guide == after:
            sys.exit(f"{a_dir}: 원고의 style_guide가 이미 새 문장이다 — 전·후가 같다")
        runs = {"before": story, "after": story.model_copy(update={"style_guide": after})}
        outs = {k: a_dir.with_name(f"{a_dir.name}__style-{k}") / "images" for k in runs}
        t0 = time.time()
        with ThreadPoolExecutor(2) as ex:
            made = dict(zip(runs, ex.map(lambda k: draw(runs[k], outs[k]), runs)))
        dest = a_dir.parent / f"compare-style-{a_dir.name}.jpg"
        sheet(outs["before"], outs["after"], dest)
        print(f"{story.title}: images before={made['before']} after={made['after']} {time.time() - t0:.0f}s → {dest}")


if __name__ == "__main__":
    main()
