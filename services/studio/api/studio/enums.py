from enum import StrEnum


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


class MessageRole(StrEnum):
    SELF = "self"
    COUNTERPART = "counterpart"


class MessageAuthoredBy(StrEnum):
    # Reserved provenance flag. Only 'unknown' exists for now; 'ai' / 'human'
    # may be added later once a reliable signal exists.
    UNKNOWN = "unknown"


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


class OutboundAckResult(StrEnum):
    SENT = "sent"
    FAILED = "failed"
