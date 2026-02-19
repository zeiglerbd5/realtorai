#!/usr/bin/env python
"""Benchmark raw MLX model speed (no RAG, no UI)."""
import time
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler

from realtorai.config.settings import get_settings

print("Loading model...")
start = time.time()
model, tokenizer = load(get_settings().model_name)
print(f"Model loaded: {time.time()-start:.2f}s")

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What are the ethical obligations of a realtor?"}
]
prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

print("\nGenerating response...")
start = time.time()
response = generate(model, tokenizer, prompt=prompt, max_tokens=256, sampler=make_sampler(temp=0.7))
gen_time = time.time() - start

print(f"\nGeneration time: {gen_time:.2f}s")
print(f"Response:\n{response}")
