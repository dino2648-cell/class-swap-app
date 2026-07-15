from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _parse_origins(raw: str) -> list[str]:
    parts = [item.strip() for item in raw.split(",")]
    return [item for item in parts if item]


@dataclass(frozen=True)
class Settings:
    app_env: str
    allow_origins: list[str]
    secret_key: str
    session_cookie_name: str
    session_max_age_seconds: int
    database_path: Path
    preview_dir: Path
    template_path: Path
    default_admin_username: str
    default_admin_password: str
    default_teacher_password: str


def get_settings() -> Settings:
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = Path(os.getenv("DATA_DIR", base_dir / "data")).resolve()
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        allow_origins=_parse_origins(os.getenv("ALLOW_ORIGINS", "http://localhost:8000")),
        secret_key=os.getenv("SECRET_KEY", "change-this-secret-key"),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "school-swap-session"),
        session_max_age_seconds=int(os.getenv("SESSION_MAX_AGE_SECONDS", "1209600")),
        database_path=Path(os.getenv("DATABASE_PATH", data_dir / "class_swap.db")).resolve(),
        preview_dir=Path(os.getenv("PREVIEW_DIR", data_dir / "import_previews")).resolve(),
        template_path=Path(
            os.getenv("TIMETABLE_TEMPLATE_PATH", data_dir / "templates" / "주간시간표_표준양식.xlsx")
        ).resolve(),
        default_admin_username=os.getenv("DEFAULT_ADMIN_USERNAME", "admin"),
        default_admin_password=os.getenv("DEFAULT_ADMIN_PASSWORD", "1234"),
        default_teacher_password=os.getenv("DEFAULT_TEACHER_PASSWORD", "1234"),
    )
