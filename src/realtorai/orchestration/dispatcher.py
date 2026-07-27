"""Task dispatcher - routes tasks to appropriate handlers."""

from typing import Any

import structlog

from realtorai.schemas.tasks import TaskType

logger = structlog.get_logger()


class Dispatcher:
    """Routes tasks and tool calls to appropriate handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}

    def register_handler(self, task_type: TaskType, handler: Any) -> None:
        """Register a handler for a task type."""
        self._handlers[task_type.value] = handler
        logger.debug("handler_registered", task_type=task_type.value)

    async def dispatch_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate handler.

        Tool calls from the LLM are routed here for execution.
        Most tool calls will create tasks that go through the approval loop
        rather than executing directly.
        """
        logger.info("dispatching_tool_call", tool=tool_name)

        if tool_name == "send_email":
            return await self._handle_send_email(arguments)
        elif tool_name == "schedule_event":
            return await self._handle_schedule_event(arguments)
        elif tool_name == "create_reminder":
            return await self._handle_create_reminder(arguments)
        elif tool_name == "update_client_notes":
            return await self._handle_update_client_notes(arguments)
        elif tool_name == "search_listings":
            return await self._handle_search_listings(arguments)
        elif tool_name == "get_listing_details":
            return await self._handle_get_listing_details(arguments)
        elif tool_name == "find_comps":
            return await self._handle_find_comps(arguments)
        elif tool_name == "get_market_stats":
            return await self._handle_get_market_stats(arguments)
        elif tool_name == "web_search":
            return await self._handle_web_search(arguments)
        elif tool_name == "create_client":
            return await self._handle_create_client(arguments)
        elif tool_name == "list_clients":
            return await self._handle_list_clients(arguments)
        elif tool_name == "read_client_profile":
            return await self._handle_read_client_profile(arguments)
        elif tool_name == "update_client_profile":
            return await self._handle_update_client_profile(arguments)
        elif tool_name == "add_pending_item":
            return await self._handle_add_pending_item(arguments)
        elif tool_name == "get_matterport_tour":
            return await self._handle_get_matterport_tour(arguments)
        elif tool_name == "list_matterport_models":
            return await self._handle_list_matterport_models(arguments)
        elif tool_name == "download_matterport_zip":
            return await self._handle_download_matterport_zip(arguments)
        elif tool_name == "update_mls_feeder":
            return await self._handle_update_mls_feeder(arguments)
        elif tool_name == "get_mls_feeder":
            return await self._handle_get_mls_feeder(arguments)
        else:
            logger.warning("unknown_tool", tool=tool_name)
            return {"error": f"Unknown tool: {tool_name}"}

    async def _handle_send_email(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle send_email tool call - creates an approval task."""
        from realtorai.orchestration.queue import task_queue

        task_id = await task_queue.add_custom_task(
            task_type=TaskType.EMAIL_RESPONSE,
            title=f"Send email to {args.get('to', 'unknown')}",
            summary=args.get("subject", "No subject"),
            details={
                "sender_email": args.get("to"),
                "subject": args.get("subject"),
            },
            proposal_data={
                "draft_response": {
                    "subject": args.get("subject"),
                    "body": args.get("body"),
                },
                "action": "send_email",
                "reply_to_id": args.get("reply_to_id"),
            },
        )

        return {
            "status": "queued",
            "task_id": task_id,
            "message": "Email queued for approval",
        }

    async def _handle_schedule_event(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle schedule_event tool call - creates an approval task."""
        from realtorai.orchestration.queue import task_queue

        task_id = await task_queue.add_custom_task(
            task_type=TaskType.CALENDAR_EVENT,
            title=args.get("title", "Calendar Event"),
            summary=f"{args.get('start_time', '')} - {args.get('location', 'No location')}",
            details={
                "location": args.get("location"),
                "attendees": args.get("attendees", []),
            },
            proposal_data={
                "title": args.get("title"),
                "start_time": args.get("start_time"),
                "end_time": args.get("end_time"),
                "location": args.get("location"),
                "attendees": args.get("attendees", []),
                "description": args.get("description"),
                "action": "create_event",
            },
        )

        return {
            "status": "queued",
            "task_id": task_id,
            "message": "Calendar event queued for approval",
        }

    async def _handle_create_reminder(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle create_reminder tool call - creates an approval task."""
        from realtorai.orchestration.queue import task_queue

        task_id = await task_queue.add_custom_task(
            task_type=TaskType.FOLLOWUP_REMINDER,
            title=args.get("title", "Reminder"),
            summary=f"Due: {args.get('due_date', 'No date')}",
            details={
                "related_contact": args.get("related_contact"),
                "related_transaction": args.get("related_transaction"),
            },
            proposal_data={
                "title": args.get("title"),
                "due_date": args.get("due_date"),
                "notes": args.get("notes"),
                "action": "create_reminder",
            },
            related_contact=args.get("related_contact"),
            related_transaction=args.get("related_transaction"),
        )

        return {
            "status": "queued",
            "task_id": task_id,
            "message": "Reminder queued for approval",
        }

    async def _handle_update_client_notes(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle update_client_notes tool call.

        This is a low-stakes action that could potentially auto-execute,
        but for Phase 1 we'll queue it for approval.
        """
        from realtorai.orchestration.queue import task_queue

        task_id = await task_queue.add_custom_task(
            task_type=TaskType.CUSTOM,
            title=f"Add note for {args.get('client_email', 'client')}",
            summary=args.get("note", "")[:50] + "...",
            details={
                "client_email": args.get("client_email"),
                "category": args.get("category", "general"),
            },
            proposal_data={
                "note": args.get("note"),
                "category": args.get("category", "general"),
                "action": "add_client_note",
            },
            related_contact=args.get("client_email"),
        )

        return {
            "status": "queued",
            "task_id": task_id,
            "message": "Client note queued for approval",
        }

    # MLS Tools - these execute directly (read-only operations)

    async def _handle_search_listings(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle search_listings tool call - executes directly."""
        from realtorai.integrations.spark import format_listing_summary, search_listings, spark_auth

        if not await spark_auth.is_connected():
            return {"error": "Spark API not connected. Please authenticate first."}

        try:
            results = await search_listings(
                city=args.get("city"),
                postal_code=args.get("postal_code"),
                min_price=args.get("min_price"),
                max_price=args.get("max_price"),
                min_beds=args.get("min_beds"),
                min_baths=args.get("min_baths"),
                property_type=args.get("property_type"),
                status=args.get("status", "Active"),
                limit=args.get("limit", 10),
            )

            if not results:
                return {
                    "status": "success",
                    "count": 0,
                    "listings": [],
                    "summary": "No listings found.",
                }

            summaries = [format_listing_summary(listing) for listing in results]
            return {
                "status": "success",
                "count": len(results),
                "listings": results,
                "summary": "\n\n".join(summaries),
            }
        except Exception as e:
            logger.error("search_listings_error", error=str(e))
            return {"error": str(e)}

    async def _handle_get_listing_details(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_listing_details tool call - executes directly."""
        from realtorai.integrations.spark import format_listing_summary, get_listing, spark_auth

        if not await spark_auth.is_connected():
            return {"error": "Spark API not connected. Please authenticate first."}

        listing_id = args.get("listing_id")
        if not listing_id:
            return {"error": "listing_id is required"}

        try:
            listing = await get_listing(listing_id)
            if not listing:
                return {"error": f"Listing {listing_id} not found"}

            return {
                "status": "success",
                "listing": listing,
                "summary": format_listing_summary(listing),
            }
        except Exception as e:
            logger.error("get_listing_error", listing_id=listing_id, error=str(e))
            return {"error": str(e)}

    async def _handle_find_comps(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle find_comps tool call - executes directly."""
        from realtorai.integrations.spark import find_comps, format_listing_summary, spark_auth

        if not await spark_auth.is_connected():
            return {"error": "Spark API not connected. Please authenticate first."}

        try:
            results = await find_comps(
                listing_id=args.get("listing_id"),
                city=args.get("city"),
                price=args.get("price"),
                beds=args.get("beds"),
                sqft=args.get("sqft"),
                limit=args.get("limit", 10),
            )

            if not results:
                return {
                    "status": "success",
                    "count": 0,
                    "comps": [],
                    "summary": "No comparable sales found.",
                }

            summaries = [format_listing_summary(listing) for listing in results]
            return {
                "status": "success",
                "count": len(results),
                "comps": results,
                "summary": "\n\n".join(summaries),
            }
        except Exception as e:
            logger.error("find_comps_error", error=str(e))
            return {"error": str(e)}

    async def _handle_get_market_stats(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_market_stats tool call - executes directly."""
        from realtorai.integrations.spark import get_market_stats, spark_auth

        if not await spark_auth.is_connected():
            return {"error": "Spark API not connected. Please authenticate first."}

        try:
            stats = await get_market_stats(
                city=args.get("city"),
                postal_code=args.get("postal_code"),
            )

            location = args.get("city") or args.get("postal_code") or "area"
            summary = (
                f"Market stats for {location}:\n"
                f"- Active listings: {stats['active_count']}\n"
                f"- Sold (last 30 days): {stats['sold_last_30_days']}\n"
                f"- Median list price: ${stats['median_list_price']:,}\n"
                f"- Median sold price: ${stats['median_sold_price']:,}"
            )

            return {
                "status": "success",
                "stats": stats,
                "summary": summary,
            }
        except Exception as e:
            logger.error("get_market_stats_error", error=str(e))
            return {"error": str(e)}


    # Web Search Tool - executes directly (read-only)

    async def _handle_web_search(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle web_search tool call - executes directly."""
        from realtorai.integrations.web import format_search_results, web_search

        query = args.get("query")
        if not query:
            return {"error": "query is required"}

        max_results = args.get("max_results", 5)

        try:
            results = web_search(query, max_results=max_results)

            if not results:
                return {
                    "status": "success",
                    "count": 0,
                    "results": [],
                    "summary": "No results found.",
                }

            return {
                "status": "success",
                "count": len(results),
                "results": results,
                "summary": format_search_results(results),
            }
        except Exception as e:
            logger.error("web_search_error", query=query, error=str(e))
            return {"error": str(e)}


    # Client Tools - execute directly (internal records)

    async def _handle_create_client(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle create_client tool call - executes directly."""
        from realtorai.storage.database import get_database

        name = args.get("name")
        if not name:
            return {"error": "name is required"}

        try:
            db = await get_database()
            client_id = await db.create_client(
                name=name,
                email=args.get("email"),
                phone=args.get("phone"),
                transaction_type=args.get("transaction_type"),
                property_address=args.get("property_address"),
                price=args.get("price"),
            )

            client = await db.get_client(client_id)
            return {
                "status": "success",
                "client_id": client_id,
                "message": f"Created client '{name}'",
                "file_path": client.get("file_path"),
            }
        except Exception as e:
            logger.error("create_client_error", error=str(e))
            return {"error": str(e)}

    async def _handle_list_clients(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle list_clients tool call - executes directly."""
        from realtorai.storage.database import get_database

        try:
            db = await get_database()
            clients = await db.get_clients(
                status=args.get("status"),
                limit=args.get("limit", 20),
            )

            if not clients:
                return {
                    "status": "success",
                    "count": 0,
                    "clients": [],
                    "summary": "No clients found.",
                }

            summaries = []
            for c in clients:
                tx = c.get("transaction_type", "").title() or "—"
                status = c.get("status", "").replace("_", " ").title() or "—"
                summaries.append(f"- {c['name']} (ID: {c['id']}) — {tx}, {status}")

            return {
                "status": "success",
                "count": len(clients),
                "clients": clients,
                "summary": "\n".join(summaries),
            }
        except Exception as e:
            logger.error("list_clients_error", error=str(e))
            return {"error": str(e)}

    async def _handle_read_client_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle read_client_profile tool call - executes directly."""
        from realtorai.storage.client_files import read_client_file
        from realtorai.storage.database import get_database

        client_id = args.get("client_id")
        client_name = args.get("client_name")

        try:
            db = await get_database()

            # Find client by ID or name
            if client_id:
                client = await db.get_client(client_id)
            elif client_name:
                results = await db.search_clients(client_name, limit=1)
                client = results[0] if results else None
            else:
                return {"error": "Either client_id or client_name is required"}

            if not client:
                return {"error": "Client not found"}

            content = read_client_file(client["id"], client["name"])
            if content is None:
                return {"error": f"Profile file not found for client {client['name']}"}

            return {
                "status": "success",
                "client_id": client["id"],
                "name": client["name"],
                "profile": content,
            }
        except Exception as e:
            logger.error("read_client_profile_error", error=str(e))
            return {"error": str(e)}

    async def _handle_update_client_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle update_client_profile tool call - executes directly."""
        from realtorai.storage.client_files import append_note, update_client_header
        from realtorai.storage.database import get_database

        client_id = args.get("client_id")
        if not client_id:
            return {"error": "client_id is required"}

        try:
            db = await get_database()
            client = await db.get_client(client_id)
            if not client:
                return {"error": f"Client {client_id} not found"}

            updates_made = []

            # Add note if provided
            note = args.get("note")
            if note:
                append_note(client_id, client["name"], note, source="llm")
                await db.add_client_note(client_id, note, source="llm")
                updates_made.append("added note")

            # Update header fields if provided
            header_updates = {}
            if args.get("status"):
                header_updates["status"] = args["status"]
            if args.get("property_address"):
                header_updates["property_address"] = args["property_address"]
            if args.get("price"):
                header_updates["price"] = args["price"]

            if header_updates:
                update_client_header(client_id, client["name"], **header_updates)
                await db.update_client(client_id, **header_updates)
                updates_made.append(f"updated {', '.join(header_updates.keys())}")

            if not updates_made:
                return {"status": "success", "message": "No updates provided"}

            return {
                "status": "success",
                "client_id": client_id,
                "message": f"Profile updated: {'; '.join(updates_made)}",
            }
        except Exception as e:
            logger.error("update_client_profile_error", error=str(e))
            return {"error": str(e)}

    async def _handle_add_pending_item(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle add_pending_item tool call - executes directly."""
        from realtorai.storage.client_files import add_pending_item
        from realtorai.storage.database import get_database

        client_id = args.get("client_id")
        description = args.get("description")
        waiting_on = args.get("waiting_on")

        if not client_id:
            return {"error": "client_id is required"}
        if not description:
            return {"error": "description is required"}
        if not waiting_on:
            return {"error": "waiting_on is required"}

        try:
            db = await get_database()
            client = await db.get_client(client_id)
            if not client:
                return {"error": f"Client {client_id} not found"}

            # Add to database
            item_id = await db.create_pending_item(
                client_id=client_id,
                item_type="document",
                description=description,
                waiting_on=waiting_on,
                due_date=args.get("due_date"),
            )

            # Add to markdown file
            add_pending_item(client_id, client["name"], description, waiting_on)

            return {
                "status": "success",
                "item_id": item_id,
                "message": f"Added pending item: {description} (waiting on {waiting_on})",
            }
        except Exception as e:
            logger.error("add_pending_item_error", error=str(e))
            return {"error": str(e)}

    # Matterport Tools - execute directly (read-only + file operations)

    async def _handle_get_matterport_tour(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_matterport_tour tool call - downloads tour to client folder."""
        from realtorai.integrations.matterport import download_tour_assets, matterport_auth
        from realtorai.storage.database import get_database

        client_id = args.get("client_id")
        model_id = args.get("model_id")

        if not client_id:
            return {"error": "client_id is required"}
        if not model_id:
            return {"error": "model_id is required"}

        if not await matterport_auth.is_connected():
            return {"error": "Matterport API not connected. Please configure credentials first."}

        try:
            # Get client name for folder path
            db = await get_database()
            client = await db.get_client(client_id)
            if not client:
                return {"error": f"Client {client_id} not found"}

            result = await download_tour_assets(
                client_id=client_id,
                client_name=client["name"],
                model_id=model_id,
                max_images=args.get("max_images", 9999),
            )

            if result.get("status") == "error":
                return result

            return {
                "status": "success",
                "client_id": client_id,
                "model_id": model_id,
                "matterport_dir": result.get("matterport_dir"),
                "images_downloaded": result.get("images_downloaded"),
                "embed_url": result.get("embed_url"),
                "summary": (
                    f"Downloaded Matterport tour '{result.get('model_name', model_id)}' "
                    f"with {result.get('images_downloaded', 0)} images "
                    f"to {result.get('matterport_dir')}"
                ),
            }
        except Exception as e:
            logger.error("get_matterport_tour_error", client_id=client_id, error=str(e))
            return {"error": str(e)}

    async def _handle_list_matterport_models(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle list_matterport_models tool call - lists available tours."""
        from realtorai.integrations.matterport import list_models, matterport_auth
        from realtorai.integrations.matterport.models import format_model_summary

        if not await matterport_auth.is_connected():
            return {"error": "Matterport API not connected. Please configure credentials first."}

        try:
            limit = args.get("limit", 50)
            models = await list_models(limit=limit)

            if not models:
                return {
                    "status": "success",
                    "count": 0,
                    "models": [],
                    "summary": "No Matterport models found.",
                }

            summaries = [format_model_summary(m) for m in models]
            return {
                "status": "success",
                "count": len(models),
                "models": models,
                "summary": "\n".join(summaries),
            }
        except Exception as e:
            logger.error("list_matterport_models_error", error=str(e))
            return {"error": str(e)}

    async def _handle_download_matterport_zip(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle download_matterport_zip tool call - downloads zip from email link."""
        from realtorai.integrations.matterport import (
            download_and_extract_zip,
            extract_download_url,
        )
        from realtorai.storage.database import get_database

        client_id = args.get("client_id")
        if not client_id:
            return {"error": "client_id is required"}

        try:
            # Get client name for folder path
            db = await get_database()
            client = await db.get_client(client_id)
            if not client:
                return {"error": f"Client {client_id} not found"}

            # Get download URL from args or extract from email body
            download_url = args.get("download_url")
            email_body = args.get("email_body")

            if not download_url and email_body:
                download_url = extract_download_url(email_body)

            if not download_url:
                return {"error": "No download URL provided or found in email body"}

            # Download and extract
            result = await download_and_extract_zip(
                url=download_url,
                client_id=client_id,
                client_name=client["name"],
            )

            if result.get("status") == "error":
                return result

            return {
                "status": "success",
                "client_id": client_id,
                "matterport_dir": result.get("matterport_dir"),
                "files_extracted": result.get("files_extracted"),
                "images_count": result.get("images_count"),
                "models_count": result.get("models_count"),
                "summary": (
                    f"Downloaded Matterport assets for {client['name']}: "
                    f"{result.get('files_extracted', 0)} files extracted "
                    f"({result.get('images_count', 0)} images, "
                    f"{result.get('models_count', 0)} 3D models)"
                ),
            }
        except Exception as e:
            logger.error("download_matterport_zip_error", client_id=client_id, error=str(e))
            return {"error": str(e)}

    # MLS Feeder Tools

    async def _handle_update_mls_feeder(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle update_mls_feeder tool call - updates listing data."""
        from realtorai.integrations.spark.mls_feeder import (
            format_feeder_summary,
            get_feeder_completeness,
            update_mls_feeder,
        )
        from realtorai.storage.database import get_database

        client_id = args.get("client_id")
        if not client_id:
            return {"error": "client_id is required"}

        try:
            db = await get_database()
            client = await db.get_client(client_id)
            if not client:
                return {"error": f"Client {client_id} not found"}

            # Build updates dict from args
            updates = {}
            for key in ["address", "property", "listing", "marketing", "features"]:
                if args.get(key):
                    updates[key] = args[key]

            if not updates:
                return {"error": "No update fields provided"}

            source = args.get("source", "conversation")

            feeder = update_mls_feeder(
                client_id=client_id,
                name=client["name"],
                updates=updates,
                source=source,
            )

            completeness = get_feeder_completeness(feeder)

            return {
                "status": "success",
                "client_id": client_id,
                "feeder_status": feeder.get("status"),
                "completeness_pct": completeness["completeness_pct"],
                "missing_fields": completeness["missing_fields"],
                "summary": format_feeder_summary(feeder),
            }
        except Exception as e:
            logger.error("update_mls_feeder_error", client_id=client_id, error=str(e))
            return {"error": str(e)}

    async def _handle_get_mls_feeder(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_mls_feeder tool call - retrieves feeder status."""
        from realtorai.integrations.spark.mls_feeder import (
            format_feeder_summary,
            get_feeder_completeness,
            get_mls_feeder,
        )
        from realtorai.storage.database import get_database

        client_id = args.get("client_id")
        if not client_id:
            return {"error": "client_id is required"}

        try:
            db = await get_database()
            client = await db.get_client(client_id)
            if not client:
                return {"error": f"Client {client_id} not found"}

            feeder = get_mls_feeder(client_id, client["name"])

            if feeder is None:
                return {
                    "status": "success",
                    "has_feeder": False,
                    "message": "No MLS feeder exists yet for this client. "
                    "Use update_mls_feeder to start collecting listing data.",
                }

            completeness = get_feeder_completeness(feeder)

            return {
                "status": "success",
                "has_feeder": True,
                "client_id": client_id,
                "feeder_status": feeder.get("status"),
                "completeness_pct": completeness["completeness_pct"],
                "missing_fields": completeness["missing_fields"],
                "feeder": feeder,
                "summary": format_feeder_summary(feeder),
            }
        except Exception as e:
            logger.error("get_mls_feeder_error", client_id=client_id, error=str(e))
            return {"error": str(e)}


# Default instance
dispatcher = Dispatcher()
