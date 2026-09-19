#!/usr/bin/env python3
"""Charter extension: charter.py — Python runtime launcher.

Usage: charter.py <script-name> [args...]

Dispatches to the Charter helper scripts so that Spec Kit projects initialised
with ``--script py`` can reference a single ``{SCRIPT}`` entry point.

Resolution order for ``<script-name>``:

1. A native module ``scripts/python/<script_name>.py`` (dashes replaced by
   underscores) exposing ``main(argv: list[str]) -> int`` is imported and run
   in-process.
2. Otherwise the bash twin ``scripts/bash/<script-name>.sh`` is executed with a
   bash interpreter located by ``find_bash`` (``CHARTER_BASH``, Git for
   Windows, then ``PATH``), with stdin/stdout/stderr inherited and the child's
   exit code returned.

Exit codes:
  0   dispatched script succeeded (or --help)
  1   no argument, unknown script name, bash not found, native module failure
  130 interrupted
  *   exit code of the dispatched script
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASH_DIR = SCRIPT_DIR.parent / "bash"
NAME_RE = re.compile(r"^[a-z0-9-]+$")
RESERVED = frozenset({"charter", "charter-common"})
IS_WINDOWS = os.name == "nt"


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def configure_utf8() -> None:
    """Make stdout/stderr UTF-8 so ❌/⚠️ prefixes never raise on a legacy console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ── Name resolution ──────────────────────────────────────────────────────────


def available_scripts(bash_dir: Path, python_dir: Path) -> list[str]:
    """Sorted dash-form names of every dispatchable script (bash or native)."""
    names: set[str] = set()
    if bash_dir.is_dir():
        for path in bash_dir.glob("*.sh"):
            names.add(path.stem)
    if python_dir.is_dir():
        for path in python_dir.glob("*.py"):
            names.add(path.stem.replace("_", "-"))
    return sorted(name for name in names if name not in RESERVED)


def usage(bash_dir: Path, python_dir: Path) -> str:
    lines = ["Usage: charter.py <script-name> [args...]", "", "Available scripts:"]
    lines.extend(f"  {name}" for name in available_scripts(bash_dir, python_dir))
    return "\n".join(lines)


def resolve_script(name: str, bash_dir: Path, python_dir: Path) -> tuple[str, Path] | None:
    """Return ("python", module_path) or ("bash", script_path), or None if unknown."""
    if not NAME_RE.match(name) or name in RESERVED:
        return None
    native = python_dir / f"{name.replace('-', '_')}.py"
    if native.is_file():
        return ("python", native)
    twin = bash_dir / f"{name}.sh"
    if twin.is_file():
        return ("bash", twin)
    return None


# ── Native modules (Phase 2 seam) ────────────────────────────────────────────


def run_native(name: str, module_path: Path, args: list[str]) -> int:
    """Import ``module_path`` and call its ``main(argv) -> int``."""
    try:
        spec = importlib.util.spec_from_file_location(f"charter_{module_path.stem}", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        entry = getattr(module, "main", None)
        if not callable(entry):
            raise AttributeError("module has no main(argv) function")
        result = entry(list(args))
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        _err(str(code))
        return 1
    except Exception as exc:  # noqa: BLE001 — any failure must become a clean exit code
        _err(f"❌ ERROR: charter script '{name}' failed: {exc}")
        return 1
    return int(result or 0)


# ── Bash execution (completed in the next task) ──────────────────────────────


def find_bash() -> str | None:
    return shutil.which("bash")


def run_bash(bash: str, script: Path, args: list[str]) -> int:
    try:
        return subprocess.run([bash, script.as_posix(), *args]).returncode
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        _err(f"❌ ERROR: failed to start bash ({bash}): {exc}")
        return 1


# ── Entry point ──────────────────────────────────────────────────────────────


def main(argv: list[str], bash_dir: Path = BASH_DIR, python_dir: Path = SCRIPT_DIR) -> int:
    configure_utf8()
    if not argv:
        print(usage(bash_dir, python_dir))
        return 1
    if argv[0] in ("-h", "--help"):
        print(usage(bash_dir, python_dir))
        return 0

    name, args = argv[0], list(argv[1:])
    resolved = resolve_script(name, bash_dir, python_dir)
    if resolved is None:
        _err(f"❌ ERROR: Unknown charter script: {name}")
        return 1

    kind, path = resolved
    if kind == "python":
        return run_native(name, path, args)

    bash = find_bash()
    if bash is None:
        _err(
            f"❌ ERROR: Charter's Python launcher needs bash to run '{name}'. "
            "Install Git for Windows (or bash) or set CHARTER_BASH to a bash executable."
        )
        return 1
    return run_bash(bash, path, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
