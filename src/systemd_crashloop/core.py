"""Core logic for systemd-crashloop.

The problem: Kubernetes has a well-developed ecosystem of tools
(crashcause, k8s-crashloop, kubernetes-crash-guard-operator, ...) that
classify *why* a pod is in CrashLoopBackOff -- OOMKilled vs. probe
failure vs. missing config vs. plain application exit -- instead of
leaving the operator to manually run `kubectl describe` + `kubectl logs
--previous` and eyeball it. Bare-metal/VM systemd services have the
exact same "Start request repeated too quickly" / start-limit-hit
failure mode (extensively documented across forums and blog posts), but
nothing plays the "crashcause" role for a plain `systemctl` unit: the
standard advice everywhere is the same manual ritual --
`systemctl status`, `journalctl -u`, `systemctl reset-failed` -- with no
automated root-cause classification.

This tool automates that triage for one or more systemd units: it reads
unit state (`systemctl show`) and recent journal history
(`journalctl -u`), classifies the crash-loop cause into one of a small
set of stable codes (oom_killed, start_limit_hit, missing_dependency,
timeout, nonzero_exit, config_error, unknown), and reports the specific
evidence (exit code, signal, last relevant log lines) it based that on.

Strictly read-only: it never restarts, resets, stops, or reconfigures
anything -- no `systemctl reset-failed`, no `systemctl restart`, no
editing of unit files. It only reads `systemctl show` and `journalctl`.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional


CAUSE_OOM_KILLED = "oom_killed"
CAUSE_START_LIMIT_HIT = "start_limit_hit"
CAUSE_MISSING_DEPENDENCY = "missing_dependency"
CAUSE_TIMEOUT = "timeout"
CAUSE_CONFIG_ERROR = "config_error"
CAUSE_NONZERO_EXIT = "nonzero_exit"
CAUSE_CLEAN_NOT_CRASHING = "not_crashing"
CAUSE_UNKNOWN = "unknown"
CAUSE_DIAGNOSTIC_FAILED = "diagnostic_failed"
CAUSE_UNIT_NOT_FOUND = "unit_not_found"

# Human-readable one-line explanations per cause code.
CAUSE_EXPLANATIONS = {
    CAUSE_OOM_KILLED: "The kernel OOM killer terminated this service's process(es) "
                       "due to memory pressure.",
    CAUSE_START_LIMIT_HIT: "systemd's start-rate limiter tripped: the service crashed "
                            "faster than StartLimitBurst/StartLimitIntervalSec allow, "
                            "so systemd gave up restarting it automatically.",
    CAUSE_MISSING_DEPENDENCY: "The service failed to start because a dependency "
                               "(another unit, a device, a mount, a socket) was not "
                               "available when it tried to start.",
    CAUSE_TIMEOUT: "The service did not signal readiness within its configured "
                   "start/stop timeout and systemd killed it.",
    CAUSE_CONFIG_ERROR: "The service's own unit file or configuration is invalid "
                        "(syntax error, missing ExecStart, bad option), preventing "
                        "it from ever starting correctly.",
    CAUSE_NONZERO_EXIT: "The service's process exited with a non-zero code or was "
                        "killed by a signal -- likely an application-level bug or "
                        "misconfiguration, not a systemd/environment problem.",
    CAUSE_CLEAN_NOT_CRASHING: "This service is not currently in a crash-loop state.",
    CAUSE_UNKNOWN: "Could not confidently classify the failure from available "
                   "evidence -- review the log excerpt manually.",
    CAUSE_DIAGNOSTIC_FAILED: "Could not query this unit's state at all (systemctl "
                              "produced no properties -- systemctl may be missing, "
                              "the D-Bus/systemd connection may be unavailable, or "
                              "permission was denied). This is NOT a confirmed "
                              "healthy/not-crashing result.",
    CAUSE_UNIT_NOT_FOUND: "systemd has no loaded unit by this name (LoadState is "
                          "'not-found' or 'masked') -- likely a typo in the unit "
                          "name, or the unit file was removed/never installed. "
                          "This is NOT a confirmed healthy/not-crashing result.",
}


def run(cmd: list, timeout: int = 15) -> str:
    """Run a read-only subprocess command, returning stdout (empty on error)."""
    return _run_checked(cmd, timeout=timeout)[0]


def _run_checked(cmd: list, timeout: int = 15) -> tuple:
    """Run a read-only subprocess command, returning (stdout, ok).

    ``ok`` is False when the command could not be run at all (binary
    missing, timeout) or exited non-zero -- i.e. whenever empty stdout does
    NOT reliably mean "ran fine, nothing to report", only "we could not
    check". Callers that need to distinguish those two cases (like
    `list_failed_units`) must use this instead of plain `run`.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return (result.stdout or "", result.returncode == 0)
    except (OSError, subprocess.SubprocessError):
        return ("", False)


