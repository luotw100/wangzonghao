# Bridge CLI / Bridge 命令行总览

## 当前形态

`bridge/cli/` 是跑在主播/运营本机的 **Python 命令行 daemon**。它是一个交互式 REPL：双击可执行文件或在终端启动后进入黑框框，输入 slash 命令管理登录与 channel。tty 模式用 prompt_toolkit 提供命令历史（↑/↓，持久化到 `<state>/.history`）、Tab 补全、样式化输出；非 tty（管道）自动 fallback 到纯 stdin 循环，保持可脚本化与可测试。**进程本身就是 daemon**——登录、注册 channel、6 个后台循环都跑在这个进程里，关掉进程即断线。没有图形界面、没有 IPC、没有后台服务托管。

对 text 消息，Bridge 是透明管道；媒体消息当前 ack 为 `failed`（chat sandbox 实践上只发 text）。

## 目录结构

```text
bridge/
  cli/
    pyproject.toml                 # 包元数据；entry points: laborster-bridge, lbr
    laborster_bridge/
      __init__.py
      __main__.py                  # 入口：解析可选 --state，起 REPL
      repl.py                      # 主线程：读输入 → 解析 slash → dispatch → 渲染
      commands.py                  # 每个命令一个 handler，返回 dict；运行时装配；HELP 文本
      config.py                    # 硬编码 CHAT/STUDIO base url；状态目录解析（无默认/无 env）
      state.py                     # laborster.json 原子读写（0600）
      store.py                     # sqlite local_messages 去重表（单连接 + Lock，WAL）
      http.py                      # urllib JSON helper；Unauthorized/HttpError；自定义 UA
      studio_client.py             # Studio /api/bridge/* 全部端点
      chat_adapter.py              # Chat sandbox HTTP 轮询适配器（token 登录/scan/send）
      runtime.py                   # BridgeRuntime：6 个循环线程 + 状态聚合
      events.py                    # 线程安全：日志环形缓冲 + DaemonState 快照
```

## 技术栈

- **Python 3.12+**。网络/存储/并发全用 stdlib（`urllib` / `sqlite3` / `hashlib` / `threading` / `json` / `argparse`）。唯一第三方依赖 `prompt_toolkit`，仅交互式 REPL（历史/补全/样式）使用，在 `repl._run_interactive` 内懒导入；非 tty fallback 不依赖它。
- 打包定位：`pyproject.toml` 用 hatchling，`project.scripts` 暴露 `laborster-bridge` 和 `lbr`，二者都指向 `laborster_bridge.__main__:main`。

## 命令集（slash）

| 命令 | 作用 |
| --- | --- |
| `/help` | 显示命令指南 |
| `/state <path>` | 设置本会话状态目录（无默认，每次启动都要指定） |
| `/login` | 提示输入 Studio 账号密码 → handshake 换 token 落盘（之后自动连接） |
| `/logout` | 清除 Studio token（自动断开 daemon） |
| `/status` | daemon 与各 channel 状态快照 |
| `/channel add` | 提示输入 Chat 账号密码 → 换 Chat token 存入（自动重连注册） |
| `/channel rm <n>` | 删除第 n 个 channel（自动重连） |
| `/channel list` | 列出已保存 channel（不含任何凭据） |
| `/log [-f]` | 看日志；`-f` 跟随（仅交互终端） |
| `/studio` | 打印 Studio 地址 |
| `/quit` | 停 daemon 并退出 |

每个 handler 返回一个 dict（`{"lines": [...]}` / `{"error": str}` / `{"logs": [...]}` / `{"quit": True}` / `{"follow": True}`），由 `repl` 渲染。返回 dict 的结构便于将来加非交互/JSON 模式。

**daemon 不是用户可感知概念，没有 `/start` `/stop`。** `commands._ensure(ctx)` 做调和：只要状态目录已设、有 `studio_token` 且至少一个 channel，daemon 就运行；否则停。它在 REPL 启动（`commands.autostart`）、`/state`、`/login`、`/channel add|rm` 后调用；ready 时总是 (重)启动以便变更后的 channel 集合重新注册。`/logout` `/quit` 内部调 `_stop_daemon`。

接管与回复策略不在 Bridge 配置，`/studio` 引导用户去 Studio 设置。

## 凭据与状态文件

状态目录来源**只有两条，无默认值、无环境变量**：启动参数 `--state <path>`，或 REPL 内 `/state <path>`（当次会话生效，不持久化）。都没有时进入「无状态模式」，只有 `/help` `/state` `/quit` 可用。

状态目录下：

- `laborster.json`（0600，原子写：临时文件 + `os.replace`）：`username`、`machine_id`、`bridge_id`、`studio_token`、`channels:[{username, chat_token}]`。**磁盘上一个密码都不存**——Studio 与 Chat 两侧都只存 session token。`studio_token` 在 401 或 `/logout` 时清除。
- `messages.db`：SQLite 去重消息表。

Chat/Studio 地址在 `config.py` 硬编码为 `https://chat.laborster.com` / `https://studio.laborster.com`，没有任何 base-URL 输入。

## 启动生命周期

```text
laborster-bridge [--state DIR]
  → __main__.main()：--state 有值则 config.set_state_dir()
  → repl.run()
       打印 banner；有状态目录则 commands.autostart()（自动连接）
       循环：读一行 → 去掉前导 '/' → 按 DISPATCH 分发
       无状态模式下非 NO_STATE_OK 命令被拒
  /login    → StudioClient.handshake(pwd) → 写 token/machine_id/bridge_id → _ensure()
  /channel add → ChatAdapter.obtain_token(pwd) → 存 chat_token → _ensure()
  _ensure() ready 时 → 构造 StudioClient(token getter=读 laborster.json)
            → LocalStore(messages.db) → BridgeRuntime.start()（后台 bootstrap 线程）
```

`BridgeRuntime.start()` 不阻塞 REPL：bootstrap 在后台线程对每个 channel 用持久化 chat_token 调 `/api/auth/me` 恢复 selfId，token 鉴权注册 inbox，然后并行启动 6 个循环线程。401 时回调 `on_auth_error` 清 Studio token 并提示重新 `/login`。

## Bridge 当前不做的事

- 不调 LLM
- 不存 Persona / Contact Card
- 不判断 autoreply 是否开启
- 不选择 ProviderConfig
- 不实现媒体 S3 搬运（媒体 outbound ack failed）
- 磁盘不存任何密码（Studio/Chat 均 token-only）
- 不提供图形界面、不后台 daemon 化、不读环境变量、不用默认状态目录
