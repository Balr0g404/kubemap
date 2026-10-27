from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

RECENT_LIMIT = 50


def _condition(status: dict, kind: str):
    return next((c for c in status.get("conditions") or [] if c.get("type") == kind and c.get("status") == "True"), None)


def _job(job: dict) -> dict:
    meta, spec, status = job["metadata"], job.get("spec") or {}, job.get("status") or {}
    failed, complete = _condition(status, "Failed"), _condition(status, "Complete")
    if failed:
        state, end = "failed", failed.get("lastTransitionTime")
    elif complete:
        state, end = "complete", status.get("completionTime")
    elif status.get("active"):
        state, end = "running", None
    else:
        state, end = "pending", None
    owner = next((o["name"] for o in meta.get("ownerReferences") or [] if o.get("kind") == "CronJob"), None)
    return {
        "namespace": meta.get("namespace", ""),
        "name": meta["name"],
        "owner": owner,
        "state": state,
        "active": status.get("active", 0),
        "succeeded": status.get("succeeded", 0),
        "failed": status.get("failed", 0),
        "start": status.get("startTime") or meta.get("creationTimestamp"),
        "end": end,
        "completions": spec.get("completions"),
        "backoffLimit": spec.get("backoffLimit"),
    }


def _next_run(spec: dict, now: datetime):
    if spec.get("suspend"):
        return None
    try:
        tz = ZoneInfo(spec["timeZone"]) if spec.get("timeZone") else timezone.utc
        return croniter(spec["schedule"], now.astimezone(tz)).get_next(datetime).isoformat()
    except (ValueError, KeyError, LookupError):
        return None


def _cron(cj: dict, now: datetime) -> dict:
    meta, spec, status = cj["metadata"], cj.get("spec") or {}, cj.get("status") or {}
    return {
        "namespace": meta.get("namespace", ""),
        "name": meta["name"],
        "schedule": spec.get("schedule"),
        "timezone": spec.get("timeZone"),
        "suspend": bool(spec.get("suspend")),
        "active": len(status.get("active") or []),
        "lastSchedule": status.get("lastScheduleTime"),
        "lastSuccess": status.get("lastSuccessfulTime"),
        "next": _next_run(spec, now),
    }


def build_jobs(jobs, cronjobs, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    items = [_job(j) for j in jobs]
    running = sorted((j for j in items if j["state"] == "running"), key=lambda j: j["start"] or "")
    others = [j for j in items if j["state"] != "running"]
    recent = sorted(others, key=lambda j: j["end"] or j["start"] or "", reverse=True)[:RECENT_LIMIT]
    crons = sorted((_cron(c, now) for c in cronjobs), key=lambda c: (c["namespace"], c["name"]))
    return {"running": running, "recent": recent, "cronjobs": crons}
