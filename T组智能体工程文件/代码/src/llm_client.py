"""OpenAI-compatible chat client used by the dialogue agent.

The implementation intentionally uses only the Python standard library so the
project can still run on a small cloud VM without extra dependencies.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator


DEFAULT_BASE_URL = ""
DEFAULT_MODEL = ""


class LLMClientError(RuntimeError):
    """Raised when the external LLM endpoint cannot return a valid response."""


@dataclass
class ChatCompletion:
    """Compact completion result."""

    content: str
    message: dict[str, Any]
    raw: dict[str, Any]
    finish_reason: str | None = None


class OpenAICompatibleClient:
    """Small client for OpenAI-compatible ``/chat/completions`` APIs."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        timeout: float = 45.0,
        enabled: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.enabled = enabled

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient":
        """Create a client from environment variables.

        Supported variables:
        - ``RS_AGENT_LLM_API_KEY`` or ``OPENAI_API_KEY``
        - ``RS_AGENT_LLM_BASE_URL`` or ``OPENAI_BASE_URL``
        - ``RS_AGENT_LLM_MODEL`` or ``OPENAI_MODEL``
        - ``RS_AGENT_LLM_ENABLED`` set to ``0``/``false``/``off`` to disable
        """

        enabled_text = os.getenv("RS_AGENT_LLM_ENABLED", "auto").strip().lower()
        enabled = enabled_text not in {"0", "false", "off", "no"}
        return cls(
            base_url=os.getenv("RS_AGENT_LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or DEFAULT_BASE_URL,
            api_key=os.getenv("RS_AGENT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
            model=os.getenv("RS_AGENT_LLM_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
            timeout=float(os.getenv("RS_AGENT_LLM_TIMEOUT", "45")),
            enabled=enabled,
        )

    @property
    def configured(self) -> bool:
        """Whether the client can be used for external calls."""

        return self.enabled and bool(self.api_key and self.base_url and self.model)

    def status(self) -> dict[str, Any]:
        """Return non-secret runtime status for the UI/API."""

        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "base_url": self.base_url,
            "model": self.model,
        }

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 700,
        timeout: float | None = None,
    ) -> ChatCompletion:
        """Call non-streaming chat completion."""

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        data = self._request_json("/chat/completions", payload, timeout=timeout)
        choices = data.get("choices") or []
        if not choices:
            raise LLMClientError("chat completion returned no choices")
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content") or ""
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None:
            finish_reason = str(finish_reason)
        return ChatCompletion(content=content.strip(), message=message, raw=data, finish_reason=finish_reason)

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 700,
    ) -> Iterator[str]:
        """Yield text deltas from a streaming chat completion."""

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        response = self._open("/chat/completions", payload)
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if data_text == "[DONE]":
                    break
                try:
                    event = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield str(content)
        finally:
            response.close()

    def _request_json(self, path: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        response = self._open(path, payload, timeout=timeout)
        try:
            raw = response.read().decode("utf-8", errors="replace")
        finally:
            response.close()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"invalid JSON response: {raw[:300]}") from exc
        if not isinstance(data, dict):
            raise LLMClientError("chat completion response is not an object")
        return data

    def _open(self, path: str, payload: dict[str, Any], timeout: float | None = None) -> Any:
        if not self.configured:
            raise LLMClientError("external LLM is not configured")
        url = f"{self.base_url}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            return urllib.request.urlopen(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LLMClientError(f"HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise LLMClientError(str(exc)) from exc
