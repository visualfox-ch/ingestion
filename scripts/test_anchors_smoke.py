"""Simple smoke test for anchors endpoints."""

import os
import sys
import requests

BASE_URL = os.getenv("ANCHORS_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("ANCHORS_API_KEY")


def check_status(label: str, resp: requests.Response, expected: int) -> bool:
    ok = resp.status_code == expected
    status = "ok" if ok else f"fail (got {resp.status_code}, expected {expected})"
    print(f"{label}: {status}")
    return ok


def main() -> int:
    ok = True
    stats_url = f"{BASE_URL}/anchors/consciousness-stats"

    # No key should be unauthorized when ANCHORS_API_KEY is configured server-side.
    no_key_resp = requests.get(stats_url, timeout=10)
    ok &= check_status("no-key", no_key_resp, 401)

    if not API_KEY:
        print("ANCHORS_API_KEY not set in environment. Skipping auth success check.")
        return 0 if ok else 1

    with_key_resp = requests.get(
        stats_url,
        headers={"X-API-Key": API_KEY},
        timeout=10,
    )
    ok &= check_status("with-key", with_key_resp, 200)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
