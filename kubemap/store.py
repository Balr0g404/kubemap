import asyncio
import logging
from datetime import datetime, timezone
from dataclasses import dataclass

import httpx

from .kube import ReadOnlyViolation
from .quantity import parse_bytes, parse_cpu

log = logging.getLogger("kubemap.store")
LAST_APPLIED = "kubectl.kubernetes.io/last-applied-configuration"


@dataclass(frozen=True)
class Resource:
    path: str
    meta_only: bool = False


RESOURCES = {
    "nodes": Resource("/api/v1/nodes"),
    "namespaces": Resource("/api/v1/namespaces"),
    "pods": Resource("/api/v1/pods"),
    "events": Resource("/api/v1/events"),
    "configmaps": Resource("/api/v1/configmaps", meta_only=True),
    "hpas": Resource("/apis/autoscaling/v2/horizontalpodautoscalers"),
    "networkpolicies": Resource("/apis/networking.k8s.io/v1/networkpolicies"),
    "services": Resource("/api/v1/services"),
    "endpointslices": Resource("/apis/discovery.k8s.io/v1/endpointslices"),
    "pvcs": Resource("/api/v1/persistentvolumeclaims"),
    "secrets": Resource("/api/v1/secrets", meta_only=True),
    "deployments": Resource("/apis/apps/v1/deployments"),
    "replicasets": Resource("/apis/apps/v1/replicasets", meta_only=True),
    "statefulsets": Resource("/apis/apps/v1/statefulsets"),
    "daemonsets": Resource("/apis/apps/v1/daemonsets"),
    "jobs": Resource("/apis/batch/v1/jobs"),
    "cronjobs": Resource("/apis/batch/v1/cronjobs"),
    "ingresses": Resource("/apis/networking.k8s.io/v1/ingresses"),
    "ingressroutes": Resource("/apis/traefik.io/v1alpha1/ingressroutes"),
    "middlewares": Resource("/apis/traefik.io/v1alpha1/middlewares"),
    "certificates": Resource("/apis/cert-manager.io/v1/certificates"),
    "cnpg_clusters": Resource("/apis/postgresql.cnpg.io/v1/clusters"),
    "helmreleases": Resource("/apis/helm.toolkit.fluxcd.io/v2/helmreleases"),
}


class ResyncNeeded(Exception):
    pass


def key(obj: dict) -> str:
    meta = obj["metadata"]
    return f'{meta.get("namespace", "")}/{meta["name"]}'


def slim(obj: dict) -> dict:
    meta = obj.get("metadata", {})
    meta.pop("managedFields", None)
    (meta.get("annotations") or {}).pop(LAST_APPLIED, None)
    return obj


def redact(node):
    """Masque ce qui peut contenir des secrets en clair dans les specs de conteneurs."""
    if isinstance(node, dict):
        if "image" in node and "name" in node:
            node.pop("args", None)
            node.pop("command", None)
            for env in node.get("env") or []:
                if isinstance(env, dict) and "value" in env:
                    env["value"] = None
        if "httpHeaders" in node:
            for header in node.get("httpHeaders") or []:
                if isinstance(header, dict):
                    header["value"] = None
        if isinstance(node.get("exec"), dict) and "command" in node["exec"]:
            node["exec"]["command"] = ["[masqué]"]
        for value in node.values():
            redact(value)
    elif isinstance(node, list):
        for value in node:
            redact(value)
    return node


