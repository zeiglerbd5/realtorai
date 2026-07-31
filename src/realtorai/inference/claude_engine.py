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

CACHE_CONTROL = {"type": "ephemeral"}


class ClaudeEngineError(RuntimeError):
    """A Claude API call failed or is unavailable."""


def _cacheable_system(system_prompt: str | None) -> Any:
    """System prompt as a cache breakpoint over the static tools+system prefix."""
    if not system_prompt:
        return None
    return [{"type": "text", "text": system_prompt, "cache_control": CACHE_CONTROL}]


def _rolling_breakpoint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy of `messages` with a cache breakpoint on the final content block.

    The transcript grows by one exchange per agent-loop iteration, so marking
    the tail means each call caches everything it just added and the next call
    reads the whole prefix back. Returns the input unchanged when the tail is
    not a shape we can safely mark (SDK block objects are passed through as-is).
    """
    if not messages:
        return messages
    content = messages[-1].get("content")
    if isinstance(content, str):
        blocks: list[Any] = [{"type": "text", "text": content}]
    elif isinstance(content, list):
        blocks = [dict(b) if isinstance(b, dict) else b for b in content]
    else:
        return messages

    for block in reversed(blocks):
        if isinstance(block, dict):
            block["cache_control"] = CACHE_CONTROL
            break
    else:
        return messages

    tail = dict(messages[-1])
    tail["content"] = blocks
    return [*messages[:-1], tail]


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

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        task: LLMTask = LLMTask.CHAT,
        max_tokens: int = 8000,
    ) -> Any:
        """One raw assistant turn with tool definitions. Returns the response.

        The caller owns the agent loop — executing tool calls and appending
        tool_result blocks (see orchestration/copilot.py). Thinking blocks in
        the response content must be passed back verbatim on the next turn.

        Prompt-cached: the loop re-sends tools + system + the whole transcript
        on every iteration, so a scoping conversation pays for the same prefix
        five or six times over. Two breakpoints (static prefix, rolling tail)
        drop the repeat to 10% of input price. Deliberately not applied to the
        generate_* calls — those run once per transaction, days apart, so the
        1.25x cache write would never be read back.
        """
        import anthropic

        client = self._get_client()
        model = model_for(task)
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                system=_cacheable_system(system_prompt) or anthropic.NOT_GIVEN,
                tools=tools,
                messages=_rolling_breakpoint(messages),
            )
        except anthropic.APIConnectionError as e:
            raise ClaudeEngineError(f"Claude API unreachable: {e}") from e
        except anthropic.APIStatusError as e:
            raise ClaudeEngineError(f"Claude API error {e.status_code}: {e.message}") from e

        usage = response.usage
        logger.info(
            "claude_chat_turn",
            task=task.value,
            model=model,
            stop_reason=response.stop_reason,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write=getattr(usage, "cache_creation_input_tokens", None),
            cache_read=getattr(usage, "cache_read_input_tokens", None),
        )
        return response

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
