"""Print a signed, 15-minute coach console link for the operator.

Normally the coach sends /console to the bot. This is the fallback for the
person who holds the deployment's COACH_LINK_SECRET and PUBLIC_BASE_URL:

    python scripts/coach_link.py            # link to Today
    python scripts/coach_link.py /coach/athletes
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.access import console_link  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/coach"
    if not settings.coach_link_secret or not settings.public_base_url:
        print("Set COACH_LINK_SECRET and PUBLIC_BASE_URL first.", file=sys.stderr)
        return 1
    print(console_link(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
