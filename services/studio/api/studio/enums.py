from enum import StrEnum


class AccountRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ProviderScope(StrEnum):
    GLOBAL = "global"


class ProviderStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PersonaStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class BridgeStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    REVOKED = "revoked"


class InboxPlatform(StrEnum):
    CHAT = "chat"
    WECHAT = "wechat"
    FEISHU = "feishu"


class ContactStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MessageSource(StrEnum):
    ARCHIVE = "archive"
    LIVE = "live"


class MessageRole(StrEnum):
    SELF = "self"
    COUNTERPART = "counterpart"


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


class OutboundAckResult(StrEnum):
    SENT = "sent"
    FAILED = "failed"
