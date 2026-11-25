"""
낭독(TTS) 준비와 만들기. 동화 글을 해설·대사 조각으로 나누고 조각마다 목소리를 정한다.
- segments: 한 쪽의 글을 따옴표 안(대사)·밖(해설) 조각으로
- cast_voices: 인물 → 목소리 id (풀에서 안 겹치게)
- assign_voices: 따옴표 조각마다 누가 말했는지 모델이 정하고, 인물마다 목소리 종류를 받아 목소리를 배정한다
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .. import voices
from ..config import config
from ..llm import prompt, structured
from ..schemas import CostEntry, SpeakerAssignment, VoiceType
from ..state import PipelineState
from .layout import split_lines

NARRATOR_NAME = "narrator"
_QUOTED = re.compile(r'["“”]([^"“”]*)["“”]')
_QUOTE_CHARS = re.compile(r'["“”]')


@dataclass(frozen=True)
class Segment:
    text: str
    quoted: bool
    id: Optional[str]   # 따옴표 조각만 "{쪽}-{순번}" (쪽 안에서 1부터)


def _pieces(page_no: int, text: str) -> list[tuple[str, Segment]]:
    """(조각이 든 줄 전체, 조각). 줄은 모델에게 문맥으로 보여 주려고 같이 돌려준다."""
    out: list[tuple[str, Segment]] = []
    n = 0
    for line in split_lines(text.replace("**", "")):
        pos = 0
        parts: list[tuple[str, bool]] = []
        for m in _QUOTED.finditer(line):
            parts.append((line[pos:m.start()], False))
            parts.append((m.group(1), True))
            pos = m.end()
        parts.append((line[pos:], False))
        for raw, quoted in parts:
            seg = _QUOTE_CHARS.sub("", raw).strip()   # 짝 없는 따옴표 문자는 빼고 글은 해설로 남긴다
            if not seg:
                continue
            if quoted:
                n += 1
            out.append((line, Segment(seg, quoted, f"{page_no}-{n}" if quoted else None)))
    return out


def segments(page_no: int, text: str) -> list[Segment]:
    return [seg for _, seg in _pieces(page_no, text)]


def cast_voices(types: dict[str, VoiceType], keep: Optional[dict[str, str]] = None) -> dict[str, str]:
    """인물마다 목소리 id. keep에 있는 이름은 그대로, 나머지는 자기 종류 풀에서 안 쓴 첫 목소리
    (풀이 다 쓰였으면 POOL 순서대로 안 쓴 첫 목소리). 해설자 목소리는 고르지 않는다."""
    keep = keep or {}
    out: dict[str, str] = {}
    used: set[str] = {keep[n] for n in types if n in keep}
    for name, vtype in types.items():
        if name in keep:
            out[name] = keep[name]
            continue
        candidates = list(voices.POOL[vtype]) + [v for vs in voices.POOL.values() for v in vs]
        pick = next((v for v in candidates if v not in used and v != voices.NARRATOR), None)
        if pick is None:   # 목소리가 전부 쓰였다 (인물이 12명을 넘을 때): 자기 종류 첫 목소리를 다시 쓴다
            pick = voices.POOL[vtype][0]
        used.add(pick)
        out[name] = pick
    return out


def assign_voices(state: PipelineState) -> dict:
    story = state["story"]
    prev = state.get("narration") if state.get("regenerate_scope") == "text" else None
    keep_types = dict(prev.cast_types) if prev else {}
    keep_voices = dict(prev.cast_voices) if prev else {}

    pieces = [(line, seg) for p in story.pages for line, seg in _pieces(p.order, p.text) if seg.quoted]
    if not pieces:   # 대사가 없으면 모델을 부르지 않는다
        return {"voice_plan": {"cast_types": keep_types, "cast_voices": keep_voices, "speakers": {}}, "cost": []}

    chars = story.characters
    names = {c.name for c in chars}
    protagonist = story.protagonist().name
    cast_text = "\n".join(f"- {c.name} / {'주인공' if c.name == protagonist else '조연'} / {c.visual_description}" for c in chars)
    quotes_text = "\n".join(f"[{seg.id}] 줄: {line} / 대사: {seg.text}" for line, seg in pieces)
    result, cost = structured(
        node="assign_voices",
        model=config.model_light,
        schema=SpeakerAssignment,
        system=prompt("assign_voices", cast=cast_text, quotes=quotes_text),
        user="위 대사마다 말한 사람을 정하고, 인물마다 목소리 종류를 골라 주세요.",
    )

    given = {c.name: c.voice_type for c in result.cast if c.name in names}   # 인물 목록에 없는 이름은 버린다
    cast_types: dict[str, VoiceType] = {}
    for c in chars:
        if c.name in keep_types:   # 글만 다시 만들 때는 이전 배정을 지킨다
            cast_types[c.name] = keep_types[c.name]
        else:
            cast_types[c.name] = given.get(c.name) or ("child_girl" if c.name == protagonist else "adult_woman")
    said = {q.id: q.speaker for q in result.quotes}
    speakers = {seg.id: (said.get(seg.id) if said.get(seg.id) in names else NARRATOR_NAME) for _, seg in pieces}
    return {
        "voice_plan": {"cast_types": cast_types, "cast_voices": cast_voices(cast_types, keep_voices), "speakers": speakers},
        "cost": [cost],
    }
