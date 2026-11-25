"""낭독 목소리 목록. 해설자 한 명 + 목소리 종류별 후보 (ElevenLabs voice_id)."""
from __future__ import annotations

from .schemas import VoiceType

NARRATOR: str = "k5siOxi4qsPS2kASoRt7"

# 첫 값. 사용자가 들어 보고 확정한다. 서로 겹치면 안 된다
POOL: dict[VoiceType, list[str]] = {
    "child_girl": ["Lb7qkOn5hF8p7qfCDH8q", "5n5gqmaQi9Ewevrz7bOS"],   # Annie, Sian
    "child_boy": ["1W00IGEmNmwmsDeYy7ag", "m3gJBS8OofDJfycyA2Ip"],    # Krys, Taehyung
    "adult_woman": ["AW5wrnG1jVizOYY7R1Oo", "uyVNoMrnUku1dZyVEXwD"],  # Jiyoung, Anna Kim
    "adult_man": ["BbsagRO6ohd8MKPS2Ob0", "WqVy7827vjE2r3jWvbnP"],    # Jin Geon Song, Hyuk
    "elder_woman": ["ksaI0TCD9BstzEzlxj4q", "8MwPLtBplylvbrksiBOC"],  # Seulki, Chungman
    "elder_man": ["YBRudLRm83BV5Mazcr42", "K3qo7ugXmpT87FDhLBbN"],    # Jason, Gale
}
