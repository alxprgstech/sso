"""Local SMTP receiver for browser E2E; stores only six-digit test codes."""

from __future__ import annotations

import argparse
import json
import re
import socketserver
from email import message_from_bytes
from email.policy import default
from pathlib import Path


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.wfile.write(b"220 e2e-smtp ready\r\n")
        recipients: list[str] = []
        while command := self.rfile.readline():
            upper = command.upper()
            if upper.startswith((b"EHLO", b"HELO")):
                self.wfile.write(b"250 e2e-smtp\r\n")
            elif upper.startswith(b"MAIL FROM:"):
                recipients = []
                self.wfile.write(b"250 ok\r\n")
            elif upper.startswith(b"RCPT TO:"):
                recipients.append(command[8:].decode("utf-8").strip().strip("<>"))
                self.wfile.write(b"250 ok\r\n")
            elif upper.startswith(b"DATA"):
                self.wfile.write(b"354 end with dot\r\n")
                lines: list[bytes] = []
                while line := self.rfile.readline():
                    if line == b".\r\n":
                        break
                    lines.append(line[1:] if line.startswith(b"..") else line)
                message = message_from_bytes(b"".join(lines), policy=default)
                plain = message.get_body(preferencelist=("plain",))
                match = (
                    re.search(r"Ваш код подтверждения: (\d{6})", plain.get_content())
                    if plain
                    else None
                )
                if match:
                    with self.server.output.open("a", encoding="utf-8") as stream:  # type: ignore[attr-defined]
                        stream.write(json.dumps({"to": recipients, "code": match.group(1)}) + "\n")
                self.wfile.write(b"250 queued\r\n")
            elif upper.startswith(b"QUIT"):
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=1025)
    args = parser.parse_args()
    args.output.touch(mode=0o600, exist_ok=True)
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), SMTPHandler) as server:
        server.output = args.output  # type: ignore[attr-defined]
        server.serve_forever()


if __name__ == "__main__":
    main()
