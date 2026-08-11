"""``python -m worker`` — the container's command."""

from __future__ import annotations

import sys

from worker.main import main

if __name__ == "__main__":
    sys.exit(main())
