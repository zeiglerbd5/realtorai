"""RAG configuration loader."""

from pathlib import Path
from typing import Any

import yaml


def load_rag_config() -> dict[str, Any]:
    """Load RAG settings from realtorAI_config.yaml."""
    config_paths = [
        Path("/Users/bz/RealtyAI/realtorAI_config.yaml"),
        Path.home() / "RealtyAI" / "realtorAI_config.yaml",
        Path("realtorAI_config.yaml"),
    ]

    for path in config_paths:
        if path.exists():
            with open(path) as f:
                config = yaml.safe_load(f)
                return config.get("embedding", {})

    # Defaults if no config found
    return {
        "model": "all-MiniLM-L6-v2",
        "chunk_size": 512,
        "chunk_overlap": 50,
        "top_k_results": 5,
    }


def get_embedding_model() -> str:
    """Get the embedding model name."""
    return load_rag_config().get("model", "all-MiniLM-L6-v2")


def get_chunk_size() -> int:
    """Get chunk size in tokens."""
    return load_rag_config().get("chunk_size", 512)


def get_chunk_overlap() -> int:
    """Get chunk overlap in tokens."""
    return load_rag_config().get("chunk_overlap", 50)


def get_top_k() -> int:
    """Get number of results to retrieve."""
    return load_rag_config().get("top_k_results", 5)
