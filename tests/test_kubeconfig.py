import pytest
import yaml

from kubemap.kubeconfig import load, parse, from_document, describe


def write_cfg(tmp_path, user):
    cfg = {
        "current-context": "ctx",
        "contexts": [{"name": "ctx", "context": {"cluster": "c", "user": "u"}}],
        "clusters": [{"name": "c", "cluster": {"server": "https://k8s.example:6443/"}}],
        "users": [{"name": "u", "user": user}],
    }
    p = tmp_path / "config"
    p.write_text(yaml.safe_dump(cfg))
    return str(p)


def test_token_auth(tmp_path):
    cfg = load(write_cfg(tmp_path, {"token": "abc"}))
    assert cfg.server == "https://k8s.example:6443"
    assert cfg.token == "abc"
    assert cfg.cluster_name == "c"


def test_unsupported_auth_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="certificat client ou token"):
        load(write_cfg(tmp_path, {"exec": {"command": "aws"}}))


def test_uploaded_config_lists_contexts_and_selects_one(tmp_path):
    text = open(write_cfg(tmp_path, {"token": "private-token"})).read()
    doc = parse(text)
    assert describe(doc) == {"contexts": ["ctx"], "currentContext": "ctx"}
    config = from_document(doc, "ctx")
    assert config.token == "private-token"
    assert config.context_name == "ctx"
    with pytest.raises(ValueError, match="Contexte introuvable"):
        from_document(doc, "absent")


@pytest.mark.parametrize("text", ["", "[]", "contexts: [", "contexts: [null]", "contexts: [{name: a, context: {}}]"])
def test_malformed_upload_is_rejected(text):
    with pytest.raises(ValueError):
        parse(text)


@pytest.mark.parametrize("field,value", [
    ("exec", {"command": "touch", "args": ["/tmp/never-run"]}),
    ("auth-provider", {"name": "gcp"}),
    ("client-certificate", "/etc/passwd"),
    ("tokenFile", "/etc/passwd"),
])
def test_upload_never_uses_commands_or_local_user_files(tmp_path, field, value):
    doc = parse(open(write_cfg(tmp_path, {"token": "abc", field: value})).read())
    with pytest.raises(ValueError):
        from_document(doc)


@pytest.mark.parametrize("extra", [{"certificate-authority": "/etc/passwd"}, {"insecure-skip-tls-verify": True}, {"proxy-url": "http://localhost"}, {"server": "http://k8s.example"}, {"server": "https://k8s.example:bad-port"}, {"server": "https://k8s.example\n"}])
def test_upload_requires_embedded_certificates_and_verified_https(tmp_path, extra):
    doc = parse(open(write_cfg(tmp_path, {"token": "abc"})).read())
    doc["clusters"][0]["cluster"].update(extra)
    with pytest.raises(ValueError):
        from_document(doc)


def test_exec_auth_requires_explicit_trust_and_caches_credentials(monkeypatch, tmp_path):
    import json
    import subprocess
    from types import SimpleNamespace
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs.get("shell", False) is False
        info = json.loads(kwargs["env"]["KUBERNETES_EXEC_INFO"])
        assert info["spec"]["interactive"] is False
        return SimpleNamespace(stdout=json.dumps({"apiVersion": "client.authentication.k8s.io/v1", "kind": "ExecCredential", "status": {"token": "temporary-token", "expirationTimestamp": "2099-01-01T00:00:00Z"}}), returncode=0)
    monkeypatch.setattr(subprocess, "run", run)
    path = write_cfg(tmp_path, {"exec": {"apiVersion": "client.authentication.k8s.io/v1", "command": "cloud-login", "args": ["token"], "interactiveMode": "Never"}})
    with pytest.raises(ValueError):
        load(path)
    assert not calls
    config = load(path, allow_exec_auth=True)
    assert config.token == "temporary-token"
    config.credentials.refresh()
    assert calls == [["cloud-login", "token"]]


def test_import_cannot_run_plugins_even_when_exec_auth_is_allowed(tmp_path):
    path = write_cfg(tmp_path, {"exec": {"apiVersion": "client.authentication.k8s.io/v1", "command": "do-not-run", "interactiveMode": "Never"}})
    doc = parse(open(path).read())
    with pytest.raises(ValueError):
        from_document(doc, allow_exec_auth=True)


async def test_exec_auth_refreshes_once_after_unauthorized(monkeypatch, tmp_path):
    import json
    import subprocess
    from types import SimpleNamespace
    import httpx
    from kubemap.kube import KubeClient
    count = 0
    def run(*args, **kwargs):
        nonlocal count
        count += 1
        return SimpleNamespace(stdout=json.dumps({"apiVersion": "client.authentication.k8s.io/v1", "kind": "ExecCredential", "status": {"token": "old" if count == 1 else "new"}}))
    monkeypatch.setattr(subprocess, "run", run)
    path = write_cfg(tmp_path, {"exec": {"apiVersion": "client.authentication.k8s.io/v1", "command": "fixture-login", "interactiveMode": "Never"}})
    config = load(path, allow_exec_auth=True)
    def handler(request):
        if request.headers["Authorization"] == "Bearer old":
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer new"
        return httpx.Response(200, json={"items": []})
    client = KubeClient(config.server, config.ssl_context, config.token, credentials=config.credentials, transport=httpx.MockTransport(handler))
    try:
        assert await client.list("/api/v1/pods") == {"items": []}
        assert count == 2
    finally:
        await client.aclose()
