#!/usr/bin/env python3
"""
Update fx.json with the latest USD->CHF rate from Frankfurter (ECB).

Example:
  python3 scripts/update_fx_rates.py --output app/static/fx.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=CHF"


def fetch_rate(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-fx/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "rates" not in data or "CHF" not in data["rates"]:
        raise ValueError("Missing CHF rate in response")
    return data


def write_fx(output: Path, payload: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL, help="Frankfurter API URL")
    parser.add_argument(
        "--output",
        default="/brain/system/ingestion/metrics/fx.json",
        help="Output fx.json path",
    )
    parser.add_argument("--print", action="store_true", help="Print payload to stdout")
    args = parser.parse_args()

    try:
        data = fetch_rate(args.url)
    except Exception as exc:
        print(f"Failed to fetch FX rate: {exc}", file=sys.stderr)
        return 2

    rate = float(data["rates"]["CHF"])
    as_of = data.get("date") or datetime.utcnow().date().isoformat()

    payload = {
        "base": data.get("base", "USD"),
        "target": "CHF",
        "usd_chf": round(rate, 6),
        "as_of": as_of,
        "source": "Frankfurter (ECB reference rates)",
        "locale": "de-CH",
        "updated": datetime.utcnow().isoformat() + "Z",
    }

    if args.print:
        print(json.dumps(payload, indent=2))

    try:
        write_fx(Path(args.output), payload)
    except Exception as exc:
        print(f"Failed to write {args.output}: {exc}", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