class Store:
    def __init__(self, client, views_fn=None, resources=None, cluster_name="Cluster connecté", context_name="", layers=None):
        self.client = client
        self.allow_exec = False
        self.allow_secrets = False
        self.cluster_name = cluster_name
        self.context_name = context_name
        self.resources = RESOURCES if resources is None else resources
        self.layers = layers
        self.connection_document = None
        self.connection_trusted = False
        self.connection_id = 0
        self.connection_lock = asyncio.Lock()
        self.allow_write = False
        self.allow_portforward = False
        self.allow_exec_auth = False
        self.forwards = {}
        self.views_fn = views_fn or (lambda res, metrics: {})
        self.objects = {k: {} for k in self.resources}
        self.status = {k: "loading" for k in self.resources}
        self.metrics: dict = {}
        self.metrics_status = "loading"
        self.metrics_updated_at = None
        self.rev = 0
        self.unavailable_delay = 300.0
        self.error_delay_max = 30.0
        self.views_debounce = 1.0
        self.metrics_interval = 30.0
        self._subs: set[asyncio.Queue] = set()
        self._dirty = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    @property
    def connected(self) -> bool:
        return self.client is not None and all(s in ("ok", "unavailable") for s in self.status.values())

    # --- cycle de vie -------------------------------------------------
    def start(self) -> None:
        if self.client is None:
            return
        coros = [self._run_kind(k) for k in self.resources] + [self._run_metrics(), self._run_views()]
        self._tasks = [asyncio.create_task(c) for c in coros]
        for t in self._tasks:
            t.add_done_callback(self._on_done)

    async def stop(self) -> None:
        for forward in self.forwards.values():
            await forward.close()
        self.forwards.clear()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def configure(self, client, cluster_name, context_name) -> None:
        await self.stop()
        if self.client is not None and hasattr(self.client, "aclose"):
            await self.client.aclose()
        self.client = client
        self.connection_id += 1
        self.cluster_name = cluster_name
        self.context_name = context_name
        self.objects = {k: {} for k in self.resources}
        self.status = {k: "loading" for k in self.resources}
        self.metrics = {}
        self.metrics_status = "loading"
        self.metrics_updated_at = None
        self._dirty.clear()
        self._publish({"event": "resync", "connectionChanged": True})
        self.start()

    @staticmethod
    def _on_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception():
            log.error("tâche arrêtée : %r", task.exception())

    # --- abonnés ------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _publish(self, event: dict, dirty: bool = False) -> None:
        self.rev += 1
        event["rev"] = self.rev
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                while not q.empty():
                    q.get_nowait()
                q.put_nowait({"event": "resync", "rev": self.rev})
        if dirty:
            self._dirty.set()

    def _set_status(self, kind: str, status: str) -> None:
        if self.status[kind] != status:
            self.status[kind] = status
            self._publish({"event": "status", "connected": self.connected, "status": dict(self.status)})

    # --- état ---------------------------------------------------------
    def _clean(self, kind: str, obj: dict) -> dict:
        if kind == "configmaps" or self.resources[kind].meta_only:
            obj = {"metadata": obj.get("metadata", {})}
        return redact(slim(obj))

    def apply(self, kind: str, etype: str, obj: dict) -> None:
        obj = self._clean(kind, obj)
        if etype == "DELETED":
            self.objects[kind].pop(key(obj), None)
        else:
            self.objects[kind][key(obj)] = obj
        self._publish({"event": "delta", "kind": kind, "type": etype, "object": obj}, dirty=True)

    def replace(self, kind: str, items: list) -> None:
        cleaned = [self._clean(kind, i) for i in items]
        self.objects[kind] = {key(o): o for o in cleaned}
        self._publish({"event": "reset", "kind": kind, "objects": cleaned}, dirty=True)

    def compute_views(self) -> dict:
        res = {k: list(v.values()) for k, v in self.objects.items()}
        if self.layers is not None:
            from .views import build_views
            return build_views(res, self.metrics, self.layers, status=self.status)
        return self.views_fn(res, self.metrics)

    def snapshot(self) -> dict:
        return {
            "configured": self.client is not None,
            "connectionId": self.connection_id,
            "writeEnabled": self.allow_write,
            "portforwardEnabled": self.allow_portforward,
            "contexts": [c["name"] for c in (self.connection_document or {}).get("contexts", [])],
            "execEnabled": self.allow_exec,
            "secretsEnabled": self.allow_secrets,
            "clusterName": self.cluster_name,
            "contextName": self.context_name,
            "rev": self.rev,
            "connected": self.connected,
            "status": dict(self.status),
            "metrics": self.metrics,
            "metricsStatus": self.metrics_status,
            "metricsUpdatedAt": self.metrics_updated_at,
            "resources": {k: list(v.values()) for k, v in self.objects.items()},
            "views": self.compute_views(),
        }

    # --- boucles ------------------------------------------------------
    async def _run_kind(self, kind: str) -> None:
        res, delay = self.resources[kind], 1.0
        while True:
            try:
                data = await self.client.list(res.path, res.meta_only)
                self.replace(kind, data.get("items") or [])
                self._set_status(kind, "ok")
                delay = 1.0
                rv = data["metadata"]["resourceVersion"]
                while True:
                    async for ev in self.client.watch(res.path, rv, res.meta_only):
                        if ev["type"] == "ERROR":
                            raise ResyncNeeded(ev)
                        obj = ev["object"]
                        rv = obj.get("metadata", {}).get("resourceVersion", rv)
                        if ev["type"] != "BOOKMARK":
                            self.apply(kind, ev["type"], obj)
                    await asyncio.sleep(0.2)
            except (asyncio.CancelledError, ReadOnlyViolation):
                raise
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code == 410:
                    continue
                if code in (403, 404):
                    self.replace(kind, [])
                    self._set_status(kind, "unavailable")
                    await asyncio.sleep(self.unavailable_delay)
                    continue
                await self._fail(kind, exc, delay)
                delay = min(delay * 2, self.error_delay_max)
            except (httpx.HTTPError, OSError, ResyncNeeded) as exc:
                await self._fail(kind, exc, delay)
                delay = min(delay * 2, self.error_delay_max)

    async def _fail(self, kind: str, exc: Exception, delay: float) -> None:
        log.warning("%s : %r", kind, exc)
        self._set_status(kind, "error")
        await asyncio.sleep(delay)

    async def _run_metrics(self) -> None:
        while True:
            try:
                data = await self.client.list("/apis/metrics.k8s.io/v1beta1/nodes")
                self.metrics = {
                    i["metadata"]["name"]: {"cpu": parse_cpu(i["usage"]["cpu"]), "memory": parse_bytes(i["usage"]["memory"])}
                    for i in data.get("items", [])
                }
                self.metrics_status = "ok"
                self.metrics_updated_at = datetime.now(timezone.utc).isoformat()
            except (asyncio.CancelledError, ReadOnlyViolation):
                raise
            except (httpx.HTTPError, OSError, KeyError, ValueError) as exc:
                log.warning("metrics : %r", exc)
                self.metrics = {}
                self.metrics_status = "unavailable" if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (403, 404) else "error"
            self._publish({"event": "metrics", "metrics": self.metrics, "metricsStatus": self.metrics_status, "metricsUpdatedAt": self.metrics_updated_at}, dirty=True)
            await asyncio.sleep(self.metrics_interval)

    async def _run_views(self) -> None:
        last = None
        while True:
            await self._dirty.wait()
            await asyncio.sleep(self.views_debounce)
            self._dirty.clear()
            try:
                views = self.compute_views()
            except Exception:  # une vue cassée ne doit pas arrêter le flux
                log.exception("calcul des vues")
                continue
            if views != last:
                last = views
                self._publish({"event": "views", "views": views})
