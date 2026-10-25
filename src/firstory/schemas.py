"""
스키마 — 백엔드 개발 사전 조사 ①③⑤ 확정안을 pydantic으로 옮긴 것.
💡 표시는 ARCHITECTURE.md 제안 항목.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, create_model


# ──────────────────────────────────────────────────────────────
# ① StoryInputContext — 1차 폼 + 인터뷰가 함께 채우는 입력 Context
# ──────────────────────────────────────────────────────────────
SituationCategory = Literal[
    "friend_conflict",   # 친구와 갈등
    "new_environment",   # 새로운 환경(입학, 이사 등)
    "separation",        # 이별·죽음
    "safety",            # 안전교육
    "rules",             # 규칙·훈육
    "family_change",     # 가족 변화(동생, 이혼 등)
    "fear",              # 두려움(병원, 어둠 등)
    "other",
]
Trait = Literal["shy", "active", "sensitive", "curious", "stubborn", "cautious", "other"]
Interest = Literal["dinosaur", "space", "animal", "vehicle", "princess", "hero", "drawing", "other"]
Reaction = Literal["cried", "silent", "angry_outburst", "clingy", "avoided", "asked_questions", "other"]
Emotion = Literal["sad", "angry", "scared", "confused", "ashamed", "excited", "unknown"]
MessageDirection = Literal[
    "comfort_first",       # 아이 마음 위로 우선
    "perspective_taking",  # 상대 입장 생각해보기
    "explain_situation",   # 상황 자체를 설명
    "set_boundary",        # 규칙·경계 전달
    "reassure",            # 안심시키기
    "undecided",
]


class Situation(BaseModel):
    category: SituationCategory
    custom_category: Optional[str] = None
    timing: Literal["past", "upcoming"]
    description: str = Field(max_length=60, description="상황에 대한 짧은 설명")


class Child(BaseModel):
    age_months: int = Field(description="만 나이×12 + 개월")
    gender: Literal["male", "female", "unspecified"] = "unspecified"
    traits: list[Trait] = []
    custom_trait: Optional[str] = None
    interests: list[Interest] = []
    custom_interest: Optional[str] = None


class Moment(BaseModel):
    """당시 정보. timing=upcoming 이면 비어 있을 수 있음."""
    reactions: list[Reaction] = []
    custom_reaction: Optional[str] = None
    emotions: list[Emotion] = []


class Parent(BaseModel):
    """전부 인터뷰에서 채움."""
    response: Optional[str] = Field(None, description="당시 부모가 어떻게 대응했는지")
    concern: Optional[str] = Field(None, description="부모가 고민하는 지점. '딱히 없다'도 유효")
    message: Optional[str] = Field(None, description="아이에게 전달하고 싶은 메시지 (원문 그대로)")
    message_direction: Optional[MessageDirection] = Field(
        None, description="AI가 정리한 전달 방향. 모르면 undecided"
    )


class StoryInputContext(BaseModel):
    situation: Situation
    child: Child
    moment: Moment = Moment()
    parent: Parent = Parent()

    # 종료 조건 이중 확인 (서버 쪽 판단, AI 말만 믿지 않음)
    def missing_fields(self) -> list[str]:
        m: list[str] = []
        if not self.parent.concern:
            m.append("parent.concern")
        if not self.parent.message_direction:
            m.append("parent.message_direction")
        if self.situation.timing == "past" and self.moment.emotions == ["unknown"]:
            m.append("moment.emotions(unknown→1회 보완 시도)")
        return m

    def is_sufficient(self) -> bool:
        return bool(self.parent.concern) and bool(self.parent.message_direction)


# ──────────────────────────────────────────────────────────────
# ② 인터뷰 — Role A
# ──────────────────────────────────────────────────────────────
class ParentUpdate(BaseModel):
    response: Optional[str] = None
    concern: Optional[str] = None
    message: Optional[str] = None
    message_direction: Optional[MessageDirection] = None


class MomentUpdate(BaseModel):
    reactions: Optional[list[Reaction]] = None
    custom_reaction: Optional[str] = None
    emotions: Optional[list[Emotion]] = None


class InterviewTurnResult(BaseModel):
    """AI가 매 턴 '질문'과 '필드 추출'을 동시에 한다."""
    context_update: ParentUpdate = Field(description="이번 답변(및 지금까지 대화)에서 뽑은 부모 정보")
    moment_update: Optional[MomentUpdate] = Field(None, description="당시 정보가 보완됐으면")
    status: Literal["ask", "sufficient"]
    next_question: Optional[str] = Field(None, description="status=ask 일 때 다음 질문 하나")
    reason: str = Field(description="디버깅용: 왜 이 질문을 했는지 / 왜 충분하다고 봤는지")


class InterviewSummary(BaseModel):
    summary: str = Field(description="이 부모는 ~를 걱정하고 ~를 전하고 싶어한다 — 한 문단")


class Turn(BaseModel):
    question: str
    answer: str
    reason: str = ""


# ──────────────────────────────────────────────────────────────
# 💡 StoryDesign — 간접화 설계 (design_story 노드)
# ──────────────────────────────────────────────────────────────
class Protagonist(BaseModel):
    name: str = Field(description="아이 이름이 아닌 새 이름. 2~3글자, 발음 쉬운")
    species: str = Field(description="아이 관심사에서 끌어온 동물. 옷을 입고 아이처럼 생활한다. 사람은 안 됨")
    traits: list[str]


class SupportingCharacter(BaseModel):
    name: str
    species: str = Field(description="주인공과 한눈에 구분되는 다른 동물. 사람은 안 됨")
    role: str = Field(description="주인공과의 관계 (설계 메모용. 본문에서는 가족 호칭 대신 이름으로 부른다). 예: 같은 반 친구, 함께 사는 어른, 선생님")
    traits: list[str]


class StoryDesign(BaseModel):
    protagonist: Protagonist
    supporting: Optional[SupportingCharacter] = Field(
        None, description="이야기에 가장 필요한 한 명. 꼭 없어도 되면 null"
    )
    world: str = Field(description="아이가 아는 일상 공간 (동물 아이들의 유치원·놀이터·집). 실제 기관 이름·지어낸 지명·환상 요소 없이")
    mirrored_situation: str = Field(description="감정 구조는 같고 겉의 디테일은 바꾼, 비슷한 일을 겪는 동물 아이의 상황")
    problem_cause: str = Field(description="주인공이 그러는 원인 **하나**. 사연의 단서(언제 그러는지·몸 증상)를 가장 잘 설명하고, 부모가 읽고 '우리 애도 그럴 수 있겠다' 할 만한 이유. 지어낸 소품 금지. 기·승에서 먼저 보여 준 뒤 전에서 말로 나온다")
    values_to_honor: list[str] = Field(description="이야기 안에 자연스럽게 있되 결론으로 주입하지 않을 가치")
    must_show: list[str] = Field(default_factory=list, description="부모가 직접 한 말(parent.message·concern)에서 나온, 동화에 꼭 장면으로 보여 줄 것. '누가 무엇을 하는 장면' 꼴. 부모가 따로 바란 게 없으면 빈 칸")
    solution: str = Field("", description="주인공이 스스로 낸 방법 하나와, 그게 problem_cause를 어떻게 직접 푸는지. 상황이 저절로 나아지는 것은 안 된다")
    setups: list[str] = Field(default_factory=list, description="뒤에서 쓰는 사물·말·장소를 앞에서 먼저 보여 주는 짝. '오리: 1쪽에서 보여 줌 → 7쪽에서 씀' 꼴. 전·결에서 쓰는 것은 모두 여기 있어야 한다")
    story_arc: list[str] = Field(description="페이지별 흐름, 페이지 수만큼. 기(배경·발단)→승(반복하며 커지는 감정)→전(주인공의 시도)→결(결과·마무리)")


# ──────────────────────────────────────────────────────────────
# 프롬프트 전략 — 켜고 끄며 비교한다 (prompts/strategies/, lab.py)
# ──────────────────────────────────────────────────────────────
class Strategy(BaseModel):
    """다 꺼져 있으면 지금 프롬프트 그대로."""
    arc: bool = False       # 상황 카테고리별 감정 흐름 템플릿 (prompts/arcs/)
    engine: bool = False    # 원하는 것·시도 3번·그 뒤로 (Story Spine)
    fewshot: bool = False   # 좋은 설계 예시를 보여 준다 (Dramatron)
    motif: bool = False     # 반복 문구·위로 물건 (StoryTale)

    def on(self) -> list[str]:
        return [k for k, v in self.model_dump().items() if v]


class Attempt(BaseModel):
    action: str = Field(description="주인공이 해 보는 일 (눈에 보이는 행동)")
    result: str = Field(description="어떻게 됐나. 1·2번은 왜 안 됐는지, 3번은 어떻게 됐는지")


class Refrain(BaseModel):
    line: str = Field(description="되풀이할 짧은 말 하나 (소리 말이나 짧은 문장). 쪽마다 글자 그대로 쓴다")
    uses: list[str] = Field(description="정확히 3번. '몇 쪽: 어떤 마음으로' (예: '3쪽: 놀라서', '5쪽: 울면서', '9쪽: 웃으며')")


_ENGINE = {
    "want": (str, Field(description="주인공이 이 이야기에서 원하는 것 하나. 눈에 보이는 것, '~하고 싶다'")),
    "attempts": (list[Attempt], Field(description="주인공의 시도 정확히 3번. 1·2번은 안 되고, 3번은 주인공이 스스로 생각해 낸 방법으로 된다")),
    "ever_since": (str, Field(description="'그 뒤로' 한 문장. 이 일 뒤에 달라진 주인공의 일상")),
}
_MOTIF = {
    "refrain": (Refrain, Field(description="이야기 내내 감정만 바뀌며 돌아오는 말")),
    "comfort_object": (str, Field(description="주인공 곁의 실제 물건 하나. 1쪽에 나오고, 2쪽 이상 더 나오며, 해결 장면에서 쓰인다")),
}


def _design_variant(name: str, *extras: dict):
    """StoryDesign에 전략 칸을 끼운 스키마. story_arc 바로 앞에 둬서 흐름을 쓰기 전에 그 칸부터 정하게 한다."""
    fields = {k: (f.annotation, f) for k, f in StoryDesign.model_fields.items()}
    arc = fields.pop("story_arc")
    for e in extras:
        fields.update(e)
    fields["story_arc"] = arc
    return create_model(name, __module__=__name__, **fields)


StoryDesignEngine = _design_variant("StoryDesignEngine", _ENGINE)
StoryDesignMotif = _design_variant("StoryDesignMotif", _MOTIF)
StoryDesignEngineMotif = _design_variant("StoryDesignEngineMotif", _ENGINE, _MOTIF)


def design_schema(s: Strategy):
    return {(False, False): StoryDesign, (True, False): StoryDesignEngine,
            (False, True): StoryDesignMotif, (True, True): StoryDesignEngineMotif}[(s.engine, s.motif)]


class JudgeScore(BaseModel):
    criterion: Literal["재미", "개연성", "따뜻함", "눈높이", "부모 의도", "주인공 주도"]
    feedback: str = Field(description="기준에 비춘 근거 1~2문장. 점수보다 먼저 쓴다")
    score: int = Field(description="1~5")


class StoryJudgement(BaseModel):
    """story_judge — 실험 비교용 채점. 파이프라인에는 안 들어간다."""
    scores: list[JudgeScore] = Field(description="여섯 기준 모두, 위 순서대로")
    arc_followed: list[bool] = Field(description="설계 story_arc 항목마다 본문에 실제로 일어났는지, 항목 순서대로")


# ──────────────────────────────────────────────────────────────
# ④ 동화 텍스트 — 생성기
# ──────────────────────────────────────────────────────────────
class CharacterSheet(BaseModel):
    name: str = Field(description="동화 속 이름 (한국어)")
    role: Literal["protagonist", "supporting"]
    visual_description: str = Field(
        description="외형 한 문단: 종, 몸 색, 크기감(주인공 대비), 눈, 특징적 표식/소지품, 옷. 모든 페이지에서 같게 그려질 고정 특징. 영어로"
    )


class StoryPage(BaseModel):
    order: int = Field(description="1부터")
    text: str = Field(description="4~6세 눈높이, 2~4문장. 의성어·의태어는 **별표**로 감싼다 (책에서 굵게 표시)")
    characters_in_scene: list[str] = Field(description="이 페이지 그림에 등장하는 캐릭터 이름들 (CharacterSheet.name과 동일하게)")
    image_prompt: str = Field(
        description="이 페이지 장면. 캐릭터 외형은 반복하지 말고 **정확한 자세·동작·위치·표정·구도**를 구체적으로. 본문의 미묘한 동작(예: 바퀴 하나만 담요 밖으로)을 그대로. 영어로"
    )


class StoryText(BaseModel):
    title: str
    characters: list[CharacterSheet] = Field(description="주인공 1 + 조연 0~1. 설계의 인물 그대로")
    style_guide: str = Field(description="그림책 화풍 (예: soft watercolor, warm pastel, rounded outlines). 영어로")
    pages: list[StoryPage]

    def protagonist(self) -> CharacterSheet:
        return next((c for c in self.characters if c.role == "protagonist"), self.characters[0])


class PolishedPage(BaseModel):
    order: int = Field(description="입력 원고의 order 그대로")
    text: str = Field(description="다듬은 본문. 내용·순서는 그대로, 문장만 쉽게")


class PolishedStory(BaseModel):
    """polish_story — 본문만 고친다. 쪽 수·order는 입력과 같아야 한다."""
    pages: list[PolishedPage]


# ──────────────────────────────────────────────────────────────
# ③ ReadingGuide — Role B
# ──────────────────────────────────────────────────────────────
PromptPurpose = Literal["empathy", "predict", "perspective", "connect"]


class GuidePrompt(BaseModel):
    id: str
    after_page: int = Field(description="이 페이지를 읽은 뒤 등장")
    text: str = Field(description="아이에게 하는 질문. 캐릭터의 속마음 형태")
    purpose: PromptPurpose
    parent_hint: Optional[str] = Field(None, description="부모용 한 줄. '아이가 대답 안 해도 괜찮아요'")


class BeforeReading(BaseModel):
    intent: str = Field(description="이 동화가 담은 방향 한 문단")
    tips: list[str] = Field(description="2~3개. 지시가 아닌 제안")


class AfterReading(BaseModel):
    bridge_question: str = Field(description="아이 실제 경험으로 연결하는 질문")
    if_undecided: Optional[str] = Field(
        None, description="message_direction=undecided 일 때만: 부모가 스스로 정리하도록 돕는 문장"
    )


class ReadingGuide(BaseModel):
    prompts: list[GuidePrompt] = Field(description="기본 2개, 최대 3개")
    before_reading: BeforeReading
    after_reading: AfterReading


# ──────────────────────────────────────────────────────────────
# 산출물 / 상태
# ──────────────────────────────────────────────────────────────
class PageImage(BaseModel):
    order: int
    path: Optional[str] = None   # 저장소 key (storage.py). 그림만 다시 그린 실행에서 안 바뀐 쪽은 이전 실행의 key
    status: Literal["pending", "generating", "completed", "failed"] = "pending"
    error: Optional[str] = None


class Illustrations(BaseModel):
    character_sheets: dict[str, str] = {}   # 이름 → 저장소 key
    pages: list[PageImage] = []

    @property
    def character_sheet_path(self) -> Optional[str]:  # 하위 호환 (주인공)
        return next(iter(self.character_sheets.values()), None)


class CostEntry(BaseModel):
    node: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    ms: int = 0


SafetyLevel = Literal["OK", "SENSITIVE", "REVISE", "CRISIS"]


class SafetyResult(BaseModel):
    """위기 신호 판단 (API 스펙 4장). reason은 부모에게 그대로 보여줄 문장."""
    level: SafetyLevel
    category: Optional[str] = None   # 값 목록은 D4에서 정함
    reason: Optional[str] = None


StoryStatus = Literal["requested", "generating_text", "reviewing", "generating_images", "completed", "failed"]
RegenerateScope = Literal["character", "story", "text", "images"]
