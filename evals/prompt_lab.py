"""
프롬프트 전략별로 동화(텍스트)를 뽑고 채점해서 나란히 본다. 뷰어 '프롬프트 실험' 화면과 같은 일.
  uv run python evals/prompt_lab.py out/<기준 실행 폴더>                 # 전략 전부 (기본·상황별 흐름·엔진·설계 예시·반복·전부)
  uv run python evals/prompt_lab.py out/<기준 실행 폴더> --presets base engine motif
  uv run python evals/prompt_lab.py datasets/inputs/byeol.json         # 기준 실행이 없으면 먼저 만든다 (텍스트만)
결과: out/lab/<시각>_<샘플>/compare.md  (뷰어 '프롬프트 실험' → 지난 실험에서도 보인다)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firstory import lab  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", type=Path, help="기준 실행 폴더 (00-context·01-interview 있는) 또는 datasets/inputs/*.json")
    ap.add_argument("--presets", nargs="+", choices=list(lab.PRESETS), default=list(lab.PRESETS))
    ap.add_argument("--no-judge", action="store_true", help="채점 건너뛰기")
    ap.add_argument("--workers", type=int, default=3, help="동시에 돌릴 전략 수")
    args = ap.parse_args()

    base = args.base
    if base.suffix == ".json":
        print(f"기준 실행 만드는 중: {base.stem} (텍스트만)")
        base = lab.make_base(base)
        print("  →", base)

    def done(k, err):
        if err:
            print(f"  ✗ {lab.PRESETS[k][0]}  {err}")
        else:
            print(f"  ✓ {lab.PRESETS[k][0]}")

    exp = lab.run_experiment(base, args.presets, judge_on=not args.no_judge, workers=args.workers, on_done=done)
    print("→", exp / "compare.md")


if __name__ == "__main__":
    main()
