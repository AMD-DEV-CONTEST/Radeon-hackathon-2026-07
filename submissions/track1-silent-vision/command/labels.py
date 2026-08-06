from enum import Enum


class CommandIntent(str, Enum):
    UNKNOWN = "UNKNOWN"
    LIGHT_ON = "LIGHT_ON"
    LIGHT_OFF = "LIGHT_OFF"
    OPEN_DOOR = "OPEN_DOOR"
    CHAT_OTHER = "CHAT_OTHER"


COMMAND_LABELS: tuple[CommandIntent, ...] = (
    CommandIntent.UNKNOWN,
    CommandIntent.LIGHT_ON,
    CommandIntent.LIGHT_OFF,
    CommandIntent.OPEN_DOOR,
    CommandIntent.CHAT_OTHER,
)

EXECUTABLE_INTENTS: frozenset[CommandIntent] = frozenset(
    {
        CommandIntent.LIGHT_ON,
        CommandIntent.LIGHT_OFF,
        CommandIntent.OPEN_DOOR,
    }
)


STARTER_VARIANTS: dict[CommandIntent, list[str]] = {
    CommandIntent.LIGHT_ON: [
        "你好，请帮我打开灯",
        "现在请打开房间的灯",
        "hello, please turn on the light",
        "please turn on the room light now",
    ],
    CommandIntent.CHAT_OTHER: [
        "你吃饭了吗？",
        "今天去哪里玩了？",
        "have you eaten?",
        "where are you going today?",
    ],
}
