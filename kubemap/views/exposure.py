import re
from collections import defaultdict

HOST_CALL = re.compile(r"\bHost\(([^)]*)\)")
PATH_CALL = re.compile(r"\bPath(?:Prefix)?\(([^)]*)\)")
BACKTICK = re.compile(r"`([^`]*)`")
AUTH_KEYS = {
    "basicAuth": "basic auth",
    "digestAuth": "digest auth",
    "forwardAuth": "forward auth",
    "ipAllowList": "IP allow-list",
    "ipWhiteList": "IP allow-list",
}
ENV_SUFFIXES = {"sandbox", "qa", "preprod", "beta"}


def _ns(obj) -> str:
    return obj["metadata"].get("namespace", "")


def _hosts_and_paths(match: str):
    hosts = [h for call in HOST_CALL.findall(match) for h in BACKTICK.findall(call)]
    paths = [p for call in PATH_CALL.findall(match) for p in BACKTICK.findall(call)]
    return hosts, paths


def _env(namespace: str) -> str:
    suffix = namespace.rsplit("-", 1)[-1]
    if suffix in ENV_SUFFIXES:
        return suffix
    return namespace


def _root(host: str) -> str:
    return ".".join(host.split(".")[-2:])


def _service_index(services, slices):
    ready, total, addrs = defaultdict(int), defaultdict(int), defaultdict(list)
    for s in slices:
        svc = (s["metadata"].get("labels") or {}).get("kubernetes.io/service-name")
        if not svc:
            continue
        k = (_ns(s), svc)
        for ep in s.get("endpoints") or []:
            total[k] += 1
            if (ep.get("conditions") or {}).get("ready") is not False:
                ready[k] += 1
            addrs[k] += ep.get("addresses") or []
    index = {}
    for s in services:
        k, spec = (_ns(s), s["metadata"]["name"]), s.get("spec") or {}
        if spec.get("type") == "ExternalName":
            index[k] = {"state": "external", "ready": 0, "total": 0, "external": spec.get("externalName")}
        elif not spec.get("selector"):
            index[k] = {"state": "external", "ready": ready[k], "total": total[k], "external": ",".join(sorted(set(addrs[k]))) or None}
        else:
            index[k] = {"state": "ok" if ready[k] > 0 else "down", "ready": ready[k], "total": total[k], "external": None}
    return index


def _target(ref, ns, svc_index):
    name = ref.get("name", "")
    tns = ref.get("namespace") or ns
    base = {"name": name, "namespace": tns, "port": ref.get("port")}
    if ref.get("kind") == "TraefikService":
        return {**base, "state": "unknown", "ready": 0, "total": 0, "external": None}
    info = svc_index.get((tns, name))
    if info is None:
        return {**base, "state": "missing", "ready": 0, "total": 0, "external": None}
    return {**base, **info}


def _row_status(targets) -> str:
    states = {t["state"] for t in targets}
    if states & {"down", "missing"}:
        return "down"
    if "external" in states:
        return "external"
    if not states or "unknown" in states:
        return "unknown"
    return "ok"


def _middlewares(refs, ns, index, depth=0):
    names, auth = [], set()
    for ref in refs or []:
        mns, name = ref.get("namespace") or ns, ref.get("name", "")
        names.append(name)
        spec = (index.get((mns, name)) or {}).get("spec") or {}
        auth |= {label for key, label in AUTH_KEYS.items() if key in spec}
        if "chain" in spec and depth < 5:
            sub_names, sub_auth = _middlewares((spec["chain"] or {}).get("middlewares"), mns, index, depth + 1)
            names += sub_names
            auth |= set(sub_auth)
    return names, sorted(auth)


def _find_cert(certs, ns, secret, host):
    for c in certs:
        if secret and _ns(c) == ns and (c.get("spec") or {}).get("secretName") == secret:
            return c
    for c in certs:
        for dn in (c.get("spec") or {}).get("dnsNames") or []:
            if dn == host or (dn.startswith("*.") and host.split(".", 1)[1:] == [dn[2:]]):
                return c
    return None


def _tls(tls_spec, ns, host, certs):
    if tls_spec is None:
        return {"enabled": False, "secret": None, "resolver": None, "expires": None, "ready": None}
    secret = tls_spec.get("secretName")
    cert = _find_cert(certs, ns, secret, host)
    status = (cert or {}).get("status") or {}
    ready = None
    if cert:
        ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions") or [])
    return {"enabled": True, "secret": secret, "resolver": tls_spec.get("certResolver"), "expires": status.get("notAfter"), "ready": ready}


def _row(**kw):
    host, scheme, ns = kw["host"], kw["scheme"], kw["namespace"]
    return {
        **kw,
        "url": f"{scheme}://{host}",
        "root": _root(host),
        "env": _env(ns),
        "status": _row_status(kw["targets"]),
    }


def build_exposure(res: dict) -> list[dict]:
    services, slices = res.get("services", []), res.get("endpointslices", [])
    svc_index = _service_index(services, slices)
    mw_index = {(_ns(m), m["metadata"]["name"]): m for m in res.get("middlewares", [])}
    certs = res.get("certificates", [])
    rows = []

    for ir in res.get("ingressroutes", []):
        ns, name, spec = _ns(ir), ir["metadata"]["name"], ir.get("spec") or {}
        scheme = "https" if "websecure" in (spec.get("entryPoints") or []) or "tls" in spec else "http"
        for i, route in enumerate(spec.get("routes") or []):
            hosts, paths = _hosts_and_paths(route.get("match", ""))
            targets = [_target(ref, ns, svc_index) for ref in route.get("services") or []]
            mw_names, auth = _middlewares(route.get("middlewares"), ns, mw_index)
            for host in sorted(set(hosts)):
                rows.append(_row(
                    id=f"{ns}/{name}#{i}/{host}", host=host, paths=paths, scheme=scheme, namespace=ns,
                    kind="IngressRoute", route=name, targets=targets, middlewares=mw_names, auth=auth,
                    tls=_tls(spec.get("tls"), ns, host, certs),
                ))

    for ing in res.get("ingresses", []):
        ns, name, spec = _ns(ing), ing["metadata"]["name"], ing.get("spec") or {}
        tls_by_host = {h: t for t in spec.get("tls") or [] for h in t.get("hosts") or []}
        for i, rule in enumerate(spec.get("rules") or []):
            host = rule.get("host")
            if not host:
                continue
            http_paths = (rule.get("http") or {}).get("paths") or []
            targets = []
            for p in http_paths:
                backend = (p.get("backend") or {}).get("service") or {}
                port = backend.get("port") or {}
                targets.append(_target({"name": backend.get("name", ""), "port": port.get("number") or port.get("name")}, ns, svc_index))
            tls_spec = tls_by_host.get(host)
            rows.append(_row(
                id=f"{ns}/{name}#{i}/{host}", host=host, paths=[p.get("path", "/") for p in http_paths],
                scheme="https" if tls_spec is not None else "http", namespace=ns, kind="Ingress", route=name,
                targets=targets, middlewares=[], auth=[], tls=_tls(tls_spec, ns, host, certs),
            ))

    return sorted(rows, key=lambda r: (r["root"], r["host"], r["paths"]))
