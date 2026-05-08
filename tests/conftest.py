from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MVP0_REPLAY_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "replay" / "mvp0"


def load_json_fixture(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fixture_file:
        loaded = json.load(fixture_file)
    assert isinstance(loaded, dict)
    return loaded
