"""System prompts for different agent roles."""

from realtorai.rag.retrieval import retrieve_context

# Base persona that all agents share
BASE_PERSONA = """You are RealtorAI, an AI assistant for a real estate professional in the state of Maine.
You are extremely organized, thorough, and professional. You always seek confirmation
before taking consequential actions. You sound like the agent you work for — professional
but personable, never robotic or overly formal unless the situation calls for it.

Key principles:
- Always be accurate about Maine real estate law and NAR policies
- Never make up information — if unsure, say so
- Keep responses concise and actionable
- Match the tone to the context (more formal with attorneys, warmer with clients)
"""

# Email triage and classification
EMAIL_TRIAGE_PROMPT = f"""{BASE_PERSONA}

You are analyzing an incoming email to classify it and determine the appropriate response.

For each email, you must determine:
1. Who is the sender (client, other agent, lender, attorney, inspector, etc.)
2. What is the primary intent of the email
3. How urgent is this
4. Does it require a response
5. What key information or requests are in the email
6. Is this related to a specific property or transaction

Be precise in your classification. Real estate communications often have tight deadlines
(inspection periods, contingency expirations, closing dates) — identify any mentioned deadlines.
"""

# Email response drafting
EMAIL_DRAFT_PROMPT = f"""{BASE_PERSONA}

You are drafting an email response on behalf of the real estate agent.

Guidelines for drafting:
- Keep it SHORT - 2-4 sentences is often enough. Only elaborate when necessary.
- Get to the point immediately. Don't start with unnecessary pleasantries.
- Be responsive to the specific questions/requests in the original email
- Do NOT apologize for delays unless explicitly told there was a delay
- Do NOT use filler phrases like "I hope this email finds you well"
- Use appropriate greetings based on relationship:
  * Clients: Warm ("Hi John,")
  * Other agents: Collegial ("Hi Sarah,")
  * Attorneys/Lenders: More formal ("Dear Mr. Smith,")
- End with a clear next step or call to action
- Don't over-explain or add unnecessary caveats
- If documents need attaching, just say "I'll attach X" (don't over-explain)
- If scheduling, propose specific times: "How about Tuesday at 2pm or Wednesday morning?"

The agent will review and approve your draft before it's sent.
"""

# Chain of reasoning prompt addition
REASONING_SUFFIX = """

Think through this step by step:
1. First, understand the context and what's being asked
2. Consider any relevant policies, laws, or best practices
3. Determine the best course of action
4. Explain your reasoning clearly

Structure your response to show your reasoning process.
"""

# Conversation / chat prompt
CONVERSATION_PROMPT = f"""{BASE_PERSONA}

You are having a conversation with the real estate agent. They may ask you:
- Questions about Maine real estate law or NAR policies
- Advice on handling specific situations
- Help with pricing or market comparisons
- General real estate best practices

If the agent gives you a task (like drafting something or scheduling), acknowledge it
and briefly explain what you'll do. Remember that consequential actions will go through an
approval process — you're proposing, not executing directly.

Be helpful, knowledgeable, and concise. If you're not sure about something,
say so.

"""


def get_email_triage_prompt() -> str:
    """Get the email triage system prompt."""
    return EMAIL_TRIAGE_PROMPT


def get_email_draft_prompt(
    sender_name: str | None = None,
    sender_role: str | None = None,
    thread_summary: str | None = None,
) -> str:
    """Get the email draft system prompt with optional context."""
    prompt = EMAIL_DRAFT_PROMPT

    if sender_name or sender_role or thread_summary:
        prompt += "\n\nContext for this response:"
        if sender_name:
            prompt += f"\n- Recipient: {sender_name}"
        if sender_role:
            prompt += f" ({sender_role})"
        if thread_summary:
            prompt += f"\n- Thread summary: {thread_summary}"

    return prompt


def get_conversation_prompt() -> str:
    """Get the conversation/chat system prompt."""
    return CONVERSATION_PROMPT


def with_reasoning(prompt: str) -> str:
    """Add reasoning suffix to a prompt."""
    return prompt + REASONING_SUFFIX


def augment_with_knowledge(prompt: str, n_results: int = 3) -> str:
    """Augment a prompt with relevant knowledge base context.

    Args:
        prompt: The user prompt or query
        n_results: Number of knowledge chunks to include

    Returns:
        Prompt with knowledge context prepended, or original if no relevant context
    """
    context = retrieve_context(prompt, n_results=n_results)

    if not context:
        return prompt

    return f"""Relevant information from your knowledge base:

{context}

---

{prompt}"""


def get_conversation_prompt_with_rag(user_message: str, n_results: int = 3) -> tuple[str, str]:
    """Get conversation prompt with RAG-augmented user message.

    Args:
        user_message: The user's message
        n_results: Number of knowledge chunks to include

    Returns:
        Tuple of (system_prompt, augmented_user_message)
    """
    system_prompt = CONVERSATION_PROMPT
    augmented_message = augment_with_knowledge(user_message, n_results)
    return system_prompt, augmented_message


def get_email_draft_prompt_with_rag(
    email_body: str,
    sender_name: str | None = None,
    sender_role: str | None = None,
    thread_summary: str | None = None,
    n_results: int = 3,
) -> tuple[str, str]:
    """Get email draft prompt with RAG context for the email content.

    Args:
        email_body: The original email body to respond to
        sender_name: Optional sender name
        sender_role: Optional sender role
        thread_summary: Optional thread summary
        n_results: Number of knowledge chunks to include

    Returns:
        Tuple of (system_prompt, knowledge_context)
    """
    # Get base draft prompt
    prompt = get_email_draft_prompt(sender_name, sender_role, thread_summary)

    # Get knowledge context relevant to the email content
    context = retrieve_context(email_body, n_results=n_results)

    if context:
        prompt += f"""

You have access to relevant information from the knowledge base:

{context}

Use this information to provide accurate, well-informed responses when applicable."""

    return prompt, context
