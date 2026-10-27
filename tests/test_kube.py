import httpx
import pytest

from kubemap.kube import KubeClient, ReadOnlyViolation


def make_client(handler):
    return KubeClient("https://k8s.test", None, transport=httpx.MockTransport(handler))


def ok(request):
    return httpx.Response(200, json={"items": [], "metadata": {"resourceVersion": "1"}})


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_non_get_methods_are_refused(method):
    client = make_client(ok)
    with pytest.raises(ReadOnlyViolation):
        await client._http.request(method, "/api/v1/namespaces/x/pods")


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/namespaces/x/pods/p/exec",
        "/api/v1/namespaces/x/pods/p/attach",
        "/api/v1/namespaces/x/pods/p/portforward",
        "/api/v1/namespaces/x/services/s/proxy",
    ],
)
async def test_dangerous_subresources_are_refused(path):
    client = make_client(ok)
    with pytest.raises(ReadOnlyViolation):
        await client._http.get(path)


@pytest.mark.parametrize(
    "path",
    ["/api/v1/secrets", "/api/v1/namespaces/x/secrets", "/api/v1/namespaces/x/secrets/db"],
)
async def test_secrets_require_metadata_only(path):
    client = make_client(ok)
    with pytest.raises(ReadOnlyViolation):
        await client._http.get(path)
    with pytest.raises(ReadOnlyViolation):
        await client._http.get(path, headers={"Accept": "application/json"})
    r = await client._http.get(
        path, headers={"Accept": "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1"}
    )
    assert r.status_code == 200


async def test_get_secret_reads_one_named_secret_only():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"data": {"k": "dg=="}})
    client = make_client(handler)
    assert await client.get_secret("x", "db") == {"k": "dg=="}
    assert seen == ["/api/v1/namespaces/x/secrets/db"]
    for path in ["/api/v1/secrets", "/api/v1/namespaces/x/secrets"]:
        with pytest.raises(ReadOnlyViolation):
            await client._http.get(path, headers={"X-Kubemap-Reveal": "1"})


async def test_namespace_named_secrets_is_not_a_secret_read():
    client = make_client(ok)
    r = await client._http.get("/api/v1/namespaces/secrets/pods")
    assert r.status_code == 200


async def test_list_meta_only_sends_strict_accept_header():
    seen = {}

    def handler(request):
        seen["accept"] = request.headers["accept"]
        return httpx.Response(200, json={"items": [], "metadata": {"resourceVersion": "1"}})

    client = make_client(handler)
    await client.list("/api/v1/secrets", meta_only=True)
    assert seen["accept"] == "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1"


@pytest.mark.parametrize("path", ["/api/v1/pods", "/api/v1/events"])
async def test_watch_yields_events(path):
    def handler(request):
        assert request.method == "GET"
        assert request.url.params["watch"] == "true"
        body = '{"type":"ADDED","object":{"metadata":{"name":"a"}}}\n{"type":"DELETED","object":{"metadata":{"name":"a"}}}\n'
        return httpx.Response(200, content=body)

    client = make_client(handler)
    events = [e async for e in client.watch(path, "1")]
    assert [e["type"] for e in events] == ["ADDED", "DELETED"]


async def test_log_stream_caps_and_renders_errors_as_text():
    def handler(request):
        assert request.url.params["tailLines"] == "500"
        return httpx.Response(404, text="not found")

    client = make_client(handler)
    chunks = [c async for c in client.log_stream("ns", "pod", tail=500)]
    assert "404" in "".join(chunks)


async def test_previous_logs_are_requested_without_following():
    def handler(request):
        assert request.url.params["previous"] == "true"
        assert "follow" not in request.url.params
        return httpx.Response(200, text="previous crash")
    client = make_client(handler)
    assert "".join([c async for c in client.log_stream("ns", "pod", previous=True)]) == "previous crash"


async def test_switching_context_closes_active_websockets(monkeypatch):
    from kubemap.store import Store
    from kubemap import kube
    class Socket:
        closed = False
        async def close(self):
            self.closed = True
    socket = Socket()
    async def connect(*args, **kwargs):
        return socket
    monkeypatch.setattr(kube.websockets, "connect", connect)
    old = make_client(ok)
    store = Store(old, resources={})
    async with old.exec_connect("team", "api"):
        await store.configure(None, "", "")
        assert socket.closed
    with pytest.raises(OSError):
        async with old.exec_connect("team", "api"):
            raise AssertionError("a closed client cannot open a terminal")
