from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.internal_tools import *  # noqa: F401,F403
from backend.services.internal_tools import _week_context_for_date  # noqa: F401


def main() -> None:
    from backend.app import main as run_backend

    run_backend()


if __name__ == "__main__":
    main()
