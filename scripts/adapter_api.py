"""Sends a build event JSON file to the DummyJSON posts API (https://dummyjson.com/docs/posts).

DummyJSON's "add post" endpoint requires `title` and `userId` and drops unknown top-level
fields, so the build event is sent as a JSON object nested under `body`.

Usage:
  python adapter_consumer.py build_event.json
  python adapter_consumer.py build_event.json --url https://dummyjson.com/posts/add
"""
import argparse
import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "https://dummyjson.com/posts/add"
DEFAULT_USER_ID = 1


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("json_file", help="path to the build event JSON")
    p.add_argument("--url", default=os.environ.get("API_URL") or DEFAULT_URL)
    p.add_argument("--user-id", type=int, default=int(os.environ.get("API_USER_ID") or DEFAULT_USER_ID))
    return p.parse_args()


def build_post(event, user_id):
    """Wraps the build event in the post shape DummyJSON expects."""
    return {
        "title": f"Build event {event.get('buildId', 'unknown')}",
        "userId": user_id,
        "tags": ["build-event", str(event.get("status", "unknown"))],
        "body": event,
    }


def load_payload(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise SystemExit(f"File not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}")


def send_payload(payload, url):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "kpi-adapter-consumer/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode(errors="replace")
            print(f"API replied {resp.status}: {text}")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"API replied {exc.code}: {exc.read().decode(errors='replace')}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {url}: {exc.reason}")


def main():
    args = parse_args()
    event = load_payload(args.json_file)
    print(f"Sending build {event.get('buildId')} to {args.url}")
    reply = send_payload(build_post(event, args.user_id), args.url)
    echoed = reply.get("body") if isinstance(reply, dict) else None
    if not isinstance(echoed, dict) or echoed.get("buildId") != event.get("buildId"):
        raise SystemExit("API response did not echo the build event back")
    print(f"Created post id {reply.get('id')} for build {echoed['buildId']}")


if __name__ == "__main__":
    main()
