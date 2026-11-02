"""Entry point shared by `python -m turingscreen` and start.pyw."""

from __future__ import annotations

from . import crash


def run(argv: list[str] | None = None) -> int:
    crash.install()
    from .cli import main  # imported late so import errors are caught by the crash hook

    return main(argv)
