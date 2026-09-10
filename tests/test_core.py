from systemd_crashloop.core import (
    CAUSE_CLEAN_NOT_CRASHING,
    CAUSE_CONFIG_ERROR,
    CAUSE_MISSING_DEPENDENCY,
    CAUSE_NONZERO_EXIT,
    CAUSE_OOM_KILLED,
    CAUSE_START_LIMIT_HIT,
    CAUSE_TIMEOUT,
    CAUSE_UNKNOWN,
    UnitState,
    classify_from_journal,
    diagnose,
    get_recent_journal,
    get_unit_show,
    list_failed_units,
)


def _state(**kwargs):
    defaults = dict(
        name="myapp.service", active_state="failed", sub_state="failed",
        result="exit-code", exec_main_status=1, exec_main_code="exited",
        n_restarts=5, unit_file_state="enabled",
    )
    defaults.update(kwargs)
    return UnitState(**defaults)


def test_classify_from_journal_oom():
    text = "Sep 10 08:00:00 host kernel: Out of memory: Killed process 1234 (myapp)"
    assert classify_from_journal(text) == CAUSE_OOM_KILLED


def test_classify_from_journal_start_limit_hit():
    text = "Sep 10 08:00:00 host systemd[1]: myapp.service: Start request repeated too quickly."
    assert classify_from_journal(text) == CAUSE_START_LIMIT_HIT


def test_classify_from_journal_missing_dependency():
    text = "Sep 10 08:00:00 host systemd[1]: Dependency failed for My App."
    assert classify_from_journal(text) == CAUSE_MISSING_DEPENDENCY


def test_classify_from_journal_timeout():
    text = "Sep 10 08:00:00 host systemd[1]: myapp.service: Timeout starting service."
    assert classify_from_journal(text) == CAUSE_TIMEOUT


def test_classify_from_journal_config_error():
    text = "Sep 10 08:00:00 host systemd[1]: myapp.service: Unknown lvalue 'Bogus' in section 'Service'."
    assert classify_from_journal(text) == CAUSE_CONFIG_ERROR


def test_classify_from_journal_no_match_returns_none():
    text = "Sep 10 08:00:00 host myapp[1234]: doing normal application work"
    assert classify_from_journal(text) is None


def test_diagnose_not_crashing_when_active_and_no_restarts():
    state = _state(active_state="active", sub_state="running", result="", n_restarts=0)
    report = diagnose(state, "some normal log output")
    assert report.cause == CAUSE_CLEAN_NOT_CRASHING


def test_diagnose_uses_journal_classification_first():
    state = _state()
    journal = "kernel: Out of memory: Killed process 999 (myapp)"
    report = diagnose(state, journal)
    assert report.cause == CAUSE_OOM_KILLED
    assert report.evidence


def test_diagnose_falls_back_to_result_oom_kill():
    state = _state(result="oom-kill")
    report = diagnose(state, "no useful pattern here")
    assert report.cause == CAUSE_OOM_KILLED


def test_diagnose_falls_back_to_result_start_limit_hit():
    state = _state(result="start-limit-hit")
    report = diagnose(state, "no useful pattern here")
    assert report.cause == CAUSE_START_LIMIT_HIT


def test_diagnose_falls_back_to_nonzero_exit():
    state = _state(result="exit-code", exec_main_code="exited", exec_main_status=1)
    report = diagnose(state, "no useful pattern here at all")
    assert report.cause == CAUSE_NONZERO_EXIT


def test_diagnose_falls_back_to_killed_signal():
    state = _state(result="signal", exec_main_code="killed", exec_main_status=None)
    report = diagnose(state, "no useful pattern here at all")
    assert report.cause == CAUSE_NONZERO_EXIT


def test_diagnose_unknown_when_nothing_matches():
    state = _state(result="", exec_main_code="", exec_main_status=None, active_state="failed")
    report = diagnose(state, "totally uninformative log text")
    assert report.cause == CAUSE_UNKNOWN


def test_diagnose_treats_high_restart_count_as_crash_loop_even_if_not_failed():
    state = _state(active_state="activating", sub_state="auto-restart", result="", n_restarts=10)
    journal = "systemd[1]: myapp.service: Start request repeated too quickly."
    report = diagnose(state, journal)
    assert report.cause == CAUSE_START_LIMIT_HIT


def test_report_to_dict_roundtrip():
    state = _state()
    journal = "kernel: Out of memory: Killed process 999 (myapp)"
    report = diagnose(state, journal)
    d = report.to_dict()
    assert d["unit"] == "myapp.service"
    assert d["cause"] == CAUSE_OOM_KILLED
    assert d["state"]["n_restarts"] == 5
    assert isinstance(d["evidence"], list)


def test_get_unit_show_parses_properties():
    sample = (
        "ActiveState=failed\nSubState=failed\nResult=exit-code\n"
        "ExecMainStatus=1\nExecMainCode=exited\nNRestarts=5\nUnitFileState=enabled\n"
    )

    def fake_runner(cmd, timeout=15):
        return sample

    state = get_unit_show("myapp.service", runner=fake_runner)
    assert state.active_state == "failed"
    assert state.n_restarts == 5
    assert state.exec_main_status == 1


def test_get_unit_show_handles_missing_int_gracefully():
    sample = "ActiveState=active\nSubState=running\nResult=\nExecMainStatus=\nExecMainCode=\nNRestarts=\nUnitFileState=enabled\n"

    def fake_runner(cmd, timeout=15):
        return sample

    state = get_unit_show("myapp.service", runner=fake_runner)
    assert state.exec_main_status is None
    assert state.n_restarts is None


def test_get_recent_journal_calls_journalctl_with_unit(monkeypatch):
    calls = []

    def fake_runner(cmd, timeout=15):
        calls.append(cmd)
        return "some log lines"

    text = get_recent_journal("myapp.service", lines=50, runner=fake_runner)
    assert text == "some log lines"
    assert calls[0][:2] == ["journalctl", "-u"]
    assert "myapp.service" in calls[0]
    assert "50" in calls[0]


def test_list_failed_units_parses_names():
    sample = "myapp.service loaded failed failed My App\nother.service loaded failed failed Other\n"

    def fake_runner(cmd, timeout=15):
        return sample

    names = list_failed_units(runner=fake_runner)
    assert names == ["myapp.service", "other.service"]


def test_list_failed_units_empty_when_no_output():
    def fake_runner(cmd, timeout=15):
        return ""

    assert list_failed_units(runner=fake_runner) == []
