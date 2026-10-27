import asyncio
import base64
import json
import logging
import time
from uuid import UUID
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .kube import KubeClient
from .kubeconfig import parse, describe, from_document
from .store import Store
from .access import NAME_RE, require_origin

MAX_TAIL = 2000
MAX_CONFIG = 1_048_576
log = logging.getLogger(__name__)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


async def event_stream(store, keepalive: float = 15.0):
    q = store.subscribe()
    try:
        yield _sse({"event": "hello", "rev": store.rev})
        while True:
            try:
                event = await asyncio.wait_for(q.get(), keepalive)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _sse(event)
    finally:
        store.unsubscribe(q)


async def _exec_error(ws, message: str) -> None:
    try:
        await ws.send_text(json.dumps({"error": message}))
    except RuntimeError:
        pass


def create_app(store, static_dir=None) -> FastAPI:
    sessions = {}

    async def session_store(token):
        if not token:
            return store
        try:
            if str(UUID(token)) != token:
                raise ValueError
        except (ValueError, AttributeError):
            raise HTTPException(400, "Session invalide.") from None
        if token not in sessions:
            while len(sessions) >= 32:
                idle = [(key, entry) for key, entry in sessions.items() if not entry[0]._subs and not entry[0].connection_lock.locked() and not entry[0].forwards and not getattr(entry[0].client, "_sockets", ())]
                if not idle:
                    raise HTTPException(429, "Trop de sessions ouvertes ; fermez les onglets inutilisés.")
                key, (current, _) = min(idle, key=lambda item: item[1][1])
                sessions.pop(key)
                await close_store(current)
            client = None
            if isinstance(store.client, KubeClient):
                client = store.client.clone()
            current = Store(client, views_fn=store.views_fn, resources=store.resources, layers=store.layers, cluster_name=store.cluster_name if client else "", context_name=store.context_name if client else "")
            for flag in ("allow_exec", "allow_secrets", "allow_write", "allow_portforward", "allow_exec_auth"):
                setattr(current, flag, getattr(store, flag))
            current.connection_document = store.connection_document
            current.connection_trusted = store.connection_trusted
            current.start()
            sessions[token] = [current, time.monotonic()]
        sessions[token][1] = time.monotonic()
        return sessions[token][0]

    async def close_store(current):
        await current.stop()
        if current.client is not None and hasattr(current.client, "aclose"):
            await current.client.aclose()

    async def reap_sessions():
        while True:
            await asyncio.sleep(60)
            for token, (current, used) in list(sessions.items()):
                if not current._subs and time.monotonic() - used > 900:
                    sessions.pop(token)
                    await close_store(current)

    @asynccontextmanager
    async def lifespan(app):
        store.start()
        reaper = asyncio.create_task(reap_sessions())
        try:
            yield
        finally:
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)
            await close_store(store)
            for current, _ in list(sessions.values()):
                await close_store(current)

    app = FastAPI(title="kubemap", lifespan=lifespan)

    @app.middleware("http")
    async def isolated_session(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            try:
                origin = request.headers.get("origin")
                if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                    raise HTTPException(403, "Accès autorisé uniquement depuis cette application.")
                token = request.headers.get("x-kubemap-session") or request.query_params.get("session")
                request.state.session_token = token
                request.state.store = (sessions.get(token, [store])[0] if request.url.path == "/api/session/close" else await session_store(token))
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)

    @app.post("/api/session/close")
    async def close_session(request: Request):
        require_origin(request)
        entry = sessions.pop(request.state.session_token, None)
        if entry:
            async with entry[0].connection_lock:
                await close_store(entry[0])
        return {"closed": True}

    async def uploaded_config(request: Request):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Import autorisé uniquement depuis cette application.")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "Un document JSON est requis.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_CONFIG:
                raise HTTPException(413, "Kubeconfig trop volumineux (1 Mo maximum).")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("kubeconfig"), str) or (payload.get("context") is not None and not isinstance(payload["context"], str)):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(400, "Fichier kubeconfig invalide.") from None
        try:
            return parse(payload["kubeconfig"]), payload.get("context")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/kubeconfig/contexts")
    async def contexts(request: Request):
        cfg, _ = await uploaded_config(request)
        return describe(cfg)

    @app.post("/api/connection")
    async def connect(request: Request):
        store = request.state.store
        document, context = await uploaded_config(request)
        try:
            cfg = from_document(document, context)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc) if isinstance(exc, ValueError) else "Kubeconfig invalide.") from None
        async with store.connection_lock:
            try:
                client = KubeClient(cfg.server, cfg.ssl_context, cfg.token, credentials=cfg.credentials)
            except (httpx.InvalidURL, ValueError):
                raise HTTPException(400, "Adresse du cluster invalide.") from None
            await store.configure(client, cfg.cluster_name, cfg.context_name)
            store.connection_document = document
            store.connection_trusted = False
        return {"clusterName": cfg.cluster_name, "contextName": cfg.context_name}

    @app.post("/api/connection/context")
    async def change_context(request: Request):
        require_origin(request)
        store = request.state.store
        if store.connection_document is None:
            raise HTTPException(409, "Chargez d’abord un kubeconfig.")
        try:
            payload = await request.json()
            context = payload["context"]
            if not isinstance(context, str):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, "Contexte invalide.") from None
        async with store.connection_lock:
            try:
                cfg = await asyncio.to_thread(from_document, store.connection_document, context, allow_files=store.connection_trusted, allow_exec_auth=store.allow_exec_auth and store.connection_trusted)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            client = KubeClient(cfg.server, cfg.ssl_context, cfg.token, credentials=cfg.credentials)
            await store.configure(client, cfg.cluster_name, cfg.context_name)
        return {"clusterName": cfg.cluster_name, "contextName": cfg.context_name}

    @app.get("/api/snapshot")
    async def snapshot(request: Request):
        return request.state.store.snapshot()

    @app.get("/api/events")
    async def events(request: Request):
        store = request.state.store
        headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        return StreamingResponse(event_stream(store), media_type="text/event-stream", headers=headers)

    @app.get("/api/logs/{namespace}/{pod}")
    async def logs(request: Request, namespace: str, pod: str, container: str | None = None, tail: int = 500, follow: bool = False, previous: bool = False):
        store = request.state.store
        if store.client is None:
            raise HTTPException(409, "Chargez un kubeconfig pour consulter les logs.")
        if not NAME_RE.match(namespace) or not NAME_RE.match(pod) or (container and not NAME_RE.match(container)):
            raise HTTPException(400, "nom invalide")
        tail = max(1, min(tail, MAX_TAIL))
        stream = store.client.log_stream(namespace, pod, container=container, tail=tail, follow=follow and not previous, previous=previous)
        return StreamingResponse(stream, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})

    @app.post("/api/secrets/{namespace}/{name}/reveal")
    async def reveal_secret(namespace: str, name: str, request: Request):
        store = request.state.store
        origin = request.headers.get("origin")
        if not origin or origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Affichage autorisé uniquement depuis cette application.")
        if not store.allow_secrets or store.client is None:
            raise HTTPException(403, "Affichage des secrets désactivé : lancez kubemap avec --allow-secrets.")
        if not NAME_RE.match(namespace) or not NAME_RE.match(name):
            raise HTTPException(400, "nom invalide")
        try:
            data = await store.client.get_secret(namespace, name)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, "Kubernetes a refusé la lecture : droit RBAC `get secrets` ou secret introuvable.") from None
        except httpx.HTTPError:
            raise HTTPException(502, "Connexion au cluster impossible.") from None
        log.info("secret affiché : %s/%s", namespace, name)
        # Clés non UTF-8 (certificats binaires, etc.) : renvoyées en base64 avec binary=true.
        out = {}
        for k, v in data.items():
            raw = base64.b64decode(v)
            try:
                out[k] = {"value": raw.decode(), "binary": False}
            except UnicodeDecodeError:
                out[k] = {"value": v, "binary": True}
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    @app.websocket("/api/exec/{namespace}/{pod}")
    async def exec_pod(ws: WebSocket, namespace: str, pod: str, container: str | None = None, connectionId: int = 0):
        origin = urlparse(ws.headers.get("origin", ""))
        expected_scheme = "https" if ws.url.scheme == "wss" else "http"
        if origin.scheme != expected_scheme or origin.netloc != ws.headers.get("host"):
            await ws.close(1008)
            return
        try:
            store = await session_store(ws.query_params.get("session"))
        except HTTPException:
            await ws.close(1008)
            return
        # Shell local sans authentification : refuser toute origine autre que cette application (détournement via une page tierce).
        same_origin = urlparse(ws.headers.get("origin", "")).netloc == ws.headers.get("host")
        valid = NAME_RE.match(namespace) and NAME_RE.match(pod) and (not container or NAME_RE.match(container))
        if not (store.allow_exec and store.client is not None and same_origin and valid and connectionId == store.connection_id):
            await ws.close(1008)
            return
        client = store.client
        await ws.accept()
        log.info("exec ouvert : %s/%s (%s)", namespace, pod, container or "conteneur par défaut")
        try:
            async with client.exec_connect(namespace, pod, container) as up:
                async def to_browser():
                    async for msg in up:
                        if not isinstance(msg, bytes) or not msg:
                            continue
                        channel, data = msg[0], msg[1:]
                        if channel in (1, 2):
                            await ws.send_bytes(data)
                        elif channel == 3:
                            status = json.loads(data or b"{}")
                            if status.get("status") != "Success":
                                await ws.send_text(json.dumps({"error": status.get("message") or "session terminée"}))
                            return

                async def to_cluster():
                    while True:
                        m = await ws.receive()
                        if m["type"] == "websocket.disconnect":
                            return
                        if m.get("bytes"):
                            await up.send(b"\x00" + m["bytes"])
                        elif m.get("text"):
                            size = json.loads(m["text"]).get("resize") or {}
                            await up.send(b"\x04" + json.dumps({"Width": int(size["cols"]), "Height": int(size["rows"])}).encode())

                tasks = [asyncio.create_task(to_browser()), asyncio.create_task(to_cluster())]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for t in done:
                    t.result()
        except websockets.exceptions.InvalidStatus as exc:
            await _exec_error(ws, f"Kubernetes a refusé la session (HTTP {exc.response.status_code}) : droits `pods/exec` ou pod introuvable.")
        except (OSError, websockets.WebSocketException) as exc:
            await _exec_error(ws, f"Connexion impossible : {exc}")
        except Exception as exc:  # noqa: BLE001 - navigateur parti, message mal formé : on ferme proprement
            log.info("exec interrompu : %r", exc)
        finally:
            log.info("exec fermé : %s/%s", namespace, pod)
            try:
                await ws.close()
            except RuntimeError:
                pass

    from .resources import router as resource_router
    app.include_router(resource_router)
    from .management import router as management_router
    app.include_router(management_router)
    from .portforward import router as forward_router
    app.include_router(forward_router)

    if static_dir and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app
