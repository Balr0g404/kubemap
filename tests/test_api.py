import asyncio
import json

from fastapi.testclient import TestClient

from kubemap.api import create_app, event_stream
from kubemap.store import Resource, Store

PODS = {"pods": Resource("/api/v1/pods")}


class LogClient:
    def __init__(self):
        self.calls = []

    async def log_stream(self, namespace, pod, container=None, tail=500, follow=False, previous=False):
        self.calls.append({"namespace": namespace, "pod": pod, "container": container, "tail": tail, "follow": follow, "previous": previous})
        yield "ligne 1\n"
        yield "ligne 2\n"


def make(store_client=None):
    store = Store(store_client or LogClient(), views_fn=lambda res, m: {"pods": len(res["pods"])}, resources=PODS)
    return store, TestClient(create_app(store))


def test_snapshot_contains_state_and_views():
    store, client = make()
    store.apply("pods", "ADDED", {"metadata": {"name": "a", "namespace": "n"}})
    body = client.get("/api/snapshot").json()
    assert body["resources"]["pods"][0]["metadata"]["name"] == "a"
    assert body["views"] == {"pods": 1}
    assert body["rev"] == store.rev and "connected" in body and "status" in body


def test_snapshot_identifies_the_connected_cluster_without_credentials():
    store = Store(LogClient(), resources=PODS, cluster_name="Demo cluster")
    client = TestClient(create_app(store))
    assert client.get("/api/snapshot").json()["clusterName"] == "Demo cluster"


def test_logs_stream_text_and_tail_is_capped():
    log_client = LogClient()
    _, client = make(log_client)
    r = client.get("/api/logs/team/pod-1?tail=99999&container=app")
    assert r.status_code == 200 and r.text == "ligne 1\nligne 2\n"
    assert log_client.calls[0] == {"namespace": "team", "pod": "pod-1", "container": "app", "tail": 2000, "follow": False, "previous": False}


def test_logs_reject_invalid_names():
    _, client = make()
    assert client.get("/api/logs/BAD_NS/pod").status_code == 400
    assert client.get("/api/logs/ns/..%2Fetc").status_code in (400, 404)
    assert client.get("/api/logs/ns/pod?container=a%20b").status_code == 400


def test_logs_tail_lower_bound():
    log_client = LogClient()
    _, client = make(log_client)
    client.get("/api/logs/ns/pod?tail=-5")
    assert log_client.calls[0]["tail"] == 1


async def test_event_stream_hello_then_events_then_cleanup():
    store = Store(LogClient(), resources=PODS)
    gen = event_stream(store, keepalive=0.05)
    hello = await gen.__anext__()
    assert json.loads(hello.removeprefix("data: "))["event"] == "hello"
    assert len(store._subs) == 1
    store.apply("pods", "ADDED", {"metadata": {"name": "a", "namespace": "n"}})
    ev = json.loads((await gen.__anext__()).removeprefix("data: "))
    assert (ev["event"], ev["type"]) == ("delta", "ADDED")
    assert (await gen.__anext__()).startswith(": keepalive")
    await gen.aclose()
    await asyncio.sleep(0)
    assert len(store._subs) == 0


CONFIG = {"current-context": "ctx", "contexts": [{"name": "ctx", "context": {"cluster": "new", "user": "u"}}], "clusters": [{"name": "new", "cluster": {"server": "https://k8s.example"}}], "users": [{"name": "u", "user": {"token": "secret-token"}}]}


def test_kubeconfig_preview_only_returns_context_names():
    import yaml
    _, client = make()
    response = client.post("/api/kubeconfig/contexts", json={"kubeconfig": yaml.safe_dump(CONFIG)})
    assert response.status_code == 200
    assert response.json() == {"contexts": ["ctx"], "currentContext": "ctx"}
    assert "secret-token" not in response.text


