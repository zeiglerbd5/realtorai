#!/usr/bin/env python
"""Benchmark RAG retrieval speed (no model)."""
import time

print("Loading RAG...")
start = time.time()
from realtorai.rag.retrieval import retrieve_context
print(f"RAG loaded: {time.time()-start:.2f}s")

query = "What are the ethical obligations of a realtor?"

print(f"\nQuerying: {query}")
start = time.time()
ctx = retrieve_context(query)
rag_time = time.time() - start

print(f"\nRAG retrieval time: {rag_time:.2f}s")
print(f"Context length: {len(ctx)} chars")
print(f"\nContext preview:\n{ctx[:500]}...")
