from kubemap.views import build_views
from kubemap.views.health import build_anomalies, build_map, build_overview


def pod(name, ns="app", phase="Running", waiting=None, labels=None):
    status = {"phase": phase}
    if waiting:
        status["containerStatuses"] = [{"state": {"waiting": {"reason": waiting}}}]
    return {"metadata": {"name": name, "namespace": ns, "labels": labels or {}}, "status": status}


def node(name, ready="True", cpu="8", mem="64Gi"):
    return {"metadata": {"name": name, "creationTimestamp": "2026-01-01T00:00:00Z"},
            "status": {"conditions": [{"type": "Ready", "status": ready}], "allocatable": {"cpu": cpu, "memory": mem},
                       "nodeInfo": {"kubeletVersion": "v1.35.2", "osImage": "Ubuntu"}, "addresses": [{"type": "InternalIP", "address": "10.0.0.1"}]}}


def test_pod_problems_and_pending_pod_without_container_statuses():
    res = {"pods": [pod("ok"), pod("crash", waiting="CrashLoopBackOff"), pod("dead", phase="Failed"), pod("pending", phase="Pending"), pod("done", phase="Succeeded")]}
    got = {(a["name"], a["reason"]) for a in build_anomalies(res, {})}
    assert got == {("crash", "CrashLoopBackOff"), ("dead", "Failed")}


def test_workloads_not_ready():
    res = {
        "deployments": [{"metadata": {"name": "d", "namespace": "a"}, "spec": {"replicas": 3}, "status": {"readyReplicas": 1}},
                        {"metadata": {"name": "off", "namespace": "a"}, "spec": {"replicas": 0}, "status": {}}],
        "statefulsets": [{"metadata": {"name": "s", "namespace": "a"}, "spec": {"replicas": 1}, "status": {}}],
        "daemonsets": [{"metadata": {"name": "ds", "namespace": "a"}, "status": {"desiredNumberScheduled": 4, "numberReady": 4}}],
    }
    got = {(a["kind"], a["name"], a["reason"]) for a in build_anomalies(res, {})}
    assert got == {("Deployment", "d", "1/3 prêts"), ("StatefulSet", "s", "0/1 prêts")}


def test_nodes_not_ready_or_loaded():
    res = {"nodes": [node("n1", ready="False"), node("n2"), node("n3")]}
    metrics = {"n2": {"cpu": 7500, "memory": 10 * 1024**3}, "n3": {"cpu": 1000, "memory": 10 * 1024**3}}
    got = {(a["name"], a["severity"]) for a in build_anomalies(res, metrics)}
    assert got == {("n1", "bad"), ("n2", "warn")}


def test_pvc_cnpg_and_helmrelease_anomalies():
    res = {
        "pvcs": [{"metadata": {"name": "p", "namespace": "a"}, "status": {"phase": "Pending"}}],
        "cnpg_clusters": [{"metadata": {"name": "pg", "namespace": "a"}, "spec": {"instances": 3}, "status": {"readyInstances": 2, "phase": "Cluster in healthy state"}}],
        "helmreleases": [{"metadata": {"name": "h", "namespace": "flux-system"}, "status": {"conditions": [{"type": "Ready", "status": "False", "message": "boom"}]}}],
    }
    got = {a["kind"] for a in build_anomalies(res, {})}
    assert got == {"PersistentVolumeClaim", "Cluster", "HelmRelease"}


def test_overview_counts_and_node_percentages():
    res = {"nodes": [node("n1")], "namespaces": [{"metadata": {"name": "app"}}], "pods": [pod("a"), pod("b", phase="Pending"), pod("c", waiting="ImagePullBackOff")]}
    ov = build_overview(res, {"n1": {"cpu": 4000, "memory": 32 * 1024**3}})
    assert ov["counts"]["pods"] == 3 and ov["counts"]["pods_pending"] == 1 and ov["counts"]["nodes"] == 1
    n = ov["nodes"][0]
    assert (n["cpu_pct"], n["mem_pct"], n["ready"], n["ip"]) == (50, 50, True, "10.0.0.1")
    assert ov["pods_by_namespace"] == [{"namespace": "app", "total": 3, "bad": 1}]


def test_node_without_metrics_has_none_percentages():
    ov = build_overview({"nodes": [node("n1")]}, {})
    assert ov["nodes"][0]["cpu_pct"] is None


def test_map_groups_namespaces_by_layer_with_fallback():
    res = {"namespaces": [{"metadata": {"name": "tsdb"}}, {"metadata": {"name": "demo-app-qa"}}, {"metadata": {"name": "mystery"}}],
           "pods": [pod("a", "tsdb"), pod("b", "tsdb", waiting="CrashLoopBackOff")],
           "deployments": [{"metadata": {"name": "d", "namespace": "demo-app-qa"}, "spec": {}, "status": {}}]}
    layers = [{"name": "Données", "namespaces": ["tsdb"]}, {"name": "Applications", "namespaces": ["demo-app-*"]}]
    out = build_map(res, [{"namespace": "tsdb"}], layers)
    assert [layer["name"] for layer in out] == ["Données", "Applications", "Autres"]
    tsdb = out[0]["namespaces"][0]
    assert (tsdb["pods"], tsdb["bad"], tsdb["hosts"]) == (2, 1, 1)
    assert out[1]["namespaces"][0]["workloads"] == 1
    assert out[2]["namespaces"][0]["name"] == "mystery"


def test_build_views_has_all_sections_on_empty_input():
    views = build_views({}, {}, [])
    assert set(views) == {"overview", "anomalies", "incidents", "events", "map", "exposure", "jobs", "storage"}
