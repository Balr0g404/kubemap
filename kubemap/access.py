from contextlib import contextmanager
import re
import httpx
from fastapi import HTTPException

NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")


def require_origin(request):
    origin = request.headers.get("origin", "").rstrip("/")
    if origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Action autorisée uniquement depuis cette application.")


def connected(request):
    store = request.state.store
    if store.client is None:
        raise HTTPException(409, "Connectez un cluster avant cette opération.")
    return store


def valid_name(value):
    if not NAME_RE.fullmatch(value):
        raise HTTPException(400, "Nom Kubernetes invalide.")
    return value


@contextmanager
def kubernetes_errors():
    try:
        yield
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = {401: "Identifiants refusés ou expirés.", 403: "Droits Kubernetes (RBAC) insuffisants.", 404: "Ressource Kubernetes introuvable.", 409: "La ressource a changé ; rechargez ses détails.", 422: "Kubernetes a refusé les paramètres."}.get(code, "L’API Kubernetes est indisponible.")
        raise HTTPException(code if code in (401, 403, 404, 409, 422) else 502, detail) from None
    except (httpx.HTTPError, OSError):
        raise HTTPException(502, "Connexion au cluster impossible.") from None
