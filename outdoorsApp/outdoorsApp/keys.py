"""API keys, loaded from ``outdoorsApp/.env`` (see ``.env.example``).

Real environment variables take precedence over values in ``.env``.
A missing key is ``None``; check it before calling that API.
"""

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def _key(name: str) -> str | None:
    return os.environ.get(name) or None


_load_env_file(_ENV_FILE)

# Have already
RIDB_API_KEY = _key("RIDB_API_KEY")
GOOGLE_MAPS_API_KEY = _key("GOOGLE_MAPS_API_KEY")

# Need to sign up (free)
NPS_API_KEY = _key("NPS_API_KEY")
UDOT_API_KEY = _key("UDOT_API_KEY")

# Optional
NOAA_CDO_TOKEN = _key("NOAA_CDO_TOKEN")
AIRNOW_API_KEY = _key("AIRNOW_API_KEY")
