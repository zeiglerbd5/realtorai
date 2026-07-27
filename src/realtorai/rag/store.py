"""ChromaDB vector store for document embeddings."""

from typing import Any

import chromadb
import structlog
from chromadb.config import Settings

from realtorai.config.settings import get_settings
from realtorai.rag.config import get_embedding_model

logger = structlog.get_logger()


class VectorStore:
    """ChromaDB-based vector store for RAG.

    Stores document chunks with embeddings for semantic search.
    Persists to disk for durability across restarts.
    """

    def __init__(self, collection_name: str = "knowledge_base"):
        self.settings = get_settings()
        self.db_path = self.settings.data_dir / "chromadb"
        self.collection_name = collection_name
        self._client = None
        self._collection = None
        self._embedding_fn = None

    def _get_client(self) -> chromadb.ClientAPI:
        """Get or create ChromaDB client."""
        if self._client is None:
            self.db_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.db_path),
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("chromadb_initialized", path=str(self.db_path))
        return self._client

    def _get_embedding_function(self):
        """Get the embedding function using sentence-transformers."""
        if self._embedding_fn is None:
            from chromadb.utils import embedding_functions

            model_name = get_embedding_model()
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model_name
            )
            logger.info("embedding_model_loaded", model=model_name)
        return self._embedding_fn

    def _get_collection(self) -> chromadb.Collection:
        """Get or create the collection."""
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self._get_embedding_function(),
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "collection_ready",
                name=self.collection_name,
                count=self._collection.count(),
            )
        return self._collection

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> list[str]:
        """Add documents to the vector store.

        Args:
            texts: List of text chunks to add
            metadatas: Optional metadata for each chunk
            ids: Optional IDs (auto-generated if not provided)

        Returns:
            List of document IDs
        """
        collection = self._get_collection()

        # Generate IDs if not provided
        if ids is None:
            import hashlib
            ids = [
                hashlib.sha256(text.encode()).hexdigest()[:16]
                for text in texts
            ]

        # Ensure metadatas exists
        if metadatas is None:
            metadatas = [{}] * len(texts)

        # Add to collection
        collection.add(
            documents=texts,
            metadatas=metadatas,
            ids=ids,
        )

        logger.info("documents_added", count=len(texts))
        return ids

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query the vector store for similar documents.

        Args:
            query_text: The query text
            n_results: Number of results to return
            where: Optional filter conditions

        Returns:
            List of results with 'text', 'metadata', 'distance'
        """
        collection = self._get_collection()

        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where,
        )

        # Format results
        formatted = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                formatted.append({
                    "text": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                    "id": results["ids"][0][i] if results["ids"] else None,
                })

        logger.debug("query_executed", query=query_text[:50], results=len(formatted))
        return formatted

    def delete_by_source(self, source: str) -> int:
        """Delete all documents from a specific source.

        Args:
            source: The source identifier (e.g., filename)

        Returns:
            Number of documents deleted
        """
        collection = self._get_collection()

        # Get IDs matching the source
        results = collection.get(
            where={"source": source},
        )

        if results["ids"]:
            collection.delete(ids=results["ids"])
            logger.info("documents_deleted", source=source, count=len(results["ids"]))
            return len(results["ids"])

        return 0

    def count(self) -> int:
        """Get total number of documents in the store."""
        return self._get_collection().count()

    def list_sources(self) -> list[str]:
        """List all unique sources in the store."""
        collection = self._get_collection()
        results = collection.get()

        sources = set()
        if results["metadatas"]:
            for meta in results["metadatas"]:
                if meta and "source" in meta:
                    sources.add(meta["source"])

        return sorted(sources)


# Global instance
_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get the global vector store instance."""
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
