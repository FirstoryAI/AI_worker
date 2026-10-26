import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    v = os.getenv(name, "").strip()
    return v or default


@dataclass(frozen=True)
class Config:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    model_light: str = _env("MODEL_LIGHT", "gpt-5.4-mini")
    model_main: str = _env("MODEL_MAIN", "gpt-5.5")
    model_judge: str = _env("MODEL_JUDGE", _env("MODEL_MAIN", "gpt-5.5"))   # 프롬프트 실험 채점용 (lab.py)
    image_model: str = _env("IMAGE_MODEL", "gpt-image-2")
    image_quality: str = _env("IMAGE_QUALITY", "low")
    image_size: str = _env("IMAGE_SIZE", "1024x1024")
    image_concurrency: int = int(_env("IMAGE_CONCURRENCY", "3"))

    page_count: int = 10
    max_interview_turns: int = 5        # 🔒 ②-5
    max_clarify_turns: int = 2          # 🔒 ②-4 "모르겠다" 정리 질문
    max_interview_choices: int = 4      # 질문마다 주는 답변 카드 수 (화면이 4개까지 보여 준다)
    guide_prompts_min: int = 2          # 🔒 ③-4
    guide_prompts_max: int = 3

    out_dir: Path = ROOT / "out"
    checkpoint_db: Path = ROOT / "out" / "checkpoints.db"
    output_root: Path = Path(_env("FIRSTORY_OUTPUT_ROOT", str(ROOT / "out")))   # 결과물 저장소 루트 (storage.py)

    # FastAPI 서버 (server.py)
    mock: bool = _env("FIRSTORY_MOCK", "false").lower() in ("1", "true", "yes")
    internal_token: str = os.getenv("FIRSTORY_INTERNAL_TOKEN", "")   # Spring이 X-Internal-Token으로 보내는 값


config = Config()
config.out_dir.mkdir(parents=True, exist_ok=True)
