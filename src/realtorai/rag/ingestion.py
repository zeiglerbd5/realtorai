"""Document ingestion and chunking for RAG."""

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import structlog

from realtorai.rag.config import get_chunk_overlap, get_chunk_size
from realtorai.rag.section_aware import detect_section_style, split_by_sections
from realtorai.rag.store import get_vector_store

logger = structlog.get_logger()


class DocumentIngester:
    """Ingests documents into the vector store.

    Supports:
    - PDF files
    - Text/Markdown files
    - RTF files
    - Web pages (HTML)
    """

    def __init__(self):
        self.store = get_vector_store()
        self.chunk_size = get_chunk_size()
        self.chunk_overlap = get_chunk_overlap()

    def ingest_file(self, file_path: str | Path) -> int:
        """Ingest a file into the vector store.

        Args:
            file_path: Path to the file

        Returns:
            Number of chunks added
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = path.suffix.lower()
        source = path.name

        # Extract text based on file type
        if suffix == ".pdf":
            text = self._extract_pdf(path)
        elif suffix == ".rtf":
            text = self._extract_rtf(path)
        elif suffix in (".txt", ".md", ".markdown"):
            text = path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

        # Chunk (section-aware if the doc looks like a statute/rule)
        chunks, chunk_meta = self._chunk_with_section_awareness(text)
        if not chunks:
            logger.warning("no_chunks_extracted", source=source)
            return 0

        # Create metadata and IDs
        metadatas = [
            {"source": source, "type": suffix[1:], "chunk_index": i, **chunk_meta[i]}
            for i in range(len(chunks))
        ]
        ids = [
            f"{hashlib.sha256(source.encode()).hexdigest()[:8]}_{i}"
            for i in range(len(chunks))
        ]

        # Delete existing chunks from this source first
        self.store.delete_by_source(source)

        # Add new chunks
        self.store.add_documents(chunks, metadatas, ids)

        section_count = sum(1 for m in chunk_meta if m.get("section"))
        logger.info(
            "file_ingested",
            source=source,
            chunks=len(chunks),
            section_aware=section_count > 0,
        )
        return len(chunks)

    def ingest_url(self, url: str) -> int:
        """Ingest a web page into the vector store.

        Args:
            url: URL to fetch and ingest

        Returns:
            Number of chunks added
        """
        parsed = urlparse(url)
        source = f"web:{parsed.netloc}{parsed.path}"

        # Fetch the page
        response = httpx.get(url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()

        # Extract text from HTML
        text = self._extract_html(response.text)

        # Chunk and add
        chunks = self._chunk_text(text)
        if not chunks:
            logger.warning("no_chunks_extracted", source=source)
            return 0

        # Create metadata and IDs
        metadatas = [
            {"source": source, "type": "html", "url": url, "chunk_index": i}
            for i in range(len(chunks))
        ]
        ids = [
            f"{hashlib.sha256(url.encode()).hexdigest()[:8]}_{i}"
            for i in range(len(chunks))
        ]

        # Delete existing chunks from this source first
        self.store.delete_by_source(source)

        # Add new chunks
        self.store.add_documents(chunks, metadatas, ids)

        logger.info("url_ingested", source=source, chunks=len(chunks))
        return len(chunks)

    def ingest_text(self, text: str, source: str, metadata: dict | None = None) -> int:
        """Ingest raw text into the vector store.

        Args:
            text: The text content
            source: Source identifier
            metadata: Optional additional metadata

        Returns:
            Number of chunks added
        """
        chunks = self._chunk_text(text)
        if not chunks:
            return 0

        base_meta = {"source": source, "type": "text"}
        if metadata:
            base_meta.update(metadata)

        metadatas = [
            {**base_meta, "chunk_index": i}
            for i in range(len(chunks))
        ]
        ids = [
            f"{hashlib.sha256(source.encode()).hexdigest()[:8]}_{i}"
            for i in range(len(chunks))
        ]

        self.store.delete_by_source(source)
        self.store.add_documents(chunks, metadatas, ids)

        logger.info("text_ingested", source=source, chunks=len(chunks))
        return len(chunks)

    def _extract_pdf(self, path: Path) -> str:
        """Extract text from a PDF file."""
        from pypdf import PdfReader

        reader = PdfReader(path)
        text_parts = []

        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

        return "\n\n".join(text_parts)

    def _extract_rtf(self, path: Path) -> str:
        """Extract text from an RTF file."""
        content = path.read_text(encoding="utf-8", errors="ignore")

        # Simple RTF stripping - remove RTF control codes
        # Remove RTF header and control words
        text = re.sub(r'\\[a-z]+\d*\s?', ' ', content)
        # Remove braces
        text = re.sub(r'[{}]', '', text)
        # Remove remaining backslashes
        text = text.replace('\\', '')
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def _extract_html(self, html: str) -> str:
        """Extract text from HTML content."""
        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html)

        # Decode HTML entities
        import html as html_module
        text = html_module.unescape(text)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def _chunk_with_section_awareness(self, text: str) -> tuple[list[str], list[dict]]:
        """Chunk text with legal-doc section awareness when applicable.

        Detects whether the document uses Maine MRSA-style (§NNNNN) or Maine
        Commission Rules-style (SECTION N) section headers. If so, splits
        text into sections first, chunks each section's body, and prepends
        the section header to every chunk produced from that section. The
        section header is also added to that chunk's metadata.

        For non-legal documents, falls back to plain chunking.

        Returns:
            (chunks, per_chunk_metadata_extras)
        """
        style = detect_section_style(text)
        if style is None:
            plain = self._chunk_text(text)
            return plain, [{} for _ in plain]

        chunks: list[str] = []
        metas: list[dict] = []
        for header, body in split_by_sections(text, style):
            for body_chunk in self._chunk_text(body):
                if header:
                    chunks.append(f"[{header}]\n\n{body_chunk}")
                    metas.append({"section": header})
                else:
                    chunks.append(body_chunk)
                    metas.append({})
        return chunks, metas

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks.

        Uses simple character-based chunking with sentence boundary awareness.
        """
        if not text or len(text.strip()) < 50:
            return []

        # Approximate chars per token (rough estimate)
        chars_per_token = 4
        chunk_chars = self.chunk_size * chars_per_token
        overlap_chars = self.chunk_overlap * chars_per_token

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_chars

            # Try to end at a sentence boundary
            if end < len(text):
                # Look for sentence endings near the chunk boundary
                search_start = max(end - 100, start)
                search_end = min(end + 100, len(text))
                search_region = text[search_start:search_end]

                # Find last sentence ending in the region
                for pattern in ['. ', '.\n', '? ', '?\n', '! ', '!\n']:
                    last_idx = search_region.rfind(pattern)
                    if last_idx != -1:
                        end = search_start + last_idx + len(pattern)
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Move start forward, accounting for overlap
            start = end - overlap_chars

        return chunks


# Convenience function
def ingest(source: str) -> int:
    """Ingest a file or URL into the knowledge base.

    Args:
        source: File path or URL

    Returns:
        Number of chunks added
    """
    ingester = DocumentIngester()

    if source.startswith("http://") or source.startswith("https://"):
        return ingester.ingest_url(source)
    else:
        return ingester.ingest_file(source)
