"""Base class for specialized agents."""

from abc import ABC, abstractmethod
from typing import Any

import structlog

from realtorai.inference.engine import InferenceEngine, get_engine

logger = structlog.get_logger()


class Agent(ABC):
    """Base class for specialized agent configurations.

    An agent is a specific configuration of:
    - System prompt (defines role and behavior)
    - Tool set (what actions it can take)
    - Output schemas (expected output formats)

    All agents share the same underlying LLM via the inference engine.
    """

    def __init__(self) -> None:
        self._engine: InferenceEngine | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent name for logging and display."""
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt that defines this agent's role."""
        ...

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Tool definitions available to this agent."""
        return []

    async def get_engine(self) -> InferenceEngine:
        """Get the inference engine instance."""
        if self._engine is None:
            self._engine = await get_engine()
        return self._engine

    async def generate(
        self,
        prompt: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Generate a completion using this agent's configuration."""
        engine = await self.get_engine()

        return await engine.generate(
            prompt=prompt,
            system_prompt=self.system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def generate_structured(
        self,
        prompt: str,
        output_schema: type,
        max_tokens: int | None = None,
    ) -> Any:
        """Generate a structured output using this agent's configuration."""
        engine = await self.get_engine()

        return await engine.generate_structured(
            prompt=prompt,
            output_schema=output_schema,
            system_prompt=self.system_prompt,
            max_tokens=max_tokens,
        )

    async def call_tools(self, prompt: str) -> dict[str, Any]:
        """Generate a tool call using this agent's configuration."""
        if not self.tools:
            return {"tool": None, "response": await self.generate(prompt)}

        engine = await self.get_engine()

        return await engine.call_tool(
            prompt=prompt,
            tools=self.tools,
            system_prompt=self.system_prompt,
        )
