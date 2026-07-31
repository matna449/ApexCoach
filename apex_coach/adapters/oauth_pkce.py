"""OAuth 2.0 PKCE helpers, shared across providers (WHOOP §2.1, Strava §3.1).

wait_for_callback() spins up a temporary local HTTP server to receive the
provider's redirect — see docs/adr/0018.
"""

import base64
import hashlib
import http.server
import secrets
import threading
import urllib.parse


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) — S256 method."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


def generate_state() -> str:
    return secrets.token_urlsafe(16)


class CallbackResult:
    def __init__(self):
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None


def _make_handler(result: CallbackResult, expected_path: str, done_event: threading.Event):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != expected_path:
                self.send_response(404)
                self.end_headers()
                return

            params = urllib.parse.parse_qs(parsed.query)
            result.code = params.get("code", [None])[0]
            result.state = params.get("state", [None])[0]
            result.error = params.get("error", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if result.error:
                self.wfile.write(
                    b"<html><body><h1>Authorization failed.</h1>"
                    b"You can close this window and return to the terminal.</body></html>"
                )
            else:
                self.wfile.write(
                    b"<html><body><h1>Authorization complete.</h1>"
                    b"You can close this window and return to the terminal.</body></html>"
                )
            done_event.set()

        def log_message(self, format, *args):
            pass  # suppress default request logging to stderr

    return Handler


def wait_for_callback(
    host: str, port: int, path: str, timeout_seconds: int = 120
) -> CallbackResult:
    """Starts a local HTTP server, blocks until the OAuth redirect hits it
    (or times out), then shuts down."""
    result = CallbackResult()
    done_event = threading.Event()
    server = http.server.HTTPServer((host, port), _make_handler(result, path, done_event))

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    completed = done_event.wait(timeout=timeout_seconds)
    server.shutdown()
    server_thread.join(timeout=5)

    if not completed:
        raise TimeoutError(f"no OAuth callback received within {timeout_seconds}s")
    return result
