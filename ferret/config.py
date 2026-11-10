"""Settings read from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SMTP_SECURITY_MODES = ("starttls", "ssl", "none")


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    return environ.get(name, "").strip() or None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    master_key_file: Path | None
    base_url: str = "http://127.0.0.1:8000"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "Ferret <no-reply@localhost>"
    smtp_security: str = "starttls"
    dev_print_links: bool = False
    google_client_id: str | None = None
    google_client_secret: str | None = None

    @property
    def control_db_path(self) -> Path:
        return self.data_dir / "control.db"

    @property
    def users_dir(self) -> Path:
        return self.data_dir / "users"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> Settings:
        data_dir = Path(environ.get("FERRET_DATA_DIR", "data"))
        key = environ.get("FERRET_MASTER_KEY_FILE", "").strip()
        security = environ.get("FERRET_SMTP_SECURITY", "").strip() or "starttls"
        if security not in SMTP_SECURITY_MODES:
            raise ValueError("FERRET_SMTP_SECURITY must be starttls, ssl or none")
        try:
            port = int(environ.get("FERRET_SMTP_PORT", "").strip() or 587)
        except ValueError:
            raise ValueError("FERRET_SMTP_PORT must be a number") from None
        base_url = environ.get("FERRET_BASE_URL", "").strip() or cls.base_url
        return cls(
            data_dir=data_dir,
            master_key_file=Path(key) if key else None,
            base_url=base_url.rstrip("/"),
            smtp_host=_optional(environ, "FERRET_SMTP_HOST"),
            smtp_port=port,
            smtp_username=_optional(environ, "FERRET_SMTP_USERNAME"),
            smtp_password=environ.get("FERRET_SMTP_PASSWORD") or None,
            smtp_from=_optional(environ, "FERRET_SMTP_FROM") or cls.smtp_from,
            smtp_security=security,
            dev_print_links=environ.get("FERRET_DEV_PRINT_LINKS") == "1",
            google_client_id=_optional(environ, "FERRET_GOOGLE_CLIENT_ID"),
            google_client_secret=environ.get("FERRET_GOOGLE_CLIENT_SECRET") or None,
        )
