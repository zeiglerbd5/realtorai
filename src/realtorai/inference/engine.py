"""MLX inference engine wrapper for Llama 3.2."""

import json
from pathlib import Path
from typing import Any, AsyncIterator, TypeVar

import structlog
from pydantic import BaseModel


from realtorai.config.settings import get_settings

logger = structlog.get_logger()

# Type variable for structured output
T = TypeVar("T", bound=BaseModel)


class InferenceEngine:
    """MLX-based inference engine for local LLM.

    Supports:
    - System prompts for different agent roles
    - Structured output via Pydantic schemas
    - Tool/function calling
    - Streaming responses
    """

    def __init__(self, model_path: Path | str | None = None) -> None:
        self.settings = get_settings()
        self.model_path = model_path or self.settings.model_name
        self._model = None
        self._tokenizer = None
        self._loaded = False

    async def load(self) -> None:
        """Load the model into memory."""
        if self._loaded:
            return

        logger.info("loading_model", path=str(self.model_path))

        try:
            # Import MLX-LM
            from mlx_lm import load

            # Load model and tokenizer
            self._model, self._tokenizer = load(str(self.model_path))
            self._loaded = True

            logger.info("model_loaded", path=str(self.model_path))

        except ImportError as e:
            logger.error("mlx_import_error", error=str(e))
            raise RuntimeError(
                "MLX-LM not installed. Install with: pip install mlx-lm"
            ) from e
        except Exception as e:
            logger.error("model_load_error", path=str(self.model_path), error=str(e))
            raise

    async def unload(self) -> None:
        """Unload the model from memory."""
        self._model = None
        self._tokenizer = None
        self._loaded = False
        logger.info("model_unloaded")

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._loaded

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
    ) -> str:
        """Generate a completion from the model.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt for context
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            stop_sequences: Sequences that stop generation

        Returns:
            Generated text
        """
        if not self._loaded:
            await self.load()

        from mlx_lm import generate

        # Build messages in chat format
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Format as chat
        formatted_prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        # Create sampler with temperature
        from mlx_lm.sample_utils import make_sampler
        sampler = make_sampler(temp=temperature or self.settings.model_temperature)

        # Generate
        response = generate(
            self._model,
            self._tokenizer,
            prompt=formatted_prompt,
            max_tokens=max_tokens or self.settings.model_max_tokens,
            sampler=sampler,
        )

        logger.debug(
            "generation_complete",
            prompt_length=len(prompt),
            response_length=len(response),
        )

        return response

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Generate a streaming completion from the model.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Yields:
            Generated text chunks
        """
        if not self._loaded:
            await self.load()

        from mlx_lm.generate import generate_step

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        formatted_prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        # Tokenize
        input_ids = self._tokenizer.encode(formatted_prompt, return_tensors="mlx")

        # Stream generation
        from mlx_lm.sample_utils import make_sampler
        max_toks = max_tokens or self.settings.model_max_tokens
        temp = temperature or self.settings.model_temperature
        sampler = make_sampler(temp=temp)

        for token, _ in zip(
            generate_step(input_ids, self._model, sampler=sampler),
            range(max_toks),
        ):
            text = self._tokenizer.decode([token])
            yield text

    async def generate_structured(
        self,
        prompt: str,
        output_schema: type[T],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> T:
        """Generate a structured output matching a Pydantic schema.

        Args:
            prompt: The user prompt
            output_schema: Pydantic model class to validate against
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate

        Returns:
            Validated Pydantic model instance
        """
        # Build schema-aware system prompt - use simplified field descriptions instead of full JSON schema
        fields = []
        schema = output_schema.model_json_schema()
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        for field_name, field_info in properties.items():
            field_type = field_info.get("type", "string")
            description = field_info.get("description", "")
            is_required = field_name in required

            # Handle enums
            if "enum" in field_info:
                field_type = f"one of: {field_info['enum']}"
            elif "$ref" in field_info:
                ref_name = field_info["$ref"].split("/")[-1]
                field_type = ref_name
            elif "anyOf" in field_info:
                field_type = "optional"

            req_marker = "(required)" if is_required else "(optional)"
            fields.append(f'  "{field_name}": {field_type} {req_marker} - {description}')

        fields_description = "\n".join(fields)

        structured_system_prompt = f"""{system_prompt or "You are a helpful assistant."}

Respond with a JSON object containing these fields:
{fields_description}

