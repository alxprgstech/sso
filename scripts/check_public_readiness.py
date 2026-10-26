"""Check production readiness from outside EC2, without credentials or redirects."""

from __future__ import annotations

import json
import ssl
import urllib.request

URL = "https://auth.alxprgs.tech/health/ready"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check() -> None:
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()), NoRedirect()
    )
    request = urllib.request.Request(URL, headers={"Accept": "application/json"})
    with opener.open(request, timeout=15) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ValueError("Unexpected readiness HTTP response")
        if json.loads(response.read(4096)) != {"status": "ready", "database": "connected"}:
            raise ValueError("Unexpected readiness payload")


def main() -> int:
    try:
        check()
    except (OSError, ValueError):
        print(f"Public readiness FAILED: {URL} (DNS/TLS/HTTP/readiness check)")
        return 1
    print(f"Public readiness OK: {URL} (HTTP 200, database connected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
