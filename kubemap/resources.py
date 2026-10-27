from fastapi import APIRouter, HTTPException, Request
from .access import connected, valid_name, kubernetes_errors
from .store import slim

router = APIRouter()


@router.get("/api/catalog")
async def catalog(request: Request):
    store = connected(request)
    with kubernetes_errors():
        return await store.client.discover()


@router.get("/api/resource")
async def resources(request: Request, apiVersion: str, resource: str, namespace: str = "", cursor: str = ""):
    store = connected(request)
    valid_name(resource)
    if namespace:
        valid_name(namespace)
    with kubernetes_errors():
        catalog = await store.client.discover()
        entry = next((r for r in catalog["resources"] if r["apiVersion"] == apiVersion and r["resource"] == resource), None)
        if entry is None:
            raise HTTPException(404, "Type de ressource absent du catalogue.")
        if namespace and not entry["namespaced"]:
            raise HTTPException(400, "Cette ressource n’appartient pas à un namespace.")
        path = ("/api/" if apiVersion == "v1" else "/apis/") + apiVersion
        if namespace:
            path += f"/namespaces/{namespace}"
        data = await store.client.page(f"{path}/{resource}", cursor)
    items = []
    for item in data.get("items") or []:
        meta = slim({"metadata": item.get("metadata") or {}})["metadata"]
        meta.pop("annotations", None)
        items.append({"apiVersion": apiVersion, "kind": entry["kind"], "metadata": meta})
    return {"items": items, "continue": (data.get("metadata") or {}).get("continue", ""), "metadataOnly": True}
