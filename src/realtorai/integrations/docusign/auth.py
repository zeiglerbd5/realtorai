"""DocuSign Rooms OAuth 2.0 authentication with PKCE.

Uses Authorization Code Grant flow with Proof Key for Code Exchange.
"""

import base64
import hashlib
import secrets
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

# DocuSign OAuth endpoints (demo environment)
DOCUSIGN_AUTH_URL = "https://account-d.docusign.com/oauth/auth"
DOCUSIGN_TOKEN_URL = "https://account-d.docusign.com/oauth/token"

# Local callback
REDIRECT_URI = "http://localhost:8423"


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    # Generate random code verifier (43-128 chars)
    code_verifier = secrets.token_urlsafe(32)

    # Create SHA256 hash and base64url encode it
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()

    return code_verifier, code_challenge


class DocuSignAuth(Integration):
    """DocuSign OAuth 2.0 authentication with PKCE."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

    @property
    def name(self) -> str:
        return "DocuSign Rooms"

    async def is_configured(self) -> bool:
        """Check if DocuSign credentials are configured."""
        return bool(
            getattr(self.settings, 'docusign_integration_key', None) and
            getattr(self.settings, 'docusign_secret_key', None) and
            getattr(self.settings, 'docusign_account_id', None)
        )

    async def is_connected(self) -> bool:
        """Check if we have a valid access token."""
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
            logger.error("docusign_not_configured")
            return False

        # Try to refresh existing token first
        if await self._load_tokens() and await self._refresh_token():
            return True

        # Need fresh authentication
        return await self._authenticate()

    async def disconnect(self) -> None:
        """Clear stored tokens."""
        keychain.delete(KeychainKeys.DOCUSIGN_ACCESS_TOKEN)
        keychain.delete(KeychainKeys.DOCUSIGN_REFRESH_TOKEN)
        keychain.delete("docusign_token_expiry")
        self._access_token = None
        self._token_expiry = None
        logger.info("docusign_disconnected")

    async def get_access_token(self) -> str | None:
        """Get a valid access token, refreshing if necessary."""
        if not await self.is_connected():
            return None
        return self._access_token

    async def _load_tokens(self) -> bool:
        """Load tokens from keychain."""
        access_token = keychain.get(KeychainKeys.DOCUSIGN_ACCESS_TOKEN)
        expiry_str = keychain.get("docusign_token_expiry")

        if access_token and expiry_str:
            self._access_token = access_token
            try:
                self._token_expiry = datetime.fromisoformat(expiry_str)
            except ValueError:
                self._token_expiry = None

            logger.debug("docusign_tokens_loaded")
            return True

        return False

    def _save_tokens(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        """Save tokens to keychain."""
        expiry = datetime.utcnow() + timedelta(seconds=expires_in - 300)  # 5 min buffer

        keychain.set(KeychainKeys.DOCUSIGN_ACCESS_TOKEN, access_token)
        keychain.set(KeychainKeys.DOCUSIGN_REFRESH_TOKEN, refresh_token)
        keychain.set("docusign_token_expiry", expiry.isoformat())

        self._access_token = access_token
        self._token_expiry = expiry

        logger.debug("docusign_tokens_saved")

    async def _refresh_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        refresh_token = keychain.get(KeychainKeys.DOCUSIGN_REFRESH_TOKEN)
        if not refresh_token:
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    DOCUSIGN_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    auth=(
                        self.settings.docusign_integration_key,
                        self.settings.docusign_secret_key,
                    ),
                )

                if response.status_code == 200:
                    data = response.json()
                    self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token", refresh_token),
                        expires_in=data.get("expires_in", 28800),  # 8 hours default
                    )
                    logger.info("docusign_token_refreshed")
                    return True
                else:
                    logger.warning("docusign_refresh_failed", status=response.status_code)
                    return False

        except Exception as e:
            logger.error("docusign_refresh_error", error=str(e))
            return False

    async def _authenticate(self) -> bool:
        """Perform interactive OAuth authentication with PKCE."""
        logger.info("starting_docusign_auth")

        # Generate PKCE pair
        code_verifier, code_challenge = generate_pkce_pair()

        # Get authorization code via browser
        auth_code = await self._get_auth_code_interactive(code_challenge)

        if not auth_code:
            logger.error("docusign_auth_no_code")
            return False

        # Exchange code for tokens
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    DOCUSIGN_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": auth_code,
                        "code_verifier": code_verifier,
                        "redirect_uri": REDIRECT_URI,
                    },
                    auth=(
                        self.settings.docusign_integration_key,
                        self.settings.docusign_secret_key,
                    ),
                )

                if response.status_code == 200:
                    data = response.json()
                    self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token", ""),
                        expires_in=data.get("expires_in", 28800),
                    )
                    logger.info("docusign_authenticated")
                    return True
                else:
                    logger.error("docusign_auth_failed", status=response.status_code, body=response.text)
                    return False

        except Exception as e:
            logger.exception("docusign_auth_error", error=str(e))
            return False

    async def _get_auth_code_interactive(self, code_challenge: str) -> str | None:
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
                        <h1>DocuSign Connected!</h1>
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

        # Start callback server
        server = HTTPServer(("localhost", 8423), CallbackHandler)
        server_thread = Thread(target=server.handle_request)
        server_thread.start()

        # Build auth URL with PKCE
        params = {
            "response_type": "code",
            "client_id": self.settings.docusign_integration_key,
            "redirect_uri": REDIRECT_URI,
            "scope": "signature dtr.rooms.read dtr.rooms.write dtr.documents.read dtr.documents.write dtr.profile.read dtr.profile.write dtr.company.read dtr.company.write room_forms",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{DOCUSIGN_AUTH_URL}?{urlencode(params)}"

        logger.info("opening_browser_for_docusign_auth")
        webbrowser.open(auth_url)

        # Wait for callback
        server_thread.join(timeout=120)

        return auth_code_result.get("code")


# Default instance
docusign_auth = DocuSignAuth()
