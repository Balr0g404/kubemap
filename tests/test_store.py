import asyncio

import httpx

from kubemap.store import Resource, Store

PODS = {"pods": Resource("/api/v1/pods")}


def pod(name, ns="ns", rv="1", **extra):
    return {"metadata": {"name": name, "namespace": ns, "resourceVersion": rv}, **extra}


class FakeClient:
    def __init__(self, items=None, watches=None, list_error=None):
        self.items = items or []
        self.watches = watches or []  # une liste de scripts, un par appel de watch
        self.list_error = list_error
        self.list_calls = 0
        self.watch_calls = 0

    async def list(self, path, meta_only=False):
        self.list_calls += 1
        if self.list_error:
            raise self.list_error
        return {"metadata": {"resourceVersion": "1"}, "items": self.items}

    async def watch(self, path, rv, meta_only=False):
        script = self.watches[self.watch_calls] if self.watch_calls < len(self.watches) else []
        self.watch_calls += 1
        for ev in script:
            if isinstance(ev, Exception):
                raise ev
            yield ev
        await asyncio.Event().wait()


async def until(cond, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        assert loop.time() < end, "condition non atteinte"
        await asyncio.sleep(0.01)


def http_error(code):
    req = httpx.Request("GET", "http://x")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(code, request=req))


async def test_initial_list_populates_store():
    store = Store(FakeClient(items=[pod("a"), pod("b")]), resources=PODS)
    store.start()
    try:
        await until(lambda: store.status["pods"] == "ok")
        assert set(store.objects["pods"]) == {"ns/a", "ns/b"}
        assert store.connected
    finally:
        await store.stop()


async def test_watch_events_are_applied():
    watches = [[
        {"type": "ADDED", "object": pod("c", rv="2")},
        {"type": "MODIFIED", "object": pod("a", rv="3", status={"phase": "Running"})},
        {"type": "DELETED", "object": pod("b", rv="4")},
        {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": "5"}}},
    ]]
    store = Store(FakeClient(items=[pod("a"), pod("b")], watches=watches), resources=PODS)
    store.start()
    try:
        await until(lambda: set(store.objects["pods"]) == {"ns/a", "ns/c"})
        assert store.objects["pods"]["ns/a"]["status"]["phase"] == "Running"
    finally:
        await store.stop()


async def test_410_gone_triggers_relist():
    client = FakeClient(items=[pod("a")], watches=[[http_error(410)]])
    store = Store(client, resources=PODS)
    store.start()
    try:
        await until(lambda: client.list_calls >= 2)
    finally:
        await store.stop()


async def test_forbidden_kind_is_unavailable_and_others_still_work():
    class Mixed(FakeClient):
        async def list(self, path, meta_only=False):
            if path == "/apis/x/crds":
                raise http_error(404)
            return await super().list(path, meta_only)

    resources = {"pods": Resource("/api/v1/pods"), "crds": Resource("/apis/x/crds")}
    store = Store(Mixed(items=[pod("a")]), resources=resources)
    store.unavailable_delay = 3600
    store.start()
    try:
        await until(lambda: store.status["crds"] == "unavailable" and store.status["pods"] == "ok")
        assert store.objects["crds"] == {}
        assert store.connected
        assert store.snapshot()["resources"]["crds"] == []
    finally:
        await store.stop()


async def test_subscribers_receive_deltas_with_increasing_rev():
    store = Store(FakeClient(), resources=PODS)
    q = store.subscribe()
    store.apply("pods", "ADDED", pod("a"))
    store.apply("pods", "DELETED", pod("a"))
    e1, e2 = q.get_nowait(), q.get_nowait()
    assert (e1["event"], e1["type"], e1["kind"]) == ("delta", "ADDED", "pods")
    assert e2["rev"] > e1["rev"]
    store.unsubscribe(q)


async def test_slow_subscriber_gets_resync_instead_of_unbounded_queue():
    store = Store(FakeClient(), resources=PODS)
    q = store.subscribe()
    for i in range(5001):
        store.apply("pods", "ADDED", pod(f"p{i}"))
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert events[-1]["event"] == "resync"


def test_secrets_are_reduced_to_metadata():
    store = Store(FakeClient(), resources={"secrets": Resource("/api/v1/secrets", meta_only=True)})
    store.apply("secrets", "ADDED", {"metadata": {"name": "s", "namespace": "n"}, "data": {"password": "eHg="}, "type": "Opaque"})
    assert store.objects["secrets"]["n/s"] == {"metadata": {"name": "s", "namespace": "n"}}


def test_noise_and_env_values_are_stripped():
    store = Store(FakeClient(), resources=PODS)
    obj = pod("a", spec={"containers": [{"name": "c", "image": "i", "args": ["--password=x"], "command": ["run"],
                                          "env": [{"name": "TOKEN", "value": "secret"}, {"name": "REF", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}}]}]})
    obj["metadata"]["managedFields"] = [{"x": 1}]
    obj["metadata"]["annotations"] = {"kubectl.kubernetes.io/last-applied-configuration": "{...}", "keep": "1"}
    store.apply("pods", "ADDED", obj)
    stored = store.objects["pods"]["ns/a"]
    c = stored["spec"]["containers"][0]
    assert "managedFields" not in stored["metadata"]
    assert stored["metadata"]["annotations"] == {"keep": "1"}
    assert "args" not in c and "command" not in c
    assert c["env"][0] == {"name": "TOKEN", "value": None}
    assert c["env"][1]["valueFrom"]["secretKeyRef"]["name"] == "s"


