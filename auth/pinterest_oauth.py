import base64
import http.server
import threading
import urllib.parse
import webbrowser

import httpx


class PinterestOAuth:
    AUTH_URL = "https://www.pinterest.com/oauth/"
    TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
    REDIRECT_URI = "http://localhost:8000/callback"
    SCOPES = "pins:read,pins:write,boards:read,boards:write,user_accounts:read"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._auth_code: str | None = None

    def authorize(self) -> dict:
        """Run the full OAuth flow. Opens browser, waits for callback, returns tokens."""
        auth_url = self._build_auth_url()
        print(f"\nOpening browser for Pinterest authorization...")
        print(f"If it doesn't open, visit: {auth_url}\n")
        webbrowser.open(auth_url)

        self._auth_code = self._wait_for_callback()
        if not self._auth_code:
            raise RuntimeError("Failed to receive authorization code")

        return self._exchange_code(self._auth_code)

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

    def _build_auth_url(self) -> str:
        params = {
            "response_type": "code",
            "client_id": self.app_id,
            "redirect_uri": self.REDIRECT_URI,
            "scope": self.SCOPES,
            "state": "socialmediaagent",
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def _wait_for_callback(self) -> str | None:
        """Start a local HTTP server and wait for the OAuth callback."""
        code_holder = {"code": None}

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(query)
                code_holder["code"] = params.get("code", [None])[0]

                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authorization successful!</h2>"
                    b"<p>You can close this tab and return to the terminal.</p></body></html>"
                )

            def log_message(self, format, *args):
                pass

        server = http.server.HTTPServer(("localhost", 8000), CallbackHandler)
        server.timeout = 120

        thread = threading.Thread(target=server.handle_request)
        thread.start()
        thread.join(timeout=120)
        server.server_close()

        return code_holder["code"]

    def _exchange_code(self, code: str) -> dict:
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
                "redirect_uri": self.REDIRECT_URI,
            },
        )
        response.raise_for_status()
        return response.json()
