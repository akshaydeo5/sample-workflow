"""Sends a build event JSON file to the consumer service.

Usage:
  python adapter_consumer.py build_event.json
  python adapter_consumer.py build_event.json --url http://localhost:8004/api/v1/events/build
"""
import argparse
import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:8004/api/v1/events/build"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("json_file", help="path to the build event JSON")
    p.add_argument("--url", default=os.environ.get("API_URL") or DEFAULT_URL)
    return p.parse_args()


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
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"API replied {resp.status}: {resp.read().decode(errors='replace')}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"API replied {exc.code}: {exc.read().decode(errors='replace')}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {url}: {exc.reason}")


def main():
    args = parse_args()
    payload = load_payload(args.json_file)
    print(f"Sending build {payload.get('buildId')} to {args.url}")
    send_payload(payload, args.url)


if __name__ == "__main__":
    main()
