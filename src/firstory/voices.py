"""낭독 목소리 목록. 해설자 한 명 + 목소리 종류별 후보 (ElevenLabs voice_id)."""
from __future__ import annotations

from .schemas import VoiceType

NARRATOR: str = "k5siOxi4qsPS2kASoRt7"

# 종류끼리 겹치지 않는다. 남자아이만 여자아이와 같은 목소리를 쓴다 (아래 STYLE_TAG)
POOL: dict[VoiceType, list[str]] = {
    "child_girl": ["Lb7qkOn5hF8p7qfCDH8q", "5n5gqmaQi9Ewevrz7bOS"],   # Annie, Sian
    # 한국어 남자아이 목소리는 라이브러리에 사실상 없다(Krys·Taehyung은 어른 남자처럼 무거웠다, #135).
    # 여자아이 목소리에 아이 연기 태그를 붙여 남자아이를 맡긴다 (11/25 사용자가 Annie + 태그를 골랐다)
    "child_boy": ["Lb7qkOn5hF8p7qfCDH8q", "5n5gqmaQi9Ewevrz7bOS"],    # Annie, Sian
    "adult_woman": ["AW5wrnG1jVizOYY7R1Oo", "uyVNoMrnUku1dZyVEXwD"],  # Jiyoung, Anna Kim
    "adult_man": ["BbsagRO6ohd8MKPS2Ob0", "WqVy7827vjE2r3jWvbnP"],    # Jin Geon Song, Hyuk
    "elder_woman": ["ksaI0TCD9BstzEzlxj4q", "8MwPLtBplylvbrksiBOC"],  # Seulki, Chungman
    "elder_man": ["YBRudLRm83BV5Mazcr42", "K3qo7ugXmpT87FDhLBbN"],    # Jason, Gale
}

# 목소리 종류별로 대사 앞에 붙이는 eleven_v3 연기 태그. 태그 글자도 크레딧에 세어진다
STYLE_TAG: dict[VoiceType, str] = {
    "child_boy": "[childlike voice, like a six-year-old boy]",
}
