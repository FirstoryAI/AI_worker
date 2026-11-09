"""인터뷰 다음 질문을 같은 상황에서 프롬프트·reasoning 안별로 다시 만들어 시간과 결과를 비교한다 (#82).
입력: 개발 서버 체크포인트에서 뽑은 interview_step 직전 상태 목록(JSON). 출력: 결과 JSON + 나란히 보는 markdown.
  uv run python evals/interview_variants.py steps.json out/interview-variants [2026-11-06T15]
"""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from firstory import llm
from firstory.config import config
from firstory.llm import prompt
from firstory.nodes import interview as iv
from firstory.schemas import InterviewTurnResult, StoryInputContext, Turn

# 이름: (prompts/ 아래 프롬프트 파일, reasoning). 다른 프롬프트를 견주려면 prompts/에 파일을 두고 여기에 더한다.
# 11/9 비교(#82)는 A 옛 순서(interview_orig, low) / B 순서 바꿈(low) / C 순서 바꿈(none) → C를 씀
VARIANTS = {
    "low": ("interview", "low"),
    "none (지금)": ("interview", "none"),
}

_local = threading.local()
_orig_client = llm.client


def _client():
    c = _orig_client()
    if not getattr(c.responses, "_timed", False):
        real = c.responses.parse

        def parse(**kw):
            r = real(**kw)
            u = r.usage
            _local.usage = {"in": u.input_tokens, "cached": getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
                            "out": u.output_tokens, "reasoning": getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0}
            return r
        c.responses.parse = parse
        c.responses._timed = True
    return c


llm.client = _client


def run(step: dict, name: str) -> dict:
    file, effort = VARIANTS[name]
    ctx = StoryInputContext.model_validate(step["context"])
    turns = [Turn.model_validate(t) for t in step["turns"]]
    wants_more = bool(turns) and turns[-1].question == iv.READY_QUESTION and iv._norm(turns[-1].answer) in iv._MORE
    system = prompt(file, persona=iv._persona, context=ctx, missing_fields=ctx.missing_fields() or "(없음)",
                    answered=len(iv._answers(turns)), remaining=config.max_interview_turns - len(turns),
                    clarify_remaining=max(0, config.max_clarify_turns - step["clarify_count"]),
                    turns=[t.model_dump() for t in turns] or "(아직 없음)", deepen=iv._DEEPEN if wants_more else "")
    t0 = time.time()
    r, _ = llm.structured(node="interview", model=config.model_light, schema=InterviewTurnResult, system=system,
                          user="다음 행동을 결정하세요.", reasoning=effort)
    ms = int((time.time() - t0) * 1000)
    return {"variant": name, "ms": ms, **_local.usage, "status": r.status, "question": r.next_question,
            "choices": r.choices, "reason": r.reason}


def main(src: str, out: str) -> None:
    steps = json.loads(Path(src).read_text())
    since = sys.argv[3] if len(sys.argv) > 3 else ""   # 이 시각(UTC ISO) 뒤의 차례만. 예 2026-11-06T15 = 11/7 한국 시각부터
    steps = [s for s in steps if s["at"] >= since]
    steps.sort(key=lambda s: (s["thread"], len(s["turns"])))
    # 캐시가 걸리게 B·C의 같은 앞부분을 한 번 먼저 보낸다
    run(steps[0], next(iter(VARIANTS)))
    results: list[dict] = [None] * len(steps)

    def one(i):
        results[i] = {"step": i, "rows": [run(steps[i], v) for v in VARIANTS]}

    with ThreadPoolExecutor(3) as pool:
        list(pool.map(one, range(len(steps))))
    Path(out + ".json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(len(steps), "steps")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
