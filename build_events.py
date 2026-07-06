#!/usr/bin/env python3
"""
Fetches the Bitcoin Sydney Meetup ical feed and converts it into a small
events.json file that the static site can read directly (no CORS issues,
since it's served from the same domain as the site itself).

Run daily by a GitHub Actions workflow; requires no external dependencies
beyond the Python standard library (zoneinfo needs Python 3.9+, which
GitHub's ubuntu-latest runners have by default).
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ICAL_URL = "https://www.meetup.com/Bitcoin_Sydney/events/ical/"
OUTPUT_PATH = "events.json"
DEFAULT_TZID = "Australia/Sydney"
MAX_EVENTS = 20


def fetch_ics(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


def unfold_lines(text: str):
    """ICS lines can be 'folded' across multiple physical lines; a
    continuation line starts with a space or tab and should be joined
    onto the previous logical line."""
    raw_lines = text.replace("\r\n", "\n").split("\n")
    unfolded = []
    for line in raw_lines:
        if line.startswith(" ") or line.startswith("\t"):
            if unfolded:
                unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def unescape_ics_text(value: str) -> str:
    return (
        value.replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\n", " ")
        .replace("\\N", " ")
        .replace("\\\\", "\\")
        .strip()
    )


def parse_events(ics_text: str):
    lines = unfold_lines(ics_text)
    events = []
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped == "BEGIN:VEVENT":
            current = {}
            continue
        if stripped == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue

        key, _, value = line.partition(":")
        key_parts = key.split(";")
        base_key = key_parts[0].upper()

        if base_key == "SUMMARY":
            current["title"] = unescape_ics_text(value)
        elif base_key == "DTSTART":
            current["start_raw"] = value.strip()
            for p in key_parts[1:]:
                if p.upper().startswith("TZID="):
                    current["tzid"] = p.split("=", 1)[1]
        elif base_key == "DTEND":
            current["end_raw"] = value.strip()
        elif base_key == "URL":
            current["url"] = value.strip()
        elif base_key == "LOCATION":
            current["location"] = unescape_ics_text(value)
    return events


def parse_ics_datetime(raw: str, tzid: str):
    raw = raw.strip()
    if raw.endswith("Z"):
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    else:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%S")
        dt = dt.replace(tzinfo=ZoneInfo(tzid or DEFAULT_TZID))
    return dt


def main():
    try:
        ics_text = fetch_ics(ICAL_URL)
    except Exception as exc:  # noqa: BLE001 - want to fail soft, not crash the workflow
        print(f"Failed to fetch ICS feed: {exc}", file=sys.stderr)
        sys.exit(1)

    raw_events = parse_events(ics_text)
    now = datetime.now(ZoneInfo(DEFAULT_TZID))

    upcoming = []
    for e in raw_events:
        if "start_raw" not in e or "title" not in e:
            continue
        tzid = e.get("tzid", DEFAULT_TZID)
        try:
            start_dt = parse_ics_datetime(e["start_raw"], tzid)
        except ValueError:
            continue
        if start_dt < now:
            continue

        end_dt = None
        if "end_raw" in e:
            try:
                end_dt = parse_ics_datetime(e["end_raw"], tzid)
            except ValueError:
                end_dt = None

        upcoming.append({
            "title": e["title"],
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat() if end_dt else None,
            "location": e.get("location", ""),
            "url": e.get("url", ""),
        })

    upcoming.sort(key=lambda x: x["start"])
    upcoming = upcoming[:MAX_EVENTS]

    payload = {
        "source": ICAL_URL,
        "updated": datetime.now(timezone.utc).isoformat(),
        "events": upcoming,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(upcoming)} upcoming event(s) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
