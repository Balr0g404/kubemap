from collections import Counter, defaultdict
from fnmatch import fnmatch

from ..quantity import parse_bytes, parse_cpu

BAD_WAITING = {
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerError",
    "CreateContainerConfigError", "InvalidImageName", "RunContainerError",
}
LOAD_THRESHOLD = 85


def _ns(obj) -> str:
    return obj["metadata"].get("namespace", "")


def pod_problem(pod: dict):
    status = pod.get("status") or {}
    for c in (status.get("containerStatuses") or []) + (status.get("initContainerStatuses") or []):
        reason = ((c.get("state") or {}).get("waiting") or {}).get("reason")
        if reason in BAD_WAITING:
            return reason
    if status.get("phase") == "Failed":
        return status.get("reason") or "Failed"
    return None


def _node_ready(node: dict) -> bool:
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in (node.get("status") or {}).get("conditions") or [])


def _pct(used, total):
    return round(used / total * 100) if total else None


def _node_load(node, metrics):
    usage = metrics.get(node["metadata"]["name"])
    alloc = (node.get("status") or {}).get("allocatable") or {}
    if not usage or "cpu" not in alloc or "memory" not in alloc:
        return None, None
    return _pct(usage["cpu"], parse_cpu(alloc["cpu"])), _pct(usage["memory"], parse_bytes(alloc["memory"]))


def _condition(obj, kind):
    return next((c for c in (obj.get("status") or {}).get("conditions") or [] if c.get("type") == kind), None)


def build_anomalies(res: dict, metrics: dict) -> list[dict]:
    out = []

    def add(kind, obj, severity, reason):
        out.append({"kind": kind, "namespace": _ns(obj), "name": obj["metadata"]["name"], "severity": severity, "reason": reason})

    for node in res.get("nodes", []):
        pct_cpu, pct_mem = _node_load(node, metrics)
        if not _node_ready(node):
            add("Node", node, "bad", "NotReady")
        elif (pct_cpu or 0) >= LOAD_THRESHOLD or (pct_mem or 0) >= LOAD_THRESHOLD:
            add("Node", node, "warn", f"charge CPU {pct_cpu}% · RAM {pct_mem}%")
    for pod in res.get("pods", []):
        reason = pod_problem(pod)
        if reason:
            add("Pod", pod, "bad", reason)
    for kind, key in (("Deployment", "deployments"), ("StatefulSet", "statefulsets")):
        for w in res.get(key, []):
            desired, ready = (w.get("spec") or {}).get("replicas", 1), (w.get("status") or {}).get("readyReplicas", 0)
            if desired and ready < desired:
                add(kind, w, "warn", f"{ready}/{desired} prêts")
    for ds in res.get("daemonsets", []):
        status = ds.get("status") or {}
        desired, ready = status.get("desiredNumberScheduled", 0), status.get("numberReady", 0)
        if desired and ready < desired:
            add("DaemonSet", ds, "warn", f"{ready}/{desired} prêts")
    for pvc in res.get("pvcs", []):
        phase = (pvc.get("status") or {}).get("phase")
        if phase != "Bound":
            add("PersistentVolumeClaim", pvc, "warn", phase or "inconnu")
    for c in res.get("cnpg_clusters", []):
        want, ready = (c.get("spec") or {}).get("instances", 0), (c.get("status") or {}).get("readyInstances", 0)
        if ready < want:
            add("Cluster", c, "warn", f"{ready}/{want} instances prêtes")
    for hr in res.get("helmreleases", []):
        cond = _condition(hr, "Ready")
        if cond and cond.get("status") == "False":
            add("HelmRelease", hr, "warn", (cond.get("message") or "non prêt")[:120])
    return sorted(out, key=lambda a: (a["severity"] != "bad", a["kind"], a["namespace"], a["name"]))


def build_overview(res: dict, metrics: dict) -> dict:
    pods = res.get("pods", [])
    phases = Counter((p.get("status") or {}).get("phase") for p in pods)
    counts = {
        "nodes": len(res.get("nodes", [])), "namespaces": len(res.get("namespaces", [])), "pods": len(pods),
        "pods_running": phases["Running"], "pods_pending": phases["Pending"], "pods_failed": phases["Failed"],
        "pods_succeeded": phases["Succeeded"], "deployments": len(res.get("deployments", [])),
        "statefulsets": len(res.get("statefulsets", [])), "daemonsets": len(res.get("daemonsets", [])),
        "services": len(res.get("services", [])), "pvcs": len(res.get("pvcs", [])),
        "jobs_running": sum(1 for j in res.get("jobs", []) if (j.get("status") or {}).get("active")),
    }
    nodes = []
    for n in sorted(res.get("nodes", []), key=lambda n: n["metadata"]["name"]):
        cpu_pct, mem_pct = _node_load(n, metrics)
        info, usage = (n.get("status") or {}).get("nodeInfo") or {}, metrics.get(n["metadata"]["name"]) or {}
        ip = next((a["address"] for a in (n.get("status") or {}).get("addresses") or [] if a.get("type") == "InternalIP"), None)
        nodes.append({
            "name": n["metadata"]["name"], "ready": _node_ready(n), "cpu_pct": cpu_pct, "mem_pct": mem_pct,
            "cpu_m": usage.get("cpu"), "mem_bytes": usage.get("memory"), "version": info.get("kubeletVersion"),
            "os": info.get("osImage"), "ip": ip, "created": n["metadata"].get("creationTimestamp"),
        })
    per_ns = defaultdict(lambda: [0, 0])
    for p in pods:
        per_ns[_ns(p)][0] += 1
        per_ns[_ns(p)][1] += 1 if pod_problem(p) else 0
    by_ns = sorted(({"namespace": ns, "total": t, "bad": b} for ns, (t, b) in per_ns.items()), key=lambda r: (-r["total"], r["namespace"]))
    return {"counts": counts, "nodes": nodes, "pods_by_namespace": by_ns}


def build_map(res: dict, exposure: list[dict], layers: list[dict]) -> list[dict]:
    pods, bad, workloads, pvcs, hosts = Counter(), Counter(), Counter(), Counter(), Counter(r["namespace"] for r in exposure)
    for p in res.get("pods", []):
        pods[_ns(p)] += 1
        bad[_ns(p)] += 1 if pod_problem(p) else 0
    for key in ("deployments", "statefulsets", "daemonsets"):
        for w in res.get(key, []):
            workloads[_ns(w)] += 1
    for pvc in res.get("pvcs", []):
        pvcs[_ns(pvc)] += 1

    grouped = {layer["name"]: [] for layer in layers}
    grouped["Autres"] = []
    for ns in sorted(n["metadata"]["name"] for n in res.get("namespaces", [])):
        layer = next((l["name"] for l in layers if any(fnmatch(ns, pat) for pat in l["namespaces"])), "Autres")
        grouped[layer].append({"name": ns, "pods": pods[ns], "bad": bad[ns], "workloads": workloads[ns], "hosts": hosts[ns], "pvcs": pvcs[ns]})
    return [{"name": name, "namespaces": items} for name, items in grouped.items() if items]
