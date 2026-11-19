"""Start Formatly on the LAN using the shared CLI/service entry point.

Run ``python app.py`` to serve the built Vue workbench and open a ready browser.
Use ``--local-only`` for loopback access or ``--no-browser`` for terminal use.
Development with Vue hot reload uses ``python start_dev.py``.
"""
from __future__ import annotations

import sys

from formatly.interfaces.cli import main as cli_main


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return cli_main(["serve", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
