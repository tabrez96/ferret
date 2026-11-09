"""Settings read from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    master_key_file: Path | None

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
        return cls(data_dir=data_dir, master_key_file=Path(key) if key else None)
