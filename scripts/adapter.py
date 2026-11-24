"""Pipeline event adapter: builds start/end/kpi events and POSTs them as JSON to an API.
 
Usage:
  python adapter.py start --pipeline-name NAME --pipeline-id ID [--start-time ISO]
  python adapter.py end   --pipeline-name NAME --pipeline-id ID --start-time ISO --status success
  python adapter.py kpi   --pipeline-name NAME --pipeline-id ID --kpi tests_total=120 --kpi coverage_pct=87.5
 
Defaults come from env vars: CONSUMER_URL, CONSUMER_TOKEN, PIPELINE_NAME, PIPELINE_ID, START_TIME.
If CONSUMER_URL is not set, events go to the public echo API https://httpbin.org/post.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
 
DEFAULT_URL = "https://httpbin.org/post"
 
 
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
 
 
def parse_kpi(text):
    name, sep, value = text.partition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"KPI must be name=value, got '{text}'")
    try:
        value = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"KPI value must be numeric, got '{text}'")
    return {"name": name, "value": value}
 
 
def build_event(args):
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": args.event,
        "timestamp": now_iso(),
        "pipeline_name": args.pipeline_name,
        "pipeline_id": args.pipeline_id,
    }
    if args.event in ("start", "end"):
        event["start_time"] = args.start_time or now_iso()
    if args.event == "end":
        event["end_time"] = now_iso()
        event["status"] = args.status
    if args.event == "kpi":
        for k in args.kpi:
            if k["name"] in event:
                raise SystemExit(f"KPI name '{k['name']}' clashes with an event field")
            event[k["name"]] = k["value"]
    return event
 
 
def send(event, url, token, retries=3):
    body = json.dumps(event).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "pipeline-adapter/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode()
                print(f"API replied {resp.status}")
                try:
                    reply = json.loads(text)
                    # Echo APIs (httpbin/postman-echo) return what we sent under "json"
                    print(json.dumps(reply.get("json", reply) if isinstance(reply, dict) else reply, indent=2))
                except json.JSONDecodeError:
                    print(text)
                return
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:  # other client errors won't succeed on retry
                raise SystemExit(f"API rejected event ({e.code}): {e.read().decode()}")
            err = e
        except urllib.error.URLError as e:
            err = e
        print(f"Attempt {attempt}/{retries} failed: {err}", file=sys.stderr)
        if attempt < retries:
            time.sleep(5)
    raise SystemExit("Failed to send event")
 
 
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("event", choices=["start", "end", "kpi"])
    p.add_argument("--pipeline-name", default=os.environ.get("PIPELINE_NAME"))
    p.add_argument("--pipeline-id", default=os.environ.get("PIPELINE_ID"))
    p.add_argument("--start-time", default=os.environ.get("START_TIME"), help="ISO-8601 UTC; defaults to now for start")
    p.add_argument("--status", help="pipeline status (required for end)")
    p.add_argument("--kpi", type=parse_kpi, action="append", default=[], help="name=value, repeatable")
    p.add_argument("--url", default=os.environ.get("CONSUMER_URL") or DEFAULT_URL)
    p.add_argument("--token", default=os.environ.get("CONSUMER_TOKEN"))
    p.add_argument("--dry-run", action="store_true", help="print the event without sending")
    args = p.parse_args()
 
    if not args.pipeline_name:
        p.error("--pipeline-name (or PIPELINE_NAME env) is required")
    if not args.pipeline_id:
        p.error("--pipeline-id (or PIPELINE_ID env) is required")
    if args.event == "end" and not args.status:
        p.error("--status is required for end events")
    if args.event == "kpi" and not args.kpi:
        p.error("at least one --kpi is required for kpi events")
 
    event = build_event(args)
    print(f"Sending {args.event} event to {args.url}:")
    print(json.dumps(event, indent=2))
 
    if not args.dry_run:
        send(event, args.url, args.token)
 
 
if __name__ == "__main__":
    main()
 
