# Laborster 项目背景

## 产品定位

Laborster 的核心产品是 **Robot** —— 一个面向销售、客服、运营等人群的拟人自动化回复服务。

用户在后台注册自己的 profile（即 Robot profile），再添加当前客户的 profile（即 Contact profile），
让 AI 基于这两个角色画像生成拟人化的回复。

## 当前阶段

- **Chat Service** 是一个**调试用的简易聊天平台（Adapter）**，不是最终产品。
- 未来 Robot 会接入微信、企微、飞书等多个消息平台，Chat 只是其中一个调试 Adapter。
- 除非 Chat 有重大设计失误，否则尽量不动它。

## 架构原则

- 简单可靠、耐操、易于理解、可扩展、性能好
- 消息队列 + 消费者模型（Redis 作为传输管道）
- Robot Service 拥有完整消息历史（source of truth），不依赖 Adapter 在线
- 流水表全砍，Worker 处理过程纯内存，可靠性靠 DB 兜底
- 延迟发送用 asyncio.sleep 实现，不需要额外表

## 编码偏好

- **禁止偷偷搞默认值**：所有配置（环境变量、CLI 参数、连接串）必须由外部显式指定，缺失时直接报错。不允许用 fallback 默认值静默连接到错误的服务。唯一例外是布尔开关型 flag（如 `--echo-mode`），默认关闭是合理的。

## 技术栈

- 后端：Python 3.12+, FastAPI, SQLAlchemy, SQLite, Redis
- 前端：React + TypeScript + Tailwind CSS + Vite
- 部署：Docker Compose + Nginx 反向代理