def test_invalid_upload_and_cross_origin_requests_leave_connection_unchanged():
    _, client = make()
    for content in [{"kubeconfig": "not yaml"}, {"kubeconfig": []}, {}]:
        response = client.post("/api/connection", json=content)
        assert response.status_code == 400
    assert client.post("/api/connection", json={"kubeconfig": "x" * 1_048_577}).status_code == 413
    assert client.post("/api/connection", json={"kubeconfig": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/snapshot").json()["clusterName"] == "Cluster connecté"


def test_connect_uses_read_only_client_and_resets_old_resources(monkeypatch):
    import yaml
    from kubemap.kube import KubeClient, ReadOnlyTransport
    store, client = make()
    store.apply("pods", "ADDED", {"metadata": {"name": "old", "namespace": "n"}})
    monkeypatch.setattr(Store, "start", lambda self: None)
    response = client.post("/api/connection", json={"kubeconfig": yaml.safe_dump(CONFIG), "context": "ctx"})
    assert response.status_code == 200
    assert isinstance(store.client, KubeClient)
    assert isinstance(store.client._http._transport, ReadOnlyTransport)
    snap = client.get("/api/snapshot").json()
    assert snap["configured"] is True and snap["clusterName"] == "new"
    assert snap["contextName"] == "ctx" and snap["resources"]["pods"] == []
    assert "secret-token" not in response.text + str(snap)


def test_logs_without_connection_return_an_actionable_error():
    client = TestClient(create_app(Store(None, resources=PODS)))
    assert client.get("/api/logs/ns/pod").status_code == 409


def test_cli_startup_does_not_read_personal_kubeconfig(monkeypatch):
    from kubemap import __main__ as main
    monkeypatch.setattr("sys.argv", ["kubemap"])
    def forbidden_load(*args, **kwargs):
        raise AssertionError("aucun kubeconfig ne doit être lu par défaut")
    monkeypatch.setattr(main, "load", forbidden_load)
    apps = []
    monkeypatch.setattr(main.uvicorn, "run", lambda app, **kwargs: apps.append(app))
    main.main()
    snapshot = TestClient(apps[0]).get("/api/snapshot").json()
    assert snapshot["configured"] is False
    assert snapshot["clusterName"] == ""


def test_unsupported_upload_preserves_existing_connection():
    import copy
    import yaml
    store, client = make()
    store.apply("pods", "ADDED", {"metadata": {"name": "kept", "namespace": "n"}})
    config = copy.deepcopy(CONFIG)
    config["users"][0]["user"]["exec"] = {"command": "do-not-run"}
    response = client.post("/api/connection", json={"kubeconfig": yaml.safe_dump(config)})
    assert response.status_code == 400
    assert "secret-token" not in response.text
    assert client.get("/api/snapshot").json()["resources"]["pods"][0]["metadata"]["name"] == "kept"


class FakeUpstream:
    def __init__(self, messages, hang=False):
        self.messages, self.hang, self.sent = messages, hang, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for m in self.messages:
            yield m
        if self.hang:
            await asyncio.sleep(10)

    async def send(self, data):
        self.sent.append(data)


class ExecClient(LogClient):
    def __init__(self, upstream):
        super().__init__()
        self.upstream = upstream

    def exec_connect(self, namespace, pod, container=None, command=("bash",)):
        self.calls.append({"exec": (namespace, pod, container, command)})
        return self.upstream


ORIGIN = {"origin": "http://testserver"}


def exec_app(allow, upstream=None):
    kube = ExecClient(upstream or FakeUpstream([]))
    store, client = make(kube)
    store.allow_exec = allow
    return kube, client


def refused(client, headers):
    from starlette.websockets import WebSocketDisconnect
    try:
        with client.websocket_connect("/api/exec/n/p", headers=headers) as ws:
            ws.receive_bytes()
    except WebSocketDisconnect as exc:
        return exc.code == 1008
    return False


def test_exec_is_refused_unless_enabled_and_same_origin():
    _, client = exec_app(False)
    assert refused(client, ORIGIN)
    kube, client = exec_app(True)
    assert refused(client, {"origin": "http://evil.example"}) and refused(client, {})
    assert not any("exec" in c for c in kube.calls)


def test_exec_relays_output_and_errors():
    up = FakeUpstream([b"\x01hello", b"\x03" + json.dumps({"status": "Failure", "message": "bash introuvable"}).encode()])
    kube, client = exec_app(True, up)
    assert client.get("/api/snapshot").json()["execEnabled"] is True
    with client.websocket_connect("/api/exec/n/p?container=c", headers=ORIGIN) as ws:
        assert ws.receive_bytes() == b"hello"
        assert json.loads(ws.receive_text()) == {"error": "bash introuvable"}
    assert kube.calls[-1]["exec"] == ("n", "p", "c", ("bash",))


def test_exec_forwards_keystrokes_and_resize():
    up = FakeUpstream([], hang=True)
    _, client = exec_app(True, up)
    with client.websocket_connect("/api/exec/n/p", headers=ORIGIN) as ws:
        ws.send_bytes(b"ls\n")
        ws.send_text(json.dumps({"resize": {"cols": 80, "rows": 24}}))
    assert up.sent == [b"\x00ls\n", b"\x04" + b'{"Width": 80, "Height": 24}']


class SecretClient(LogClient):
    async def get_secret(self, namespace, name):
        self.calls.append({"secret": (namespace, name)})
        return {"user": "YWRtaW4=", "blob": "gP8="}  # "admin" et un octet non UTF-8


def test_reveal_secret_requires_flag_and_same_origin():
    kube = SecretClient()
    store, client = make(kube)
    url = "/api/secrets/n/db/reveal"
    assert client.post(url, headers=ORIGIN).status_code == 403
    store.allow_secrets = True
    assert client.post(url).status_code == 403
    assert client.post(url, headers={"origin": "http://evil.test"}).status_code == 403
    assert client.post("/api/secrets/N_/db/reveal", headers=ORIGIN).status_code == 400
    assert kube.calls == []
    r = client.post(url, headers=ORIGIN)
    assert r.json() == {"user": {"value": "admin", "binary": False}, "blob": {"value": "gP8=", "binary": True}}
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/api/snapshot").json()["secretsEnabled"] is True


def test_tabs_have_independent_connections_and_unknown_ids_are_rejected(monkeypatch):
    import yaml
    monkeypatch.setattr(Store, "start", lambda self: None)
    store, client = make()
    a = {"X-Kubemap-Session": "11111111-1111-4111-8111-111111111111"}
    b = {"X-Kubemap-Session": "22222222-2222-4222-8222-222222222222"}
    assert client.get("/api/snapshot", headers=a).json()["configured"] is False
    assert client.post("/api/connection", headers=a, json={"kubeconfig": yaml.safe_dump(CONFIG)}).status_code == 200
    assert client.get("/api/snapshot", headers=a).json()["contextName"] == "ctx"
    assert client.get("/api/snapshot", headers=b).json()["configured"] is False
    assert store.client.__class__ is LogClient
    assert client.get("/api/snapshot", headers={"X-Kubemap-Session": "../bad"}).status_code == 400


def test_context_can_be_changed_without_uploading_credentials_again(monkeypatch):
    import copy
    import yaml
    monkeypatch.setattr(Store, "start", lambda self: None)
    store, client = make()
    config = copy.deepcopy(CONFIG)
    config["contexts"].append({"name": "other", "context": {"cluster": "new", "user": "u"}})
    assert client.post("/api/connection", json={"kubeconfig": yaml.safe_dump(config)}).status_code == 200
    response = client.post("/api/connection/context", json={"context": "other"}, headers=ORIGIN)
    assert response.status_code == 200
    snapshot = client.get("/api/snapshot").json()
    assert snapshot["contextName"] == "other"
    assert snapshot["contexts"] == ["ctx", "other"]
    assert "secret-token" not in str(snapshot)


def test_inactive_tabs_are_reclaimed_before_session_limit_is_reached(monkeypatch):
    from uuid import uuid4
    monkeypatch.setattr(Store, "start", lambda self: None)
    client = TestClient(create_app(Store(None)))
    for _ in range(40):
        response = client.get("/api/snapshot", headers={"X-Kubemap-Session": str(uuid4())})
        assert response.status_code == 200


def test_previous_logs_disable_follow_at_api_boundary():
    kube = LogClient()
    _, client = make(kube)
    response = client.get("/api/logs/team/api?previous=true&follow=true&container=migrate")
    assert response.status_code == 200
    assert kube.calls[0]["previous"] is True
    assert kube.calls[0]["follow"] is False
