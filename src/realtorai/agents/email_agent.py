"""Email agent for triage and response drafting."""

from typing import Any

import structlog

from realtorai.agents.base import Agent
from realtorai.inference.prompts import (
    get_email_draft_prompt_with_rag,
    get_email_triage_prompt,
    with_reasoning,
)
from realtorai.inference.tools import EMAIL_AGENT_TOOLS
from realtorai.inference.extraction import extract_from_email
from realtorai.integrations.graph.email import format_email_for_display, get_email_thread
from realtorai.schemas.common import ChainOfReasoning, Confidence, ReasoningStep
from realtorai.schemas.email import DraftResponse, EmailClassification, EmailProposal
from realtorai.storage.database import get_database

logger = structlog.get_logger()


class EmailAgent(Agent):
    """Agent specialized for email triage and response drafting.

    Responsibilities:
    - Classify incoming emails (sender, intent, priority, etc.)
    - Generate draft responses
    - Produce reasoning chains explaining decisions
    """

    @property
    def name(self) -> str:
        return "Email Agent"

    @property
    def system_prompt(self) -> str:
        return get_email_triage_prompt()

    @property
    def tools(self) -> list[dict[str, Any]]:
        return EMAIL_AGENT_TOOLS

    async def classify_email(self, email: dict[str, Any]) -> EmailClassification:
        """Classify an incoming email.

        Args:
            email: Email object from Graph API

        Returns:
            EmailClassification with sender, intent, priority, etc.
        """
        formatted = format_email_for_display(email)

        prompt = f"""Analyze this email and classify it.

From: {formatted['from_name']} <{formatted['from_email']}>
Subject: {formatted['subject']}
Received: {formatted['received_at']}

Body:
{formatted['body'][:2000]}  # Truncate very long emails

Classify this email according to the schema."""

        classification = await self.generate_structured(
            prompt=prompt,
            output_schema=EmailClassification,
        )

        logger.info(
            "email_classified",
            email_id=email.get("id"),
            intent=classification.intent.value,
            priority=classification.priority.value,
            requires_response=classification.requires_response,
        )

        return classification

    async def draft_response(
        self,
        email: dict[str, Any],
        classification: EmailClassification,
        thread_context: str | None = None,
    ) -> DraftResponse:
        """Generate a draft response to an email.

        Args:
            email: Original email object
            classification: Classification of the email
            thread_context: Optional summary of thread history

        Returns:
            DraftResponse with subject and body
        """
        formatted = format_email_for_display(email)

        # Get RAG-augmented draft prompt with knowledge context
        # The email body is used to retrieve relevant knowledge
        draft_prompt, rag_context = get_email_draft_prompt_with_rag(
            email_body=formatted["body"][:1000],
            sender_name=formatted["from_name"],
            sender_role=classification.sender.role,
            thread_summary=thread_context,
        )

        # Build the prompt
        prompt = f"""Draft a response to this email.

Original email:
From: {formatted['from_name']} <{formatted['from_email']}>
Subject: {formatted['subject']}

{formatted['body'][:2000]}

Key points identified:
{chr(10).join('- ' + point for point in classification.key_points)}

Draft an appropriate response."""

        # Use the draft system prompt (with RAG context included)
        engine = await self.get_engine()
        draft = await engine.generate_structured(
            prompt=prompt,
            output_schema=DraftResponse,
            system_prompt=draft_prompt,
        )

        logger.info(
            "draft_generated",
            email_id=email.get("id"),
            subject=draft.subject[:50],
            rag_context_used=bool(rag_context),
        )

        return draft

    async def generate_reasoning(
        self,
        email: dict[str, Any],
        classification: EmailClassification,
        draft: DraftResponse | None,
    ) -> ChainOfReasoning:
        """Generate a chain-of-reasoning explanation for the proposed action.

        Args:
            email: Original email
            classification: Email classification
            draft: Draft response if applicable

        Returns:
            ChainOfReasoning explaining the decision
        """
        formatted = format_email_for_display(email)

        prompt = f"""Explain your reasoning for how to handle this email.

Email from: {formatted['from_name']} <{formatted['from_email']}>
Subject: {formatted['subject']}

You classified this as:
- Intent: {classification.intent.value}
- Priority: {classification.priority.value}
- Requires response: {classification.requires_response}

{"You drafted a response." if draft else "You determined no response is needed."}

Walk through your reasoning step by step."""

        prompt = with_reasoning(prompt)

        # Generate reasoning (free-form, then structure it)
        reasoning_text = await self.generate(prompt=prompt, temperature=0.5)

        # For now, create a simple reasoning chain
        # In the future, we could have the model output structured reasoning directly
        reasoning = ChainOfReasoning(
            steps=[
                ReasoningStep(
                    step=1,
                    thought=f"Identified sender as {classification.sender.role or 'unknown role'}",
                    observation=f"Email from {formatted['from_email']}",
                ),
                ReasoningStep(
                    step=2,
                    thought=f"Classified intent as {classification.intent.value}",
                    observation=f"Priority: {classification.priority.value}",
                ),
                ReasoningStep(
                    step=3,
                    thought="Response needed" if classification.requires_response else "No response needed",
                    observation=classification.subject_summary,
                ),
            ],
            conclusion=f"{'Draft response for approval' if draft else 'No action needed'}",
            confidence=classification.confidence,
        )

        return reasoning

    async def process_email(self, email: dict[str, Any]) -> EmailProposal:
        """Process an email end-to-end: classify, draft response, generate reasoning.

        Also extracts structured data (MLS feeder, transaction tracker) if the
        sender is a known client.

        Args:
            email: Email object from Graph API

        Returns:
            Complete EmailProposal for the approval queue
        """
        from datetime import datetime

        formatted = format_email_for_display(email)

        # Get thread context if this is part of a conversation
        thread_context = None
        conversation_id = email.get("conversationId")
        if conversation_id:
            try:
                thread = await get_email_thread(conversation_id)
                if len(thread) > 1:
                    # Summarize thread (excluding current email)
                    thread_emails = [e for e in thread if e.get("id") != email.get("id")]
                    thread_context = self._summarize_thread(thread_emails)
            except Exception:
                # Thread fetching often fails on consumer accounts - expected behavior
                logger.debug("thread_context_unavailable", conversation_id=conversation_id)

        # Classify the email
        classification = await self.classify_email(email)

        # Generate draft if response is needed
        draft = None
        if classification.requires_response:
            draft = await self.draft_response(email, classification, thread_context)

        # Generate reasoning
        reasoning = await self.generate_reasoning(email, classification, draft)

        # --- Data Extraction ---
        # Try to extract structured data if sender is a known client
        extraction_result = None
        try:
            db = await get_database()
            sender_email = formatted.get("from_email")
            if sender_email:
                client = await db.find_client_by_email(sender_email)
                if client:
                    # Extract MLS feeder and transaction data
                    representation = None
                    tx_type = client.get("transaction_type", "").lower()
                    if "buy" in tx_type:
                        representation = "buyer"
                    elif "sell" in tx_type:
                        representation = "seller"

                    extraction_result = await extract_from_email(
                        client_id=client["id"],
                        name=client["name"],
                        email_content=formatted["body"],
                        email_subject=formatted.get("subject"),
                        sender=f"{formatted.get('from_name')} <{sender_email}>",
                        representation=representation,
                    )

                    logger.info(
                        "email_data_extracted",
                        email_id=email.get("id"),
                        client_id=client["id"],
                        data_type=extraction_result.get("classification", {}).get("data_type"),
                    )
        except Exception as e:
            # Extraction failures shouldn't block email processing
            logger.warning("extraction_failed", error=str(e))

        # Determine proposed action
        if draft:
            proposed_action = "Send reply"
        elif classification.priority in ("critical", "high"):
            proposed_action = "Review manually"
        else:
            proposed_action = "Archive (no action needed)"

        # Build proposal
        proposal = EmailProposal(
            email_id=email.get("id", ""),
            thread_id=conversation_id,
            received_at=datetime.fromisoformat(
                email.get("receivedDateTime", datetime.utcnow().isoformat())
            ),
            classification=classification,
            reasoning=reasoning,
            proposed_action=proposed_action,
            draft_response=draft,
            thread_summary=thread_context,
        )

        logger.info(
            "email_processed",
            email_id=email.get("id"),
            proposed_action=proposed_action,
            data_extracted=extraction_result is not None,
        )

        return proposal

    def _summarize_thread(self, emails: list[dict[str, Any]]) -> str:
        """Create a brief summary of thread history.

        For now, just list senders and subjects. In the future, we could
        use the LLM to summarize the conversation.
        """
        summaries = []
        for email in emails[-5:]:  # Last 5 messages
            formatted = format_email_for_display(email)
            summaries.append(
                f"- {formatted['from_name'] or formatted['from_email']}: "
                f"{formatted['preview'][:100]}"
            )
        return "\n".join(summaries)


# Default instance
email_agent = EmailAgent()
