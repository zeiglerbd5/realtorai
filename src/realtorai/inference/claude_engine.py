"""Claude API engine for workflow automation.

Complements the local MLX engine (inference/engine.py): chat and email triage
stay on-device; the transaction workflows (paperwork extraction, form fill,
verification, deed review) run on the Claude API with automatic model
selection (see inference/model_router.py).

Degrades gracefully: when no ANTHROPIC_API_KEY is configured, `available` is
False and workflow steps that need the LLM are skipped with a note instead of
failing — the mock demo runs fully offline.
"""

from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

from realtorai.config.settings import get_settings
from realtorai.inference.model_router import LLMTask, model_for

logger = structlog.get_logger()

ModelT = TypeVar("ModelT", bound=BaseModel)


class ClaudeEngineError(RuntimeError):
    """A Claude API call failed or is unavailable."""


class ClaudeEngine:
    """Thin async wrapper over the Anthropic SDK with task-based routing."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any = None

    @property
    def available(self) -> bool:
        """True when a key is configured and the SDK is importable."""
        if not self.settings.anthropic_api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as e:
                raise ClaudeEngineError("anthropic SDK not installed") from e
            if not self.settings.anthropic_api_key:
                raise ClaudeEngineError("ANTHROPIC_API_KEY not configured")
            self._client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        task: LLMTask = LLMTask.DRAFT,
        system_prompt: str | None = None,
        max_tokens: int = 16000,
    ) -> str:
        """Free-text generation. Returns the response text."""
        import anthropic

        client = self._get_client()
        model = model_for(task)
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                system=system_prompt or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIConnectionError as e:
            raise ClaudeEngineError(f"Claude API unreachable: {e}") from e
        except anthropic.APIStatusError as e:
            raise ClaudeEngineError(f"Claude API error {e.status_code}: {e.message}") from e

        if response.stop_reason == "refusal":
            raise ClaudeEngineError("Claude declined the request (stop_reason=refusal)")

        text = "".join(block.text for block in response.content if block.type == "text")
        logger.info(
            "claude_generate",
            task=task.value,
            model=model,
            output_tokens=response.usage.output_tokens,
        )
        return text

    async def generate_structured(
        self,
        prompt: str,
        output_schema: type[ModelT],
        *,
        task: LLMTask = LLMTask.EXTRACT,
        system_prompt: str | None = None,
        max_tokens: int = 16000,
        pdf: bytes | None = None,
    ) -> ModelT:
        """Schema-validated generation via structured outputs.

        Uses `messages.parse()` so the response is guaranteed to validate
        against the Pydantic schema. Pass `pdf` to attach a document (e.g. a
        scanned deed) — Claude reads it visually, so no OCR step is needed.
        """
        import anthropic

        client = self._get_client()
        model = model_for(task)

        content: Any = prompt
        if pdf is not None:
            import base64

            content = [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(pdf).decode(),
                    },
                },
                {"type": "text", "text": prompt},
            ]

        try:
            response = await client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                system=system_prompt or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": content}],
                output_format=output_schema,
            )
        except anthropic.APIConnectionError as e:
            raise ClaudeEngineError(f"Claude API unreachable: {e}") from e
        except anthropic.APIStatusError as e:
            raise ClaudeEngineError(f"Claude API error {e.status_code}: {e.message}") from e

        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise ClaudeEngineError(
                f"No structured output returned (stop_reason={response.stop_reason})"
            )

        logger.info(
            "claude_generate_structured",
            task=task.value,
            model=model,
            schema=output_schema.__name__,
            output_tokens=response.usage.output_tokens,
        )
        return response.parsed_output


_engine: ClaudeEngine | None = None


def get_claude_engine() -> ClaudeEngine:
    global _engine
    if _engine is None:
        _engine = ClaudeEngine()
    return _engine
