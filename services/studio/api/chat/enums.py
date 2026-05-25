from enum import StrEnum


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"


class CommandStatus(StrEnum):
    SUCCESS = "success"
