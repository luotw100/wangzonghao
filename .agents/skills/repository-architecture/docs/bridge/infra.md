# Bridge CLI Infrastructure / Bridge 基础设施

## 包结构

`bridge/cli/` 是独立 Python 包，不属于 `services/` 工作流，与 Chat/Studio 的 Docker/uv 无关。

```text
bridge/cli/
  pyproject.toml          # [project] name=laborster-bridge, requires-python>=3.12
                          #   dependencies = ["prompt_toolkit>=3.0"]
                          # [project.scripts] laborster-bridge / lbr → laborster_bridge.__main__:main
                          # build-backend = hatchling；wheel packages = ["laborster_bridge"]
  laborster_bridge/       # 见 overview.md 目录结构
```

## 依赖

唯一第三方依赖 `prompt_toolkit`（交互式 REPL 的历史/补全/样式渲染），在 `repl._run_interactive` 内懒导入。其余全部 CPython 标准库：`urllib`、`sqlite3`、`hashlib`、`threading`、`json`、`getpass`、`argparse`、`tempfile`、`os`、`datetime`、`collections`。非 tty fallback（`_run_plain`）不导入 prompt_toolkit，可在无依赖环境下脚本化运行。

## 运行与打包定位

- 开发运行：`cd bridge/cli && uv run laborster-bridge [--state DIR]`（uv 自动解析 prompt_toolkit）。
- 安装后运行：`pip install .` / `uv tool install --editable .` 暴露 `laborster-bridge` 和 `lbr` 两个等价入口。
- 终端启动可带 `--state <path>`；双击场景无参数进入无状态模式，靠 `/state <path>` 设置。
- 单文件可执行打包（PyInstaller 等）属于发布层，不在当前代码内。

## 网络与环境

- Chat/Studio 地址在 `laborster_bridge/config.py` 硬编码（`https://chat.laborster.com` / `https://studio.laborster.com`）。无 base-URL 输入、无环境变量、无默认覆盖。
- 所有出站 HTTP 带 `User-Agent: laborster-bridge/0.1`；服务前置 Cloudflare 会对默认 `Python-urllib` UA 返回 403 code 1010。
- 状态目录无默认值、无环境变量，只能 `--state` 或 `/state` 指定；路径不持久化，每次启动都要给。

## 本机文件

状态目录下仅两个文件：`laborster.json`（0600，所有 token，无密码）与 `messages.db`（SQLite 去重表）。凭据安全模型是「磁盘只存可撤销 token + 文件权限 0600」，不依赖任何外部 keychain。
