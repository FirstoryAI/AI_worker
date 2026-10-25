"""
같은 원고·같은 그림 지시문으로 IMAGE_QUALITY만 바꿔 다시 그려 나란히 본다.
  IMAGE_QUALITY=low uv run python evals/compare_image_quality.py out/<기준 실행 폴더>

결과: <기준 폴더>__<quality>/images/ 와 out/compare-quality-<이름>.jpg (왼쪽 기준, 오른쪽 새 품질)
분당 이미지 한도(429)에 걸린 페이지는 잠시 쉬었다가 그 페이지만 다시 그린다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firstory.config import config  # noqa: E402
from firstory.nodes import illustrate as ill  # noqa: E402
from firstory.schemas import StoryText  # noqa: E402


def draw(a_dir: Path) -> tuple[Path, float, int]:
    story = StoryText(**json.loads((a_dir / "03-story.json").read_text(encoding="utf-8")))
    out = a_dir.with_name(f"{a_dir.name}__{config.image_quality}") / "images"
    key = out.resolve().relative_to(config.output_root.resolve()).as_posix()   # 기준 폴더가 저장소 루트(out/) 아래여야 한다
    t0, made = time.time(), 0
    result, costs = ill._run(story, key)
    made += sum(c.images for c in costs)
    for _ in range(6):
        failed = {p.order for p in result.pages if p.status != "completed"}
        if not failed:
            break
        time.sleep(65)
        result, costs = ill._run(story, key, only_pages=failed, prev=result)
        made += sum(c.images for c in costs)
    return out, time.time() - t0, made


def sheet(a_img: Path, b_img: Path, dest: Path, b_label: str):
    names = sorted(p.name for p in b_img.glob("page-*.png"))
    S, G, H = 768, 12, 36
    im = Image.new("RGB", (2 * S + 3 * G, len(names) * (S + H + G) + G), "white")
    d = ImageDraw.Draw(im)
    for r, name in enumerate(names):
        y = G + r * (S + H + G)
        for c, (folder, label) in enumerate(((a_img, "medium"), (b_img, b_label))):
            x = G + c * (S + G)
            d.text((x + 4, y + 10), f"{label}  {name}", fill="black")
            f = folder / name
            if f.exists():
                im.paste(Image.open(f).convert("RGB").resize((S, S), Image.LANCZOS), (x, y + H))
            else:
                d.text((x + 4, y + H + 20), "(none)", fill="gray")
    im.save(dest, quality=88)


def main():
    a_dir = Path(sys.argv[1])
    out, sec, made = draw(a_dir)
    dest = a_dir.parent / f"compare-quality-{a_dir.name.split('_', 1)[-1]}.jpg"
    sheet(a_dir / "images", out, dest, config.image_quality)
    print(f"quality={config.image_quality} images={made} {sec:.0f}s → {dest}")


if __name__ == "__main__":
    main()
