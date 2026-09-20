from systemd_crashloop.core import (
    CAUSE_CLEAN_NOT_CRASHING,
    CAUSE_CONFIG_ERROR,
    CAUSE_DIAGNOSTIC_FAILED,
    CAUSE_MISSING_DEPENDENCY,
    CAUSE_NONZERO_EXIT,
    CAUSE_OOM_KILLED,
    CAUSE_START_LIMIT_HIT,
    CAUSE_TIMEOUT,
    CAUSE_UNIT_NOT_FOUND,
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


def test_diagnose_reports_unit_not_found_for_nonexistent_unit():
    """`systemctl show typo.service` for a unit systemd never loaded does NOT
    fail or produce empty output -- it returns LoadState=not-found,
    ActiveState=inactive, SubState=dead, Result="", n_restarts=None. Before
    this fix that flowed straight past the state_is_empty check into the
    'not failed, no restarts' branch and was reported as CAUSE_CLEAN_NOT_CRASHING
    -- false reassurance that a typo'd/uninstalled unit is healthy, exactly
    the failure mode this tool exists to catch. Must be reported as
    CAUSE_UNIT_NOT_FOUND instead."""
    state = _state(
        active_state="inactive", sub_state="dead", result="",
        exec_main_status=None, exec_main_code="", n_restarts=None,
        unit_file_state="", load_state="not-found",
    )
    report = diagnose(state, "")
    assert report.cause == CAUSE_UNIT_NOT_FOUND
    assert report.cause != CAUSE_CLEAN_NOT_CRASHING


def test_diagnose_reports_unit_not_found_for_masked_unit():
    state = _state(
        active_state="inactive", sub_state="dead", result="",
        exec_main_status=None, exec_main_code="", n_restarts=None,
        unit_file_state="masked", load_state="masked",
    )
    report = diagnose(state, "")
    assert report.cause == CAUSE_UNIT_NOT_FOUND


def test_diagnose_unit_via_get_unit_show_with_not_found_unit(monkeypatch):
    """End-to-end: get_unit_show() parsing systemctl's real LoadState=not-found
    output must flow through diagnose() as CAUSE_UNIT_NOT_FOUND, not silently
    as 'not crashing'."""
    sample = (
        "LoadState=not-found\nActiveState=inactive\nSubState=dead\nResult=\n"
        "ExecMainStatus=\nExecMainCode=\nNRestarts=\nUnitFileState=\n"
    )

    def fake_runner(cmd, timeout=15):
        return sample

    state = get_unit_show("typo.service", runner=fake_runner)
    assert state.load_state == "not-found"
    report = diagnose(state, get_recent_journal("typo.service", runner=lambda cmd, timeout=15: ""))
    assert report.cause == CAUSE_UNIT_NOT_FOUND


def test_diagnose_uses_journal_classification_first():
    state = _state()
    journal = "kernel: Out of memory: Killed process 999 (myapp)"
    report = diagnose(state, journal)
    assert report.cause == CAUSE_OOM_KILLED
    assert report.evidence


def test_diagnose_reports_diagnostic_failed_when_systemctl_show_returns_nothing():
    """If systemctl show produced no properties at all (systemctl missing, D-Bus
    down, permission denied), get_unit_show returns an all-empty/None UnitState.
    diagnose() must NOT interpret that as a healthy 'not crashing' unit -- it is
    an undetermined/failed diagnosis, not a confirmed all-clear."""
    state = UnitState(name="myapp.service")  # all defaults: "" / None
    report = diagnose(state, "")
    assert report.cause == CAUSE_DIAGNOSTIC_FAILED
    assert report.cause != CAUSE_CLEAN_NOT_CRASHING


def test_diagnose_unit_via_get_unit_show_with_empty_runner_output():
    """End-to-end: a runner that returns empty stdout (systemctl unavailable)
    must flow through get_unit_show -> diagnose as DIAGNOSTIC_FAILED, not
    silently as 'not crashing'."""
    def empty_runner(cmd):
        return ""

    state = get_unit_show("myapp.service", runner=empty_runner)
    report = diagnose(state, get_recent_journal("myapp.service", runner=empty_runner))
    assert report.cause == CAUSE_DIAGNOSTIC_FAILED


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


def test_diagnose_falls_back_to_result_timeout():
    # `systemctl show`'s Result property is set to "timeout" when a service
    # fails to signal readiness/stop within its configured timeout, distinct
    # from any journal text pattern. This fallback branch (core.py's
    # `elif state.result == "timeout": cause = CAUSE_TIMEOUT`) previously had
    # zero test coverage -- a regression here would silently misclassify a
    # timeout as CAUSE_UNKNOWN with nobody noticing.
    state = _state(result="timeout", exec_main_code="", exec_main_status=None)
    report = diagnose(state, "no useful pattern here at all")
    assert report.cause == CAUSE_TIMEOUT


def test_diagnose_unit_integration_wires_runner_through(monkeypatch):
    # diagnose_unit() (the public entry point CLI actually calls) had no
    # direct test coverage -- only its two halves (get_unit_show +
    # get_recent_journal) were tested in isolation. A wiring bug (e.g.
    # passing the wrong runner, or swapping state/journal_text arguments)
    # would not have been caught by the unit-level tests alone.
    calls = []

    def fake_runner(cmd, timeout=15):
        calls.append(cmd)
        if cmd[:2] == ["systemctl", "show"]:
            return (
                "ActiveState=failed\nSubState=failed\nResult=oom-kill\n"
                "ExecMainStatus=137\nExecMainCode=killed\nNRestarts=5\n"
                "UnitFileState=enabled\n"
            )
        if cmd[0] == "journalctl":
            return "Sep 10 08:00:00 host kernel: Out of memory: Killed process 1234 (myapp)\n"
        return ""

    from systemd_crashloop.core import diagnose_unit

    report = diagnose_unit("myapp.service", journal_lines=50, runner=fake_runner)
    assert report.cause == CAUSE_OOM_KILLED
    assert report.unit == "myapp.service"
    # Confirm the journal_lines argument was actually threaded through to
    # `journalctl -n <journal_lines>`, not silently dropped/hardcoded.
    journal_cmd = next(c for c in calls if c[0] == "journalctl")
    assert "50" in journal_cmd


def test_diagnose_trusts_authoritative_result_over_stale_journal_text():
    """The journal window (`-n 200` by default) commonly spans MULTIPLE
    restart cycles of a crash-looping unit. Before this fix,
    classify_from_journal()'s fixed-priority text scan ran FIRST and could
    match a stale line from an EARLIER, unrelated cycle (here: an OOM kill
    two restarts ago) even though systemd's own Result property for the
    CURRENT cycle names a different, unambiguous cause
    (start-limit-hit) -- silently reporting the wrong cause. Verified by
    reproducing against the pre-fix code: it returned 'oom_killed' here,
    not 'start_limit_hit'. Result is authoritative for the current cycle
    and must win over heuristic journal-text matching."""
    state = _state(
        active_state="failed", sub_state="failed", result="start-limit-hit",
        exec_main_status=None, exec_main_code="", n_restarts=6,
    )
    journal = (
        "Sep 10 07:00:00 host kernel: myapp invoked oom-killer\n"
        "Sep 10 07:00:00 host kernel: Out of memory: Killed process 1000 (myapp)\n"
        "Sep 10 07:00:05 host systemd[1]: myapp.service: Scheduled restart job.\n"
        "Sep 10 07:00:10 host myapp[1001]: starting up\n"
        "Sep 10 07:00:20 host myapp[1001]: exiting immediately, crash loop\n"
        "Sep 10 07:05:00 host systemd[1]: myapp.service: Start request repeated too quickly.\n"
        "Sep 10 07:05:00 host systemd[1]: myapp.service: Failed with result 'start-limit-hit'.\n"
    )
    report = diagnose(state, journal)
    assert report.cause == CAUSE_START_LIMIT_HIT
    assert report.cause != CAUSE_OOM_KILLED


def test_diagnose_still_uses_journal_when_result_is_generic():
    """Sanity check the fix doesn't over-trust Result: a generic/ambiguous
    Result value (e.g. exit-code, which covers many distinct application
    failures) must still fall through to journal-text classification when
    it matches a specific pattern -- Result-first only short-circuits for
    the three unambiguous values (oom-kill, start-limit-hit, timeout)."""
    state = _state(result="exit-code", exec_main_code="exited", exec_main_status=1)
    journal = "kernel: Out of memory: Killed process 999 (myapp)"
    report = diagnose(state, journal)
    assert report.cause == CAUSE_OOM_KILLED


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
        return sample, True

    names, ok = list_failed_units(runner=fake_runner)
    assert names == ["myapp.service", "other.service"]
    assert ok is True


def test_list_failed_units_empty_when_no_output():
    def fake_runner(cmd, timeout=15):
        return "", True

    names, ok = list_failed_units(runner=fake_runner)
    assert names == []
    assert ok is True


def test_list_failed_units_reports_not_ok_on_command_failure():
    """A failed/erroring `systemctl list-units` (missing binary, no D-Bus,
    permission denied) must surface ok=False, not be indistinguishable from
    a genuine empty result -- this is the exact false-clean-bill-of-health
    bug class already fixed in usbsmart-doctor/nft-splitbrain/trim-doctor/
    oom-postmortem, now closed here too."""

    def fake_runner(cmd, timeout=15):
        return "", False

    names, ok = list_failed_units(runner=fake_runner)
    assert names == []
    assert ok is False


def test_run_returns_empty_string_on_oserror(monkeypatch):
    """core.run() must swallow OSError from a missing/broken systemctl binary
    (e.g. PATH misconfiguration) and degrade to empty output rather than
    crashing the whole diagnostic -- this is what upstream callers rely on to
    reach CAUSE_DIAGNOSTIC_FAILED instead of propagating an exception."""
    import subprocess as sp

    from systemd_crashloop.core import run

    def fake_run(*args, **kwargs):
        raise OSError("systemctl: command not found")

    monkeypatch.setattr(sp, "run", fake_run)
    assert run(["systemctl", "show", "myapp.service"]) == ""


def test_run_returns_empty_string_on_timeout(monkeypatch):
    """Same guarantee, but for a hung systemctl/journalctl call exceeding the
    timeout: subprocess.TimeoutExpired is a SubprocessError subclass and must
    also degrade to empty output, not propagate."""
    import subprocess as sp

    from systemd_crashloop.core import run

    def fake_run(*args, **kwargs):
        raise sp.TimeoutExpired(cmd=["journalctl"], timeout=15)

    monkeypatch.setattr(sp, "run", fake_run)
    assert run(["journalctl", "-u", "myapp.service"]) == ""


def test_run_checked_reports_ok_true_on_successful_exit(monkeypatch):
    """The success path of _run_checked (subprocess actually runs and exits
    0) was never exercised by any prior test -- every existing test either
    raised an exception or bypassed _run_checked entirely via a fake
    runner. This is exactly the ok=True side of the ActiveState/ok mapping
    that list_failed_units and get_unit_show rely on to distinguish "ran
    fine" from "could not check" -- if returncode==0 were ever compared
    wrong (e.g. inverted, or compared against the wrong attribute), this
    line alone would silently convert every healthy systemctl call into a
    false CAUSE_DIAGNOSTIC_FAILED / ok=False report, with no test catching
    it."""
    import subprocess as sp

    from systemd_crashloop.core import _run_checked

    def fake_run(*args, **kwargs):
        return sp.CompletedProcess(args=args[0] if args else [], returncode=0, stdout="ActiveState=active\n")

    monkeypatch.setattr(sp, "run", fake_run)
    out, ok = _run_checked(["systemctl", "show", "myapp.service"])
    assert out == "ActiveState=active\n"
    assert ok is True


def test_run_checked_reports_ok_false_on_nonzero_exit_without_exception(monkeypatch):
    """Mirror case: the subprocess runs to completion (no OSError/timeout)
    but exits non-zero -- e.g. `systemctl list-units` refused by a
    misconfigured D-Bus policy, which returns a non-zero exit and empty
    stdout rather than raising. This must also surface ok=False so callers
    don't mistake a refused/failed command for a genuinely empty, healthy
    result."""
    import subprocess as sp

    from systemd_crashloop.core import _run_checked

    def fake_run(*args, **kwargs):
        return sp.CompletedProcess(args=args[0] if args else [], returncode=1, stdout="")

    monkeypatch.setattr(sp, "run", fake_run)
    out, ok = _run_checked(["systemctl", "list-units", "--state=failed"])
    assert out == ""
    assert ok is False
