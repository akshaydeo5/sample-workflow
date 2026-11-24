"""Pipeline event adapter: builds start/end/kpi events and POSTs them as flat JSON to an API.
 
Usage:
  python adapter.py start --pipeline-name NAME --pipeline-id ID [--start-time TIME]
  python adapter.py end   --pipeline-name NAME --pipeline-id ID --start-time TIME --status success
  python adapter.py kpi   --pipeline-name NAME --pipeline-id ID --kpi tests_total=120 --kpi coverage_pct=87.5
 
Defaults come from env vars: API_URL, PIPELINE_NAME, PIPELINE_ID, START_TIME.
Times are UTC in the format YYYY-MM-DDTHH:MM:SS.
"""
import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
 
DEFAULT_URL = "https://httpbin.org/post"
 
 
def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
 
 
def parse_kpi(text):
    name, sep, value = text.partition("=")
    try:
        if not sep or not name:
            raise ValueError
        return name, float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"KPI must be name=<number>, got '{text}'")
 
 
def build_event(args):
    event = {
        "event_type": args.event,
        "timestamp": now(),
        "pipeline_name": args.pipeline_name,
        "pipeline_id": args.pipeline_id,
    }
    if args.event == "start":
        event["start_time"] = args.start_time or event["timestamp"]
    elif args.event == "end":
        event["start_time"] = args.start_time
        event["end_time"] = event["timestamp"]
        event["status"] = args.status
    else:
        for name, value in args.kpi:
            if name in event:
                raise SystemExit(f"KPI name '{name}' clashes with an event field")
            event[name] = value
    return event
 
 
def send(event, url):
    req = urllib.request.Request(
        url,
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "pipeline-adapter"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"API replied {resp.status}")
 
 
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("event", choices=["start", "end", "kpi"])
    p.add_argument("--pipeline-name", default=os.environ.get("PIPELINE_NAME"))
    p.add_argument("--pipeline-id", default=os.environ.get("PIPELINE_ID"))
    p.add_argument("--start-time", default=os.environ.get("START_TIME"))
    p.add_argument("--status", help="pipeline status (required for end)")
    p.add_argument("--kpi", type=parse_kpi, action="append", default=[], help="name=value, repeatable")
    p.add_argument("--url", default=os.environ.get("API_URL") or DEFAULT_URL)
    p.add_argument("--dry-run", action="store_true", help="print the event without sending")
    args = p.parse_args()
 
    if not args.pipeline_name or not args.pipeline_id:
        p.error("--pipeline-name and --pipeline-id (or PIPELINE_NAME/PIPELINE_ID env) are required")
    if args.event == "end" and not (args.status and args.start_time):
        p.error("--status and --start-time are required for end events")
    if args.event == "kpi" and not args.kpi:
        p.error("at least one --kpi is required for kpi events")
 
    event = build_event(args)
    print(json.dumps(event, indent=2))
    if not args.dry_run:
        send(event, args.url)
 
 
if __name__ == "__main__":
    main()
 
