# systemd-crashloop

[![CI](https://github.com/zhuhroscar-tech/systemd-crashloop/actions/workflows/ci.yml/badge.svg)](https://github.com/zhuhroscar-tech/systemd-crashloop/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/zhuhroscar-tech/systemd-crashloop?include_prereleases&label=release)](https://github.com/zhuhroscar-tech/systemd-crashloop/releases)
![Linux](https://img.shields.io/badge/platform-Linux-111111?logo=linux)

Classify *why* a systemd service is crash-looping — OOM killed, start-limit
hit, missing dependency, timeout, a config error, or a plain nonzero exit —
instead of manually reading `journalctl` output line by line.

## Simple explanation

When a background service on a Linux server keeps crashing and
restarting in a loop, there are several different possible reasons —
it ran out of memory, it's missing something it depends on, it's too
slow to start, its configuration is broken, or it just failed on its
own. This tool reads the service's logs and status and tells you
plainly which of these it actually is, instead of you scrolling through
raw log output trying to figure it out. It's purely diagnostic — it
never restarts, stops, or edits the service.

## The problem

Kubernetes has a well-developed ecosystem of tools (`crashcause`,
`k8s-crashloop`, `kubernetes-crash-guard-operator`, and others) that
classify *why* a pod is in `CrashLoopBackOff` — `OOMKilled` vs. a failed
probe vs. missing config vs. plain application exit — instead of leaving
the operator to manually run `kubectl describe` + `kubectl logs --previous`
and eyeball it.

Bare-metal and VM systemd services have the *exact same* failure mode —
"Start request repeated too quickly" / `start-limit-hit` is extensively
documented across forums and blog posts as a recurring point of confusion
— but nothing plays the "crashcause" role for a plain `systemctl` unit.
The standard advice everywhere is the same manual ritual: `systemctl
status`, `journalctl -u`, `systemctl reset-failed`, repeat. No existing
tool does the root-cause classification automatically.

## What this does

```
$ systemd-crashloop myapp.service

myapp.service: start_limit_hit
  systemd's start-rate limiter tripped: the service crashed faster than
  StartLimitBurst/StartLimitIntervalSec allow, so systemd gave up
  restarting it automatically.
  state: active=failed sub=failed result=start-limit-hit n_restarts=5
  recent journal lines:
    2026-09-10T08:00:01+0000 host myapp[1234]: connection refused
    2026-09-10T08:00:01+0000 host systemd[1]: myapp.service: Failed with result 'exit-code'.
    2026-09-10T08:00:01+0000 host systemd[1]: myapp.service: Scheduled restart job, restart counter is at 5.
    2026-09-10T08:00:01+0000 host systemd[1]: Start request repeated too quickly.
    2026-09-10T08:00:01+0000 host systemd[1]: myapp.service: Failed with result 'start-limit-hit'.
```

Run it with no arguments to diagnose every currently-failed unit on the
system, or name specific units to check them regardless of current state.

Classification codes:

| Cause | Meaning |
|---|---|
| `oom_killed` | The kernel OOM killer terminated the process. |
| `start_limit_hit` | systemd's rate limiter tripped (crashed too fast, too often). |
| `missing_dependency` | A required unit/device/mount wasn't ready at start time. |
| `timeout` | The service didn't signal readiness within its start/stop timeout. |
| `config_error` | The unit file or its config is invalid. |
| `nonzero_exit` | Plain application-level failure — exited nonzero or was signaled. |
| `not_crashing` | The unit isn't currently in a crash-loop state. |
| `unknown` | Not enough evidence to classify confidently — review manually. |

**Strictly read-only.** It never runs `systemctl restart`, `systemctl
reset-failed`, `systemctl stop`, or edits any unit file — it only reads
`systemctl show` and `journalctl -u`.

## Install

Requires Python 3.9+ on a systemd-based Linux distribution (uses
`systemctl`/`journalctl`, so it is meaningless on non-systemd systems and
on macOS/Windows).

```bash
pip install systemd-crashloop
```

Or run the standalone zipapp with no install:

```bash
curl -LO https://github.com/zhuhroscar-tech/systemd-crashloop/releases/download/v0.1.0/systemd-crashloop.pyz
python3 systemd-crashloop.pyz --version
```

Verify the download against `SHA256SUMS.txt` in the same release before
running it.

## Usage

```bash
systemd-crashloop                      # diagnose every currently-failed unit
systemd-crashloop myapp.service        # diagnose one specific unit
systemd-crashloop a.service b.service  # diagnose several
systemd-crashloop --json               # machine-readable output
systemd-crashloop --journal-lines 500  # inspect more journal history per unit
```

Exit codes: `0` = no crash-looping units found (or all diagnosed units are
healthy), `1` = at least one unit could not be confidently classified
(`unknown`), `2` = at least one crash-looping unit was classified.

## If it finds a problem

This tool only diagnoses; it never modifies anything. Once you know the
cause:

- `oom_killed` → check `MemoryMax=`/`MemoryHigh=` on the unit, or the
  actual memory usage pattern of the service.
- `start_limit_hit` → fix the underlying crash cause, then run
  `systemctl reset-failed <unit>` yourself before restarting.
- `missing_dependency` → check `After=`/`Requires=`/`Wants=` ordering and
  whether the dependency (mount, device, socket) is actually available.
- `timeout` → check `TimeoutStartSec=`/`TimeoutStopSec=` and whether the
  service is slow to become ready vs. genuinely hung.
- `config_error` → run `systemd-analyze verify <unit-file>` for exact
  syntax errors.
- `nonzero_exit` → this is your application's own bug; the evidence lines
  in the report point at the actual error output.

## Uninstall

```bash
pip uninstall systemd-crashloop
```
No config files, no persistent state — a stateless read-only diagnostic.

## Privacy / permissions

- No network access, no telemetry.
- Reads `systemctl show` and `journalctl -u` output. Full journal access
  for services owned by other users may require being in the
  `systemd-journal` group or elevated privileges, same as any other use
  of `journalctl`.
- Writes nothing to disk.

## Distro / architecture support

Requires systemd (the vast majority of current distros). Tested via real
`ubuntu-latest` GitHub Actions runners (Python 3.9 and 3.12), including an
end-to-end test against a genuinely crash-looping unit created on the
runner. Pure Python, no compiled dependencies — architecture-independent.

## Reproducible build / test

```bash
git clone https://github.com/zhuhroscar-tech/systemd-crashloop
cd systemd-crashloop
python3 -m pip install -e .[dev]
python3 -m pytest -v
```

CI (`.github/workflows/ci.yml`) runs the same suite on real Ubuntu
runners across Python 3.9 and 3.12, deliberately creates and crash-loops
a real `.service` unit to verify classification against real systemd
behavior (not just mocked unit tests), then builds and smoke-tests both
the wheel/sdist and a standalone `.pyz`.

## License

MIT — see [LICENSE](LICENSE).
