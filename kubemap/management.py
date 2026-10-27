import logging
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from .access import connected, require_origin, valid_name, kubernetes_errors

router = APIRouter()
log = logging.getLogger(__name__)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["restart", "scale", "suspend"]
    uid: str = Field(min_length=1, max_length=128)
    resourceVersion: str = Field(min_length=1, max_length=128)
    connectionId: StrictInt = Field(ge=0)
    replicas: StrictInt | None = Field(default=None, ge=0, le=100000)
    suspend: StrictBool | None = None
    acknowledgeFlux: StrictBool = False


def externally_managed(obj):
    labels = obj.get("metadata", {}).get("labels") or {}
    return bool(obj.get("metadata", {}).get("annotations", {}).get("meta.helm.sh/release-name")) or any(labels.get(key) for key in ("kustomize.toolkit.fluxcd.io/name", "helm.toolkit.fluxcd.io/name"))


@router.post("/api/manage/{kind}/{namespace}/{name}")
async def manage(request: Request, kind: Literal["deployments", "statefulsets", "daemonsets", "cronjobs"], namespace: str, name: str, action: Action):
    require_origin(request)
    store = connected(request)
    if not store.allow_write:
        raise HTTPException(403, "Gestion désactivée : lancez kubemap avec --allow-write.")
    valid_name(namespace)
    valid_name(name)
    if action.action == "scale" and (kind not in ("deployments", "statefulsets") or action.replicas is None):
        raise HTTPException(400, "Le nombre de réplicas est requis pour ce contrôleur.")
    if action.action == "suspend" and (kind != "cronjobs" or action.suspend is None):
        raise HTTPException(400, "La suspension concerne uniquement les CronJobs.")
    if action.action == "restart" and kind == "cronjobs":
        raise HTTPException(400, "Un CronJob ne se redémarre pas comme un déploiement.")
    path = f"/apis/{'batch/v1' if kind == 'cronjobs' else 'apps/v1'}/namespaces/{namespace}/{kind}/{name}"
    async with store.connection_lock:
        if action.connectionId != store.connection_id:
            raise HTTPException(409, "Le contexte a changé ; rechargez les détails avant de confirmer.")
        with kubernetes_errors():
            obj = await store.client.get(path)
            meta = obj.get("metadata") or {}
            if meta.get("uid") != action.uid or meta.get("resourceVersion") != action.resourceVersion:
                raise HTTPException(409, "La ressource a changé ; rechargez ses détails.")
            if externally_managed(obj) and not action.acknowledgeFlux:
                raise HTTPException(409, "Ressource pilotée par Flux ou Helm : la modification peut être annulée par la réconciliation. Confirmez explicitement ce risque.")
            if action.action == "scale":
                spec = {"replicas": action.replicas}
            elif action.action == "suspend":
                spec = {"suspend": action.suspend}
            else:
                spec = {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()}}}}
            await store.client.managed_patch(path, {"metadata": {"uid": action.uid, "resourceVersion": action.resourceVersion}, "spec": spec})
        log.info("gestion %s : %s/%s/%s (contexte %s)", action.action, kind, namespace, name, store.context_name)
    return {"accepted": True}
