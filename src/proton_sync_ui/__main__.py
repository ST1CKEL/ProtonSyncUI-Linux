"""Erlaubt ``python -m proton_sync_ui`` als Alias der Kommandozeile."""

from __future__ import annotations

import sys

from .cli.main import main

if __name__ == "__main__":
    sys.exit(main())
