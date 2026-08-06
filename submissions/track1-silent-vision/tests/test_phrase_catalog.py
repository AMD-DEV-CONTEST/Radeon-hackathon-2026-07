from pathlib import Path

import pytest

import command.catalog as catalog_module
from command.catalog import PhraseCatalog, load_phrase_catalog, normalize_phrase


def test_initial_catalog_has_exact_registered_text_and_intents():
    catalog = load_phrase_catalog(Path("command/phrase_catalog.json"))
    assert [
        (e.phrase_id, e.text, e.language, e.intent.value) for e in catalog.entries
    ] == [
        ("zh_light_on_hello", "你好，请帮我打开灯", "zh", "LIGHT_ON"),
        ("zh_chat_meal", "你吃饭了吗？", "zh", "CHAT_OTHER"),
        ("en_light_on_hello", "Hello, please turn on the light.", "en", "LIGHT_ON"),
        ("en_chat_meal", "Have you eaten?", "en", "CHAT_OTHER"),
    ]
    assert catalog_module.catalog_records(catalog) == [
        {
            "phraseId": "zh_light_on_hello",
            "text": "你好，请帮我打开灯",
            "language": "zh",
            "intent": "LIGHT_ON",
            "enabled": True,
        },
        {
            "phraseId": "zh_chat_meal",
            "text": "你吃饭了吗？",
            "language": "zh",
            "intent": "CHAT_OTHER",
            "enabled": True,
        },
        {
            "phraseId": "en_light_on_hello",
            "text": "Hello, please turn on the light.",
            "language": "en",
            "intent": "LIGHT_ON",
            "enabled": True,
        },
        {
            "phraseId": "en_chat_meal",
            "text": "Have you eaten?",
            "language": "en",
            "intent": "CHAT_OTHER",
            "enabled": True,
        },
    ]


def test_catalog_by_id_returns_canonical_phrase_and_rejects_unknown_id():
    catalog = load_phrase_catalog(Path("command/phrase_catalog.json"))

    assert catalog.by_id("en_light_on_hello") == catalog.entries[2]
    with pytest.raises(ValueError, match="^unknown phraseId$"):
        catalog.by_id("not-a-phrase")


def test_normalization_preserves_punctuation():
    assert normalize_phrase("  Ｈello   世界？ ") == "hello 世界?"


@pytest.mark.parametrize(
    "records, message",
    [
        (
            [
                {
                    "phraseId": "x",
                    "text": "a",
                    "language": "zh",
                    "intent": "LIGHT_ON",
                    "enabled": True,
                },
                {
                    "phraseId": "x",
                    "text": "b",
                    "language": "zh",
                    "intent": "LIGHT_OFF",
                    "enabled": True,
                },
            ],
            "duplicate phraseId",
        ),
        (
            [
                {
                    "phraseId": "x",
                    "text": "a",
                    "language": "zh",
                    "intent": "NOT_REAL",
                    "enabled": True,
                }
            ],
            "unknown intent",
        ),
        (
            [
                {
                    "phraseId": "x",
                    "text": "a",
                    "language": "zh",
                    "intent": "UNKNOWN",
                    "enabled": True,
                }
            ],
            "UNKNOWN",
        ),
    ],
)
def test_invalid_catalog_is_rejected(records, message):
    with pytest.raises(ValueError, match=message):
        PhraseCatalog.from_records(records)