@dataclass
class UnitState:
    name: str
    active_state: str = ""
    sub_state: str = ""
    result: str = ""
    exec_main_status: Optional[int] = None
    exec_main_code: str = ""  # "exited" | "killed" | "dumped" | ""
    n_restarts: Optional[int] = None
    unit_file_state: str = ""
    load_state: str = ""  # "loaded" | "not-found" | "masked" | ...


def get_unit_show(unit: str, runner=run) -> UnitState:
    props = [
        "ActiveState", "SubState", "Result", "ExecMainStatus", "ExecMainCode",
        "NRestarts", "UnitFileState", "LoadState",
    ]
    out = runner(["systemctl", "show", unit, f"--property={','.join(props)}"])
    values = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            values[k] = v

    def _int(key):
        v = values.get(key, "")
        try:
            return int(v)
        except ValueError:
            return None

    return UnitState(
        name=unit,
        active_state=values.get("ActiveState", ""),
        sub_state=values.get("SubState", ""),
        result=values.get("Result", ""),
        exec_main_status=_int("ExecMainStatus"),
        exec_main_code=values.get("ExecMainCode", ""),
        n_restarts=_int("NRestarts"),
        unit_file_state=values.get("UnitFileState", ""),
        load_state=values.get("LoadState", ""),
    )


def get_recent_journal(unit: str, lines: int = 200, runner=run) -> str:
    return runner(["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"])


# Patterns checked in priority order -- first match wins, since some log
# lines could technically match more than one pattern (e.g. an OOM kill
# also produces a nonzero exit line).
_OOM_RE = re.compile(r"\b(out of memory|oom.?killer|killed process \d+)\b", re.IGNORECASE)
_START_LIMIT_RE = re.compile(r"start.limit.hit|start request repeated too quickly", re.IGNORECASE)
_DEP_RE = re.compile(
    r"(dependency failed for|timed out waiting for device|"
    r"failed to mount|job .* failed .*dependency)",
    re.IGNORECASE,
)
_TIMEOUT_RE = re.compile(r"(timeout|timed out) (starting|stopping) ", re.IGNORECASE)
_CONFIG_RE = re.compile(
    r"(unknown (lvalue|key name)|failed to parse|bad unit file|"
    r"exec(start|stop).* does not exist|configuration file .* is marked)",
    re.IGNORECASE,
)


def classify_from_journal(journal_text: str) -> Optional[str]:
    """Best-effort classification purely from journal text patterns."""
    if _OOM_RE.search(journal_text):
        return CAUSE_OOM_KILLED
    if _START_LIMIT_RE.search(journal_text):
        return CAUSE_START_LIMIT_HIT
    if _DEP_RE.search(journal_text):
        return CAUSE_MISSING_DEPENDENCY
    if _TIMEOUT_RE.search(journal_text):
        return CAUSE_TIMEOUT
    if _CONFIG_RE.search(journal_text):
        return CAUSE_CONFIG_ERROR
    return None


@dataclass
class CrashLoopReport:
    unit: str
    cause: str
    explanation: str
    evidence: list = field(default_factory=list)  # list[str] of relevant journal lines
    state: Optional[UnitState] = None

    def to_dict(self) -> dict:
        return {
            "unit": self.unit,
            "cause": self.cause,
            "explanation": self.explanation,
            "evidence": list(self.evidence),
            "state": {
                "active_state": self.state.active_state if self.state else None,
                "sub_state": self.state.sub_state if self.state else None,
                "result": self.state.result if self.state else None,
                "exec_main_status": self.state.exec_main_status if self.state else None,
                "exec_main_code": self.state.exec_main_code if self.state else None,
                "n_restarts": self.state.n_restarts if self.state else None,
                "load_state": self.state.load_state if self.state else None,
            } if self.state else None,
        }


