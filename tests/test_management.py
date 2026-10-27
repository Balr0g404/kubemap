import json
import httpx
import pytest
from fastapi.testclient import TestClient
from kubemap.api import create_app
from kubemap.kube import KubeClient
from kubemap.store import Store

ORIGIN = {"Origin": "http://testserver"}


def setup(labels=None, annotations=None):
    seen = []
    def handler(request):
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"metadata": {"name": "api", "namespace": "team", "uid": "uid-1", "resourceVersion": "7", "labels": labels or {}, "annotations": annotations or {}}})
        return httpx.Response(200, json={"metadata": {"name": "api"}})
    kube = KubeClient("https://cluster.test", None, transport=httpx.MockTransport(handler))
    store = Store(kube)
    return store, TestClient(create_app(store)), seen


def body(**extra):
    return {"action": "scale", "uid": "uid-1", "resourceVersion": "7", "connectionId": 0, "replicas": 0, **extra}


def test_management_is_off_by_default_and_requires_origin():
    store, client, seen = setup()
    path = "/api/manage/deployments/team/api"
    assert client.post(path, headers=ORIGIN, json=body()).status_code == 403
    store.allow_write = True
    assert client.post(path, json=body()).status_code == 403
    assert not seen


def test_scaling_to_zero_is_explicit_and_stale_objects_are_not_modified():
    store, client, seen = setup()
    store.allow_write = True
    path = "/api/manage/deployments/team/api"
    assert client.post(path, headers=ORIGIN, json=body(connectionId=1)).status_code == 409
    assert client.post(path, headers=ORIGIN, json=body(uid="old")).status_code == 409
    assert all(r.method == "GET" for r in seen)
    result = client.post(path, headers=ORIGIN, json=body())
    assert result.status_code == 200
    patch = json.loads(seen[-1].content)
    assert seen[-1].method == "PATCH"
    assert seen[-1].url.path == "/apis/apps/v1/namespaces/team/deployments/api"
    assert patch == {"metadata": {"uid": "uid-1", "resourceVersion": "7"}, "spec": {"replicas": 0}}
    assert client.post(path, headers=ORIGIN, json=body(replicas=-1)).status_code == 422
    assert client.post("/api/manage/secrets/team/api", headers=ORIGIN, json=body()).status_code == 422


def test_flux_requires_a_separate_acknowledgement():
    store, client, seen = setup({"kustomize.toolkit.fluxcd.io/name": "apps"})
    store.allow_write = True
    path = "/api/manage/deployments/team/api"
    assert client.post(path, headers=ORIGIN, json=body()).status_code == 409
    assert all(r.method == "GET" for r in seen)
    assert client.post(path, headers=ORIGIN, json=body(acknowledgeFlux=True)).status_code == 200


@pytest.mark.parametrize("kind,action,extra,want", [
    ("cronjobs", "suspend", {"suspend": True}, {"suspend": True}),
    ("cronjobs", "suspend", {"suspend": False}, {"suspend": False}),
    ("statefulsets", "restart", {}, None),
])
def test_supported_actions_patch_only_the_expected_spec(kind, action, extra, want):
    store, client, seen = setup()
    store.allow_write = True
    result = client.post(f"/api/manage/{kind}/team/api", headers=ORIGIN, json=body(action=action, **extra))
    assert result.status_code == 200
    spec = json.loads(seen[-1].content)["spec"]
    if want is not None:
        assert spec == want
    else:
        assert spec["template"]["metadata"]["annotations"]["kubectl.kubernetes.io/restartedAt"]


def test_helm_managed_objects_require_server_side_acknowledgement():
    store, client, seen = setup(annotations={"meta.helm.sh/release-name": "app"})
    store.allow_write = True
    path = "/api/manage/deployments/team/api"
    assert client.post(path, headers=ORIGIN, json=body()).status_code == 409
    assert all(r.method == "GET" for r in seen)
