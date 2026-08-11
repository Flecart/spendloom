from __future__ import annotations

import base64
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import ValidationError

from ..config import Settings
from ..schemas import ReceiptExtraction


class ProviderNotConfigured(RuntimeError):
    pass


class ExtractionProvider(ABC):
    def __init__(self, settings: Settings):
        self.settings = settings

    @abstractmethod
    def extract(self, prompt: str, images: list[tuple[bytes, str]]) -> ReceiptExtraction:
        raise NotImplementedError


class OpenAIProvider(ExtractionProvider):
    def extract(self, prompt: str, images: list[tuple[bytes, str]]) -> ReceiptExtraction:
        if not self.settings.openai_api_key:
            raise ProviderNotConfigured("OPENAI_API_KEY is not configured")
        from openai import OpenAI

        content: list[dict] = [{"type": "input_text", "text": prompt}]
        for data, mime in images:
            encoded = base64.b64encode(data).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"})
        client = OpenAI(api_key=self.settings.openai_api_key)
        response = client.responses.parse(
            model=self.settings.ai_model,
            input=[{"role": "user", "content": content}],
            text_format=ReceiptExtraction,
        )
        if response.output_parsed is None:
            raise ValueError("OpenAI returned no parsed extraction")
        return response.output_parsed


class AnthropicProvider(ExtractionProvider):
    def extract(self, prompt: str, images: list[tuple[bytes, str]]) -> ReceiptExtraction:
        if not self.settings.anthropic_api_key:
            raise ProviderNotConfigured("ANTHROPIC_API_KEY is not configured")
        from anthropic import Anthropic

        content: list[dict] = []
        for data, mime in images:
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode("ascii")}})
        content.append({"type": "text", "text": prompt + "\nReturn only valid JSON matching the requested schema."})
        client = Anthropic(api_key=self.settings.anthropic_api_key)
        response = client.messages.create(model=self.settings.ai_model, max_tokens=1800, messages=[{"role": "user", "content": content}])
        text = "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return ReceiptExtraction.model_validate(_parse_json(text))


class GeminiProvider(ExtractionProvider):
    def extract(self, prompt: str, images: list[tuple[bytes, str]]) -> ReceiptExtraction:
        if not self.settings.gemini_api_key:
            raise ProviderNotConfigured("GEMINI_API_KEY is not configured")
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.settings.gemini_api_key)
        contents: list = [prompt]
        contents.extend(types.Part.from_bytes(data=data, mime_type=mime) for data, mime in images)
        response = client.models.generate_content(
            model=self.settings.ai_model,
            contents=contents,
            config={"response_mime_type": "application/json", "response_schema": ReceiptExtraction},
        )
        if getattr(response, "parsed", None):
            return ReceiptExtraction.model_validate(response.parsed)
        return ReceiptExtraction.model_validate(_parse_json(response.text or ""))


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    return json.loads(text)


def provider_for(settings: Settings) -> ExtractionProvider:
    providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
    }
    provider = providers.get(settings.ai_provider.lower())
    if not provider:
        raise ProviderNotConfigured(f"Unsupported AI provider: {settings.ai_provider}")
    return provider(settings)


def build_prompt(categories: list[tuple[str, str, str]], caption: str | None, embedded_text: str) -> str:
    category_lines = "\n".join(f"- {code}: {name} ({scope})" for code, name, scope in categories)
    schema = json.dumps(ReceiptExtraction.model_json_schema(), separators=(",", ":"))
    context = caption.strip() if caption else "No user caption."
    pdf_text = embedded_text.strip()[:12_000] if embedded_text else "No embedded text."
    return f"""You extract a single expense from one receipt. Never invent values. The final paid total is original_amount.
Choose category_code only from the supplied categories. Use ISO date YYYY-MM-DD and ISO 4217 currency.
Classify scope as personal, business, or unknown. Confidence represents confidence in the complete extraction.

Categories:
{category_lines}

User caption/context:
{context}

Embedded PDF text (may be empty or noisy):
{pdf_text}

Required JSON schema:
{schema}
"""
