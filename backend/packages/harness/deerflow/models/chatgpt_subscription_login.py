#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["PyJWT[crypto]>=2.13.0"]
# ///
"""Local SIWC login helper, also downloadable as a standalone script.

Run on the computer with your browser: ``uv run deerflow-chatgpt-login.py``.
Upload the resulting protected JSON using DeerFlow Settings > Subscriptions.
It contains credentials: transfer over HTTPS, Tailscale or SSH, then remove the
transfer copy. The remote DeerFlow runtime owns subsequent token refreshes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jwt

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE_ENDPOINT = ISSUER + "/api/accounts/authorize"
TOKEN_ENDPOINT = ISSUER + "/api/accounts/oauth/token"
JWKS_ENDPOINT = ISSUER + "/.well-known/jwks.json"
DYNAMIC_CLIENT = "dynamic_agent_client"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REQUIRED_SCOPES = frozenset({"resource.invoke", "chatgpt.tokens.use.direct"})
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{3,256}")
_MAX_RESPONSE_BYTES = 1024 * 1024
_CALLBACK_SOCKET_TIMEOUT = 5


def validate_scopes(scopes: str | list[str]) -> list[str]:
    values = scopes.split() if isinstance(scopes, str) else scopes
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values) or not REQUIRED_SCOPES.issubset(values):
        raise ValueError("ChatGPT plan permission is missing; authorize ChatGPT plan usage and sign in again.")
    return list(dict.fromkeys(values))


def validate_token_response(
    response: dict[str, Any],
    *,
    client_id: str,
    jwks: dict[str, Any],
    subject: str | None = None,
    nonce: str | None = None,
    require_id_token: bool = True,
) -> dict[str, Any]:
    """Verify signed grant authority separately from untrusted export metadata."""
    if not isinstance(response, dict) or not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id) or client_id == DYNAMIC_CLIENT:
        raise ValueError("A valid issued ChatGPT client registration is required.")
    if not isinstance(response.get("token_type", "Bearer"), str) or response.get("token_type", "Bearer").lower() != "bearer":
        raise ValueError("The ChatGPT connection does not contain bearer credentials.")

    def decode(token: Any, *, audience: str, required: list[str]) -> dict[str, Any]:
        if not isinstance(token, str) or not token or len(token) > 65536:
            raise ValueError("ChatGPT credentials are missing or invalid; sign in again.")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError("Unsupported token signature")
            keys = jwt.PyJWKSet.from_dict(jwks)
            key = next(item for item in keys.keys if item.key_id == header["kid"] and item.algorithm_name == "RS256")
            return jwt.decode(token, key.key, algorithms=["RS256"], issuer=ISSUER, audience=audience, options={"require": required})
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, StopIteration):
            raise ValueError("ChatGPT token verification failed; sign in again.") from None

    access = decode(response.get("access_token"), audience=RESOURCE, required=["exp", "iss", "aud", "sub", "client_id", "scope"])
    if access["client_id"] != client_id or not isinstance(access["sub"], str) or not access["sub"]:
        raise ValueError("ChatGPT token registration or identity does not match.")
    if subject is not None and access["sub"] != subject:
        raise ValueError("ChatGPT token identity does not match the selected account.")
    scopes = validate_scopes(access["scope"])
    # A successful ID token proves identity; only the signed access grant proves
    # plan permission. Never authorize from imported `scopes` or email metadata.
    result = {
        "issuer": ISSUER,
        "subject": access["sub"],
        "client_id": client_id,
        "access_token": response["access_token"],
        "token_type": "Bearer",
        "scopes": scopes,
        "expires_at": access["exp"],
        "saved_at": time.time(),
    }
    if "scope" in response and set(validate_scopes(response["scope"])) != set(scopes):
        raise ValueError("ChatGPT granted scopes do not match the signed access grant.")
    if require_id_token or response.get("id_token"):
        identity = decode(response.get("id_token"), audience=client_id, required=["exp", "iss", "aud", "sub"])
        if identity["sub"] != access["sub"]:
            raise ValueError("ChatGPT identity and access token refer to different accounts.")
        if nonce is not None and (not isinstance(identity.get("nonce"), str) or not secrets.compare_digest(identity["nonce"], nonce)):
            raise ValueError("ChatGPT sign-in nonce does not match this attempt.")
        result["id_token"] = response["id_token"]
        if isinstance(identity.get("email"), str) and len(identity["email"]) <= 320:
            result["email"] = identity["email"]
    if "refresh_token" in response:
        refresh = response["refresh_token"]
        if not isinstance(refresh, str) or not refresh or len(refresh) > 65536:
            raise ValueError("ChatGPT refresh credentials are invalid; sign in again.")
        result["refresh_token"] = refresh
    if "earliest_refresh_at" in response and isinstance(response["earliest_refresh_at"], (int, float)):
        result["earliest_refresh_at"] = response["earliest_refresh_at"]
    return result


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    """Publish a complete record with owner-only permissions on Unix."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".chatgpt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def get_or_create_host_id(directory: Path) -> str:
    """Publish once using an atomic hard link; concurrent starters reuse it."""
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination = directory / "chatgpt-host-id.json"
    if not destination.exists():
        descriptor, temporary = tempfile.mkstemp(prefix=".host-", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"ext_agent_host_id": "urn:uuid:" + str(uuid.uuid4())}, stream)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    value = json.loads(destination.read_text(encoding="utf-8"))
    host_id = value.get("ext_agent_host_id")
    if not isinstance(host_id, str) or not host_id.startswith("urn:uuid:"):
        raise ValueError("The saved ChatGPT host identity is invalid; restore its original file.")
    uuid.UUID(host_id[len("urn:uuid:") :])
    return host_id


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise ValueError("The ChatGPT endpoint returned an unexpected redirect.")


