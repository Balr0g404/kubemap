"""Contrôle graphique optionnel : uv run --group desktop python tests/desktop_smoke.py.

Nécessite une session graphique ; aucun kubeconfig ni cluster réel n’est utilisé.
"""

import json
import os
import base64
import copy
import logging
import sys
import socket

import httpx
from websockets.sync.client import connect
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webview
from kubemap.__main__ import main
from kubemap import api
from kubemap.kube import KubeClient

patches = []
fixtures = {
    "nodes": [{"metadata": {"name": "worker-a", "uid": "worker-uid"}, "status": {"allocatable": {"cpu": "4", "memory": "8Gi"}, "conditions": [{"type": "Ready", "status": "True"}], "nodeInfo": {"kubeletVersion": "v1.34.0", "osImage": "Linux"}, "addresses": [{"type": "InternalIP", "address": "192.0.2.10"}]}}],
    "services": [{"metadata": {"name": "api", "namespace": "team", "uid": "svc-uid"}, "spec": {"type": "ClusterIP", "selector": {"app": "api"}, "ports": [{"port": 80, "targetPort": 8080}]}}],
    "endpointslices": [{"metadata": {"name": "api-1", "namespace": "team", "labels": {"kubernetes.io/service-name": "api"}}, "endpoints": [{"conditions": {"ready": True}, "addresses": ["192.0.2.20"], "targetRef": {"kind": "Pod", "name": "api-pod", "uid": "pod-uid"}}]}],
    "namespaces": [{"metadata": {"name": "team", "uid": "ns-uid"}}],
    "pods": [{"metadata": {"name": "api-pod", "namespace": "team", "uid": "pod-uid", "resourceVersion": "7", "labels": {"app": "api"}}, "spec": {"nodeName": "worker-a", "containers": [{"name": "api", "image": "app:1", "resources": {"requests": {"cpu": "100m"}}}], "initContainers": [{"name": "migrate", "image": "app:1"}]}, "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}], "containerStatuses": [{"name": "api", "ready": True}]}}],
    "deployments": [{"metadata": {"name": "api-deploy", "namespace": "team", "uid": "deploy-uid", "resourceVersion": "7"}, "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "api"}}}, "status": {"readyReplicas": 1}}],
}


def fixture_response(request):
    path = request.url.path
    if path == "/apis/metrics.k8s.io/v1beta1/nodes":
        return httpx.Response(200, json={"items": [{"metadata": {"name": "worker-a"}, "usage": {"cpu": "800m", "memory": "2Gi"}}]})
    if request.method == "PATCH":
        patches.append(json.loads(request.content))
        return httpx.Response(200, json={})
    if request.url.params.get("watch"):
        return httpx.Response(200, content=b"")
    if path.endswith("/log"):
        assert request.url.params.get("previous") == "true"
        assert request.url.params.get("container") == "migrate"
        return httpx.Response(200, text="previous init crash")
    if path == "/apis":
        return httpx.Response(200, json={"groups": []})
    if path == "/api/v1":
        return httpx.Response(200, json={"resources": [{"name": "pods", "kind": "Pod", "namespaced": True, "verbs": ["list", "get"]}]})
    collection = path.rsplit("/", 1)[-1]
    for items in fixtures.values():
        for item in items:
            if collection == item["metadata"]["name"]:
                return httpx.Response(200, json=copy.deepcopy(item))
    return httpx.Response(200, json={"items": copy.deepcopy(fixtures.get(collection, [])), "metadata": {"resourceVersion": "7"}})


class FixtureClient(KubeClient):
    def __init__(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fixture_response)
        super().__init__(*args, **kwargs)


api.KubeClient = FixtureClient

original_create = webview.create_window
original_start = webview.start
loaded = threading.Event()
finished = threading.Event()
windows = []
errors = []
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    debug_port = listener.getsockname()[1]
webview.settings['REMOTE_DEBUGGING_PORT'] = debug_port


def create(*args, **kwargs):
    window = original_create(*args, hidden=True, **kwargs)
    window.events.loaded += loaded.set
    windows.append(window)
    return window


def inspect():
    try:
        assert loaded.wait(20), 'La fenêtre ne charge pas le frontend'
        window = windows[0]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = window.evaluate_js('''({text: document.body.innerText, secure: window.isSecureContext, clipboard: !!navigator.clipboard, fullscreen: document.fullscreenEnabled, configured: document.body.innerText.includes('Charger un kubeconfig')})''')
            if result and result['configured']:
                break
            time.sleep(.1)
        print("Formulaire de connexion chargé dans Qt", flush=True)
        assert result['configured'], 'Le formulaire de connexion est absent'
        assert result['secure'] and result['clipboard'], 'Presse-papiers indisponible'
        assert result['fullscreen'], 'Plein écran HTML indisponible'
        assert window.evaluate_js('document.title') == 'Kubemap'
        assert window.evaluate_js("document.querySelector('.brand').textContent.trim()") == 'Kubemap'
        assert window.evaluate_js("document.querySelector('.brand img').naturalWidth > 0"), 'Logo absent'
        pages = httpx.get(f'http://127.0.0.1:{debug_port}/json', trust_env=False).json()
        page = next(page for page in pages if page['type'] == 'page' and page['url'].startswith('http://127.0.0.1:'))
        with connect(page['webSocketDebuggerUrl'], proxy=None) as cdp:
            def evaluate(expression):
                cdp.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expression, 'userGesture': True, 'awaitPromise': True, 'returnByValue': True}}))
                while True:
                    message = json.loads(cdp.recv(timeout=10))
                    if message.get('id') == 1:
                        assert 'exceptionDetails' not in message.get('result', {}), message
                        return message
            evaluate('document.body.requestFullscreen()')
            assert window.evaluate_js('!!document.fullscreenElement'), 'Entrée en plein écran refusée'
            evaluate('document.exitFullscreen()')
            assert window.evaluate_js('document.fullscreenElement === null'), 'Sortie du plein écran refusée'
        window.evaluate_js("document.querySelector('[aria-label=\"Changer de thème\"]').click()")
        time.sleep(.1)
        first_theme = window.evaluate_js("document.querySelector('.v-application').className")
        window.evaluate_js("document.querySelector('[aria-label=\"Changer de thème\"]').click()")
        time.sleep(.1)
        second_theme = window.evaluate_js("document.querySelector('.v-application').className")
        assert any('v-theme--kubemapDark' in theme for theme in (first_theme, second_theme))
        assert any('v-theme--kubemap ' in theme for theme in (first_theme, second_theme))
        print('Identité Kubemap, thèmes et plein écran : OK', flush=True)
        def wait_for(expression):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if window.evaluate_js(expression):
                    return
                time.sleep(.05)
            raise AssertionError(f"Interface sans résultat : {expression}")

        def click(label, scope="document"):
            assert window.evaluate_js(f"(() => {{ const button = [...{scope}.querySelectorAll('button')].find(b => b.textContent.trim().startsWith({json.dumps(label)})); if (!button) return false; button.click(); return true }})()"), label

        config = {"current-context": "demo", "contexts": [{"name": name, "context": {"cluster": "demo-cluster", "user": "user"}} for name in ("demo", "other")], "clusters": [{"name": "demo-cluster", "cluster": {"server": "https://fixture.invalid"}}], "users": [{"name": "user", "user": {"token": "fixture-token"}}]}
        window.evaluate_js(f"(() => {{ const transfer = new DataTransfer(); transfer.items.add(new File([{json.dumps(json.dumps(config))}], 'demo.json')); const input = document.querySelector('#kubeconfig-file'); input.files = transfer.files; input.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")
        wait_for("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Se connecter' && !b.disabled)")
        click('Se connecter')
        wait_for("!document.querySelector('.connection-setup') && document.body.innerText.includes('demo')")
        print("Connexion au cluster simulé : OK", flush=True)
        click('Workloads', "document.querySelector('.sidebar')")
        wait_for("document.querySelector('.table-wrap')?.innerText.includes('api-pod')")
        window.evaluate_js("document.querySelector('tr.clickable').click()")
        wait_for("document.querySelector('.drawer')?.textContent.includes('100m')")
        window.evaluate_js("(() => { const select = document.querySelector('.drawer select[aria-label=Conteneur]'); select.value = 'migrate'; select.dispatchEvent(new Event('change', {bubbles: true})); const check = [...document.querySelectorAll('.drawer label')].find(l => l.textContent.includes('Conteneur précédent')).querySelector('input'); check.click(); })()")
        click('Charger les logs', "document.querySelector('.drawer')")
        wait_for("document.querySelector('.drawer')?.innerText.includes('previous init crash')")
        print("Détails et logs précédents : OK", flush=True)
        click('Ouvrir un port-forward', "document.querySelector('.drawer')")
        wait_for("document.querySelector('dialog[open]')?.innerText.includes('demo')")
        click('Ouvrir', "document.querySelector('dialog[open]')")
        wait_for("document.querySelector('.drawer')?.innerText.includes('127.0.0.1:')")
        click('Fermer le tunnel', "document.querySelector('.drawer')")
        wait_for("!document.querySelector('.drawer')?.innerText.includes('127.0.0.1:')")
        click('Fermer', "document.querySelector('.drawer')")
        click('Deployments (1)')
        window.evaluate_js("document.querySelector('tr.clickable').click()")
        wait_for("document.querySelector('.drawer')?.innerText.includes('Redémarrer l’application')")
        click('Redémarrer l’application', "document.querySelector('.drawer')")
        wait_for("document.querySelector('dialog[open]')?.innerText.includes('team/api-deploy')")
        click('Confirmer', "document.querySelector('dialog[open]')")
        wait_for("document.querySelector('.drawer')?.innerText.includes('Demande acceptée')")
        assert len(patches) == 1 and patches[0]['metadata']['uid'] == 'deploy-uid'
        assert patches[0]['spec']['template']['metadata']['annotations']['kubectl.kubernetes.io/restartedAt']
        click('Fermer', "document.querySelector('.drawer')")
        click('Ressources', "document.querySelector('.sidebar')")
        wait_for("document.body.innerText.includes('Catalogue Kubernetes')")
        print('Qt : import, diagnostic, logs init précédents, tunnel et confirmation de gestion OK', flush=True)
        screenshots = os.environ.get("KUBEMAP_SCREENSHOT_DIR")
        if screenshots:
            destination = Path(screenshots)
            destination.mkdir(parents=True, exist_ok=True)
            def capture(name):
                with connect(page['webSocketDebuggerUrl'], proxy=None) as screenshot_cdp:
                    screenshot_cdp.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png", "captureBeyondViewport": False}}))
                    while True:
                        response = json.loads(screenshot_cdp.recv(timeout=10))
                        if response.get("id") == 1:
                            (destination / name).write_bytes(base64.b64decode(response["result"]["data"]))
                            return
            click('Vue d’ensemble', "document.querySelector('.sidebar')")
            wait_for("document.querySelector('.kpis') && document.body.innerText.includes('worker-a')")
            capture('overview.png')
            click('Carte', "document.querySelector('.sidebar')")
            wait_for("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Applications')")
            click('Applications')
            wait_for("document.querySelectorAll('.infra-card').length >= 3")
            time.sleep(.2)
            capture('applications.png')
            print('Captures du cluster fictif enregistrées', flush=True)


    except BaseException as exc:
        errors.append(exc)
    finally:
        finished.set()
        windows[0].destroy()


webview.create_window = create
webview.start = lambda **kwargs: original_start(inspect, **kwargs)
logging.getLogger('httpx').setLevel(logging.WARNING)
main(['--desktop', '--allow-write', '--allow-portforward'])
assert finished.wait(5), 'Le contrôle graphique a été interrompu avant sa fin'
if errors:
    raise errors[0]
print('Fenêtre Qt réelle : démarrage, frontend et arrêt OK', flush=True)
