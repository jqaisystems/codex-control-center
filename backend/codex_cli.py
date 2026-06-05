from __future__ import annotations

import os
import shutil
import sys


def codex_executable() -> str | None:
    candidates = ["codex.cmd", "codex.exe", "codex"] if sys.platform.startswith("win") else ["codex"]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found and os.path.isfile(found):
            return found
    return None
