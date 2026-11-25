"""
낭독(TTS) 준비와 만들기. 동화 글을 해설·대사 조각으로 나누고 조각마다 목소리를 정한다.
- segments: 한 쪽의 글을 따옴표 안(대사)·밖(해설) 조각으로
- cast_voices: 인물 → 목소리 id (풀에서 안 겹치게)
- assign_voices: 따옴표 조각마다 누가 말했는지 모델이 정하고, 인물마다 목소리 종류를 받아 목소리를 배정한다
- page_inputs·source_hash: 한 쪽의 (글, 목소리) 목록과 그 해시 (같으면 다시 만들지 않는다)
- narrate: 쪽마다 ElevenLabs 대화 음성을 만들어 저장한다. 실패한 쪽은 failed로 두고 나머지는 이어 간다
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from .. import storage, tts, voices
from ..config import config
from ..llm import prompt, structured
from ..schemas import CostEntry, Narration, PageAudio, SpeakerAssignment, VoiceType
from ..state import PipelineState
from .layout import split_lines

log = logging.getLogger("firstory.narrate")

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
    try:
        result, cost = structured(
            node="assign_voices",
            model=config.model_light,
            schema=SpeakerAssignment,
            system=prompt("assign_voices", cast=cast_text, quotes=quotes_text),
            user="위 대사마다 말한 사람을 정하고, 인물마다 목소리 종류를 골라 주세요.",
        )
    except Exception as e:   # 낭독 준비가 실패해도 동화는 끝나야 한다: 모두 해설자, 인물은 기본 목소리 종류
        log.warning("[assign_voices] 말한 사람 정하기 실패, 모두 해설자로: %s", e)
        result, cost = SpeakerAssignment(cast=[], quotes=[]), None

    given = {c.name: c.voice_type for c in result.cast if c.name in names}   # 인물 목록에 없는 이름은 버린다
    cast_types: dict[str, VoiceType] = {}
    for c in chars:
        if c.name in keep_types:   # 글만 다시 만들 때는 이전 배정을 지킨다
            cast_types[c.name] = keep_types[c.name]
        else:
            cast_types[c.name] = given.get(c.name) or ("child_girl" if c.name == protagonist else "adult_woman")
    said = {q.id: q.speaker for q in result.quotes}
    speakers = {seg.id: (said.get(seg.id) if said.get(seg.id) in names else NARRATOR_NAME) for _, seg in pieces} if cost else {}
    return {
        "voice_plan": {"cast_types": cast_types, "cast_voices": cast_voices(cast_types, keep_voices), "speakers": speakers},
        "cost": [cost] if cost else [],
    }


def page_inputs(page_no: int, text: str, plan: dict) -> list[dict]:
    """한 쪽의 [{"text", "voice_id"}]. 해설은 해설자 목소리, 대사는 말한 인물의 목소리
    (목소리 표에 없는 이름이면 해설자). 같은 목소리가 이어지면 한 조각으로 합친다."""
    cast = plan.get("cast_voices", {})
    speakers = plan.get("speakers", {})
    out: list[dict] = []
    for seg in segments(page_no, text):
        voice = cast.get(speakers.get(seg.id), voices.NARRATOR) if seg.quoted else voices.NARRATOR
        if out and out[-1]["voice_id"] == voice:
            out[-1]["text"] += " " + seg.text
        else:
            out.append({"text": seg.text, "voice_id": voice})
    return out


def source_hash(inputs: list[dict]) -> str:
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class _Failed(Exception):
    """목소리 서비스가 두 번 다 실패. 메시지는 '상태: 내용'."""


def narrate(state: PipelineState) -> dict:
    if not tts.enabled():
        log.info("[narrate] ElevenLabs 키가 없어 낭독을 만들지 않습니다")
        return {"narration": None, "cost": []}

    story = state["story"]
    plan = state.get("voice_plan") or {"cast_types": {}, "cast_voices": {}, "speakers": {}}
    prefix = state["output_prefix"]
    prev = state.get("narration")
    prev_pages = {p.order: p for p in prev.pages} if prev else {}

    def work(page) -> tuple[PageAudio, Optional[CostEntry]]:
        n = page.order
        h = None
        try:
            inputs = page_inputs(n, page.text, plan)
            h = source_hash(inputs)
            old = prev_pages.get(n)
            if old and old.status == "completed" and old.source_hash == h:
                return old, None   # 글·목소리가 그대로인 쪽은 이전 음성을 그대로 쓴다
            t0 = time.time()
            err = None
            for _ in range(2):   # 목소리 서비스 오류는 한 번 더 시도
                try:
                    data = tts.dialogue(inputs, page=n)
                    break
                except tts.TtsError as e:
                    err = f"{e.status}: {e}"
            else:
                raise _Failed(err)
            key = storage.write_bytes(storage.join(prefix, "audio", f"page-{n:02d}.mp3"), data)
        except Exception as e:   # 어떤 실패도 그 쪽만 failed로 두고 동화는 이어 간다. 실패한 쪽은 과금되지 않는다
            err = str(e) if isinstance(e, _Failed) else f"None: {e}"
            log.warning("[narrate] %d쪽 음성 실패: %s", n, err)
            return PageAudio(order=n, status="failed", error=err, source_hash=h), None
        cost = CostEntry(node=f"narrate:page{n}", model=config.tts_model,
                         tts_chars=sum(len(i["text"]) for i in inputs), ms=int((time.time() - t0) * 1000))
        return PageAudio(order=n, path=key, status="completed", source_hash=h), cost

    with ThreadPoolExecutor(max_workers=max(1, config.tts_concurrency)) as ex:
        results = list(ex.map(work, sorted(story.pages, key=lambda p: p.order)))
    return {
        "narration": Narration(cast_types=plan["cast_types"], cast_voices=plan["cast_voices"], pages=[a for a, _ in results]),
        "cost": [c for _, c in results if c],
    }
