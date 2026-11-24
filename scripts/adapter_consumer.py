"""Pipeline event adapter: sends the pipeline run as a build event to the consumer service.

The consumer service (POST /api/v1/events/build) expects the full picture of a build on
every call, so the adapter keeps the build in a small state file between workflow steps
and re-sends it after each change:

  start  -> build saved as "running"
  kpi    -> code quality added, still "running"
  end    -> build saved as "passed" / "failed" / "canceled" with its end time

Usage:
  python adapter.py start --release-id R26.01 --ecm-code IMPLEMENT
  python adapter.py kpi   --kpi lines_of_code=12000 --kpi violations=3 --kpi duplication_percent=1.5 \
                          --kpi complexity=4.2 --kpi unit_test_count=120 --kpi coverage_percent=87.5
  python adapter.py end   --status success

Defaults come from env vars: API_URL, BUILD_ID, PIPELINE_ID, PIPELINE_NAME, RELEASE_ID,
ECM_CODE, BUILD_STATE_FILE, and the GitHub Actions variables (GITHUB_RUN_ID, ...).
The release and its ECM must already be loaded in the consumer service.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_URL = "http://localhost:8004/api/v1/events/build"

CODE_QUALITY_FIELDS = {
    "lines_of_code": ("linesOfCode", int),
    "violations": ("violations", int),
    "duplication_percent": ("duplicationPercent", float),
    "complexity": ("complexity", float),
    "unit_test_count": ("unitTestCount", int),
    "coverage_percent": ("coveragePercent", float),
}

# GitHub job.status values -> consumer service build status
STATUS_MAP = {
    "success": "passed",
    "passed": "passed",
    "failure": "failed",
    "failed": "failed",
    "cancelled": "canceled",
    "canceled": "canceled",
}


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text):
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_kpi(text):
    name, sep, value = text.partition("=")
    if name not in CODE_QUALITY_FIELDS:
        raise argparse.ArgumentTypeError(
            f"unknown KPI '{name}', expected one of: {', '.join(CODE_QUALITY_FIELDS)}"
        )
    key, cast = CODE_QUALITY_FIELDS[name]
    try:
        if not sep:
            raise ValueError
        number = float(value)
        return key, int(number) if cast is int else number
    except ValueError:
        raise argparse.ArgumentTypeError(f"KPI must be name=<number>, got '{text}'")


def default_build_id():
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        return None
    return f"GH-{run_id}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"


def default_state_file():
    folder = os.environ.get("RUNNER_TEMP") or "."
    return os.path.join(folder, "pipeline-build.json")


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_state(path, build):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build, f, indent=2)


def build_event(args, build):
    if args.event == "start" or build is None:
        start = parse_time(args.start_time) if args.start_time else now()
        build = {
            "buildId": args.build_id,
            "pipelineId": args.pipeline_id,
            "pipelineName": args.pipeline_name,
            "releaseId": args.release_id,
            "ecm": {"ecmCode": args.ecm_code},
            "status": "running",
            "startTime": iso(start),
            "jobs": [],
            "logs": [],
            "codeQuality": None,
        }

    if args.event == "kpi":
        quality = dict(build.get("codeQuality") or {})
        quality.update(dict(args.kpi))
        build["codeQuality"] = quality

    elif args.event == "end":
        end = now()
        build["status"] = STATUS_MAP[args.status.lower()]
        build["endTime"] = iso(end)
        build["durationSeconds"] = max(0, int((end - parse_time(build["startTime"])).total_seconds()))
        if build["status"] == "failed":
            build["failure"] = {"failedStep": args.failed_step, "reason": args.reason}
        else:
            build.pop("failure", None)

    return build


def payload_for(build):
    # Code quality is only sent once every field is known; the service rejects partial values.
    payload = dict(build)
    quality = payload.get("codeQuality")
    if quality and set(quality) != {key for key, _ in CODE_QUALITY_FIELDS.values()}:
        missing = sorted({key for key, _ in CODE_QUALITY_FIELDS.values()} - set(quality))
        print(f"warning: code quality incomplete (missing {', '.join(missing)}), not sent", file=sys.stderr)
        payload["codeQuality"] = None
    return payload


def send(payload, url):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "pipeline-adapter"},
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
    env = os.environ.get
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("event", choices=["start", "end", "kpi"])
    p.add_argument("--build-id", default=env("BUILD_ID") or default_build_id())
    p.add_argument("--pipeline-id", default=env("PIPELINE_ID"))
    p.add_argument("--pipeline-name", default=env("PIPELINE_NAME") or env("GITHUB_WORKFLOW"))
    p.add_argument("--release-id", default=env("RELEASE_ID"))
    p.add_argument("--ecm-code", default=env("ECM_CODE"))
    p.add_argument("--start-time", default=env("START_TIME"), help="ISO time, defaults to now (start only)")
    p.add_argument("--status", help="success / failure / cancelled (required for end)")
    p.add_argument("--failed-step", default=env("FAILED_STEP") or "unknown", help="used when status is failure")
    p.add_argument("--reason", default=env("FAILURE_REASON") or "Pipeline job failed", help="used when status is failure")
    p.add_argument("--kpi", type=parse_kpi, action="append", default=[],
                   help=f"name=value, repeatable; names: {', '.join(CODE_QUALITY_FIELDS)}")
    p.add_argument("--url", default=env("API_URL") or DEFAULT_URL)
    p.add_argument("--state-file", default=env("BUILD_STATE_FILE") or default_state_file())
    p.add_argument("--dry-run", action="store_true", help="print the event without sending")
    args = p.parse_args()

    args.pipeline_id = args.pipeline_id or (args.pipeline_name or "").upper().replace(" ", "_") or None
    build = None if args.event == "start" else load_state(args.state_file)
    if build is None:
        missing = [name for name in ("build_id", "pipeline_id", "pipeline_name", "release_id", "ecm_code")
                   if not getattr(args, name)]
        if missing:
            p.error("missing " + ", ".join("--" + m.replace("_", "-") for m in missing)
                    + " (or the matching env vars)")
    if args.event == "end":
        if not args.status:
            p.error("--status is required for end events")
        if args.status.lower() not in STATUS_MAP:
            p.error(f"--status must be one of: {', '.join(STATUS_MAP)}")
    if args.event == "kpi" and not args.kpi:
        p.error("at least one --kpi is required for kpi events")

    build = build_event(args, build)
    save_state(args.state_file, build)
    payload = payload_for(build)
    print(json.dumps(payload, indent=2))
    if not args.dry_run:
        send(payload, args.url)


if __name__ == "__main__":
    main()
