"""
낭독(TTS) 준비와 만들기. 동화 글을 해설·대사 조각으로 나누고 조각마다 목소리를 정한다.
- segments: 한 쪽의 글을 따옴표 안(대사)·밖(해설) 조각으로
- cast_voices: 인물 → 목소리 id (풀에서 안 겹치게)
- assign_voices: 따옴표 조각마다 누가 말했는지 모델이 정하고, 인물마다 목소리 종류를 받아 목소리를 배정한다
- page_inputs·source_hash: 한 쪽의 (글 + 가이드 질문 줄, 목소리) 목록과 그 해시 (같으면 다시 만들지 않는다). 질문 줄은 해설자
- narrate: 쪽마다 ElevenLabs 대화 음성을 만들어 저장한다. 실패한 쪽은 failed로 두고 나머지는 이어 간다.
  전체 시간(TTS_DEADLINE)을 넘기거나 401·402를 받으면 아직 시작 안 한 쪽은 부르지 않는다
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from .. import storage, tts, voices
from ..config import config
from ..llm import prompt, structured
from ..schemas import CostEntry, Narration, PageAudio, SpeakerAssignment, VoiceType
from ..state import PipelineState
from .layout import questions_by_page, split_lines

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


def text_hash(text: str) -> str:
    """한 쪽 글(원문)의 해시. 글만 다시 만들 때 이 값이 같은 쪽은 말한 사람을 다시 정하지 않는다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _empty_plan(keep_types: Optional[dict] = None, keep_voices: Optional[dict] = None) -> dict:
    return {"voice_plan": {"cast_types": dict(keep_types or {}), "cast_voices": dict(keep_voices or {}), "speakers": {}}, "cost": []}


def assign_voices(state: PipelineState) -> dict:
    if state.get("skip_images") or not tts.enabled():   # 글만 만드는 실행이거나 낭독을 안 하면 모델도 부르지 않는다
        return _empty_plan()
    story = state["story"]
    prev = state.get("narration") if state.get("regenerate_scope") == "text" else None
    keep_types = dict(prev.cast_types) if prev else {}
    keep_voices = dict(prev.cast_voices) if prev else {}
    prev_hash = {p.order: p.text_hash for p in prev.pages if p.text_hash} if prev else {}

    chars = story.characters
    names = {c.name for c in chars}
    pieces: list[tuple[str, Segment]] = []   # 모델에게 보낼 대사 (글만 다시 만들 때는 글이 바뀐 쪽 것만)
    reused: dict[str, str] = {}              # 글이 그대로인 쪽의 대사: 이전에 정한 말한 사람을 그대로
    has_quotes = False
    for p in story.pages:
        quoted = [(line, seg) for line, seg in _pieces(p.order, p.text) if seg.quoted]
        has_quotes = has_quotes or bool(quoted)
        if prev and prev_hash.get(p.order) == text_hash(p.text):
            for _, seg in quoted:
                sp = prev.speakers.get(seg.id, NARRATOR_NAME)
                reused[seg.id] = sp if sp in names else NARRATOR_NAME
        else:
            pieces.extend(quoted)
    if not has_quotes:   # 대사가 없으면 모델을 부르지 않는다
        return _empty_plan(keep_types, keep_voices)

    protagonist = story.protagonist().name
    llm_failed = False
    cost = None
    result = SpeakerAssignment(cast=[], quotes=[])
    if pieces:   # 바뀐 쪽에 대사가 없으면 모델을 부르지 않는다
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
        except Exception as e:   # 낭독 준비가 실패해도 동화는 끝나야 한다: 새로 정할 대사는 해설자, 인물은 기본 목소리 종류
            log.warning("[assign_voices] 말한 사람 정하기 실패, 새로 정할 대사는 해설자로: %s", e)
            llm_failed = True

    given = {c.name: c.voice_type for c in result.cast if c.name in names}   # 인물 목록에 없는 이름은 버린다
    cast_types: dict[str, VoiceType] = {}
    for c in chars:
        if c.name in keep_types:   # 글만 다시 만들 때는 이전 배정을 지킨다
            cast_types[c.name] = keep_types[c.name]
        else:
            cast_types[c.name] = given.get(c.name) or ("child_girl" if c.name == protagonist else "adult_woman")
    speakers = dict(reused)
    if not llm_failed:   # 실패했으면 새로 정할 대사는 비워 둔다 (= 해설자)
        said = {q.id: q.speaker for q in result.quotes}
        speakers.update({seg.id: (said.get(seg.id) if said.get(seg.id) in names else NARRATOR_NAME) for _, seg in pieces})
    return {
        "voice_plan": {"cast_types": cast_types, "cast_voices": cast_voices(cast_types, keep_voices), "speakers": speakers},
        "cost": [cost] if cost else [],
    }


def page_inputs(page_no: int, text: str, plan: dict, questions: Optional[list[str]] = None) -> list[dict]:
    """한 쪽의 [{"text", "voice_id"}]. 해설은 해설자 목소리, 대사는 말한 인물의 목소리
    (목소리 표에 없는 이름이면 해설자). 같은 목소리가 이어지면 한 조각으로 합친다.
    questions: 화면에서 쪽 글 밑에 붙는 가이드 질문 줄. 글 뒤에 해설자 목소리로 읽는다 (Backend#95)."""
    cast = plan.get("cast_voices", {})
    speakers = plan.get("speakers", {})
    out: list[dict] = []
    items = [(seg.text, cast.get(speakers.get(seg.id), voices.NARRATOR) if seg.quoted else voices.NARRATOR)
             for seg in segments(page_no, text)]
    for q in questions or []:
        if q.replace("**", "").strip():
            items.append((q.replace("**", "").strip(), voices.NARRATOR))
    for t, voice in items:
        if out and out[-1]["voice_id"] == voice:
            out[-1]["text"] += " " + t
        else:
            out.append({"text": t, "voice_id": voice})
    return out


