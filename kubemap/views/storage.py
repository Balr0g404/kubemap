from collections import defaultdict

from ..quantity import format_bytes, parse_bytes


def _ns(obj) -> str:
    return obj["metadata"].get("namespace", "")


def _containers(pod_spec):
    return (pod_spec.get("containers") or []) + (pod_spec.get("initContainers") or [])


def _pvcs(res):
    users = defaultdict(list)
    for pod in res.get("pods", []):
        for vol in (pod.get("spec") or {}).get("volumes") or []:
            claim = (vol.get("persistentVolumeClaim") or {}).get("claimName")
            if claim:
                users[(_ns(pod), claim)].append(pod["metadata"]["name"])
    out = []
    for pvc in res.get("pvcs", []):
        spec = pvc.get("spec") or {}
        request = ((spec.get("resources") or {}).get("requests") or {}).get("storage", "0")
        size = parse_bytes(request)
        out.append({
            "namespace": _ns(pvc), "name": pvc["metadata"]["name"], "size_bytes": size, "size": format_bytes(size),
            "phase": (pvc.get("status") or {}).get("phase"), "storageClass": spec.get("storageClassName"),
            "usedBy": sorted(users[(_ns(pvc), pvc["metadata"]["name"])]),
        })
    return sorted(out, key=lambda p: (-p["size_bytes"], p["namespace"], p["name"]))


def _databases(res):
    out = []
    for c in res.get("cnpg_clusters", []):
        spec, status = c.get("spec") or {}, c.get("status") or {}
        out.append({
            "namespace": _ns(c), "name": c["metadata"]["name"], "instances": spec.get("instances", 0),
            "ready": status.get("readyInstances", 0), "phase": status.get("phase"), "primary": status.get("currentPrimary"),
            "storage": (spec.get("storage") or {}).get("size"), "image": spec.get("imageName"),
        })
    return sorted(out, key=lambda d: (d["namespace"], d["name"]))


def _secret_refs(res):
    refs = defaultdict(set)

    def add(ns, secret, kind, name):
        if secret:
            refs[(ns, secret)].add((kind, name))

    for pod in res.get("pods", []):
        ns, spec = _ns(pod), pod.get("spec") or {}
        owner = next(iter(pod["metadata"].get("ownerReferences") or []), None)
        kind, name = (owner["kind"], owner["name"]) if owner else ("Pod", pod["metadata"]["name"])
        for vol in spec.get("volumes") or []:
            add(ns, (vol.get("secret") or {}).get("secretName"), kind, name)
        for ips in spec.get("imagePullSecrets") or []:
            add(ns, ips.get("name"), kind, name)
        for c in _containers(spec):
            for env in c.get("env") or []:
                add(ns, (((env.get("valueFrom") or {}).get("secretKeyRef")) or {}).get("name"), kind, name)
            for ef in c.get("envFrom") or []:
                add(ns, (ef.get("secretRef") or {}).get("name"), kind, name)
    for mw in res.get("middlewares", []):
        spec = mw.get("spec") or {}
        for key in ("basicAuth", "digestAuth"):
            add(_ns(mw), (spec.get(key) or {}).get("secret"), "Middleware", mw["metadata"]["name"])
    for ir in res.get("ingressroutes", []):
        add(_ns(ir), ((ir.get("spec") or {}).get("tls") or {}).get("secretName"), "IngressRoute", ir["metadata"]["name"])
    for cert in res.get("certificates", []):
        add(_ns(cert), (cert.get("spec") or {}).get("secretName"), "Certificate", cert["metadata"]["name"])
    return refs


def _secrets(res):
    refs = _secret_refs(res)
    out = []
    for s in res.get("secrets", []):
        meta = s["metadata"]
        used = sorted(refs[(_ns(s), meta["name"])])
        out.append({
            "namespace": _ns(s), "name": meta["name"], "created": meta.get("creationTimestamp"), "labels": meta.get("labels") or {},
            "usedBy": [{"kind": k, "name": n} for k, n in used], "unused": not used,
        })
    return sorted(out, key=lambda s: (s["namespace"], s["name"]))


def build_storage(res: dict) -> dict:
    return {"pvcs": _pvcs(res), "databases": _databases(res), "secrets": _secrets(res)}
