#!/usr/bin/env python
"""Interactive CLI chat with RAG support (streaming) and conversation memory."""

def main():
    print("Loading model and RAG...")
    from mlx_lm import load, stream_generate
    from mlx_lm.sample_utils import make_sampler

    from realtorai.config.settings import get_settings
    from realtorai.inference.prompts import get_conversation_prompt_with_rag

    model, tokenizer = load(get_settings().model_name)
    sampler = make_sampler(temp=0.7)

    # Conversation history
    conversation_history = []
    max_history = 20

    print("Ready!\n")
    print("Commands: 'quit' to exit, 'clear' to reset conversation\n")

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
        if user_input.lower() == 'clear':
            conversation_history.clear()
            print("Conversation cleared.\n")
            continue

        # Get RAG-augmented prompt (retrieves based on current message)
        system, augmented = get_conversation_prompt_with_rag(user_input)

        # Build messages with history
        messages = [{"role": "system", "content": system}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": augmented})

        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

        # Stream response
        print("\nAssistant: ", end="", flush=True)
        response_text = []

        for response in stream_generate(
            model, tokenizer, prompt=prompt, max_tokens=512, sampler=sampler
        ):
            print(response.text, end="", flush=True)
            response_text.append(response.text)

        print("\n")

        # Add to history
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": "".join(response_text)})

        # Trim history
        while len(conversation_history) > max_history:
            conversation_history.pop(0)

main()