def _relevant_evidence(journal_text: str, max_lines: int = 8) -> list:
    """Return the last few non-empty journal lines as evidence context."""
    lines = [l for l in journal_text.splitlines() if l.strip()]
    return lines[-max_lines:]


def diagnose(state: UnitState, journal_text: str) -> CrashLoopReport:
    """Classify a unit's crash-loop cause from its current state + journal."""
    state_is_empty = (
        state.active_state == ""
        and state.sub_state == ""
        and state.result == ""
        and state.exec_main_code == ""
        and state.exec_main_status is None
        and state.n_restarts is None
        and state.unit_file_state == ""
    )
    if state_is_empty:
        return CrashLoopReport(
            unit=state.name,
            cause=CAUSE_DIAGNOSTIC_FAILED,
            explanation=CAUSE_EXPLANATIONS[CAUSE_DIAGNOSTIC_FAILED],
            evidence=_relevant_evidence(journal_text),
            state=state,
        )

    if state.load_state in ("not-found", "masked"):
        # `systemctl show <typo'd-or-uninstalled-unit>` does NOT fail or
        # produce empty output -- it happily returns ActiveState=inactive,
        # SubState=dead, Result="" for a unit that was never loaded at all.
        # Without this check that flows straight into the "not failed, few
        # restarts" branch below and gets reported as CAUSE_CLEAN_NOT_CRASHING
        # ("not currently in a crash-loop state") -- false reassurance about
        # a unit systemd never even loaded, exactly the silent-wrong-answer
        # failure mode this tool exists to prevent.
        return CrashLoopReport(
            unit=state.name,
            cause=CAUSE_UNIT_NOT_FOUND,
            explanation=CAUSE_EXPLANATIONS[CAUSE_UNIT_NOT_FOUND],
            evidence=_relevant_evidence(journal_text),
            state=state,
        )

    is_failed_state = state.active_state == "failed" or state.result not in ("", "success")
    is_restarting_a_lot = (state.n_restarts or 0) >= 3

    if not is_failed_state and not is_restarting_a_lot:
        return CrashLoopReport(
            unit=state.name,
            cause=CAUSE_CLEAN_NOT_CRASHING,
            explanation=CAUSE_EXPLANATIONS[CAUSE_CLEAN_NOT_CRASHING],
            evidence=[],
            state=state,
        )

    cause = classify_from_journal(journal_text)

    if cause is None:
        if state.result == "oom-kill":
            cause = CAUSE_OOM_KILLED
        elif state.result == "start-limit-hit":
            cause = CAUSE_START_LIMIT_HIT
        elif state.result == "timeout":
            cause = CAUSE_TIMEOUT
        elif state.exec_main_code == "killed":
            cause = CAUSE_NONZERO_EXIT
        elif state.exec_main_code == "exited" and (state.exec_main_status or 0) != 0:
            cause = CAUSE_NONZERO_EXIT
        else:
            cause = CAUSE_UNKNOWN

    return CrashLoopReport(
        unit=state.name,
        cause=cause,
        explanation=CAUSE_EXPLANATIONS[cause],
        evidence=_relevant_evidence(journal_text),
        state=state,
    )


def diagnose_unit(unit: str, journal_lines: int = 200, runner=run) -> CrashLoopReport:
    state = get_unit_show(unit, runner=runner)
    journal_text = get_recent_journal(unit, lines=journal_lines, runner=runner)
    return diagnose(state, journal_text)


def list_failed_units(runner=_run_checked) -> tuple:
    """Return (names, ok) -- the names of all units currently in the
    'failed' state, plus whether `systemctl list-units` itself succeeded.

    ``ok`` is False when the command could not be run at all (missing
    systemctl binary, no D-Bus/systemd connection, permission denied) or
    exited non-zero. In that case an empty ``names`` list means "we could
    not enumerate failed units at all", not "there are none currently
    failed" -- collapsing those two into the same empty list would let a
    caller running with insufficient permissions (or against a
    misconfigured D-Bus) report a false "no failed units" clean bill of
    health, exactly the silent-wrong-answer failure mode this tool exists
    to prevent for individual units.
    """
    out, ok = runner(["systemctl", "list-units", "--state=failed", "--no-legend", "--plain", "--no-pager"])
    names = []
    for line in out.splitlines():
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names, ok
