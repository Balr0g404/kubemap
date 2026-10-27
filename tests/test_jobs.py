from datetime import datetime, timezone

from kubemap.views.jobs import build_jobs

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def job(name, status=None, owner=None, ns="tsdb", created="2026-10-02T10:00:00Z", spec=None):
    meta = {"name": name, "namespace": ns, "creationTimestamp": created}
    if owner:
        meta["ownerReferences"] = [{"kind": "CronJob", "name": owner}]
    return {"metadata": meta, "spec": spec or {}, "status": status or {}}


def cron(name, schedule="0 1 * * *", ns="monitoring", **spec):
    return {"metadata": {"name": name, "namespace": ns}, "spec": {"schedule": schedule, **spec}, "status": {}}


def test_states():
    jobs = [
        job("run", {"active": 1, "startTime": "2026-10-02T11:00:00Z"}),
        job("ok", {"succeeded": 1, "startTime": "2026-10-02T09:00:00Z", "completionTime": "2026-10-02T09:05:00Z", "conditions": [{"type": "Complete", "status": "True"}]}),
        job("ko", {"failed": 3, "startTime": "2026-10-02T08:00:00Z", "conditions": [{"type": "Failed", "status": "True", "lastTransitionTime": "2026-10-02T08:10:00Z"}]}),
        job("wait"),
    ]
    out = build_jobs(jobs, [], NOW)
    assert [j["name"] for j in out["running"]] == ["run"]
    states = {j["name"]: j["state"] for j in out["running"] + out["recent"]}
    assert states == {"run": "running", "ok": "complete", "ko": "failed", "wait": "pending"}
    ko = next(j for j in out["recent"] if j["name"] == "ko")
    assert ko["end"] == "2026-10-02T08:10:00Z"


def test_owner_and_recent_ordering_and_cap():
    jobs = [job(f"j{i}", {"succeeded": 1, "completionTime": f"2026-10-02T{i % 10:02d}:00:00Z", "conditions": [{"type": "Complete", "status": "True"}]}, owner="nightly") for i in range(60)]
    out = build_jobs(jobs, [], NOW)
    assert len(out["recent"]) == 50
    assert out["recent"][0]["owner"] == "nightly"
    ends = [j["end"] for j in out["recent"]]
    assert ends == sorted(ends, reverse=True)


def test_cronjob_next_run():
    out = build_jobs([], [cron("nightly")], NOW)
    assert out["cronjobs"][0]["next"] == "2026-10-03T01:00:00+00:00"


def test_cronjob_suspended_and_invalid_schedule_have_no_next():
    out = build_jobs([], [cron("s", suspend=True), cron("bad", schedule="nope"), cron("tz", timeZone="Mars/Olympus")], NOW)
    assert [c["next"] for c in out["cronjobs"]] == [None, None, None]


def test_cronjob_timezone_is_applied():
    out = build_jobs([], [cron("paris", schedule="0 3 * * *", timeZone="Europe/Paris")], NOW)
    assert out["cronjobs"][0]["next"] == "2026-10-03T03:00:00+02:00"


def test_cronjob_status_fields():
    c = cron("c")
    c["status"] = {"active": [{"name": "x"}], "lastScheduleTime": "2026-10-02T01:00:00Z", "lastSuccessfulTime": "2026-10-01T01:00:00Z"}
    out = build_jobs([], [c], NOW)["cronjobs"][0]
    assert (out["active"], out["lastSchedule"], out["lastSuccess"]) == (1, "2026-10-02T01:00:00Z", "2026-10-01T01:00:00Z")
