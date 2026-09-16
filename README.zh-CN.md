[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/简体中文-555555?style=flat)](README.zh-CN.md)

# systemd-crashloop

只读 CLI，帮助排查 systemd 服务反复失败的原因。它结合 unit 状态和最近的 journal 日志给出分类，不必分别阅读 `systemctl` 与 `journalctl` 的原始输出再手动归纳。

不带参数时检查当前处于 failed 状态的 unit；也可以指定名称，不受当前状态限制。报告包含分类、说明、状态字段和相关日志。

## 安装与使用

需要 Python 3.9+，以及运行 systemd 的 Linux 系统中的 `systemctl`、`journalctl`。Python 运行时没有第三方依赖。不适用于 macOS、Windows 或未使用 systemd 的 Linux 主机。

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

独立 `.pyz` 可在 [Releases](https://github.com/zhuhroscar-tech/systemd-crashloop/releases) 下载，执行前请核对对应版本的校验和。

## 如何理解结果

| 分类 | 含义 |
| --- | --- |
| `oom_killed` | 有证据表明进程因内存不足被终止 |
| `start_limit_hit` | 启动过于频繁，systemd 停止重试 |
| `missing_dependency` | 所需依赖不可用 |
| `timeout` | 启动或停止超时 |
| `config_error` | 存在 unit 或配置错误的证据 |
| `nonzero_exit` | 应用非零退出或收到终止信号 |
| `not_crashing` | 未识别到当前的 crash-loop 状态 |
| `unknown` | 证据不足，无法分类 |

退出码：`0` 表示没有识别出的 crash-loop 或 unknown 结果，`1` 表示原因未知，`2` 表示识别出了故障，`3` 表示诊断或查询失败（包括 unit 不存在）。多个结果并存时，工具故障优先。

## 安全与判断边界

不会重启、停止、执行 reset-failed 或修改配置。不联网、不发送遥测、不保存持久状态。读取其他用户的服务日志可能需要加入 `systemd-journal` 组或使用更高权限。

分类只是对已有证据的归纳，不保证找到应用层的根因。例如，`start_limit_hit` 说明重试为何停止，不说明服务最初为何崩溃。请先阅读相关日志、解决实际问题，再决定是否手动重置或重启；可用 `--journal-lines` 扩大检查范围。

## 预览与开发

[输出截图](docs/images/example-output.png) · [演示视频](docs/demo.mp4)

```bash
python -m pip install -e ".[dev]"
python -m pytest -v
```

[分类逻辑](src/systemd_crashloop/core.py) · [CI](.github/workflows/ci.yml) · [MIT 许可证](LICENSE)
