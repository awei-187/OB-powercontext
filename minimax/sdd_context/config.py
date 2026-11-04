from dataclasses import dataclass, field
import os
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    """Read literal KEY=VALUE configuration, never execute shell expressions."""
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid KEY=VALUE line in {path.name}")
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key.strip()] = value
    return result


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)

    @classmethod
    def load(cls, env_file: Path):
        values = read_env(env_file)

        def get(key, default=""):
            return os.environ.get(key, values.get(key, default))

        password = get("SEEKDB_PASSWORD")
        if not password:
            raise ValueError("Set SEEKDB_PASSWORD in the environment or local .env file")
        port = int(get("SEEKDB_PORT", "2881"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid SEEKDB_PORT")
        return cls(get("SEEKDB_HOST", "127.0.0.1"), port,
                   get("SEEKDB_DATABASE", "minimax_sdd"),
                   get("SEEKDB_USER", "minimax_app"), password)
