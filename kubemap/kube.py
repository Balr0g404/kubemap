import json
import asyncio
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import httpx
import websockets

META_LIST = "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1"
META_ITEM = "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1"
FORBIDDEN_SEGMENTS = {"exec", "attach", "portforward", "proxy"}
REVEAL_HEADER = "x-kubemap-reveal"


class ReadOnlyViolation(Exception):
    pass


def _resource(path: str) -> str | None:
    """Nom de la ressource d'un chemin de l'API core (`/api/v1/...`), sinon None."""
    segs = path.strip("/").split("/")
    if segs[:2] != ["api", "v1"] or len(segs) < 3:
        return None
    rest = segs[2:]
    if rest[0] == "namespaces" and len(rest) >= 3:
        return rest[2]
    return rest[0]


class ReadOnlyTransport(httpx.AsyncBaseTransport):
    """Dernier rempart : refuse tout ce qui n'est pas une lecture."""

    def __init__(self, inner: httpx.AsyncBaseTransport):
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method != "GET":
            raise ReadOnlyViolation(f"{request.method} {path} refusé : kubemap est en lecture seule")
        if FORBIDDEN_SEGMENTS & set(path.strip("/").split("/")):
            raise ReadOnlyViolation(f"{path} refusé : sous-ressource interdite")
        # Seule lecture de valeurs : un secret nommé, demandé explicitement par `get_secret` (jamais une liste).
        reveal = REVEAL_HEADER in request.headers and len(path.strip("/").split("/")) == 6
        if _resource(path) == "secrets" and not reveal and "PartialObjectMetadata" not in request.headers.get("accept", ""):
            raise ReadOnlyViolation(f"{path} refusé : métadonnées de secrets uniquement")
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


