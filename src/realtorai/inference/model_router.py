"""Automatic model selection for Claude API calls.

Policy: route by task criticality, not by call site.

  - STANDARD tier (default `claude-sonnet-5`): high-volume structured work —
    paperwork extraction, form fill, intake classification, drafting remarks.
    Sonnet is strong at structured output and costs a fraction of Opus.
  - REVIEW tier (default `claude-opus-4-8`): second-model verification of
    extracted data and deed review, where a missed easement or a wrong
    deadline has real-world consequences.

The tier→model assignment lives in settings (`CLAUDE_MODEL_STANDARD`,
`CLAUDE_MODEL_REVIEW`) so models can be upgraded without code changes.
"""

from enum import Enum

from realtorai.config.settings import get_settings


class LLMTask(str, Enum):
    """What a Claude call is being asked to do."""

    EXTRACT = "extract"          # paperwork/PDF text -> TransactionRecord
    FORM_FILL = "form_fill"      # record -> per-form field payloads
    CLASSIFY = "classify"        # email intent detection (new listing / buyer / other)
    DRAFT = "draft"              # listing remarks, client-facing email text
    VERIFY = "verify"            # cross-check extraction against source docs
    DEED_REVIEW = "deed_review"  # restrictions / rights of way / easements


REVIEW_TASKS: frozenset[LLMTask] = frozenset({LLMTask.VERIFY, LLMTask.DEED_REVIEW})


def model_for(task: LLMTask) -> str:
    """Resolve the model ID for a task."""
    settings = get_settings()
    if task in REVIEW_TASKS:
        return settings.claude_model_review
    return settings.claude_model_standard
