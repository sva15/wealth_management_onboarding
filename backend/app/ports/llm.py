"""LLM invocation port. Business logic depends on this, never on a provider SDK."""
from dataclasses import dataclass
from typing import Protocol


class LlmError(Exception):
    """Provider failure. Carries a code only: provider messages may echo prompt content."""

    def __init__(self, code: str, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class LlmRequest:
    task: str
    system_prompt: str
    user_prompt: str
    prompt_version: str
    # The untrusted document text embedded in user_prompt, kept separately for the mock client.
    untrusted_text: str = ""
    max_tokens: int = 4096


@dataclass(frozen=True)
class LlmResponse:
    text: str
    model_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None


class LlmClient(Protocol):
    model_id: str

    def invoke(self, request: LlmRequest) -> LlmResponse:
        """Return raw model text. Raise LlmError on provider failure."""
