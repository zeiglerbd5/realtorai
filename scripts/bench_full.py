#!/usr/bin/env python
"""Benchmark full pipeline: RAG + model (no UI)."""
import asyncio
import time


async def main():
    print("Loading engine...")
    start = time.time()
    from realtorai.inference.engine import get_engine
    from realtorai.inference.prompts import get_conversation_prompt_with_rag
    engine = await get_engine()
    print(f"Engine loaded: {time.time()-start:.2f}s")

    query = "What are the ethical obligations of a realtor?"

    print(f"\nQuery: {query}")

    # RAG retrieval
    print("\nStep 1: RAG retrieval...")
    start = time.time()
    system, augmented = get_conversation_prompt_with_rag(query)
    rag_time = time.time() - start
    print(f"RAG time: {rag_time:.2f}s")

    # Model generation
    print("\nStep 2: Model generation...")
    start = time.time()
    response = await engine.generate(augmented, system_prompt=system, max_tokens=256)
    gen_time = time.time() - start
    print(f"Generation time: {gen_time:.2f}s")

    print(f"\nTotal: {rag_time + gen_time:.2f}s")
    print(f"\nResponse:\n{response}")

asyncio.run(main())
