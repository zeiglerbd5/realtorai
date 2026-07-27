"""Email agent for triage and response drafting."""

from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

from realtorai.agents.base import Agent
from realtorai.inference.extraction import create_extraction_proposals
from realtorai.inference.prompts import (
    get_email_draft_prompt_with_rag,
    get_email_triage_prompt,
    with_reasoning,
)
from realtorai.inference.tools import EMAIL_AGENT_TOOLS
from realtorai.integrations.graph.email import format_email_for_display, get_email_thread
from realtorai.orchestration.queue import task_queue
from realtorai.schemas.common import ChainOfReasoning, ReasoningStep
from realtorai.schemas.email import DraftResponse, EmailClassification, EmailIntent, EmailProposal
from realtorai.storage.database import get_database

logger = structlog.get_logger()


class KnowledgeQuery(BaseModel):
    """One targeted knowledge-base search the reply should draw on."""

    query: str
    kind: Literal["legal", "templates", "policies"] | None = Field(
        default=None, description="Restrict to one source kind, or search all"
    )


class RetrievalPlan(BaseModel):
    """What the reply needs from the knowledge base (0-3 searches)."""

    queries: list[KnowledgeQuery] = Field(default_factory=list)


RETRIEVAL_PLAN_SYSTEM = """You plan knowledge retrieval for a Maine real-estate \
email assistant drafting a reply. Read the inbound email and decide what the \
REPLY needs from the knowledge base — not what the email mentions. Choose 0-3 \
targeted queries: kind "legal" for Maine license law / Commission rules / NAR \
ethics, "templates" for the team's email templates (e.g. the inspection- \
scheduling or disclosure-request template), "policies" for office procedure. \
Day-to-day drafting leans on "templates" and "policies" — reach for "legal" \
ONLY when the email raises an actual legal or compliance question (agency \
relationships, disclosures, license law), not merely because a transaction \
is underway. Return an empty list when the reply needs no reference \
material — most routine emails need none."""


async def _plan_and_retrieve(email_body: str) -> str | None:
    """Claude-planned retrieval: formulate targeted queries, then search.

    Returns formatted knowledge context, or None to fall back to the
    default body-as-query retrieval (offline mode or on any failure).
    """
    from realtorai.inference.claude_engine import get_claude_engine
    from realtorai.inference.model_router import LLMTask

    claude = get_claude_engine()
    if not claude.available:
        return None
    try:
        plan = await claude.generate_structured(
            f"Inbound email:\n{email_body}\n\nWhat should the reply draw on?",
            RetrievalPlan,
            task=LLMTask.CLASSIFY,
            system_prompt=RETRIEVAL_PLAN_SYSTEM,
            max_tokens=3000,
        )
        if not plan.queries:
            return ""  # deliberate: reply needs no reference material
        from realtorai.rag.retrieval import search_knowledge

        parts = []
        for q in plan.queries[:3]:
            hit = search_knowledge(q.query, kind=q.kind, n_results=2)
            if hit and not hit.startswith("No knowledge"):
                parts.append(hit)
        logger.info(
            "retrieval_planned",
            queries=[q.query for q in plan.queries[:3]],
            hits=len(parts),
        )
        return "\n---\n".join(parts)
    except Exception as e:
        logger.warning("retrieval_plan_failed", error=str(e))
        return None


# Documents that gate providing real estate services (Maine requirement)
GATING_DOCUMENTS = [
    "buyer agency agreement",
    "buyer agency",
    "buyer agreement",
    "client agreement",
    "agency agreement",
    "representation agreement",
]


