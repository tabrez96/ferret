import io
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ferret.tools.check_real import main
from tests.fixtures.make_statements import LOCKED_PASSWORD, MERCHANTS, PAYMENT

REPO = Path(__file__).resolve().parent.parent


def run_main(directory, ask=lambda _: ""):
    out = io.StringIO()
    assert main([str(directory)], ask=ask, out=out) == 0
    return out.getvalue()


def test_reports_each_file(statements):
    text = run_main(statements["aug_2026"].path.parent)
    assert "aug_2026.pdf: reconciled, 6 lines (5 debits, 1 credits), difference 0.00 AED" in text
    assert "unbalanced.pdf: didnt_add_up" in text
    assert "difference -10.00 AED" in text
    assert "unsupported_bank.pdf: unsupported" in text
    assert "not_a_statement.pdf: unsupported" in text
    assert "locked.pdf: locked, skipped" in text
    assert "7 files: 3 reconciled, 1 didnt_add_up, 3 other" in text


def test_password_prompt_retries_and_reuses(statements):
    answers = iter(["wrong", LOCKED_PASSWORD])
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return next(answers)

    text = run_main(statements["aug_2026"].path.parent, ask)
    assert "locked.pdf: reconciled" in text
    assert "7 files: 4 reconciled, 1 didnt_add_up, 2 other" in text
    assert len(calls) == 2


def test_output_has_no_statement_content(statements):
    text = run_main(statements["aug_2026"].path.parent)
    assert not any(m in text for m in MERCHANTS)
    assert "PAYMENT" not in text and PAYMENT not in text
    assert "4821" not in text and "7305" not in text


def snapshot(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_writes_nothing(statements, tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    before = snapshot(tmp_path)
    run_main(statements["aug_2026"].path.parent)
    assert snapshot(tmp_path) == before
    assert list(cwd.iterdir()) == []


def test_logs_nothing(statements, caplog):
    caplog.set_level(logging.DEBUG)
    run_main(statements["aug_2026"].path.parent)
    assert caplog.records == []
    assert logging.getLogger("x").isEnabledFor(logging.INFO)


def test_missing_dir_exit_2(tmp_path):
    assert main([str(tmp_path / "nope")]) == 2


def test_module_runs_as_command(statements, tmp_path):
    d = tmp_path / "real"
    d.mkdir()
    for name in ("aug_2026", "unbalanced"):
        shutil.copy(statements[name].path, d)
    before = sorted(p.name for p in d.iterdir())
    result = subprocess.run(
        [sys.executable, "-m", "ferret.tools.check_real", str(d)],
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0
    assert "2 files: 1 reconciled, 1 didnt_add_up, 0 other" in result.stdout
    assert sorted(p.name for p in d.iterdir()) == before
