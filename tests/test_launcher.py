"""Tests for scripts/python/charter.py — the Python runtime launcher."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "scripts" / "python" / "charter.py"
BASH_DIR = ROOT / "scripts" / "bash"
FIXTURES = ROOT / "tests" / "fixtures"
HAS_BASH = shutil.which("bash") is not None


@pytest.fixture(scope="module")
def launcher():
    """Load scripts/python/charter.py as a module (scripts/python is not a package)."""
    spec = importlib.util.spec_from_file_location("charter_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal Spec Kit project with the sample registry, like tests/test_scripts.sh builds."""
    root = tmp_path / "project"
    (root / ".specify" / "memory").mkdir(parents=True)
    (root / ".specify" / "charter").mkdir(parents=True)
    shutil.copytree(FIXTURES / "sample-registry", root / ".charter")
    (root / ".specify" / "charter" / "config.yml").write_text(
        'registry: ".charter"\nregistry_type: "directory"\n', encoding="utf-8"
    )
    return root


def run_launcher(*args: str, stdin: str | None = None, cwd: Path | None = None):
    # encoding="utf-8": the launcher and the scripts emit ❌/⚠️; the default
    # locale decoder on Windows (cp1252) would mangle them.
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8", cwd=cwd,
    )


def run_direct(script: str, *args: str, stdin: str | None = None, cwd: Path | None = None):
    return subprocess.run(
        ["bash", str(BASH_DIR / f"{script}.sh"), *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8", cwd=cwd,
    )


# ── Name resolution and usage (pure functions) ──────────────────────────────


class TestResolveScript:
    def test_resolves_bash_twin(self, launcher, tmp_path):
        assert launcher.resolve_script("state-check", BASH_DIR, tmp_path) == (
            "bash", BASH_DIR / "state-check.sh"
        )

    def test_prefers_native_module_when_present(self, launcher, tmp_path):
        native = tmp_path / "state_check.py"
        native.write_text("def main(argv):\n    return 0\n", encoding="utf-8")
        assert launcher.resolve_script("state-check", BASH_DIR, tmp_path) == ("python", native)

    @pytest.mark.parametrize("name", ["charter", "charter-common", "no-such-script", "../etc", "State-Check", ""])
    def test_rejects_reserved_unknown_and_malformed(self, launcher, name, tmp_path):
        assert launcher.resolve_script(name, BASH_DIR, tmp_path) is None


class TestUsage:
    def test_lists_shipped_scripts_without_dispatchers(self, launcher, tmp_path):
        names = launcher.available_scripts(BASH_DIR, tmp_path)
        assert "state-check" in names
        assert "heading-normalize" in names
        assert "charter" not in names
        assert "charter-common" not in names
        assert names == sorted(names)

    def test_native_modules_appear_with_dashes(self, launcher, tmp_path):
        (tmp_path / "only_native.py").write_text("def main(argv):\n    return 0\n", encoding="utf-8")
        assert "only-native" in launcher.available_scripts(BASH_DIR, tmp_path)

    def test_usage_text(self, launcher, tmp_path):
        text = launcher.usage(BASH_DIR, tmp_path)
        assert text.startswith("Usage: charter.py <script-name> [args...]")
        assert "  state-check" in text


# ── Native module seam ───────────────────────────────────────────────────────


class TestRunNative:
    def test_returns_main_result(self, launcher, tmp_path):
        module = tmp_path / "hello_native.py"
        module.write_text("def main(argv):\n    return 7 if argv == ['a'] else 3\n", encoding="utf-8")
        assert launcher.run_native("hello-native", module, ["a"]) == 7

    def test_system_exit_code_is_propagated(self, launcher, tmp_path):
        module = tmp_path / "exits.py"
        module.write_text("def main(argv):\n    raise SystemExit(4)\n", encoding="utf-8")
        assert launcher.run_native("exits", module, []) == 4

    def test_missing_main_reports_failure(self, launcher, tmp_path, capsys):
        module = tmp_path / "nomain.py"
        module.write_text("x = 1\n", encoding="utf-8")
        assert launcher.run_native("nomain", module, []) == 1
        assert "❌ ERROR: charter script 'nomain' failed:" in capsys.readouterr().err

    def test_raising_main_reports_failure(self, launcher, tmp_path, capsys):
        module = tmp_path / "boom.py"
        module.write_text("def main(argv):\n    raise RuntimeError('boom')\n", encoding="utf-8")
        assert launcher.run_native("boom", module, []) == 1
        assert "❌ ERROR: charter script 'boom' failed: boom" in capsys.readouterr().err


class TestMainDispatch:
    def test_no_argument_prints_usage_and_exits_1(self, launcher, capsys):
        assert launcher.main([]) == 1
        assert "Usage: charter.py" in capsys.readouterr().out

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_help_exits_0(self, launcher, flag, capsys):
        assert launcher.main([flag]) == 0
        out = capsys.readouterr().out
        assert "state-check" in out
        assert "charter-common" not in out

    def test_unknown_name(self, launcher, capsys):
        assert launcher.main(["no-such-script"]) == 1
        assert capsys.readouterr().err.strip() == "❌ ERROR: Unknown charter script: no-such-script"

    def test_native_module_bypasses_bash(self, launcher, tmp_path, monkeypatch):
        (tmp_path / "hello_native.py").write_text("def main(argv):\n    return 5\n", encoding="utf-8")

        def explode(*args, **kwargs):
            raise AssertionError("bash must not be spawned for a native module")

        monkeypatch.setattr(launcher.subprocess, "run", explode)
        assert launcher.main(["hello-native", "x"], bash_dir=BASH_DIR, python_dir=tmp_path) == 5
