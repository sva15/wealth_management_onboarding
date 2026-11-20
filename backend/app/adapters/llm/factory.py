"""Select the LLM client from settings."""
from app.adapters.llm.mock import MockLlmClient
from app.config import Settings
from app.ports.llm import LlmClient


class LlmConfigurationError(RuntimeError):
    pass


def build_llm_client(settings: Settings) -> LlmClient:
    if settings.use_mock_bedrock:
        return MockLlmClient()
    if not settings.aws_region or not settings.bedrock_model_id:
        raise LlmConfigurationError(
            "AWS_REGION and BEDROCK_MODEL_ID must be set when USE_MOCK_BEDROCK is false"
        )
    from app.adapters.llm.bedrock import BedrockLlmClient

    return BedrockLlmClient(
        model_id=settings.bedrock_model_id,
        region=settings.aws_region,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_tokens=settings.llm_max_tokens,
    )
