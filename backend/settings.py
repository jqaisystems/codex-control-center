from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path


APP_STARTED_AT = time.time()


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    app_home: Path
    db_path: Path
    codex_home: Path
    control_token: str | None
    otel_token: str | None
    metadata_only: bool


def load_settings() -> Settings:
    home = Path.home()
    app_home = Path(os.environ.get("CCC_HOME", home / ".codex-control-center")).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
    db_path = Path(os.environ.get("CCC_DB_PATH", app_home / "control-center.sqlite")).expanduser()
    return Settings(
        host=os.environ.get("CCC_HOST", "127.0.0.1"),
        port=int(os.environ.get("CCC_PORT", "8765")),
        app_home=app_home,
        db_path=db_path,
        codex_home=codex_home,
        control_token=os.environ.get("CCC_CONTROL_TOKEN") or None,
        otel_token=os.environ.get("CCC_OTEL_TOKEN") or None,
        metadata_only=os.environ.get("CCC_METADATA_ONLY", "1") != "0",
    )


def ensure_app_dirs(settings: Settings) -> None:
    settings.app_home.mkdir(parents=True, exist_ok=True)
    (settings.app_home / "logs").mkdir(parents=True, exist_ok=True)
