#!/usr/bin/env python3
"""
Fetches current + historical BTC price data from mempool.space and writes it
to a small local JSON file (btc-stats.json) that the static site reads
directly (same-origin, so no browser CORS issues - mempool.space's API has
inconsistent CORS support across endpoints, so calling it directly from the
browser is unreliable; calling it from here, server-side, isn't subject to
CORS at all).

Run daily by the same GitHub Actions workflow that updates events.json.
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = "https://mempool.space/api/v1"
OUTPUT_PATH = "btc-stats.json"
MAX_HISTORY_POINTS = 800  # downsample if mempool.space's full history is larger than this


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def downsample(points, max_points):
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    return [points[int(i * step)] for i in range(max_points)] + [points[-1]]


def main():
    try:
        current = fetch_json(f"{BASE}/prices")
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to fetch current price: {exc}", file=sys.stderr)
        sys.exit(1)

    now_ts = int(time.time())
    ts_4y = now_ts - 4 * 365 * 24 * 3600
    ts_10y = now_ts - 10 * 365 * 24 * 3600

    def price_at(ts):
        try:
            data = fetch_json(f"{BASE}/historical-price?currency=USD&timestamp={ts}")
            return data["prices"][0]["USD"]
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to fetch historical price at {ts}: {exc}", file=sys.stderr)
            return None

    price_4y_ago = price_at(ts_4y)
    price_10y_ago = price_at(ts_10y)

    cagr_4y = None
    cagr_10y = None
    if price_4y_ago:
        cagr_4y = (pow(current["USD"] / price_4y_ago, 1 / 4) - 1) * 100
    if price_10y_ago:
        cagr_10y = (pow(current["USD"] / price_10y_ago, 1 / 10) - 1) * 100

    full_history = []
    try:
        hist = fetch_json(f"{BASE}/historical-price?currency=USD")
        points = [
            {"time": p["time"], "USD": p["USD"]}
            for p in hist.get("prices", [])
            if p.get("USD")
        ]
        points.sort(key=lambda p: p["time"])
        full_history = downsample(points, MAX_HISTORY_POINTS)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to fetch full price history: {exc}", file=sys.stderr)

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "price": {"usd": current.get("USD"), "aud": current.get("AUD")},
        "cagr4y": cagr_4y,
        "cagr10y": cagr_10y,
        "history": full_history,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote btc-stats.json: price=${current.get('USD')}, "
          f"cagr4y={cagr_4y}, cagr10y={cagr_10y}, history points={len(full_history)}")


if __name__ == "__main__":
    main()
