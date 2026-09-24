from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


APP_FILE = "AI测试智能体_TestPilot.html"
INDEX_FILE = "index.html"
ALLOWED_FILES = {APP_FILE, INDEX_FILE}


class TestPilotHandler(BaseHTTPRequestHandler):
    server_version = "TestPilotFrontend/1.0"

    def _send_security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src http://127.0.0.1:8001 http://frp3.ccszxc.xin:61174; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        ))
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def _path(self) -> str:
        return unquote(urlsplit(self.path).path)

    def do_GET(self) -> None:
        path = self._path()
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/" + quote(APP_FILE))
            self._send_security_headers()
            self.end_headers()
            return
        filename = path.lstrip("/")
        if filename not in ALLOWED_FILES:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        file_path = self.server.root_path / filename
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(content)

    def do_HEAD(self) -> None:
        path = self._path()
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/" + quote(APP_FILE))
            self._send_security_headers()
            self.end_headers()
            return
        filename = path.lstrip("/")
        if filename not in ALLOWED_FILES:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = self.server.root_path / filename
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self._send_security_headers()
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        message = f"{self.client_address[0]} - {format % args}"
        try:
            print(message)
        except UnicodeEncodeError:
            print(message.encode("ascii", errors="replace").decode("ascii"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve only the TestPilot frontend page")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--root", default=Path(__file__).resolve().parent, type=Path)
    args = parser.parse_args()

    root_path = args.root.resolve()
    for file_name in ALLOWED_FILES:
        file_path = root_path / file_name
        if not file_path.is_file():
            raise SystemExit(f"Frontend file not found: {file_path}")

    server = ThreadingHTTPServer((args.host, args.port), TestPilotHandler)
    server.root_path = root_path
    print(f"Serving TestPilot on http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()



