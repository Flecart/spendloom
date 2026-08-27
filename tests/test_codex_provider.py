import json
import subprocess
from pathlib import Path

import pytest

from receipt_ledger.config import Settings
from receipt_ledger.services import chat, extraction
from receipt_ledger.services.codex_cli import (
    CodexNotConfigured,
    run_codex,
    strict_output_schema,
    validate_codex_runtime,
)


def codex_settings(codex_home: Path, **values: object) -> Settings:
    return Settings(
        _env_file=None,
        app_password="correct-horse-battery-staple",
        session_secret="test-session-secret-that-is-long-enough",
        ai_provider="codex",
        ai_model="gpt-test",
        codex_home=codex_home,
        **values,
    )


def test_strict_output_schema_closes_objects_and_requires_fields() -> None:
    source = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "default": "example"},
            "nested": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
            },
        },
    }

    result = strict_output_schema(source)

    assert result["required"] == ["name", "nested"]
    assert result["additionalProperties"] is False
    assert result["properties"]["nested"]["required"] == ["count"]
    assert "default" not in result["properties"]["name"]
    assert "required" not in source


def test_run_codex_uses_ephemeral_read_only_structured_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    (auth_dir / "auth.json").write_text("{}", encoding="utf-8")
    settings = codex_settings(auth_dir)
    observed: dict[str, object] = {}

    monkeypatch.setattr("receipt_ledger.services.codex_cli.shutil.which", lambda command: "/usr/bin/codex")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["args"] = args
        observed["kwargs"] = kwargs
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text('{"merchant":"Corner Shop"}', encoding="utf-8")
        image_path = Path(args[args.index("--image") + 1])
        assert image_path.read_bytes() == b"image-data"
        schema_path = Path(args[args.index("--output-schema") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("receipt_ledger.services.codex_cli.subprocess.run", fake_run)
    monkeypatch.setenv("APP_PASSWORD", "must-not-reach-codex")

    result = run_codex(
        settings,
        model="gpt-test",
        prompt="extract this receipt",
        output_schema={
            "type": "object",
            "properties": {"merchant": {"type": "string"}},
        },
        images=[(b"image-data", "image/jpeg")],
    )

    args = observed["args"]
    kwargs = observed["kwargs"]
    assert isinstance(args, list)
    assert isinstance(kwargs, dict)
    assert "--ephemeral" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "shell_tool" in args
    assert "unified_exec" in args
    assert args[args.index("--model") + 1] == "gpt-test"
    assert kwargs["input"] == "extract this receipt"
    assert kwargs["env"]["CODEX_HOME"] == str(auth_dir)
    assert "APP_PASSWORD" not in kwargs["env"]
    assert result == {"merchant": "Corner Shop"}


def test_run_codex_requires_file_backed_chatgpt_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("receipt_ledger.services.codex_cli.shutil.which", lambda command: "/usr/bin/codex")

    with pytest.raises(CodexNotConfigured, match="login is not configured"):
        run_codex(
            codex_settings(tmp_path),
            model="gpt-test",
            prompt="test",
            output_schema={"type": "object", "properties": {}},
        )


def test_runtime_validation_ignores_non_codex_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = codex_settings(tmp_path).model_copy(update={"ai_provider": "openai"})
    monkeypatch.setattr("receipt_ledger.services.codex_cli.shutil.which", lambda command: None)

    validate_codex_runtime(settings)


def test_runtime_validation_explains_missing_worker_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("receipt_ledger.services.codex_cli.shutil.which", lambda command: None)

    with pytest.raises(CodexNotConfigured, match="rebuild and recreate"):
        validate_codex_runtime(codex_settings(tmp_path))


def test_runtime_validation_explains_unwritable_auth_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = codex_settings(tmp_path)
    monkeypatch.setattr(
        "receipt_ledger.services.codex_cli.shutil.which",
        lambda command: "/usr/local/bin/codex",
    )
    monkeypatch.setattr(
        "receipt_ledger.services.codex_cli.os.access",
        lambda path, mode: False,
    )

    with pytest.raises(CodexNotConfigured, match="not writable"):
        validate_codex_runtime(settings)


def test_codex_receipt_provider_validates_structured_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_codex(*args: object, **kwargs: object) -> dict[str, object]:
        assert "untrusted data" in str(kwargs["prompt"])
        return {
            "expense_date": "2026-08-27",
            "merchant": "Corner Shop",
            "original_amount": "12.50",
            "original_currency": "gbp",
            "category_code": "food",
            "scope": "personal",
            "payment_last_four": None,
            "payment_method_text": None,
            "location": None,
            "memo": None,
            "category_reason": "Receipt line items",
            "confidence": 0.95,
        }

    monkeypatch.setattr(extraction, "run_codex", fake_run_codex)

    provider = extraction.provider_for(codex_settings(tmp_path))
    result = provider.extract("prompt", [(b"image", "image/jpeg")])

    assert result.merchant == "Corner Shop"
    assert result.original_currency == "GBP"


def test_codex_chat_provider_decodes_tool_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat,
        "run_codex",
        lambda *args, **kwargs: {
            "text": "",
            "tool_calls": [
                {
                    "name": "search_expenses",
                    "arguments_json": '{"query":"coffee"}',
                }
            ],
        },
    )

    provider = chat.chat_provider_for(codex_settings(tmp_path))
    result = provider.complete(
        [{"role": "user", "content": "find coffee"}],
        [
            {
                "name": "search_expenses",
                "description": "Search expenses",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    )

    assert result.text == ""
    assert result.tool_calls == [
        chat.ToolCall("search_expenses", {"query": "coffee"})
    ]
