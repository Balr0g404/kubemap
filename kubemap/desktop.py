"""Fenêtre locale ; le serveur et les identifiants vivent le temps de la fenêtre."""

import socket
import threading
import time
from pathlib import Path

import uvicorn


def _configure_window(window):
    from qtpy.QtGui import QIcon
    from qtpy.QtWebEngineWidgets import QWebEngineSettings

    native = window.native
    icon = Path(__file__).resolve().parent.parent / "web" / "public" / "app-icon-512.png"
    native.setWindowIcon(QIcon(str(icon)))
    page = native.webview.page()
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
    previous_state = native.windowState()

    def fullscreen(request):
        nonlocal previous_state
        if request.toggleOn():
            previous_state = native.windowState()
            native.showFullScreen()
        else:
            native.setWindowState(previous_state)
        request.accept()

    page.fullScreenRequested.connect(fullscreen)


def run(app, static_dir, port=0):
    if not (Path(static_dir) / "index.html").is_file():
        raise RuntimeError("Interface absente : lancez npm run build --prefix web.")
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("Installez le mode desktop : uv sync --group desktop.") from exc

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", access_log=False, timeout_graceful_shutdown=2,
        ))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Le serveur local n’a pas pu démarrer.")
                time.sleep(0.01)
            window = webview.create_window("Kubemap", address, width=1440, height=960, min_size=(900, 600))
            # Qt exige une activation explicite du plein écran HTML utilisé par la carte.
            window.events.before_show += _configure_window
            webview.start(gui="qt", private_mode=True)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=2)
            if thread.is_alive():
                raise RuntimeError("Le serveur local n’a pas pu être arrêté.")
