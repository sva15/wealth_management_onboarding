"""Amazon Bedrock client via LangChain (boto3 underneath). The only cloud dependency of the system.

Errors are reduced to a code so that provider messages, which may echo prompt text, are never
logged or stored. Token usage and latency are logged without any content.
"""
import random
import time
from collections.abc import Callable
from typing import Any

import structlog

from app.ports.llm import LlmError, LlmRequest, LlmResponse

log = structlog.get_logger()

_RETRYABLE_CODES = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ModelTimeoutException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelNotReadyException",
    }
)
_RETRYABLE_TYPES = frozenset({"ReadTimeoutError", "ConnectTimeoutError", "EndpointConnectionError"})
_MAX_BACKOFF_SECONDS = 20.0


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(exc).__name__


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


class BedrockLlmClient:
    def __init__(
        self,
        model_id: str,
        region: str,
        timeout_seconds: int = 60,
        max_retries: int = 3,
        max_tokens: int = 4096,
        chat: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model_id = model_id
        self._max_retries = max_retries
        self._sleep = sleep
        if chat is None:
            from botocore.config import Config
            from langchain_aws import ChatBedrockConverse

            chat = ChatBedrockConverse(
                model=model_id,
                region_name=region,
                temperature=0,
                max_tokens=max_tokens,
                # Retries are handled here so that every attempt is visible and bounded.
                config=Config(
                    read_timeout=timeout_seconds,
                    connect_timeout=10,
                    retries={"max_attempts": 1},
                ),
            )
        self._chat = chat

    def invoke(self, request: LlmRequest) -> LlmResponse:
        messages = [("system", request.system_prompt), ("human", request.user_prompt)]
        started = time.monotonic()
        for attempt in range(self._max_retries + 1):
            try:
                message = self._chat.invoke(messages)
                break
            except Exception as exc:
                code = _error_code(exc)
                retryable = code in _RETRYABLE_CODES or type(exc).__name__ in _RETRYABLE_TYPES
                log.warning(
                    "llm_call_failed",
                    task=request.task,
                    model_id=self.model_id,
                    error_code=code,
                    attempt=attempt + 1,
                    retryable=retryable,
                )
                if retryable and attempt < self._max_retries:
                    self._sleep(min(2**attempt + random.random(), _MAX_BACKOFF_SECONDS))
                    continue
                raise LlmError(code, retryable=retryable) from None

        usage = getattr(message, "usage_metadata", None) or {}
        latency_ms = int((time.monotonic() - started) * 1000)
        response = LlmResponse(
            text=_content_text(message.content),
            model_id=self.model_id,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            latency_ms=latency_ms,
        )
        log.info(
            "llm_call_completed",
            task=request.task,
            prompt_version=request.prompt_version,
            model_id=self.model_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=latency_ms,
        )
        return response