async def test_views_are_published_after_a_change():
    store = Store(FakeClient(), views_fn=lambda res, metrics: {"pods": len(res["pods"])}, resources=PODS)
    store.views_debounce = 0.01
    q = store.subscribe()
    store.start()
    try:
        await until(lambda: store.status["pods"] == "ok")
        store.apply("pods", "ADDED", pod("a"))

        async def views_with_one_pod():
            while True:
                ev = await q.get()
                if ev["event"] == "views" and ev["views"] == {"pods": 1}:
                    return ev

        ev = await asyncio.wait_for(views_with_one_pod(), 2)
        assert ev["views"] == {"pods": 1}
    finally:
        await store.stop()


async def test_unconfigured_store_starts_without_accessing_a_cluster():
    store = Store(None, resources=PODS)
    store.start()
    assert not store.connected
    assert store.snapshot()["configured"] is False
    assert not store._tasks
    await store.stop()


async def test_switching_cluster_clears_old_data_and_resynchronizes_subscribers():
    class ClosingClient(FakeClient):
        closed = False
        async def aclose(self):
            self.closed = True
    old = ClosingClient(items=[pod("old")])
    store = Store(old, resources=PODS)
    store.start()
    await until(lambda: store.status["pods"] == "ok")
    store.metrics = {"old": {"cpu": 1}}
    queue = store.subscribe()
    previous_rev = store.rev
    try:
        await store.configure(FakeClient(items=[pod("new")]), "new-cluster", "new-context")
        assert old.closed
        assert store.snapshot()["clusterName"] == "new-cluster"
        assert store.snapshot()["contextName"] == "new-context"
        assert store.metrics == {}
        assert store.rev > previous_rev
        assert queue.get_nowait()["event"] == "resync"
        await until(lambda: store.status["pods"] == "ok")
        assert set(store.objects["pods"]) == {"ns/new"}
    finally:
        await store.stop()


async def test_metrics_failure_clears_old_values_and_publishes_freshness():
    class Metrics(FakeClient):
        async def list(self, path, meta_only=False):
            self.list_calls += 1
            if self.list_calls == 1:
                return {"items": [{"metadata": {"name": "worker"}, "usage": {"cpu": "50m", "memory": "1Gi"}}]}
            raise http_error(503)
    store = Store(Metrics(), resources={})
    store.metrics_interval = 0.01
    task = asyncio.create_task(store._run_metrics())
    try:
        await until(lambda: store.client.list_calls >= 2)
        snap = store.snapshot()
        assert snap["metrics"] == {}
        assert snap["metricsStatus"] == "error"
        assert snap["metricsUpdatedAt"] is not None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_probe_credentials_and_configmap_values_are_not_exposed():
    store = Store(None, resources={"pods": Resource("/api/v1/pods"), "configmaps": Resource("/api/v1/configmaps")})
    store.apply("pods", "ADDED", pod("app", spec={"containers": [{"name": "app", "image": "app", "readinessProbe": {"httpGet": {"path": "/ready", "httpHeaders": [{"name": "Authorization", "value": "private"}]}}, "livenessProbe": {"exec": {"command": ["check", "private"]}}}]}))
    text = str(store.snapshot())
    assert "private" not in text
    assert "/ready" in text
    store.apply("configmaps", "ADDED", {"metadata": {"name": "config"}, "data": {"password": "private"}})
    assert "private" not in str(store.snapshot())