def source_hash(inputs: list[dict]) -> str:
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class _Failed(Exception):
    """이 쪽은 음성을 못 만들었다. 메시지는 '상태: 짧은 코드'."""


_RETRY_STATUSES = {429}   # + 5xx와 None(네트워크·시간 초과·빈 응답). 400·401·402·403·404·422는 다시 해도 같다
_BREAKER_STATUSES = {401, 402}   # 키가 틀렸거나 크레딧이 없다: 남은 쪽은 부르지 않는다
_now = time.monotonic


def _retryable(status: Optional[int]) -> bool:
    return status is None or status in _RETRY_STATUSES or status >= 500


def _retry_wait() -> None:
    """다시 시도하기 전 잠깐 (2~5초, 여러 쪽이 한꺼번에 다시 부르지 않게 흩뜨린다). 테스트는 이 함수를 바꿔 치운다."""
    time.sleep(random.uniform(2, 5))


def _err(e: tts.TtsError) -> str:
    return f"{e.status}: {e}"


def narrate(state: PipelineState) -> dict:
    if state.get("skip_images"):   # 글만 만드는 실행은 낭독도 하지 않는다 (크레딧을 쓰지 않게)
        return {"narration": None, "cost": []}
    if not tts.enabled():
        log.info("[narrate] ElevenLabs 키가 없어 낭독을 만들지 않습니다")
        return {"narration": None, "cost": []}

    story = state["story"]
    plan = state.get("voice_plan") or {"cast_types": {}, "cast_voices": {}, "speakers": {}}
    prefix = state["output_prefix"]
    prev = state.get("narration")
    prev_pages = {p.order: p for p in prev.pages} if prev else {}
    qs = questions_by_page(state.get("guide"))   # 쪽 번호 → 화면에 보이는 가이드 질문 줄. 모델에는 보내지 않는다 (assign_voices는 글만)
    deadline = _now() + config.tts_deadline
    lock = threading.Lock()
    broken: list[Optional[int]] = []   # 401·402를 받으면 그 상태 코드 (차단기)

    def stopped() -> Optional[str]:
        """새로 부르면 안 되는 이유. 차단기가 내려갔거나 전체 시간을 넘겼다."""
        with lock:
            if broken:
                return f"{broken[0]}: skipped"
        if _now() >= deadline:
            return "None: deadline"
        return None

    def work(page) -> tuple[PageAudio, Optional[CostEntry]]:
        n = page.order
        th = text_hash(page.text)
        h = None
        try:
            inputs = page_inputs(n, page.text, plan, qs.get(n))
            h = source_hash(inputs)
            old = prev_pages.get(n)
            if old and old.status == "completed" and old.source_hash == h:
                return old.model_copy(update={"text_hash": th}), None   # 글·목소리가 그대로인 쪽은 이전 음성을 그대로 쓴다
            t0 = time.time()
            err: Optional[str] = None
            data = None
            for attempt in range(2):   # 다시 해서 나을 수 있는 오류(429·5xx·네트워크)만 한 번 더
                why = stopped()
                if why:   # 첫 시도 전이면 부르지 않고, 다시 시도 전이면 처음 오류를 남긴다
                    raise _Failed(err or why)
                try:
                    data = tts.dialogue(inputs, page=n)
                    break
                except tts.TtsError as e:
                    err = _err(e)
                    if e.status in _BREAKER_STATUSES:
                        with lock:
                            if not broken:
                                broken.append(e.status)
                    if attempt == 1 or not _retryable(e.status):
                        raise _Failed(err)
                    _retry_wait()
            key = storage.write_bytes(storage.join(prefix, "audio", f"page-{n:02d}.mp3"), data)
        except Exception as e:   # 어떤 실패도 그 쪽만 failed로 두고 동화는 이어 간다. 실패한 쪽은 과금되지 않는다
            err = str(e) if isinstance(e, _Failed) else f"None: {e}"
            log.warning("[narrate] %d쪽 음성 실패: %s", n, err)
            return PageAudio(order=n, status="failed", error=err, source_hash=h, text_hash=th), None
        cost = CostEntry(node=f"narrate:page{n}", model=config.tts_model,
                         tts_chars=sum(len(i["text"]) for i in inputs), ms=int((time.time() - t0) * 1000))
        return PageAudio(order=n, path=key, status="completed", source_hash=h, text_hash=th), cost

    with ThreadPoolExecutor(max_workers=max(1, config.tts_concurrency)) as ex:
        results = list(ex.map(work, sorted(story.pages, key=lambda p: p.order)))
    return {
        "narration": Narration(cast_types=plan["cast_types"], cast_voices=plan["cast_voices"],
                               speakers=dict(plan.get("speakers") or {}), pages=[a for a, _ in results]),
        "cost": [c for _, c in results if c],
    }
