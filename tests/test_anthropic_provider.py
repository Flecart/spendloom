from types import SimpleNamespace
from typing import Any

import pytest

from receipt_ledger.config import Settings
from receipt_ledger.schemas import ReceiptExtraction
from receipt_ledger.services import chat, extraction


def anthropic_settings(**values: Any) -> Settings:
    defaults: dict[str, Any] = {
        "_env_file": None,
        "app_password": "correct-horse-battery-staple",
        "session_secret": "test-session-secret-that-is-long-enough",
        "ai_provider": "anthropic",
        "anthropic_api_key": "sk-ant-test",
    }
    defaults.update(values)
    return Settings(**defaults)


class FakeMessages:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.response

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.response


def install_fake_client(monkeypatch: pytest.MonkeyPatch, response: SimpleNamespace) -> FakeMessages:
    messages = FakeMessages(response)

    def factory(api_key: str) -> SimpleNamespace:
        assert api_key == "sk-ant-test"
        return SimpleNamespace(messages=messages)

    monkeypatch.setattr("anthropic.Anthropic", factory)
    return messages


def sample_extraction() -> ReceiptExtraction:
    return ReceiptExtraction(
        expense_date="2026-11-01",
        merchant="Cafe",
        original_amount="4.50",
        original_currency="EUR",
        category_code="food",
        confidence=0.95,
    )


def test_anthropic_defaults_to_haiku_when_model_blank() -> None:
    settings = anthropic_settings(ai_model="")

    assert settings.resolved_ai_model == "claude-haiku-5-5"
    assert settings.resolved_chat_model == "claude-haiku-5-5"


def test_explicit_model_overrides_provider_default() -> None:
    settings = anthropic_settings(ai_model="claude-sonnet-5-5", chat_model=" ")

    assert settings.resolved_ai_model == "claude-sonnet-5-5"
    assert settings.resolved_chat_model == "claude-sonnet-5-5"


def test_other_providers_keep_previous_default() -> None:
    settings = anthropic_settings(ai_provider="openai")

    assert settings.resolved_ai_model == "gpt-5.6-luna"


def test_anthropic_extraction_uses_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = sample_extraction()
    response = SimpleNamespace(stop_reason="end_turn", parsed_output=expected)
    messages = install_fake_client(monkeypatch, response)

    result = extraction.provider_for(anthropic_settings()).extract("prompt", [(b"img", "image/png")])

    assert result == expected
    call = messages.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_format"] is ReceiptExtraction
    assert call["max_tokens"] >= 16_000
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[-1] == {"type": "text", "text": "prompt"}


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_anthropic_extraction_rejects_incomplete_response(
    monkeypatch: pytest.MonkeyPatch,
    stop_reason: str,
) -> None:
    response = SimpleNamespace(stop_reason=stop_reason, parsed_output=None)
    install_fake_client(monkeypatch, response)

    with pytest.raises(ValueError):
        extraction.provider_for(anthropic_settings()).extract("prompt", [])


def test_anthropic_extraction_requires_api_key() -> None:
    settings = anthropic_settings(anthropic_api_key=None)

    with pytest.raises(extraction.ProviderNotConfigured):
        extraction.provider_for(settings).extract("prompt", [])


def test_anthropic_chat_maps_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    response = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="Checking."),
            SimpleNamespace(type="tool_use", name="search_expenses", input={"query": "cafe"}),
        ],
    )
    messages = install_fake_client(monkeypatch, response)
    conversation = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "find cafe"},
    ]

    completion = chat.chat_provider_for(anthropic_settings()).complete(conversation, chat.CHAT_TOOL_CONTRACT)

    assert completion.text == "Checking."
    assert completion.tool_calls == [chat.ToolCall("search_expenses", {"query": "cafe"})]
    call = messages.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["system"] == "be brief"
    assert call["messages"] == [{"role": "user", "content": "find cafe"}]


def test_anthropic_chat_handles_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    response = SimpleNamespace(stop_reason="refusal", content=[])
    install_fake_client(monkeypatch, response)

    completion = chat.chat_provider_for(anthropic_settings()).complete(
        [{"role": "user", "content": "hi"}],
        chat.CHAT_TOOL_CONTRACT,
    )

    assert completion.tool_calls == []
    assert completion.text