class KubeClient:
    def __init__(self, server, ssl_context, token=None, transport=None, credentials=None):
        from .credentials import ExecAuth
        self._credentials = credentials
        self._auth = ExecAuth(credentials) if credentials else None
        inner = transport or httpx.AsyncHTTPTransport(verify=ssl_context)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._write_transport = transport
        self._catalog = None
        self._sockets = set()
        self._closed = False
        self._server, self._ssl, self._headers = server, ssl_context, headers
        self._http = httpx.AsyncClient(
            base_url=server,
            transport=ReadOnlyTransport(inner),
            headers=headers,
            auth=self._auth,
            timeout=httpx.Timeout(30.0, read=None),
        )

    def clone(self):
        return KubeClient(self._server, self._ssl, self._headers.get("Authorization", "").removeprefix("Bearer ") or None, credentials=self._credentials)

    async def aclose(self) -> None:
        self._closed = True
        await asyncio.gather(*(ws.close() for ws in list(self._sockets)), return_exceptions=True)
        await self._http.aclose()

    async def list(self, path: str, meta_only: bool = False) -> dict:
        r = await self._http.get(path, headers={"Accept": META_LIST if meta_only else "application/json"}, timeout=60)
        r.raise_for_status()
        return r.json()

    async def get(self, path):
        response = await self._http.get(path, timeout=30)
        response.raise_for_status()
        return response.json()

    async def managed_patch(self, path, patch):
        async with httpx.AsyncClient(transport=self._write_transport or httpx.AsyncHTTPTransport(verify=self._ssl), headers=self._headers, auth=self._auth, timeout=30) as client:
            response = await client.patch(self._server + path, json=patch, headers={"Content-Type": "application/merge-patch+json"})
            response.raise_for_status()

    async def page(self, path, cursor=""):
        response = await self._http.get(path, params={"limit": 500, "continue": cursor}, headers={"Accept": META_LIST}, timeout=60)
        response.raise_for_status()
        return response.json()

    async def discover(self):
        if self._catalog and time.monotonic() - self._catalog[0] < 60:
            return self._catalog[1]
        groups = await self.list("/apis")
        versions = ["v1"] + [g["preferredVersion"]["groupVersion"] for g in groups.get("groups", []) if g.get("preferredVersion")]
        semaphore = asyncio.Semaphore(4)
        async def fetch(version):
            async with semaphore:
                try:
                    data = await self.list(("/api/" if version == "v1" else "/apis/") + version)
                    return [{"apiVersion": version, "resource": r["name"], "kind": r.get("kind", r["name"]), "namespaced": bool(r.get("namespaced"))} for r in data.get("resources", []) if "/" not in r["name"] and "list" in r.get("verbs", [])], None
                except httpx.HTTPError:
                    return [], version
        results = await asyncio.gather(*(fetch(v) for v in versions))
        result = {"resources": sorted([r for items, _ in results for r in items], key=lambda r: (r["resource"], r["apiVersion"])), "unavailable": [v for _, v in results if v]}
        self._catalog = time.monotonic(), result
        return result

    async def get_secret(self, namespace: str, name: str) -> dict:
        """Valeurs d'un seul secret. À n'appeler que si `--allow-secrets` est actif."""
        r = await self._http.get(f"/api/v1/namespaces/{namespace}/secrets/{name}", headers={REVEAL_HEADER: "1"})
        r.raise_for_status()
        return r.json().get("data") or {}

    async def watch(self, path: str, resource_version: str, meta_only: bool = False) -> AsyncIterator[dict]:
        params = {
            "watch": "true",
            "resourceVersion": resource_version,
            "allowWatchBookmarks": "true",
            "timeoutSeconds": "300",
        }
        headers = {"Accept": META_ITEM if meta_only else "application/json"}
        async with self._http.stream("GET", path, params=params, headers=headers, timeout=None) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line:
                    yield json.loads(line)

    async def log_stream(self, namespace, pod, container=None, tail=500, follow=False, previous=False) -> AsyncIterator[str]:
        params = {"tailLines": str(tail), "timestamps": "true"}
        if container:
            params["container"] = container
        if previous:
            params["previous"] = "true"
        if follow and not previous:
            params["follow"] = "true"
        else:
            params["limitBytes"] = "1000000"
        path = f"/api/v1/namespaces/{namespace}/pods/{pod}/log"
        try:
            async with self._http.stream("GET", path, params=params, timeout=None if follow else 60) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode(errors="replace")[:300]
                    yield f"[kubemap] erreur {r.status_code} : {body}\n"
                    return
                async for chunk in r.aiter_text():
                    yield chunk
        except httpx.HTTPError as exc:
            yield f"[kubemap] erreur de connexion : {exc}\n"

    @asynccontextmanager
    async def _websocket(self, path, params):
        if self._closed:
            raise OSError("Connexion Kubernetes fermée.")
        url = self._server.replace("http", "ws", 1) + path + "?" + urlencode(params)
        headers = dict(self._headers)
        for attempt in range(2):
            if self._credentials:
                try:
                    await asyncio.to_thread(self._credentials.refresh, force=attempt > 0)
                except ValueError as exc:
                    raise OSError(str(exc)) from None
                headers = {"Authorization": "Bearer " + self._credentials.token} if self._credentials.token else {}
            try:
                ws = await websockets.connect(url, ssl=self._ssl if url.startswith("wss") else None, additional_headers=headers, subprotocols=["v4.channel.k8s.io"], max_size=1_048_576, proxy=None, close_timeout=2)
                break
            except websockets.exceptions.InvalidStatus as exc:
                if exc.response.status_code != 401 or not self._credentials or attempt:
                    raise
        if self._closed:
            await ws.close()
            raise OSError("Le contexte Kubernetes a changé.")
        self._sockets.add(ws)
        try:
            yield ws
        finally:
            self._sockets.discard(ws)
            await ws.close()

    def portforward_connect(self, namespace, pod, port):
        return self._websocket(f"/api/v1/namespaces/{namespace}/pods/{pod}/portforward", [("ports", str(port))])

    def exec_connect(self, namespace, pod, container=None, command=("bash",)):
        query = [("stdin", "true"), ("stdout", "true"), ("tty", "true")]
        if container:
            query.append(("container", container))
        query += [("command", c) for c in command]
        return self._websocket(f"/api/v1/namespaces/{namespace}/pods/{pod}/exec", query)
