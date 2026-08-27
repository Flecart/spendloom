from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config import Settings


class CodexNotConfigured(RuntimeError):
    pass


class CodexInvocationError(RuntimeError):
    pass


def codex_auth_configured(settings: Settings) -> bool:
    """Check the file-backed login used by the Docker worker."""
    return (settings.codex_home / "auth.json").is_file()


def validate_codex_runtime(settings: Settings) -> str | None:
    if settings.ai_provider.lower() != "codex":
        return None
    command = shutil.which(settings.codex_command)
    if not command:
        raise CodexNotConfigured(
            f"Codex CLI command {settings.codex_command!r} is not installed in the worker; "
            "rebuild and recreate the worker container"
        )
    if not settings.codex_home.is_dir() or not os.access(
        settings.codex_home,
        os.W_OK | os.X_OK,
    ):
        raise CodexNotConfigured(
            "Codex credential directory is not writable by the worker; run "
            "`./scripts/codex-login.sh` to repair its ownership and sign in"
        )
    if not codex_auth_configured(settings):
        raise CodexNotConfigured(
            "ChatGPT login is not configured; run "
            "`./scripts/codex-login.sh`"
        )
    return command


def strict_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make object shapes explicit for Codex structured final output."""
    value = json.loads(json.dumps(schema))

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if node.get("type") == "object" and isinstance(properties, dict):
                node["additionalProperties"] = False
                node["required"] = list(properties)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return value


def run_codex(
    settings: Settings,
    *,
    model: str,
    prompt: str,
    output_schema: dict[str, Any],
    images: list[tuple[bytes, str]] | None = None,
) -> dict[str, Any]:
    command = validate_codex_runtime(settings)
    if not command:
        raise CodexNotConfigured("Codex CLI is unavailable")

    with tempfile.TemporaryDirectory(prefix="spendloom-codex-") as directory_name:
        directory = Path(directory_name)
        schema_path = directory / "output-schema.json"
        output_path = directory / "output.json"
        schema_path.write_text(
            json.dumps(strict_output_schema(output_schema)),
            encoding="utf-8",
        )
        image_paths = _write_images(directory, images or [])
        args = [
            command,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--disable",
            "shell_tool",
            "--disable",
            "unified_exec",
            "--disable",
            "apps",
            "--disable",
            "browser_use",
            "--disable",
            "computer_use",
            "--disable",
            "multi_agent",
            "--color",
            "never",
            "--model",
            model,
            "--cd",
            str(directory),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if image_paths:
            args.extend(["--image", *(str(path) for path in image_paths)])
        args.append("-")

        try:
            result = subprocess.run(
                args,
                input=prompt,
                text=True,
                capture_output=True,
                check=False,
                cwd=directory,
                env=_codex_environment(settings),
                timeout=settings.codex_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexInvocationError(
                f"Codex did not respond within {settings.codex_timeout_seconds} seconds"
            ) from exc

        if result.returncode != 0:
            detail = _last_error_line(result.stderr)
            raise CodexInvocationError(
                f"Codex exited with status {result.returncode}: {detail}"
            )
        if not output_path.is_file():
            raise CodexInvocationError("Codex returned no structured output")
        try:
            value = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CodexInvocationError("Codex returned invalid structured output") from exc
        if not isinstance(value, dict):
            raise CodexInvocationError("Codex structured output was not an object")
        return value


def _write_images(
    directory: Path,
    images: list[tuple[bytes, str]],
) -> list[Path]:
    suffixes = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    paths: list[Path] = []
    for index, (data, mime_type) in enumerate(images, start=1):
        suffix = suffixes.get(mime_type, ".img")
        path = directory / f"receipt-{index}{suffix}"
        path.write_bytes(data)
        paths.append(path)
    return paths


def _codex_environment(settings: Settings) -> dict[str, str]:
    allowed_names = {
        "ALL_PROXY",
        "CODEX_CA_CERTIFICATE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "LANG",
        "NO_PROXY",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    }
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in allowed_names
    }
    environment["CODEX_HOME"] = str(settings.codex_home)
    return environment


def _last_error_line(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1][:500] if lines else "no error detail was provided"
