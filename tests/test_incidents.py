from datetime import datetime, timezone

from kubemap.views.incidents import build_events, build_incidents

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def obj(name, ns="prod", uid=None, **extra):
    return {"metadata": {"name": name, "namespace": ns, "uid": uid or name}, **extra}


def ref(kind, name, uid=None):
    return {"kind": kind, "name": name, "uid": uid or name, "controller": True}


def test_groups_application_readiness_and_crashing_pods_by_actual_owner():
    app = obj("web", spec={"replicas": 2}, status={"readyReplicas": 0})
    rs = obj("web-rs")
    rs["metadata"]["ownerReferences"] = [ref("Deployment", "web")]
    pods = []
    for i in range(2):
        p = obj(f"web-{i}", status={"phase": "Running", "containerStatuses": [{"state": {"waiting": {"reason": "ImagePullBackOff"}}}]})
        p["metadata"]["ownerReferences"] = [ref("ReplicaSet", "web-rs")]
        pods.append(p)
    result = build_incidents({"deployments": [app], "replicasets": [rs], "pods": pods}, {}, now=NOW)
    assert len(result["active"]) == 1
    group = result["active"][0]
    assert group["kind"] == "deployments" and group["name"] == "web"
    assert len(group["issues"]) == 3
    assert any(i["summary"] == "Image impossible à télécharger" for i in group["issues"])
    assert all(i["checks"] and i["explanation"] for i in group["issues"])


def test_terminal_failures_are_history_and_terminating_or_successful_pods_are_quiet():
    failed = obj("old", status={"phase": "Failed", "reason": "Evicted"})
    done = obj("done", status={"phase": "Succeeded"})
    deleting = obj("deleting", status={"phase": "Pending"})
    deleting["metadata"]["deletionTimestamp"] = "2026-10-15T11:00:00Z"
    result = build_incidents({"pods": [failed, done, deleting]}, {}, now=NOW)
    assert result["active"] == []
    assert result["history"][0]["issues"][0]["name"] == "old"


def test_pending_recent_oom_and_old_restarts_are_distinguished():
    pending = obj("pending", status={"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "lastTransitionTime": "2026-10-15T11:58:00Z"}]})
    def restarted(name, finished):
        return obj(name, status={"phase": "Running", "containerStatuses": [{"ready": True, "restartCount": 42, "state": {"running": {}}, "lastState": {"terminated": {"reason": "OOMKilled", "finishedAt": finished}}}]})
    result = build_incidents({"pods": [pending, restarted("recent", "2026-10-15T11:59:00Z"), restarted("old", "2026-10-14T11:00:00Z")]}, {}, now=NOW)
    issues = [i for g in result["active"] for i in g["issues"]]
    assert {i["name"] for i in issues} == {"pending", "recent"}
    assert next(i for i in issues if i["name"] == "recent")["reason"] == "OOMKilled"
    assert next(i for i in issues if i["name"] == "pending")["since"] == "2026-10-15T11:58:00Z"


def test_service_alerts_require_loaded_endpoints_and_ignore_external_services():
    services = [obj("internal", spec={"type": "ClusterIP", "selector": {"app": "web"}}), obj("external", spec={"type": "ExternalName"}), obj("manual", spec={"type": "ClusterIP"})]
    res = {"services": services, "endpointslices": []}
    assert build_incidents(res, {}, status={"services": "ok", "endpointslices": "unavailable"}, now=NOW)["active"] == []
    groups = build_incidents(res, {}, now=NOW)["active"]
    assert [g["name"] for g in groups] == ["internal"]
    res["endpointslices"] = [obj("slice", endpoints=[{"conditions": {"ready": True}}])]
    res["endpointslices"][0]["metadata"]["labels"] = {"kubernetes.io/service-name": "internal"}
    assert build_incidents(res, {}, now=NOW)["active"] == []


def test_recreated_owner_does_not_absorb_old_pod_failures():
    app = obj("web", uid="new", spec={"replicas": 1}, status={"readyReplicas": 1})
    p = obj("old", status={"phase": "Failed"})
    p["metadata"]["ownerReferences"] = [ref("Deployment", "web", "old")]
    result = build_incidents({"deployments": [app], "pods": [p]}, {}, now=NOW)
    assert result["active"] == []
    assert result["history"][0]["kind"] == "pods"


def test_events_normalize_series_times_sort_and_do_not_invent_dates():
    events = [obj("older", involvedObject=ref("Pod", "p"), firstTimestamp="2026-10-15T10:00:00Z", lastTimestamp="2026-10-15T10:30:00Z", count=3, type="Warning", reason="BackOff", message="retry"), obj("new", involvedObject=ref("Pod", "p"), eventTime="2026-10-15T11:00:00Z", series={"lastObservedTime": "2026-10-15T11:59:00Z", "count": 8}), obj("undated", involvedObject=ref("Pod", "p"), lastTimestamp="bad")]
    rows = build_events({"events": events})
    assert [r["id"] for r in rows] == ["new", "older", "undated"]
    assert rows[0]["count"] == 8 and rows[0]["timestamp"] == "2026-10-15T11:59:00Z"
    assert rows[-1]["timestamp"] is None
    assert rows[0]["object"]["kind"] == "pods"
    assert rows[0]["object"]["uid"] == "p"


def test_event_output_is_limited_and_excludes_extra_payload():
    event = obj("a", involvedObject=ref("Secret", "s"), message="hello", extraPrivate="not-for-ui")
    rows = build_events({"events": [{**event, "metadata": {"name": str(i), "namespace": "prod", "uid": str(i)}} for i in range(250)]})
    assert len(rows) == 200
    assert all("extraPrivate" not in e for e in rows)


def test_crash_loop_keeps_recent_oom_evidence_and_node_events_are_cluster_scoped():
    p = obj("crashing", status={"phase": "Running", "containerStatuses": [{"restartCount": 4, "state": {"waiting": {"reason": "CrashLoopBackOff"}}, "lastState": {"terminated": {"reason": "OOMKilled", "finishedAt": "2026-10-15T11:59:00Z"}}}]})
    issues = [i for g in build_incidents({"pods": [p]}, {}, now=NOW)["active"] for i in g["issues"]]
    assert {i["reason"] for i in issues} == {"CrashLoopBackOff", "OOMKilled"}
    event = obj("node-event", ns="default", involvedObject=ref("Node", "machine"), message="node condition")
    assert build_events({"events": [event]})[0]["object"]["namespace"] == ""