async def get_client_pending_context(client: dict) -> dict[str, Any]:
    """Get pending items context for a client.

    Returns dict with:
    - has_gating_document: bool - whether client has signed required agreement
    - gating_item: dict | None - the pending gating document if not signed
    - pending_items: list - all pending items for context
    """
    db = await get_database()
    pending_items = await db.get_pending_items(client_id=client["id"], status="waiting")

    # Check for gating documents (buyer/client agency agreement)
    gating_item = None
    for item in pending_items:
        desc_lower = item["description"].lower()
        if any(gating in desc_lower for gating in GATING_DOCUMENTS):
            gating_item = item
            break

    return {
        "has_gating_document": gating_item is None,  # True if no gating doc is pending
        "gating_item": gating_item,
        "pending_items": pending_items,
    }


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
        client: dict | None = None,
    ) -> DraftResponse:
        """Generate a draft response to an email.

        Args:
            email: Original email object
            classification: Classification of the email
            thread_context: Optional summary of thread history
            client: Optional client record if sender is a known client

        Returns:
            DraftResponse with subject and body
        """
        formatted = format_email_for_display(email)

        # Knowledge context: Claude plans targeted searches (what the REPLY
        # needs); offline falls back to body-as-query retrieval.
        planned_context = await _plan_and_retrieve(formatted["body"][:1500])
        draft_prompt, rag_context = get_email_draft_prompt_with_rag(
            email_body=formatted["body"][:1000],
            sender_name=formatted["from_name"],
            sender_role=classification.sender.role,
            thread_summary=thread_context,
            context_override=planned_context,
        )

        # Check for gating documents
        gating_context = ""
        if client:
            # Existing client - check their pending items for gating documents
            pending_context = await get_client_pending_context(client)
            if not pending_context["has_gating_document"]:
                gating_item = pending_context["gating_item"]
                gating_context = f"""
IMPORTANT: This client has NOT yet signed a required "{gating_item['description']}".
Under Maine real estate law, you CANNOT provide real estate advice, schedule showings,
or discuss specific properties until the client signs this agreement.

Your response MUST:
1. Politely explain that you need the signed Buyer Agency Agreement before you can help further
2. Offer to send the agreement if they don't have it
3. Do NOT discuss specific properties, schedule showings, or provide real estate advice yet

Once they sign and return the agreement, you can provide full services.
"""
                logger.info(
                    "gating_document_required",
                    client_id=client["id"],
                    gating_item=gating_item["description"],
                )
        else:
            # NEW LEAD - no client record yet. They definitely need to sign agreement first.
            # Check if this looks like a potential buyer/client inquiry
            body_lower = formatted["body"].lower()
            subject_lower = formatted.get("subject", "").lower()
            combined = f"{subject_lower} {body_lower}"

            buyer_signals = ["buy", "buying", "purchase", "looking for", "home", "house",
                           "property", "realtor", "agent", "represent", "help me find"]
            is_potential_client = any(signal in combined for signal in buyer_signals)

            if is_potential_client:
                gating_context = """
IMPORTANT: This is a NEW potential client who has NOT yet signed a Buyer Agency Agreement.
Under Maine real estate law, you CANNOT provide real estate advice, schedule showings,
or discuss specific properties until the client signs this agreement.

Your response MUST:
1. Welcome them warmly and thank them for reaching out
2. Explain that before you can work together, they need to sign a Buyer Agency Agreement
3. Offer to send the agreement and briefly explain what it covers \
(it establishes the working relationship)
4. You can mention general next steps (like getting pre-approved) but do NOT \
schedule showings or discuss specific properties yet
5. Keep it friendly and professional - this is standard practice, not a barrier

Do NOT skip the agreement requirement. This is legally required in Maine.
"""
                logger.info(
                    "new_lead_gating_required",
                    sender=formatted.get("from_email"),
                )

        # Build the prompt
        prompt = f"""Draft a response to this email.

Original email:
From: {formatted['from_name']} <{formatted['from_email']}>
Subject: {formatted['subject']}

{formatted['body'][:2000]}

Key points identified:
{chr(10).join('- ' + point for point in classification.key_points)}
{gating_context}
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
        await self.generate(prompt=prompt, temperature=0.5)

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
                    thought=(
                        "Response needed"
                        if classification.requires_response
                        else "No response needed"
                    ),
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
        from datetime import UTC, datetime

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

        # --- Look up client or lead early so we can use for both drafting and extraction ---
        db = await get_database()
        sender_email = formatted.get("from_email")
        sender_name = (
            formatted.get("from_name") or sender_email.split("@")[0] if sender_email else "Unknown"
        )
        client = None

        if sender_email:
            # First check for active client
            client = await db.find_client_by_email(sender_email)

            if not client:
                # Check for existing lead
                lead = await db.find_lead_by_email(sender_email)
                if lead:
                    # Treat lead as client for processing purposes
                    client = lead
                else:
                    # No client or lead - check if this looks like a buyer/seller inquiry
                    body_lower = formatted["body"].lower()
                    subject_lower = formatted.get("subject", "").lower()
                    combined = f"{subject_lower} {body_lower}"

                    buyer_signals = ["buy", "buying", "purchase", "looking for", "find a home",
                                   "house", "property", "realtor", "agent", "represent"]
                    seller_signals = ["sell", "selling", "list my", "listing"]

                    is_buyer_inquiry = any(signal in combined for signal in buyer_signals)
                    is_seller_inquiry = any(signal in combined for signal in seller_signals)

                    if is_buyer_inquiry or is_seller_inquiry:
                        # Create a new lead
                        tx_type = "sell" if is_seller_inquiry and not is_buyer_inquiry else "buy"
                        lead_id = await db.create_lead(
                            name=sender_name,
                            email=sender_email,
                            transaction_type=tx_type,
                        )
                        # Add the required agency agreement as pending item
                        await db.add_standard_lead_pending_items(lead_id, tx_type)

                        # Fetch the lead we just created
                        client = await db.find_lead_by_email(sender_email)

                        logger.info(
                            "new_lead_created_from_email",
                            lead_id=lead_id,
                            name=sender_name,
                            email=sender_email,
                            transaction_type=tx_type,
                        )

        # Generate draft if response is needed (pass client for gating document check)
        draft = None
        if classification.requires_response:
            draft = await self.draft_response(email, classification, thread_context, client)

        # Generate reasoning
        reasoning = await self.generate_reasoning(email, classification, draft)

        # --- Data Extraction (Queued for Approval) ---
        # Try to extract structured data if sender is a known client
        # Instead of auto-applying, create proposals for the approval queue
        extraction_proposals = []
        try:
            if client:
                # Determine representation
                representation = None
                tx_type = client.get("transaction_type", "").lower()
                if "buy" in tx_type:
                    representation = "buyer"
                elif "sell" in tx_type:
                    representation = "seller"

                # Create extraction proposals (does NOT apply data)
                proposals = await create_extraction_proposals(
                    client_id=client["id"],
                    name=client["name"],
                    email_content=formatted["body"],
                    email_subject=formatted.get("subject"),
                    sender=f"{formatted.get('from_name')} <{sender_email}>",
                    representation=representation,
                )

                # Queue each proposal for approval
                for proposal in proposals:
                    task_id = await task_queue.add_extraction_task(
                        proposal=proposal,
                        email_id=email.get("id"),
                    )
                    extraction_proposals.append({
                        "task_id": task_id,
                        "type": proposal.extraction_type.value,
                        "changes": len(proposal.changes),
                    })

                if proposals:
                    logger.info(
                        "extraction_proposals_queued",
                        email_id=email.get("id"),
                        client_id=client["id"],
                        proposal_count=len(proposals),
                    )

                # --- Document-type emails: Check for signed agreements ---
                # Check if email mentions sending/attaching a document
                # Don't rely solely on intent classification - check content too
                body_lower = formatted["body"].lower()
                has_attachment_mention = any(kw in body_lower for kw in [
                    "attached", "attaching", "attachment", "enclosed",
                    "here is the", "here's the", "sending the", "find attached",
                    "see attached", "letter attached", "document attached",
                ])

                if classification.intent == EmailIntent.DOCUMENT or has_attachment_mention:
                    await self._process_document_email(
                        email=email,
                        client=client,
                        formatted=formatted,
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
                email.get("receivedDateTime", datetime.now(UTC).replace(tzinfo=None).isoformat())
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
            extraction_proposals_queued=len(extraction_proposals),
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

    async def _process_document_email(
        self,
        email: dict[str, Any],
        client: dict,
        formatted: dict[str, Any],
    ) -> None:
        """Process a document-type email to check for signed agreements.

        When a client sends an email with intent=document, check if it mentions
        signing/returning a document that matches a pending item. If so, create
        a task to resolve that pending item.

        Args:
            email: Original email object
            client: Client record
            formatted: Formatted email data
        """
        db = await get_database()

        # Get pending items for this client
        pending_items = await db.get_pending_items(client_id=client["id"], status="waiting")
        if not pending_items:
            return

        # Keywords that indicate a document is being sent/returned
        sent_keywords = [
            "attached", "attaching", "sending", "here is", "here's",
            "signed", "returning", "enclosed", "see attached",
            "find attached", "please find", "i've attached", "i have attached",
        ]

        body_lower = formatted["body"].lower()
        subject_lower = formatted.get("subject", "").lower()
        combined_text = f"{subject_lower} {body_lower}"

        # Check if email indicates document is being sent
        is_sending_doc = any(kw in combined_text for kw in sent_keywords)
        if not is_sending_doc:
            return

        # Document patterns to match against pending items
        document_patterns = {
            "pre-approval": ["pre-approval", "preapproval", "pre approval", "loan approval"],
            "buyer agency agreement": [
                "buyer agency", "agency agreement", "client agreement", "representation"
            ],
            "proof of funds": ["proof of funds", "pof", "bank statement", "funds verification"],
            "inspection report": ["inspection report", "inspection", "home inspection"],
            "appraisal": ["appraisal", "appraisal report"],
            "closing disclosure": ["closing disclosure", "cd", "settlement statement"],
            "purchase agreement": ["purchase agreement", "p&s", "purchase and sale", "contract"],
        }

        matched_items = []
        for item in pending_items:
            item_desc_lower = item["description"].lower()

            # Check if any document pattern matches both the email and the pending item
            for doc_type, patterns in document_patterns.items():
                # Check if email mentions this document type
                email_mentions = any(p in combined_text for p in patterns)
                # Check if pending item is about this document type
                item_matches = any(p in item_desc_lower for p in patterns)

                if email_mentions and item_matches:
                    matched_items.append(item)
                    break

        if not matched_items:
            return

        # Create a document received task for each matched item
        for item in matched_items:
            # Create a task to resolve this pending item
            task_id = await task_queue.add_document_received_task(
                client_id=client["id"],
                client_name=client["name"],
                pending_item=item,
                email_id=email.get("id"),
                email_subject=formatted.get("subject"),
                email_snippet=formatted["body"][:300],
            )

            logger.info(
                "document_received_task_created",
                task_id=task_id,
                client_id=client["id"],
                pending_item_id=item["id"],
                pending_item_desc=item["description"],
            )


# Default instance
email_agent = EmailAgent()
