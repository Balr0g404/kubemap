import httpx
from fastapi.testclient import TestClient
from kubemap.api import create_app
from kubemap.kube import KubeClient
from kubemap.store import Store


def test_discovered_resources_are_readable_without_arbitrary_paths_or_secret_values():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/apis":
            return httpx.Response(200, json={"groups": [{"preferredVersion": {"groupVersion": "example.io/v1"}}]})
        if request.url.path in ("/api/v1", "/apis/example.io/v1"):
            return httpx.Response(200, json={"resources": [{"name": "widgets", "kind": "Widget", "namespaced": True, "verbs": ["list", "get"]}, {"name": "pods/exec", "verbs": ["get"]}]})
        assert "PartialObjectMetadata" in request.headers["accept"]
        return httpx.Response(200, json={"items": [{"metadata": {"name": "sample", "namespace": "team"}, "data": {"password": "private"}}], "metadata": {"continue": "next"}})
    kube = KubeClient("https://cluster.test", None, transport=httpx.MockTransport(handler))
    client = TestClient(create_app(Store(kube)))
    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    assert all("/" not in r["resource"] for r in catalog.json()["resources"])
    result = client.get("/api/resource", params={"apiVersion": "example.io/v1", "resource": "widgets", "namespace": "team"})
    assert result.status_code == 200
    assert result.json()["items"][0]["metadata"]["name"] == "sample"
    assert "private" not in result.text
    assert result.json()["continue"] == "next"
    assert client.get("/api/resource", params={"apiVersion": "example.io/v1", "resource": "../secrets"}).status_code == 400
    assert client.get("/api/resource", params={"apiVersion": "v1", "resource": "unlisted"}).status_code == 404
