from kubemap.views.exposure import build_exposure


def meta(name, ns="app", **labels):
    return {"name": name, "namespace": ns, "labels": labels}


def svc(name, ns="app", selector=True, type_="ClusterIP", external=None):
    spec = {"type": type_}
    if selector:
        spec["selector"] = {"a": "b"}
    if external:
        spec["externalName"] = external
    return {"metadata": meta(name, ns), "spec": spec}


def eps(service, ns="app", ready=1, notready=0, addresses=("10.0.0.1",)):
    endpoints = [{"addresses": [addresses[0]], "conditions": {"ready": True}}] * ready
    endpoints += [{"addresses": [addresses[0]], "conditions": {"ready": False}}] * notready
    return {"metadata": meta(f"{service}-x", ns, **{"kubernetes.io/service-name": service}), "endpoints": endpoints}


def route(match, services, middlewares=None):
    r = {"match": match, "services": services}
    if middlewares:
        r["middlewares"] = middlewares
    return r


def ingressroute(name, routes, ns="app", entry=("websecure",), tls=None):
    spec = {"entryPoints": list(entry), "routes": routes}
    if tls is not None:
        spec["tls"] = tls
    return {"metadata": meta(name, ns), "spec": spec}


def test_basic_route_with_ready_service():
    res = {
        "ingressroutes": [ingressroute("web", [route("Host(`a.example.com`) && PathPrefix(`/api`)", [{"name": "front", "port": 80}])])],
        "services": [svc("front")],
        "endpointslices": [eps("front", ready=2)],
    }
    (row,) = build_exposure(res)
    assert row["host"] == "a.example.com"
    assert row["paths"] == ["/api"]
    assert row["url"] == "https://a.example.com"
    assert row["root"] == "example.com"
    assert row["status"] == "ok"
    assert row["targets"][0]["ready"] == 2


def test_multiple_hosts_in_one_host_call_and_or_operator():
    res = {"ingressroutes": [ingressroute("web", [route("Host(`a.x.io`, `b.x.io`) || Host(`c.x.io`)", [{"name": "s", "port": 80}])])]}
    hosts = sorted(r["host"] for r in build_exposure(res))
    assert hosts == ["a.x.io", "b.x.io", "c.x.io"]


def test_route_without_host_or_with_regexp_only_is_skipped_without_error():
    res = {"ingressroutes": [ingressroute("web", [
        route("PathPrefix(`/x`)", [{"name": "s", "port": 80}]),
        route("HostRegexp(`^.+\\.x\\.io$`)", [{"name": "s", "port": 80}]),
        {"match": "Host(`ok.x.io`)"},
    ])]}
    assert [r["host"] for r in build_exposure(res)] == ["ok.x.io"]


def test_missing_service_and_no_ready_endpoints_are_down():
    res = {
        "ingressroutes": [ingressroute("web", [
            route("Host(`gone.x.io`)", [{"name": "nope", "port": 80}]),
            route("Host(`idle.x.io`)", [{"name": "idle", "port": 80}]),
        ])],
        "services": [svc("idle")],
        "endpointslices": [eps("idle", ready=0, notready=1)],
    }
    rows = {r["host"]: r for r in build_exposure(res)}
    assert rows["gone.x.io"]["targets"][0]["state"] == "missing"
    assert rows["gone.x.io"]["status"] == "down"
    assert rows["idle.x.io"]["status"] == "down"


def test_selectorless_and_externalname_services_are_external():
    res = {
        "ingressroutes": [ingressroute("sim", [
            route("Host(`sim.x.io`)", [{"name": "taskboard", "port": 8010}]),
            route("Host(`demo.x.io`)", [{"name": "storefront", "port": 80}]),
        ], ns="simulation")],
        "services": [svc("taskboard", "simulation", selector=False), svc("storefront", "simulation", type_="ExternalName", external="10.8.1.100")],
        "endpointslices": [eps("taskboard", "simulation", addresses=("192.168.0.50",))],
    }
    rows = {r["host"]: r for r in build_exposure(res)}
    assert rows["sim.x.io"]["status"] == "external"
    assert rows["sim.x.io"]["targets"][0]["external"] == "192.168.0.50"
    assert rows["demo.x.io"]["targets"][0]["external"] == "10.8.1.100"


def test_traefikservice_target_is_unknown():
    res = {"ingressroutes": [ingressroute("web", [route("Host(`t.x.io`)", [{"name": "wrr", "kind": "TraefikService"}])])]}
    (row,) = build_exposure(res)
    assert row["status"] == "unknown"


def test_auth_middlewares_including_chain():
    res = {
        "ingressroutes": [ingressroute("sim", [route("Host(`s.x.io`)", [{"name": "s", "port": 80}], [{"name": "chain"}, {"name": "ghost"}])], ns="simulation")],
        "middlewares": [
            {"metadata": meta("chain", "simulation"), "spec": {"chain": {"middlewares": [{"name": "basic"}]}}},
            {"metadata": meta("basic", "simulation"), "spec": {"basicAuth": {"secret": "authsecret"}}},
        ],
    }
    (row,) = build_exposure(res)
    assert row["auth"] == ["basic auth"]
    assert row["middlewares"] == ["chain", "basic", "ghost"]


def test_tls_expiry_from_certificate_secret_and_wildcard():
    cert = {"metadata": meta("c", "app"), "spec": {"secretName": "tls-secret", "dnsNames": ["*.x.io"]}, "status": {"notAfter": "2026-12-01T00:00:00Z", "conditions": [{"type": "Ready", "status": "True"}]}}
    res = {
        "ingressroutes": [ingressroute("web", [route("Host(`a.x.io`)", [{"name": "s", "port": 80}])], tls={"secretName": "tls-secret"}),
                          ingressroute("other", [route("Host(`b.x.io`)", [{"name": "s", "port": 80}])], tls={})],
        "certificates": [cert],
    }
    rows = {r["host"]: r for r in build_exposure(res)}
    assert rows["a.x.io"]["tls"] == {"enabled": True, "secret": "tls-secret", "resolver": None, "expires": "2026-12-01T00:00:00Z", "ready": True}
    assert rows["b.x.io"]["tls"]["expires"] == "2026-12-01T00:00:00Z"


def test_scheme_http_when_only_web_entrypoint_and_no_tls():
    res = {"ingressroutes": [ingressroute("web", [route("Host(`h.x.io`)", [{"name": "s", "port": 80}])], entry=("web",))]}
    assert build_exposure(res)[0]["url"] == "http://h.x.io"


def test_environment_from_namespace():
    def row(ns):
        res = {"ingressroutes": [ingressroute("w", [route("Host(`h.x.io`)", [{"name": "s", "port": 80}])], ns=ns)]}
        return build_exposure(res)[0]["env"]
    assert row("production") == "production"
    assert row("demo-app-qa") == "qa"
    assert row("demo-app-sandbox") == "sandbox"
    assert row("airflow") == "airflow"


def test_networking_ingress_rows():
    ing = {
        "metadata": meta("ing", "metabase"),
        "spec": {"tls": [{"hosts": ["m.x.io"], "secretName": "m-tls"}], "rules": [{"host": "m.x.io", "http": {"paths": [{"path": "/", "backend": {"service": {"name": "mb", "port": {"number": 3000}}}}]}}]},
    }
    res = {"ingresses": [ing], "services": [svc("mb", "metabase")], "endpointslices": [eps("mb", "metabase")]}
    (row,) = build_exposure(res)
    assert (row["kind"], row["url"], row["status"], row["paths"]) == ("Ingress", "https://m.x.io", "ok", ["/"])


def test_empty_input():
    assert build_exposure({}) == []
