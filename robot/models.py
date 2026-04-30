from sqlalchemy import Column, DateTime, Integer, String, Text

from robot.db import Base, utc_now


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id            = Column(String, primary_key=True, index=True)                  # 配置主键
    name          = Column(String, nullable=False)                                # 配置名称，如 "DeepSeek"、"OpenAI"
    base_url      = Column(String, nullable=False)                                # LLM API 基础地址，如 "https://api.deepseek.com/v1"
    api_key       = Column(Text, nullable=True)                                   # API 密钥
    default_model = Column(String, nullable=False)                                # 默认模型名称，如 "deepseek-chat"
    created_at    = Column(DateTime, default=utc_now, nullable=False)
    updated_at    = Column(DateTime, default=utc_now, nullable=False)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id                   = Column(String, primary_key=True, index=True)            # 会话主键
    adapter_type         = Column(String, nullable=False, default="chat")          # 消息平台类型，如 "chat"、"wechat"、"feishu"，对应不同的 Adapter 实现
    adapter_thread_id    = Column(String, index=True, nullable=False)               # 消息平台上的会话 ID，如 Chat 服务的 conversation_id，用于轮询消息和发送回复
    takeover_user_id     = Column(String, nullable=False)                          # 机器人接管的角色 ID，即冒充哪个用户发言；来自此 ID 的消息会被忽略，只处理对方的消息
    profile              = Column(Text, nullable=True)                             # 机器人人设 prompt，定义性格、说话风格等，注入 LLM system prompt
    counterpart_profile  = Column(Text, nullable=True)                             # 对方（聊天对象）的画像描述，帮助机器人更了解对话方
    provider_config_id   = Column(String, index=True, nullable=True)               # 关联的 LLM 提供商配置 ID，决定使用哪个 API 和模型
    status               = Column(String, nullable=False, default="active")        # 会话状态："active" 表示机器人正在运行，其他值则停止轮询
    created_at           = Column(DateTime, default=utc_now, nullable=False)
    updated_at           = Column(DateTime, default=utc_now, nullable=False)


class RobotMessage(Base):
    __tablename__ = "robot_messages"

    id            = Column(Integer, primary_key=True, autoincrement=True)  # 消息自增主键
    session_id    = Column(String, index=True, nullable=False)             # 关联的会话 ID
    role          = Column(String, nullable=False)                         # 消息角色："counterpart" 为对方发来的，"robot" 为机器人回复的
    content       = Column(Text, nullable=False)                           # 消息文本内容
    status        = Column(String, nullable=False, default="sent")         # 消息状态：scheduled（待发送）、sent（已发送）、canceled（已取消）
    scheduled_for = Column(DateTime, nullable=True)                        # 计划发送时间，用于模拟打字延迟
    created_at    = Column(DateTime, default=utc_now, nullable=False)


class LlmLog(Base):
    __tablename__ = "llm_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)  # 日志自增主键
    session_id       = Column(String, index=True, nullable=False)             # 关联的会话 ID
    request_messages = Column(Text, nullable=False)                           # 发送给 LLM 的完整消息列表（JSON）
    response_raw     = Column(Text, nullable=False)                           # LLM 返回的原始响应文本
    model            = Column(String, nullable=True)                          # 使用的模型名称
    created_at       = Column(DateTime, default=utc_now, nullable=False)
