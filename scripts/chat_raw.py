#!/usr/bin/env python
"""Interactive CLI chat - raw model only, no RAG (streaming)."""
from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler
from realtorai.config.settings import get_settings

print("Loading model...")
model, tokenizer = load(get_settings().model_name)
print("Ready!\n")
print("Type your message and press Enter. Type 'quit' to exit.\n")

sampler = make_sampler(temp=0.7)

while True:
    try:
        user_input = input("You: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nBye!")
        break

    if not user_input:
        continue
    if user_input.lower() in ('quit', 'exit', 'q'):
        print("Bye!")
        break

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": user_input}
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    print("\nAssistant: ", end="", flush=True)

    for response in stream_generate(model, tokenizer, prompt=prompt, max_tokens=512, sampler=sampler):
        print(response.text, end="", flush=True)

    print("\n")
