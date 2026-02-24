"""Spark API (FlexMLS) OAuth 2.0 authentication.

Spark API is the developer interface to FlexMLS, providing access to
MLS listing data via RESO-standards-based REST API.

Documentation: https://sparkplatform.com/docs/overview/api
"""

import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import structlog

from realtorai.config.settings import get_settings
from realtorai.integrations.base import Integration
from realtorai.storage.keychain import KeychainKeys, keychain

logger = structlog.get_logger()

# Spark API endpoints
SPARK_AUTH_URL = "https://sparkplatform.com/oauth2"
SPARK_TOKEN_URL = "https://sparkapi.com/v1/oauth2/grant"
SPARK_API_BASE = "https://sparkapi.com/v1"

# OAuth redirect URI
REDIRECT_URI = "http://localhost:8422/spark/callback"


class SparkAuth(Integration):
    """Spark API authentication via OAuth 2.0.

    Uses authorization code flow with localhost redirect.
    Tokens are stored securely in macOS Keychain.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

    @property
    def name(self) -> str:
        return "Spark API (FlexMLS)"

    async def is_configured(self) -> bool:
        """Check if Spark API credentials are configured."""
        # Either full OAuth creds or demo token works
        has_oauth = bool(
            getattr(self.settings, 'spark_client_id', None) and
            getattr(self.settings, 'spark_client_secret', None)
        )
        has_demo = bool(getattr(self.settings, 'spark_demo_token', None))
        return has_oauth or has_demo

    @property
    def is_demo_mode(self) -> bool:
        """True if using demo token (no OAuth creds configured)."""
        return (
            not (self.settings.spark_client_id and self.settings.spark_client_secret)
            and bool(self.settings.spark_demo_token)
        )

    async def is_connected(self) -> bool:
        """Check if we have a valid access token."""
        # Demo token is always "connected"
        if self.is_demo_mode:
            self._access_token = self.settings.spark_demo_token
            return True

        if not self._access_token:
            await self._load_tokens()

        if not self._access_token:
            return False

        # Check if token is expired
        if self._token_expiry and datetime.utcnow() >= self._token_expiry:
            return await self._refresh_token()

        return True

    async def connect(self) -> bool:
        """Initiate OAuth flow to get access token."""
        if not await self.is_configured():
            logger.error("spark_not_configured")
            return False

        # Try to refresh existing token first
        if await self._load_tokens() and await self._refresh_token():
            return True

        # Need fresh authentication
        return await self._authenticate()

    async def disconnect(self) -> None:
        """Clear stored tokens."""
        keychain.delete(KeychainKeys.SPARK_ACCESS_TOKEN)
        keychain.delete(KeychainKeys.SPARK_REFRESH_TOKEN)
        keychain.delete(KeychainKeys.SPARK_TOKEN_EXPIRY)
        self._access_token = None
        self._token_expiry = None
        logger.info("spark_disconnected")

    async def get_access_token(self) -> str | None:
        """Get a valid access token, refreshing if necessary."""
        if not await self.is_connected():
            return None
        return self._access_token

    async def _load_tokens(self) -> bool:
        """Load tokens from keychain."""
        access_token = keychain.get(KeychainKeys.SPARK_ACCESS_TOKEN)
        expiry_str = keychain.get(KeychainKeys.SPARK_TOKEN_EXPIRY)

        if access_token and expiry_str:
            self._access_token = access_token
            try:
                self._token_expiry = datetime.fromisoformat(expiry_str)
            except ValueError:
                self._token_expiry = None

            logger.debug("spark_tokens_loaded")
            return True

        return False

    def _save_tokens(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        """Save tokens to keychain."""
        expiry = datetime.utcnow() + timedelta(seconds=expires_in - 300)  # 5 min buffer

        keychain.set(KeychainKeys.SPARK_ACCESS_TOKEN, access_token)
        keychain.set(KeychainKeys.SPARK_REFRESH_TOKEN, refresh_token)
        keychain.set(KeychainKeys.SPARK_TOKEN_EXPIRY, expiry.isoformat())

        self._access_token = access_token
        self._token_expiry = expiry

        logger.debug("spark_tokens_saved")

    async def _refresh_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        refresh_token = keychain.get(KeychainKeys.SPARK_REFRESH_TOKEN)
        if not refresh_token:
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    SPARK_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": self.settings.spark_client_id,
                        "client_secret": self.settings.spark_client_secret,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token", refresh_token),
                        expires_in=data.get("expires_in", 86400),
                    )
                    logger.info("spark_token_refreshed")
                    return True
                else:
                    logger.warning("spark_refresh_failed", status=response.status_code)
                    return False

        except Exception as e:
            logger.error("spark_refresh_error", error=str(e))
            return False

    async def _authenticate(self) -> bool:
        """Perform interactive OAuth authentication."""
        logger.info("starting_spark_auth")

        # Get authorization code via browser
        auth_code = await self._get_auth_code_interactive()

        if not auth_code:
            logger.error("spark_auth_no_code")
            return False

        # Exchange code for tokens
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    SPARK_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": auth_code,
                        "redirect_uri": REDIRECT_URI,
                        "client_id": self.settings.spark_client_id,
                        "client_secret": self.settings.spark_client_secret,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token", ""),
                        expires_in=data.get("expires_in", 86400),
                    )
                    logger.info("spark_authenticated")
                    return True
                else:
                    logger.error("spark_auth_failed", status=response.status_code, body=response.text)
                    return False

        except Exception as e:
            logger.exception("spark_auth_error", error=str(e))
            return False

    async def _get_auth_code_interactive(self) -> str | None:
        """Get authorization code via browser redirect."""
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
                        <h1>Spark API Connected!</h1>
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

        # Start server on port 8422 (different from main app)
        server = HTTPServer(("localhost", 8422), CallbackHandler)
        server_thread = Thread(target=server.handle_request)
        server_thread.start()

        # Build auth URL and open browser
        params = {
            "response_type": "code",
            "client_id": self.settings.spark_client_id,
            "redirect_uri": REDIRECT_URI,
        }
        auth_url = f"{SPARK_AUTH_URL}?{urlencode(params)}"

        logger.info("opening_browser_for_spark_auth")
        webbrowser.open(auth_url)

        # Wait for callback
        server_thread.join(timeout=120)

        return auth_code_result.get("code")


# Default instance
spark_auth = SparkAuth()