IMPORTANT:
- Output ONLY valid JSON, nothing else
- Use real values from the user's request, not placeholder examples
- Do not include explanations or markdown formatting"""

        # Generate with lower temperature for structured output
        response = await self.generate(
            prompt=prompt,
            system_prompt=structured_system_prompt,
            max_tokens=max_tokens or 2048,
            temperature=0.3,  # Lower temp for more deterministic JSON
        )

        # Extract JSON from response
        json_str = self._extract_json(response)

        # Parse and validate
        try:
            data = json.loads(json_str)
            # Normalize common model output issues
            data = self._normalize_model_output(data, output_schema)
            result = output_schema.model_validate(data)
            logger.debug("structured_output_parsed", schema=output_schema.__name__)
            return result
        except json.JSONDecodeError as e:
            logger.error("json_parse_error", response=response[:200], error=str(e))
            raise ValueError(f"Failed to parse JSON from model response: {e}") from e
        except Exception as e:
            logger.error("schema_validation_error", error=str(e))
            raise ValueError(f"Response doesn't match schema: {e}") from e

    def _normalize_model_output(self, data: dict, schema: type) -> dict:
        """Normalize common model output issues to match schema expectations."""
        # Lowercase enum values
        for key, value in list(data.items()):
            if isinstance(value, str):
                # Try lowercase for enum values
                data[key] = value.lower() if value[0].isupper() else value

        # Convert numeric confidence to string
        if "confidence" in data:
            conf = data["confidence"]
            if isinstance(conf, (int, float)):
                if conf >= 0.8:
                    data["confidence"] = "high"
                elif conf >= 0.5:
                    data["confidence"] = "medium"
                else:
                    data["confidence"] = "low"

        # Convert None to empty list for list fields
        json_schema = schema.model_json_schema()
        properties = json_schema.get("properties", {})
        for key, prop in properties.items():
            if key in data and data[key] is None:
                if prop.get("type") == "array" or "items" in prop:
                    data[key] = []

        # Handle sender field - convert string to ContactReference dict
        if "sender" in data and isinstance(data["sender"], str):
            data["sender"] = {"email": "", "name": data["sender"], "role": None}

        # Handle mentioned_contacts - convert strings to ContactReference dicts
        if "mentioned_contacts" in data and isinstance(data["mentioned_contacts"], list):
            normalized_contacts = []
            for contact in data["mentioned_contacts"]:
                if isinstance(contact, str):
                    normalized_contacts.append({"email": "", "name": contact, "role": None})
                elif isinstance(contact, dict):
                    normalized_contacts.append(contact)
            data["mentioned_contacts"] = normalized_contacts

        # Handle deadline_mentioned - convert False/invalid to None
        if "deadline_mentioned" in data:
            val = data["deadline_mentioned"]
            if val is False or val == "false" or val == "":
                data["deadline_mentioned"] = None

        # Normalize intent values using keyword matching
        if "intent" in data:
            intent = data["intent"].lower()
            # Valid intent values
            valid_intents = [
                "question", "request", "information", "confirmation",
                "scheduling", "document", "negotiation", "introduction",
                "followup", "administrative", "other"
            ]

            # First check if it's already valid
            if intent not in valid_intents:
                # Keyword-based fuzzy matching (order matters - more specific first)
                if "follow" in intent or "followup" in intent:
                    intent = "followup"
                elif "schedul" in intent or "calendar" in intent or "appointment" in intent:
                    intent = "scheduling"
                elif "document" in intent or "attach" in intent or "file" in intent:
                    intent = "document"
                elif "negotiat" in intent or "offer" in intent or "counter" in intent:
                    intent = "negotiation"
                elif "intro" in intent or "new client" in intent or "new contact" in intent:
                    intent = "introduction"
                elif "confirm" in intent or "verify" in intent:
                    intent = "confirmation"
                elif "admin" in intent or "newsletter" in intent:
                    intent = "administrative"
                elif "request" in intent or "asking for" in intent:
                    intent = "request"
                elif "inquiry" in intent or "question" in intent or "asking" in intent:
                    intent = "question"
                elif "info" in intent or "fyi" in intent or "update" in intent:
                    intent = "information"
                else:
                    # Default to question for anything buyer/client related
                    intent = "question"

            data["intent"] = intent

        # Normalize priority values
        if "priority" in data:
            priority = data["priority"].lower()
            valid_priorities = ["critical", "high", "normal", "low"]

            if priority not in valid_priorities:
                if "urgent" in priority or "immediate" in priority:
                    priority = "critical"
                elif "medium" in priority or "moderate" in priority:
                    priority = "normal"
                elif "high" in priority or "important" in priority:
                    priority = "high"
                elif "low" in priority or "minor" in priority:
                    priority = "low"
                else:
                    priority = "normal"  # Default to normal

            data["priority"] = priority

        return data

    def _extract_json(self, text: str) -> str:
        """Extract JSON from model response, handling markdown code blocks."""
        text = text.strip()

        # Remove markdown code blocks
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]

        text = text.strip()

        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1

        if start == -1 or end == 0:
            raise ValueError("No JSON object found in response")

        return text[start:end]

    async def call_tool(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Generate a tool call from the model.

        Args:
            prompt: The user prompt
            tools: List of tool definitions (OpenAI function format)
            system_prompt: Optional system prompt

        Returns:
            Dict with 'tool' (tool name) and 'arguments' (tool args)
        """
        # Build tool-aware prompt
        tools_json = json.dumps(tools, indent=2)

        tool_system_prompt = f"""{system_prompt or "You are a helpful assistant."}

You have access to these tools:

{tools_json}

To use a tool, respond with JSON in this format:
{{"tool": "tool_name", "arguments": {{...}}}}

If no tool is needed, respond normally."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=tool_system_prompt,
            temperature=0.3,
        )

        # Try to parse as tool call
        try:
            json_str = self._extract_json(response)
            result = json.loads(json_str)
            if "tool" in result and "arguments" in result:
                logger.debug("tool_call_parsed", tool=result["tool"])
                return result
        except (ValueError, json.JSONDecodeError):
            pass

        # No tool call found
        return {"tool": None, "response": response}


# Global engine instance
_engine: InferenceEngine | None = None


async def get_engine() -> InferenceEngine:
    """Get the inference engine instance, loading if necessary."""
    global _engine
    if _engine is None:
        _engine = InferenceEngine()
    if not _engine.is_loaded:
        await _engine.load()
    return _engine
