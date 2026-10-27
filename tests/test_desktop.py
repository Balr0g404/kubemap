import socket
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from kubemap import __main__ as cli


class EventHook:
    def __iadd__(self, handler):
        return self


def test_desktop_cli_keeps_connection_and_permissions(monkeypatch, tmp_path):
    from kubemap import desktop

    (tmp_path / "index.html").write_text("<html>Kubemap</html>")
    monkeypatch.setattr(cli, "DIST", tmp_path)
    monkeypatch.setattr(sys, "argv", ["kubemap", "--desktop", "--allow-exec", "--allow-secrets"])
    opened = []

    def launch(app, static_dir, port):
        from fastapi.testclient import TestClient
        client = TestClient(app)
        snapshot = client.get("/api/snapshot").json()
        assert snapshot["configured"] is False
        assert snapshot["execEnabled"] is True
        assert snapshot["secretsEnabled"] is True
        assert client.get("/").text == "<html>Kubemap</html>"
        opened.append(port)

    monkeypatch.setattr(desktop, "run", launch)
    cli.main()
    assert opened == [0]


@pytest.mark.parametrize("gui_error", [False, True])
def test_window_opens_after_http_is_ready_and_shutdown_closes_server(monkeypatch, tmp_path, gui_error):
    from kubemap.desktop import run

    (tmp_path / "index.html").write_text("Kubemap")
    app = FastAPI()

    @app.get("/ready")
    def ready():
        return {"ready": True}

    urls = []

    def create_window(title, url, **kwargs):
        assert title == "Kubemap"
        assert httpx.get(url + "/ready", trust_env=False).json() == {"ready": True}
        urls.append(url)
        return SimpleNamespace(events=SimpleNamespace(before_show=EventHook()))

    def start(**kwargs):
        if gui_error:
            raise RuntimeError("GUI unavailable")

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=create_window, start=start))
    if gui_error:
        with pytest.raises(RuntimeError, match="GUI unavailable"):
            run(app, tmp_path)
    else:
        run(app, tmp_path)
    assert len(urls) == 1
    with pytest.raises(httpx.ConnectError):
        httpx.get(urls[0] + "/ready", trust_env=False, timeout=1)


def test_missing_frontend_fails_before_starting_gui(tmp_path, monkeypatch):
    from kubemap.desktop import run

    monkeypatch.setitem(sys.modules, "webview", None)
    with pytest.raises(RuntimeError, match="npm run build"):
        run(FastAPI(), tmp_path)


def test_busy_port_is_not_reused_for_another_application(tmp_path, monkeypatch):
    from kubemap.desktop import run

    (tmp_path / "index.html").write_text("Kubemap")
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace())
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        with pytest.raises(OSError):
            run(FastAPI(), tmp_path, port=busy.getsockname()[1])
