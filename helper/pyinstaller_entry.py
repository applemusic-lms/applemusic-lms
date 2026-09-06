"""PyInstaller entry point.

Freezing applemusic_helper/__main__.py directly breaks its `from . import ...`
relative imports, so the frozen binary starts here instead.

SPDX-License-Identifier: GPL-3.0-only
"""

from applemusic_helper.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
