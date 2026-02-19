"""Microsoft Graph API OAuth 2.0 authentication."""

import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import msal
import structlog


from realtorai.config.settings import get_settings

from realtorai.integrations.base import Integration
from realtorai.storage.keychain import KeychainKeys, keychain

logger = structlog.get_logger()

# Microsoft Graph scopes needed for email and calendar
SCOPES = [
    "User.Read",
    "Mail.Read",
    "Mail.Send",
    "Calendars.ReadWrite",
]

# OAuth redirect URI - we use localhost for desktop flow
REDIRECT_URI = "http://localhost:8421/callback"


class GraphAuth(Integration):
    """Microsoft Graph API authentication via OAuth 2.0.

    Uses MSAL (Microsoft Authentication Library) with device code flow
    or localhost redirect for user authentication.

    Tokens are stored securely in macOS Keychain.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._app: msal.PublicClientApplication | None = None
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

    @property
    def name(self) -> str:
        return "Microsoft Graph"

    async def is_configured(self) -> bool:
        """Check if Graph API credentials are configured."""
        return bool(self.settings.graph_client_id)

    async def is_connected(self) -> bool:
        """Check if we have a valid access token."""
        if not self._access_token:
            # Try to load from keychain
            await self._load_tokens()

        if not self._access_token:
            return False

        # Check if token is expired
        if self._token_expiry and datetime.utcnow() >= self._token_expiry:
            # Try to refresh
            return await self._refresh_token()

        return True

    async def connect(self) -> bool:
        """Initiate OAuth flow to get access token."""
        if not await self.is_configured():
            logger.error("graph_not_configured")
            return False

        # Try to refresh existing token first
        if await self._load_tokens() and await self._refresh_token():
            return True

        # Need fresh authentication
        return await self._authenticate()

    async def disconnect(self) -> None:
        """Clear stored tokens."""
        keychain.delete(KeychainKeys.GRAPH_ACCESS_TOKEN)
        keychain.delete(KeychainKeys.GRAPH_REFRESH_TOKEN)
        keychain.delete(KeychainKeys.GRAPH_TOKEN_EXPIRY)
        self._access_token = None
        self._token_expiry = None
        logger.info("graph_disconnected")

    async def get_access_token(self) -> str | None:
        """Get a valid access token, refreshing if necessary."""
        if not await self.is_connected():
            return None
        return self._access_token

    def _get_app(self) -> msal.PublicClientApplication:
        """Get or create MSAL application."""
        if not self._app:
            self._app = msal.PublicClientApplication(
                client_id=self.settings.graph_client_id,
                authority=f"https://login.microsoftonline.com/{self.settings.graph_tenant_id}",
            )
        return self._app

    async def _load_tokens(self) -> bool:
        """Load tokens from keychain."""
        access_token = keychain.get(KeychainKeys.GRAPH_ACCESS_TOKEN)
        refresh_token = keychain.get(KeychainKeys.GRAPH_REFRESH_TOKEN)
        expiry_str = keychain.get(KeychainKeys.GRAPH_TOKEN_EXPIRY)

        if access_token and expiry_str:
            self._access_token = access_token
            try:
                self._token_expiry = datetime.fromisoformat(expiry_str)
            except ValueError:
                self._token_expiry = None

            logger.debug("tokens_loaded_from_keychain")
            return True

        return False

    def _save_tokens(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        """Save tokens to keychain."""
        expiry = datetime.utcnow() + timedelta(seconds=expires_in - 300)  # 5 min buffer

        keychain.set(KeychainKeys.GRAPH_ACCESS_TOKEN, access_token)
        keychain.set(KeychainKeys.GRAPH_REFRESH_TOKEN, refresh_token)
        keychain.set(KeychainKeys.GRAPH_TOKEN_EXPIRY, expiry.isoformat())

        self._access_token = access_token
        self._token_expiry = expiry

        logger.debug("tokens_saved_to_keychain")

    async def _refresh_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        refresh_token = keychain.get(KeychainKeys.GRAPH_REFRESH_TOKEN)
        if not refresh_token:
            return False

        app = self._get_app()

        try:
            # MSAL doesn't have a direct refresh method for public clients,
            # but we can use acquire_token_by_refresh_token
            result = app.acquire_token_by_refresh_token(
                refresh_token=refresh_token,
                scopes=SCOPES,
            )

            if "access_token" in result:
                self._save_tokens(
                    access_token=result["access_token"],
                    refresh_token=result.get("refresh_token", refresh_token),
                    expires_in=result.get("expires_in", 3600),
                )
                logger.info("graph_token_refreshed")
                return True
            else:
                logger.warning("graph_refresh_failed", error=result.get("error_description"))
                return False

        except Exception as e:
            logger.error("graph_refresh_error", error=str(e))
            return False

    async def _authenticate(self) -> bool:
        """Perform interactive OAuth authentication."""
        app = self._get_app()

        # Use interactive flow with localhost redirect
        logger.info("starting_graph_auth")

        # Start local server to receive callback
        auth_code = await self._get_auth_code_interactive(app)

        if not auth_code:
            logger.error("graph_auth_no_code")
            return False

        # Exchange code for tokens
        try:
            result = app.acquire_token_by_authorization_code(
                code=auth_code,
                scopes=SCOPES,
                redirect_uri=REDIRECT_URI,
            )

            if "access_token" in result:
                self._save_tokens(
                    access_token=result["access_token"],
                    refresh_token=result.get("refresh_token", ""),
                    expires_in=result.get("expires_in", 3600),
                )
                logger.info("graph_authenticated")
                return True
            else:
                logger.error("graph_auth_failed", error=result.get("error_description"))
                return False

        except Exception as e:
            logger.exception("graph_auth_error", error=str(e))
            return False

    async def _get_auth_code_interactive(
        self, app: msal.PublicClientApplication
    ) -> str | None:
        """Get authorization code via browser redirect.

        Opens browser for user to authenticate, then captures the
        callback on localhost.
        """
        auth_code_result: dict[str, Any] = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)

                if "code" in params:
                    auth_code_result["code"] = params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"""
                        <html><body>
                        <h1>Authentication Successful</h1>
                        <p>You can close this window and return to RealtorAI.</p>
                        <script>window.close();</script>
                        </body></html>
                    """)
                else:
                    auth_code_result["error"] = params.get("error", ["unknown"])[0]
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"""
                        <html><body>
                        <h1>Authentication Failed</h1>
                        <p>Please try again.</p>
                        </body></html>
                    """)

            def log_message(self, format: str, *args: Any) -> None:
                pass  # Suppress server logs

        # Start server in background thread
        server = HTTPServer(("localhost", 8421), CallbackHandler)
        server_thread = Thread(target=server.handle_request)
        server_thread.start()

        # Build auth URL and open browser
        auth_url = app.get_authorization_request_url(
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,
        )

        logger.info("opening_browser_for_auth")
        webbrowser.open(auth_url)

        # Wait for callback
        server_thread.join(timeout=120)

        return auth_code_result.get("code")


# Default instance
graph_auth = GraphAuth()
