import base64
import urllib.parse

import httpx


class PinterestOAuth:
    AUTH_URL = "https://www.pinterest.com/oauth/"
    TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
    SCOPES = "pins:read,pins:write,boards:read,boards:write,user_accounts:read"

    def __init__(self, app_id: str, app_secret: str, redirect_uri: str = "http://localhost:5000/auth/pinterest/callback"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri

    def get_auth_url(self, state: str = "crosslisttosocials") -> str:
        """Build the Pinterest authorization URL that the user should be redirected to."""
        params = {
            "response_type": "code",
            "client_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.SCOPES,
            "state": state,
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Exchange authorization code for access + refresh tokens."""
        credentials = base64.b64encode(
            f"{self.app_id}:{self.app_secret}".encode()
        ).decode()

        response = httpx.post(
            self.TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> dict:
        """Get a new access token using the refresh token."""
        credentials = base64.b64encode(
            f"{self.app_id}:{self.app_secret}".encode()
        ).decode()

        response = httpx.post(
            self.TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        return response.json()
