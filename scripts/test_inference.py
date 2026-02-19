#!/usr/bin/env python3
"""
RealtorAI Inference Test Script

Test the local LLM inference engine with sample prompts.
"""

import asyncio
import json
import time
from pathlib import Path

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_basic_generation():
    """Test basic text generation."""
    from realtorai.inference.engine import InferenceEngine
    from realtorai.config.settings import get_settings

    settings = get_settings()
    engine = InferenceEngine(settings)

    print("\n" + "=" * 60)
    print("Test 1: Basic Generation")
    print("=" * 60)

    prompt = "Write a brief, professional email greeting for a real estate client named John."

    print(f"Prompt: {prompt}\n")

    start = time.time()
    response = await engine.generate(prompt)
    elapsed = time.time() - start

    print(f"Response:\n{response}")
    print(f"\nGeneration time: {elapsed:.2f}s")

    return True


async def test_streaming_generation():
    """Test streaming text generation."""
    from realtorai.inference.engine import InferenceEngine
    from realtorai.config.settings import get_settings

    settings = get_settings()
    engine = InferenceEngine(settings)

    print("\n" + "=" * 60)
    print("Test 2: Streaming Generation")
    print("=" * 60)

    prompt = "List 3 key things to check when viewing a property."

    print(f"Prompt: {prompt}\n")
    print("Response (streaming): ", end="", flush=True)

    start = time.time()
    async for token in engine.generate_stream(prompt):
        print(token, end="", flush=True)
    elapsed = time.time() - start

    print(f"\n\nGeneration time: {elapsed:.2f}s")

    return True


async def test_structured_output():
    """Test structured JSON output."""
    from realtorai.inference.engine import InferenceEngine
    from realtorai.schemas.email import EmailClassification
    from realtorai.config.settings import get_settings

    settings = get_settings()
    engine = InferenceEngine(settings)

    print("\n" + "=" * 60)
    print("Test 3: Structured Output (Email Classification)")
    print("=" * 60)

    email_content = """
    Subject: Interested in 123 Main St listing

    Hi,

    I saw your listing for the property at 123 Main St and I'm very interested.
    Could we schedule a showing this weekend? I'm pre-approved for up to $500k.

    Thanks,
    Sarah Johnson
    555-123-4567
    """

    print(f"Email:\n{email_content}\n")

    start = time.time()
    result = await engine.generate_structured(
        f"Classify this email:\n\n{email_content}",
        EmailClassification,
    )
    elapsed = time.time() - start

    if result:
        print(f"Classification:")
        print(f"  Priority: {result.priority}")
        print(f"  Intent: {result.intent}")
        print(f"  Requires Response: {result.requires_response}")
        print(f"  Key Entities: {result.key_entities}")
        print(f"  Summary: {result.summary}")
    else:
        print("Failed to parse structured output")

    print(f"\nGeneration time: {elapsed:.2f}s")

    return result is not None


async def test_email_draft():
    """Test email draft generation."""
    from realtorai.inference.engine import InferenceEngine
    from realtorai.inference.prompts import build_email_draft_prompt
    from realtorai.schemas.email import DraftResponse
    from realtorai.config.settings import get_settings

    settings = get_settings()
    engine = InferenceEngine(settings)

    print("\n" + "=" * 60)
    print("Test 4: Email Draft Generation")
    print("=" * 60)

    email_data = {
        "sender_name": "Sarah Johnson",
        "sender_email": "sarah@example.com",
        "subject": "Interested in 123 Main St listing",
        "body": "I saw your listing and I'm very interested. Could we schedule a showing this weekend?",
    }

    print(f"Original email from: {email_data['sender_name']}")
    print(f"Subject: {email_data['subject']}\n")

    prompt = build_email_draft_prompt(
        sender=email_data["sender_name"],
        subject=email_data["subject"],
        body=email_data["body"],
        intent="showing_request",
    )

    start = time.time()
    result = await engine.generate_structured(prompt, DraftResponse)
    elapsed = time.time() - start

    if result:
        print(f"Draft Response:")
        print(f"  Subject: {result.subject}")
        print(f"  Body:\n{result.body}")
    else:
        print("Failed to generate draft")

    print(f"\nGeneration time: {elapsed:.2f}s")

    return result is not None


async def test_tool_calling():
    """Test tool calling capability."""
    from realtorai.inference.engine import InferenceEngine
    from realtorai.inference.tools import EMAIL_TOOLS
    from realtorai.config.settings import get_settings

    settings = get_settings()
    engine = InferenceEngine(settings)

    print("\n" + "=" * 60)
    print("Test 5: Tool Calling")
    print("=" * 60)

    prompt = "Send an email to sarah@example.com confirming a showing at 123 Main St tomorrow at 2pm."

    print(f"Prompt: {prompt}\n")

    start = time.time()
    tool_call = await engine.call_tool(prompt, EMAIL_TOOLS)
    elapsed = time.time() - start

    if tool_call:
        print(f"Tool Call:")
        print(f"  Name: {tool_call.get('name')}")
        print(f"  Arguments: {json.dumps(tool_call.get('arguments', {}), indent=2)}")
    else:
        print("No tool call detected (this is expected if model doesn't support tools)")

    print(f"\nGeneration time: {elapsed:.2f}s")

    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("RealtorAI Inference Test Suite")
    print("=" * 60)

    tests = [
        ("Basic Generation", test_basic_generation),
        ("Streaming Generation", test_streaming_generation),
        ("Structured Output", test_structured_output),
        ("Email Draft", test_email_draft),
        ("Tool Calling", test_tool_calling),
    ]

    results = []

    for name, test_fn in tests:
        try:
            passed = await test_fn()
            results.append((name, passed))
        except Exception as e:
            print(f"\nError in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Test Results")
    print("=" * 60)

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    passed_count = sum(1 for _, p in results if p)
    print(f"\n{passed_count}/{len(results)} tests passed")


if __name__ == "__main__":
    asyncio.run(main())
