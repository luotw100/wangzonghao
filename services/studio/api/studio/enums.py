from enum import StrEnum


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class InboxPlatform(StrEnum):
    CHAT = "chat"
    WECHAT = "wechat"
    FEISHU = "feishu"


class ConversationKind(StrEnum):
    DM = "dm"
    GROUP = "group"
    UNKNOWN = "unknown"   # placeholder, set when /incoming creates a row before /conversations fills it in


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class DistillJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class OutboundStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELED = "canceled"


class LlmPurpose(StrEnum):
    DISTILL = "distill"
    REPLY = "reply"


class OutboundMessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"


class ReplyPolicy(StrEnum):
    DISABLED = "disabled"
    AUTOREPLY = "autoreply"
