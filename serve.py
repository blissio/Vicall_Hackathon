"""Authenticated WSGI adapter for a single shared research workspace."""
import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from app import Handler, Workspace, lock_workspace
from storage import connect, stamp

ROLES = {"viewer", "researcher", "admin"}
ADMIN_PATHS = {"/api/settings", "/api/collect", "/api/collect-cancel", "/api/collect-resume", "/api/research-settings", "/api/matching-settings", "/api/backup", "/api/target-catalog"}
READ_POSTS = {"/api/search", "/api/ask", "/api/export"}


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000).hex()
    return {"salt": salt, "digest": digest}


class OutputHandler(Handler):
    def send_response(self, code, message=None):
        self.status = code
        self.response_headers = []

    def send_header(self, keyword, value):
        self.response_headers.append((keyword, value))

    def end_headers(self):
        pass


class TeamApplication:
    def __init__(self, directory, users):
        if not isinstance(users, dict) or not users:
            raise ValueError("Configure at least one team account")
        for username, user in users.items():
            if not isinstance(username, str) or not isinstance(user, dict) or user.get("role") not in ROLES:
                raise ValueError("Invalid user or role")
            if not all(isinstance(user.get(k), str) for k in ("salt", "digest")) or len(user["salt"]) != 32 or len(user["digest"]) != 64:
                raise ValueError("Use manage_users.py to create password hashes")
            bytes.fromhex(user["salt"])
            bytes.fromhex(user["digest"])
        self.users = users
        self.workspace_lock = lock_workspace(Path(directory).resolve())
        try:
            self.workspace = Workspace(directory)
        except Exception:
            self.workspace_lock.close()
            raise
        self.server = SimpleNamespace(workspace=self.workspace, server_port=80, token=secrets.token_urlsafe(32), agent_token="")
        self.api_token = os.getenv("VICALL_TEAM_API_TOKEN", "")
        if self.api_token and len(self.api_token) < 32:
            self.close()
            raise ValueError("VICALL_TEAM_API_TOKEN must contain at least 32 characters")
        with connect(self.workspace.directory) as db:
            db.execute("CREATE TABLE IF NOT EXISTS access_log(id INTEGER PRIMARY KEY, observed_at TEXT, username TEXT, method TEXT, path TEXT, status INTEGER)")

    def close(self):
        self.workspace_lock.close()
        if hasattr(self, "workspace"):
            self.workspace.automation_stop.set()

    def authenticate(self, authorization):
        if self.api_token and hmac.compare_digest(authorization, "Bearer "+self.api_token):
            return "api-client", "researcher"
        if not authorization.startswith("Basic "):
            return None
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode()
            username, password = decoded.split(":", 1)
            user = self.users.get(username)
            # Unknown users also incur password derivation work.
            salt = user["salt"] if user else "0"*32
            calculated = hash_password(password, salt)["digest"]
            if user and hmac.compare_digest(calculated, user["digest"]):
                return username, user["role"]
        except (ValueError, UnicodeError):
            pass
        return None

    def __call__(self, environ, start_response):
        def error(status, message, challenge=False):
            body = json.dumps({"error": message}).encode()
            headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")]
            if challenge:
                headers.append(("WWW-Authenticate", 'Basic realm="Pittsburgh IQ", charset="UTF-8"'))
            start_response(status, headers)
            return [body]
        user = self.authenticate(environ.get("HTTP_AUTHORIZATION", ""))
        if not user:
            return error("401 Unauthorized", "Sign in to the team workspace", True)
        username, role = user
        method, path = environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO", "/")
        if method not in {"GET", "POST"}:
            return error("405 Method Not Allowed", "Use GET or POST")
        if method == "POST" and (role == "viewer" and path not in READ_POSTS or path in ADMIN_PATHS and role != "admin"):
            return error("403 Forbidden", "Your role cannot perform this action")
        origin = environ.get("HTTP_ORIGIN")
        if method == "POST" and origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != environ.get("HTTP_HOST"):
                return error("403 Forbidden", "Cross-origin requests are not accepted")
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            return error("400 Bad Request", "Invalid content length")
        if length < 0 or length > 2_000_000:
            return error("413 Content Too Large", "Request exceeds the size limit")
        body = environ["wsgi.input"].read(length)
        if len(body) != length:
            return error("400 Bad Request", "Incomplete request body")
        if role == "viewer" and path == "/api/ask":
            try:
                payload = json.loads(body)
            except ValueError:
                return error("400 Bad Request", "Expected JSON")
            if not isinstance(payload, dict) or (payload.get("use_ai") or payload.get("use_ai_plan")):
                return error("403 Forbidden", "Viewer access supports evidence search; model calls require researcher access")
        # Browser users retain the app's per-process CSRF token. Trusted bearer
        # clients use their credential instead. Origin checks run above.
        if method == "POST" and username != "api-client" and not hmac.compare_digest(environ.get("HTTP_X_VICALL_TOKEN", ""), self.server.token):
            return error("403 Forbidden", "Reload the workspace before saving")
        handler = OutputHandler.__new__(OutputHandler)
        handler.server = self.server
        handler.path = path + ("?"+environ["QUERY_STRING"] if environ.get("QUERY_STRING") else "")
        handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
        from email.message import Message
        handler.headers = Message()
        handler.headers["Host"] = "127.0.0.1:80"
        handler.headers["X-Vicall-Token"] = self.server.token
        handler.headers["Content-Type"] = environ.get("CONTENT_TYPE", "application/json")
        handler.headers["Content-Length"] = str(length)
        try:
            if method == "GET":
                handler.do_GET()
            else:
                handler.do_POST()
        except Exception:
            return error("500 Internal Server Error", "Workspace request failed; consult server diagnostics")
        content = handler.wfile.getvalue()
        if path in {'/api/intelligence', '/api/data', '/api/settings'} and handler.status == 200:
            info = json.loads(content)
            info["team_role"] = role
            if role == "viewer" and path == '/api/intelligence':
                info["ai_available"] = False
            content = json.dumps(info).encode()
            handler.response_headers = [(k, str(len(content)) if k == "Content-Length" else v) for k,v in handler.response_headers]
        if path == "/" and handler.status == 200:
            content = content.replace(b"Local application", b"Team workspace")
            handler.response_headers = [(k, str(len(content)) if k == "Content-Length" else v) for k,v in handler.response_headers]
        with connect(self.workspace.directory) as db:
            db.execute("INSERT INTO access_log(observed_at,username,method,path,status) VALUES (?,?,?,?,?)", (stamp(), username, method, path, handler.status))
        from http import HTTPStatus
        start_response(f"{handler.status} {HTTPStatus(handler.status).phrase}", handler.response_headers)
        return [content]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
    parser.add_argument("--users", type=Path, default=Path("users.json"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    from waitress import serve
    application = TeamApplication(args.data_dir, json.loads(args.users.read_text(encoding="utf-8")))
    application.workspace.start_automation()
    print(f"Authenticated team workspace at http://127.0.0.1:{args.port}. Use a TLS reverse proxy for remote access.", flush=True)
    try:
        serve(application, host="127.0.0.1", port=args.port, threads=8, max_request_body_size=2_000_000)
    finally:
        application.close()
