"""Cache breakpoints for the tool-calling agent loop.

The loop re-sends tools + system + the entire transcript on every iteration,
so a six-call scoping conversation pays for the same prefix six times. These
tests cover the two breakpoints that make the repeat cheap — and the fact that
the caller's message list is never mutated, since copilot._agent_loop keeps
appending to the list it handed us.
"""

from realtorai.inference.claude_engine import (
    CACHE_CONTROL,
    _cacheable_system,
    _rolling_breakpoint,
)


def test_system_prompt_becomes_a_cache_breakpoint() -> None:
    blocks = _cacheable_system("You are the queue copilot.")
    assert blocks == [
        {
            "type": "text",
            "text": "You are the queue copilot.",
            "cache_control": CACHE_CONTROL,
        }
    ]


def test_empty_system_prompt_stays_unset() -> None:
    """Callers pass NOT_GIVEN when there's no system prompt — don't fabricate one."""
    assert _cacheable_system(None) is None
    assert _cacheable_system("") is None


def test_string_content_is_promoted_to_a_marked_block() -> None:
    out = _rolling_breakpoint([{"role": "user", "content": "scope it for me"}])
    assert out[-1]["content"] == [
        {"type": "text", "text": "scope it for me", "cache_control": CACHE_CONTROL}
    ]


def test_breakpoint_lands_on_the_last_tool_result() -> None:
    """A turn can return several tool_results; only the tail carries the marker."""
    messages = [
        {"role": "user", "content": "scope it"},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "a", "content": "deed text"},
                {"type": "tool_result", "tool_use_id": "b", "content": "no matches"},
            ],
        },
    ]
    out = _rolling_breakpoint(messages)
    blocks = out[-1]["content"]
    assert "cache_control" not in blocks[0]
    assert blocks[1]["cache_control"] == CACHE_CONTROL


def test_caller_list_is_never_mutated() -> None:
    """_agent_loop appends to its own list across iterations — don't touch it."""
    messages = [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "x"}]}
    ]
    out = _rolling_breakpoint(messages)

    assert "cache_control" not in messages[-1]["content"][0]
    assert messages[-1]["content"][0] is not out[-1]["content"][0]


def test_unmarkable_shapes_pass_through_untouched() -> None:
    """SDK block objects and empty transcripts must not raise."""
    assert _rolling_breakpoint([]) == []

    class SdkBlock:  # not a dict — mirrors response.content blocks
        type = "text"

    messages = [{"role": "assistant", "content": SdkBlock()}]
    assert _rolling_breakpoint(messages) is messages