def request_json(url: str, form: dict[str, str] | None = None) -> dict[str, Any]:
    """Bound provider replies and avoid logging provider responses or tokens."""
    body = urllib.parse.urlencode(form).encode("ascii") if form else None
    headers = {"Accept": "application/json"}
    if form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=30) as reply:
            raw = reply.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ValueError("The ChatGPT endpoint returned an oversized response.")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Invalid provider response")
        return result
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        raise ValueError("The ChatGPT endpoint could not complete this request; retry sign-in.") from None


def build_authorization_url(*, client_id: str, host_id: str, redirect_uri: str, state: str, nonce: str, verifier: str, id_token_hint: str | None = None, login_hint: str | None = None) -> str:
    parameters = {
        "client_id": client_id,
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii"),
    }
    if client_id == DYNAMIC_CLIENT:
        parameters["agent_name_hint"] = "DeerFlow"
    else:
        if id_token_hint:
            parameters["id_token_hint"] = id_token_hint
        if login_hint:
            parameters["login_hint"] = login_hint
    return AUTHORIZE_ENDPOINT + "?" + urllib.parse.urlencode(parameters)


def parse_callback(path: str, *, state: str, client_id: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(path)
    if parsed.path != "/auth/callback":
        raise ValueError("Unexpected callback path.")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError("Ambiguous ChatGPT callback parameters.")
    if not secrets.compare_digest(query.get("state", [""])[0], state):
        raise ValueError("ChatGPT callback state does not match this attempt.")
    if "error" in query:
        raise ValueError("ChatGPT sign-in was declined or could not complete; start again.")
    issued = query.get("client_id", [client_id])[0]
    if issued == DYNAMIC_CLIENT or not _CLIENT_ID.fullmatch(issued):
        raise ValueError("ChatGPT did not return an issued client registration.")
    if client_id != DYNAMIC_CLIENT and issued != client_id:
        raise ValueError("ChatGPT callback changed the selected registration.")
    code = query.get("code", [""])[0]
    if not code:
        raise ValueError("ChatGPT callback did not include an authorization code.")
    return code, issued


def sign_in(*, profile_path: Path, host_id: str) -> dict[str, Any]:
    previous = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError("The saved ChatGPT registration is invalid.")
    client_id = previous.get("client_id", DYNAMIC_CLIENT)
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        raise ValueError("The saved ChatGPT client registration is invalid.")
    state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    callback: list[tuple[str, str] | ValueError] = []

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Request URLs contain authorization codes.

        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send_error(400, "Unexpected callback host")
                return
            try:
                result = parse_callback(self.path, state=state, client_id=client_id)
            except ValueError as error:
                self.send_error(400, str(error))
                # Unsolicited callbacks must not consume the legitimate attempt.
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                if query.get("state") == [state] and "error" in query:
                    callback.append(error)
                return
            callback.append(result)
            body = b"ChatGPT sign-in received. You can close this tab and return to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class CallbackServer(ThreadingHTTPServer):
        # Spare browser connections must neither block the real callback nor
        # outlive the helper's listener. Each handler has bounded socket IO.
        daemon_threads = False

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(_CALLBACK_SOCKET_TIMEOUT)
            return connection, address

    with CallbackServer(("127.0.0.1", 0), CallbackHandler) as server:
        server.timeout = 1
        redirect_uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
        url = build_authorization_url(client_id=client_id, host_id=host_id, redirect_uri=redirect_uri, state=state, nonce=nonce, verifier=verifier, id_token_hint=previous.get("id_token"), login_hint=previous.get("email"))
        print("Opening Continue with ChatGPT in your browser. This attempt expires in five minutes.")
        if not webbrowser.open(url):
            raise ValueError("Could not open a browser. Configure your system browser and run the helper again.")
        deadline = time.monotonic() + 300
        while not callback and time.monotonic() < deadline:
            server.handle_request()
    if not callback:
        raise ValueError("ChatGPT sign-in timed out; run the helper again.")
    if isinstance(callback[0], ValueError):
        raise callback[0]
    code, issued_client_id = callback[0]
    # Keep a newly issued registration even if the one-time code exchange fails.
    if client_id == DYNAMIC_CLIENT:
        write_private_json(profile_path, {"client_id": issued_client_id})
    response = request_json(TOKEN_ENDPOINT, {"grant_type": "authorization_code", "client_id": issued_client_id, "code": code, "code_verifier": verifier, "redirect_uri": redirect_uri, "resource": RESOURCE})
    record = validate_token_response(response, client_id=issued_client_id, jwks=request_json(JWKS_ENDPOINT), subject=previous.get("subject"), nonce=nonce)
    if not record.get("refresh_token"):
        raise ValueError("ChatGPT did not grant renewable access; sign in again with offline access.")
    record["ext_agent_host_id"] = host_id
    write_private_json(profile_path, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="default", help="Saved account label; use another label to add an account or workspace.")
    parser.add_argument("--output", type=Path, default=Path.cwd() / "deerflow-chatgpt-connection.json")
    config_home = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    parser.add_argument("--state-dir", type=Path, default=config_home / "deerflow" / "chatgpt", help="Protected local registration directory.")
    arguments = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", arguments.profile) or arguments.profile in {".", ".."} or arguments.profile.casefold() == "chatgpt-host-id":
        parser.error("Profile must be a simple account label without path separators.")
    try:
        host_id = get_or_create_host_id(arguments.state_dir)
        record = sign_in(profile_path=arguments.state_dir / (arguments.profile + ".json"), host_id=host_id)
        write_private_json(arguments.output, record)
    except (ValueError, OSError, KeyboardInterrupt) as error:
        # OSError paths and provider responses can contain sensitive context.
        message = str(error) if isinstance(error, ValueError) else "Sign-in stopped or the protected credential file could not be written."
        print(message, file=sys.stderr)
        return 1
    print(f"Saved protected connection file: {arguments.output}")
    print("Upload it in DeerFlow Settings > Subscriptions over HTTPS or Tailscale, then delete this transfer copy.")
    print("Keep the local registration directory: later sign-ins reuse its client registration and host ID.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
