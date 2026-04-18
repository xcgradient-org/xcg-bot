#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: open_obsidian.py <vault-path>")

    vault_path = Path(sys.argv[1]).expanduser().resolve()
    vault_path.mkdir(parents=True, exist_ok=True)
    uri = f"obsidian://open?path={quote(str(vault_path), safe='/')}"

    if shutil.which("obsidian"):
        result = subprocess.run(["obsidian", uri], check=False)
        if result.returncode == 0:
            return 0

    if shutil.which("xdg-open"):
        result = subprocess.run(["xdg-open", uri], check=False)
        return result.returncode

    raise SystemExit("Neither 'obsidian' nor 'xdg-open' is available.")


if __name__ == "__main__":
    raise SystemExit(main())

