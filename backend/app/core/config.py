import os
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    TUSHARE_TOKEN: str = os.getenv("TUSHARE_TOKEN", "")

    # Tushare rate limits (requests per minute)
    TUSHARE_DAILY_RPM: int = 200
    TUSHARE_DEFAULT_RPM: int = 80

    # Data pull range
    DATA_START_DATE: str = "20250922"
    DATA_END_DATE: str = "20260328"


settings = Settings()
