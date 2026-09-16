[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/简体中文-555555?style=flat)](README.zh-CN.md)

# systemd-crashloop

A read-only CLI for understanding failed systemd services. It combines unit state and recent journal evidence into a cause classification, instead of requiring you to interpret `systemctl` and `journalctl` output separately.

Run without arguments to inspect currently failed units, or name units to inspect regardless of their current state. The report includes the classification, an explanation, state fields, and recent evidence lines.

## Install and use

Requires Python 3.9+ on a systemd-based Linux system with `systemctl` and `journalctl`. There are no third-party Python runtime dependencies. It is not a diagnostic for macOS, Windows, or non-systemd Linux hosts.

```bash
git clone https://github.com/zhuhroscar-tech/systemd-crashloop.git
cd systemd-crashloop
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
systemd-crashloop
systemd-crashloop myapp.service
systemd-crashloop a.service b.service --journal-lines 500
systemd-crashloop --json
```

For standalone `.pyz` downloads, see [Releases](https://github.com/zhuhroscar-tech/systemd-crashloop/releases) and verify the matching release checksums before execution.

## Read the result

| Classification | Meaning |
| --- | --- |
| `oom_killed` | Evidence of an out-of-memory kill |
| `start_limit_hit` | systemd stopped retrying after repeated starts |
| `missing_dependency` | A required dependency was unavailable |
| `timeout` | A start/stop timeout was reached |
| `config_error` | Unit/configuration error evidence |
| `nonzero_exit` | Application exit or signal failure |
| `not_crashing` | No current crash-loop state identified |
| `unknown` | Insufficient evidence for classification |

Exit codes: `0` means no classified crash-loop or unknown result, `1` means an unknown cause, `2` means a classified failure, and `3` means a diagnostic/lookup failure (including a nonexistent unit). When results are mixed, tooling failures take precedence.

## Safety and interpretation

No restart, stop, reset-failed, or configuration edit is performed. The tool has no telemetry or network access and writes no persistent state. Reading other users' service journals may require membership in `systemd-journal` or elevated privileges.

Classifications summarize available evidence, not a guaranteed application root cause. In particular, `start_limit_hit` explains why retries stopped, not why the service originally failed. Review the evidence and fix the underlying issue before manually resetting or restarting a unit; use `--journal-lines` to expand the inspection window.

## Preview and development

[Example output](docs/images/example-output.png) · [Demo video](docs/demo.mp4)

```bash
python -m pip install -e ".[dev]"
python -m pytest -v
```

[Classification logic](src/systemd_crashloop/core.py) · [CI](.github/workflows/ci.yml) · [MIT license](LICENSE)
