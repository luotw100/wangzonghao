from enum import StrEnum


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class SenderType(StrEnum):
    SELF = "self"
    CONTACT = "contact"


class MessageType(StrEnum):
    TEXT = "text"


class MessageSource(StrEnum):
    LIVE = "live"
    IMPORT = "import"


class CommandStatus(StrEnum):
    SUCCESS = "success"
