import json

from systemd_crashloop.cli import main
from systemd_crashloop.core import CrashLoopReport, UnitState, CAUSE_OOM_KILLED, CAUSE_CLEAN_NOT_CRASHING


def _fake_report(cause=CAUSE_OOM_KILLED, unit="myapp.service"):
    state = UnitState(
        name=unit, active_state="failed", sub_state="failed", result="oom-kill",
        exec_main_status=137, exec_main_code="killed", n_restarts=5, unit_file_state="enabled",
    )
    return CrashLoopReport(
        unit=unit, cause=cause, explanation="example explanation",
        evidence=["log line 1", "log line 2"], state=state,
    )


def test_version(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert "systemd-crashloop" in capsys.readouterr().out


def test_diagnose_explicit_unit_text_output(monkeypatch, capsys):
    monkeypatch.setattr(
        "systemd_crashloop.cli.diagnose_unit",
        lambda unit, journal_lines: _fake_report(unit=unit),
    )
    rc = main(["myapp.service"])
    out = capsys.readouterr().out
    assert "myapp.service: oom_killed" in out
    assert rc == 2


def test_diagnose_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        "systemd_crashloop.cli.diagnose_unit",
        lambda unit, journal_lines: _fake_report(unit=unit),
    )
    rc = main(["myapp.service", "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert len(parsed) == 1
    assert parsed[0]["cause"] == CAUSE_OOM_KILLED
    assert rc == 2


def test_no_units_uses_list_failed_units(monkeypatch, capsys):
    monkeypatch.setattr("systemd_crashloop.cli.list_failed_units", lambda: ["a.service", "b.service"])
    monkeypatch.setattr(
        "systemd_crashloop.cli.diagnose_unit",
        lambda unit, journal_lines: _fake_report(unit=unit),
    )
    rc = main([])
    out = capsys.readouterr().out
    assert "a.service" in out and "b.service" in out
    assert rc == 2


def test_no_units_and_none_failed_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr("systemd_crashloop.cli.list_failed_units", lambda: [])
    rc = main([])
    out = capsys.readouterr().out
    assert "No failed units found" in out
    assert rc == 0


def test_not_crashing_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        "systemd_crashloop.cli.diagnose_unit",
        lambda unit, journal_lines: _fake_report(cause=CAUSE_CLEAN_NOT_CRASHING, unit=unit),
    )
    rc = main(["myapp.service"])
    assert rc == 0
