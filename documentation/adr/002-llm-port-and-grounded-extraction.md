# ADR 002: Model access behind a port, grounded extraction, mock-first development

**Status:** Accepted

**Context:** Amazon Bedrock is the only permitted cloud dependency. Extraction output feeds financial conclusions, so a model must never be the only evidence for a value, and the system must run offline.

**Decision**
- All model calls go through the `LlmClient` port. `BedrockLlmClient` (LangChain `ChatBedrockConverse`, boto3) implements it with bounded retries and exponential backoff on throttling and timeouts. Provider errors are reduced to a code, because provider messages can echo prompt text. Token usage and latency are logged without content.
- `USE_MOCK_BEDROCK=true` selects `MockLlmClient`, a deterministic regex parser for the synthetic documents. Its facts carry `model_id = mock-rules-v1`, so they can never pass for real model output.
- One schema and one prompt per document type. Document text is wrapped in `<document>` tags, labelled as untrusted data, and cannot forge page markers or close the data block.
- Output is parsed with `Decimal` floats and validated by Pydantic. An invalid result gets exactly one repair attempt. After that the document goes to review. Every failure is kept in `extraction_diagnostics`. The raw response stays in the database and is never returned by the API or logged.
- **Grounding:** every item must cite a page and a quote that really appears on that page. Numbers must appear inside the quote, and text values must be substrings of it. Items that fail are dropped, reported and never saved, so a hallucinated figure cannot become a fact.
- Facts are idempotent through a content hash. A later run keeps identical facts, supersedes facts that disappeared, and never touches analyst-edited facts.
- The LLM classification fallback is used only when the deterministic rules need review. It is accepted only at confidence 0.8 or higher.

**Consequences:** Real-model quality is untested until Bedrock credentials are configured. The grounding check is deliberately strict, so formatting differences may send valid documents to review, which is the safe failure.
