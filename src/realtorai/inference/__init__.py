"""MLX inference engine for local LLM."""

from realtorai.inference.engine import InferenceEngine, get_engine
from realtorai.inference.extraction import (
    classify_email_content,
    extract_from_document,
    extract_from_email,
    extract_mls_data,
    extract_transaction_data,
)

__all__ = [
    "InferenceEngine",
    "get_engine",
    "extract_from_email",
    "extract_from_document",
    "extract_mls_data",
    "extract_transaction_data",
    "classify_email_content",
]
