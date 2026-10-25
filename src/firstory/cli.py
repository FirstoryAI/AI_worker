"""
CLI.
  uv run firstory datasets/inputs/donggeul.json              # 인터뷰·생성 전 확인·검토를 터미널에서
  uv run firstory datasets/inputs/donggeul.json --auto       # 스크립트 답변 + 확인·검토 자동 통과
  uv run firstory datasets/inputs/donggeul.json --skip-images
  uv run firstory datasets/inputs/donggeul.json --strategy arc,engine   # 프롬프트 전략 켜기 (schemas.Strategy)
  uv run firstory --resume <thread_id>                        # 멈춘 곳부터 재개
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from langgraph.types import Command

from .graph import compile_graph, new_thread_id
from .schemas import Strategy

C = {"b": "\033[1m", "d": "\033[2m", "c": "\033[36m", "m": "\033[35m", "g": "\033[32m", "y": "\033[33m", "r": "\033[31m", "0": "\033[0m"}


def say(k, s):
    print(f"{C[k]}{s}{C['0']}")


def print_story(story: dict, guide: dict | None = None):
    say("b", f"\n📖 {story['title']}")
    q_after: dict[int, list] = {}
    for q in (guide or {}).get("prompts", []):
        q_after.setdefault(q["after_page"], []).append(q)
    for p in story["pages"]:
        print(f"  {C['d']}{p['order']:>2}{C['0']}  {p['text']}")
        for q in q_after.get(p["order"], []):
            print(f"      {C['m']}[{q['purpose']}]{C['0']} {q['text']}")


def handle_interrupt(payload: dict, args) -> object:
    """interrupt 값을 보고 사람에게 묻는다. 돌려주는 값이 Command(resume=...)."""
    t = payload.get("type")
    if t == "interview":
        say("m", f"\nFIRSTORY AI › {payload['question']}")
        print(f"{C['d']}  (skip 입력 시 인터뷰 종료){C['0']}")
        if args.auto:  # scripted_answers가 바닥나면 더 묻지 않고 끝낸다
            print(f"{C['b']}부모{C['0']} › skip  {C['d']}(--auto){C['0']}")
            return "skip"
        return input(f"{C['b']}부모{C['0']} › ").strip()
    if t == "confirm":
        say("c", f"\n인터뷰 정리 ({payload.get('end_reason')})")
        print(f"  {payload.get('summary')}")
        if not args.auto:
            input(f"\n  {C['d']}[Enter] 이대로 만들기{C['0']} › ")
        return {"action": "generate"}
    if t == "review":
        print_story(payload["story"], payload.get("guide"))
        say("g", f"\n  → {payload['run_dir']}/book.html 을 열어서 그림까지 확인")
        print("\n  [1] 완료   [2] 다시 쓰기(피드백)   [3] 캐릭터/이야기 바꾸기   [4] 그림만 다시")
        a = (input("  › ").strip() or "1")
        if a == "2":
            fb = input("  어떻게 바꿀까요? › ").strip()
            return {"action": "regenerate", "scope": "text", "feedback": fb}
        if a == "3":
            fb = input("  어떤 쪽으로? (예: 토끼 말고 공룡으로) › ").strip()
            return {"action": "regenerate", "scope": "character", "feedback": fb}
        if a == "4":
            fb = input("  페이지 번호 (비우면 전부) › ").strip()
            return {"action": "regenerate", "scope": "images", "feedback": fb}
        return {"action": "approve"}
    return None


def run(graph, inp, cfg, args):
    """invoke → interrupt 나오면 사람에게 묻고 → Command(resume)로 재개. 끝날 때까지."""
    result = graph.invoke(inp, cfg)
    while "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        answer = handle_interrupt(payload, args)
        result = graph.invoke(Command(resume=answer), cfg)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="datasets/inputs/*.json")
    ap.add_argument("--auto", action="store_true", help="scripted answers로 인터뷰 자동, 검토 자동 완료")
    ap.add_argument("--skip-images", action="store_true")
    ap.add_argument("--resume", metavar="THREAD_ID")
    ap.add_argument("--strategy", default="", help="쉼표로: " + ",".join(Strategy.model_fields))
    args = ap.parse_args(argv)
    keys = [k.strip() for k in args.strategy.split(",") if k.strip()]
    if bad := [k for k in keys if k not in Strategy.model_fields]:
        ap.error(f"모르는 전략: {bad}")

    graph = compile_graph()

    if args.resume:
        thread_id = args.resume
        cfg = {"configurable": {"thread_id": thread_id}}
        snap = graph.get_state(cfg)
        if not snap.next and not snap.tasks:
            say("y", "이 thread는 이미 끝났거나 없음")
            return 1
        say("c", f"재개: {thread_id}")
        inp = None
    else:
        if not args.input:
            ap.error("입력 JSON 경로가 필요합니다")
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        auto_answers = data.pop("scripted_answers", [])
        thread_id = new_thread_id()
        cfg = {"configurable": {"thread_id": thread_id}}
        inp = {
            "context": data,
            "run_name": Path(args.input).stem,
            "auto_answers": auto_answers if args.auto else [],
            "auto_confirm": args.auto,
            "auto_approve": args.auto,
            "skip_images": args.skip_images,
            "strategy": Strategy(**{k: True for k in keys}),
        }
        say("b", f"\nFIRSTORY pipeline  {C['d']}thread={thread_id}{' · 전략 ' + ','.join(keys) if keys else ''}{C['0']}")

    if inp is None:
        # 멈춘 interrupt 다시 보여주기
        snap = graph.get_state(cfg)
        pend = [t for t in snap.tasks if t.interrupts]
        if pend:
            answer = handle_interrupt(pend[0].interrupts[0].value, args)
            result = run(graph, Command(resume=answer), cfg, args)
        else:
            result = run(graph, None, cfg, args)
    else:
        result = run(graph, inp, cfg, args)

    # 요약
    story = result.get("story")
    guide = result.get("guide")
    if story:
        print_story(story.model_dump(), guide.model_dump() if guide else None)
    turns = result.get("interview_turns", [])
    say("d", f"\n인터뷰 {len(turns)}턴 ({result.get('interview_done_by')})")
    if result.get("interview_summary"):
        print(f"  {result['interview_summary']}")
    cost = result.get("cost", [])
    tin = sum(c.input_tokens for c in cost); tout = sum(c.output_tokens for c in cost)
    imgs = sum(c.images for c in cost); ms = sum(c.ms for c in cost)
    say("d", f"\n텍스트 {len([c for c in cost if not c.node.startswith('illustrate')])}회 · in {tin} / out {tout} tokens · 이미지 {imgs}장 · {ms/1000:.1f}s")
    say("g", f"\n→ {result['run_dir']}/book.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
