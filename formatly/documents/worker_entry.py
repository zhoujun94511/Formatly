"""Execute a Python worker only after its parent has established containment."""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys


def main() -> None:
    if sys.stdin.buffer.readline(32) != b"FORMATLY-WORKER\n":
        raise SystemExit(2)
    arguments = json.loads(sys.argv[1])
    if not isinstance(arguments, list) or not arguments or any(not isinstance(value, str) for value in arguments):
        raise SystemExit(2)
    if arguments[0] == "-B":
        arguments = arguments[1:]
    if not arguments:
        raise SystemExit(2)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from formatly.documents.processes import managed_worker_scope

    with managed_worker_scope():
        if arguments[0] == "-m" and len(arguments) >= 2:
            module = arguments[1]
            sys.argv = [module, *arguments[2:]]
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        elif not arguments[0].startswith("-"):
            sys.argv = arguments
            runpy.run_path(arguments[0], run_name="__main__")
        else:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
