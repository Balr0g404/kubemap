import base64
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


@dataclass
class KubeConfig:
    server: str
    ssl_context: ssl.SSLContext
    token: str | None
    cluster_name: str = "Cluster connecté"
    context_name: str = ""
    credentials: object = None


def _load_chain(ctx: ssl.SSLContext, cert_b64: str, key_b64: str) -> None:
    # Le dossier temporaire est en 0700 et supprimé dès le chargement.
    with tempfile.TemporaryDirectory() as d:
        cert, key = Path(d, "c.pem"), Path(d, "k.pem")
        cert.write_bytes(base64.b64decode(cert_b64, validate=True))
        key.write_bytes(base64.b64decode(key_b64, validate=True))
        key.chmod(0o600)
        ctx.load_cert_chain(cert, key)


def parse(text: str) -> dict:
    try:
        cfg = yaml.safe_load(text)
        if not isinstance(cfg, dict):
            raise ValueError
        for section, field in (("contexts", "context"), ("clusters", "cluster"), ("users", "user")):
            items = cfg.get(section)
            if not isinstance(items, list) or not items:
                raise ValueError
            names = set()
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"] or not isinstance(item.get(field), dict) or item["name"] in names:
                    raise ValueError
                names.add(item["name"])
        for item in cfg["contexts"]:
            ctx = item["context"]
            if not isinstance(ctx.get("cluster"), str) or not isinstance(ctx.get("user"), str):
                raise ValueError
        return cfg
    except (yaml.YAMLError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Kubeconfig invalide : vérifiez les contextes, clusters et utilisateurs.") from exc


def describe(cfg: dict) -> dict:
    names = [c["name"] for c in cfg["contexts"]]
    current = cfg.get("current-context")
    return {"contexts": names, "currentContext": current if current in names else names[0]}


def from_document(cfg: dict, context: str | None = None, *, allow_files: bool = False, allow_exec_auth: bool = False) -> KubeConfig:
    chosen = context or describe(cfg)["currentContext"]
    ctx = next((c["context"] for c in cfg["contexts"] if c["name"] == chosen), None)
    if ctx is None:
        raise ValueError("Contexte introuvable dans ce kubeconfig.")
    cluster = next((c["cluster"] for c in cfg["clusters"] if c["name"] == ctx["cluster"]), None)
    user = next((u["user"] for u in cfg["users"] if u["name"] == ctx["user"]), None)
    if cluster is None or user is None:
        raise ValueError("Le contexte référence un cluster ou un utilisateur absent.")
    if "auth-provider" in user or ("exec" in user and not (allow_exec_auth and allow_files)):
        raise ValueError("kubeconfig : seules l'authentification par certificat client ou token est prise en charge ; les plugins ne sont pas exécutés.")
    if not allow_files and (any(k in user for k in ("client-certificate", "client-key", "tokenFile")) or "certificate-authority" in cluster):
        raise ValueError("Utilisez un kubeconfig autonome : certificats et clé intégrés en base64, ou token. Les chemins de fichiers ne sont pas acceptés à l’import.")
    if cluster.get("insecure-skip-tls-verify") or "proxy-url" in cluster:
        raise ValueError("La vérification TLS est obligatoire et les proxys de kubeconfig ne sont pas pris en charge.")
    server = cluster.get("server")
    if not isinstance(server, str):
        raise ValueError("Adresse du cluster absente.")
    try:
        url = urlsplit(server)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or any(ord(c) <= 32 for c in server):
            raise ValueError
        _ = url.port
    except ValueError:
        raise ValueError("L’adresse du cluster doit être une URL HTTPS valide sans identifiants.") from None
    token = user.get("token")
    if token is not None and (not isinstance(token, str) or not token or any(ord(c) < 32 or ord(c) > 126 for c in token)):
        raise ValueError("Token invalide.")
    ssl_ctx = ssl.create_default_context()
    credentials = None
    try:
        if "certificate-authority-data" in cluster:
            ssl_ctx.load_verify_locations(cadata=base64.b64decode(cluster["certificate-authority-data"], validate=True).decode())
        elif "certificate-authority" in cluster:
            ssl_ctx.load_verify_locations(cafile=cluster["certificate-authority"])
        if "exec" in user:
            from .credentials import ExecCredentials
            credentials = ExecCredentials(user["exec"], cluster, ssl_ctx)
            credentials.refresh()
            token = credentials.token
        elif "client-certificate-data" in user:
            _load_chain(ssl_ctx, user["client-certificate-data"], user["client-key-data"])
        elif "client-certificate" in user:
            ssl_ctx.load_cert_chain(user["client-certificate"], user["client-key"])
        elif token is None:
            raise ValueError("kubeconfig : seules l'authentification par certificat client ou token est prise en charge")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("kubeconfig : certificat client ou token requis ; vérifiez les certificats et leur encodage.") from exc
    return KubeConfig(server.rstrip("/"), ssl_ctx, token, ctx["cluster"], chosen, credentials)


def local_document(path):
    path = Path(path).expanduser().resolve()
    document = parse(path.read_text())
    for item in document["clusters"]:
        cluster = item["cluster"]
        if "certificate-authority" in cluster:
            ca = Path(cluster["certificate-authority"])
            cluster["certificate-authority"] = str(ca if ca.is_absolute() else path.parent / ca)
            cluster["certificate-authority-data"] = base64.b64encode(Path(cluster["certificate-authority"]).read_bytes()).decode()
    for item in document["users"]:
        user = item["user"]
        for field in ("client-certificate", "client-key", "tokenFile"):
            if field in user:
                value = Path(user[field])
                user[field] = str(value if value.is_absolute() else path.parent / value)
        plugin = user.get("exec")
        if isinstance(plugin, dict) and isinstance(plugin.get("command"), str) and "/" in plugin["command"]:
            command = Path(plugin["command"])
            plugin["command"] = str(command if command.is_absolute() else path.parent / command)
    return document


def load(path: str, context: str | None = None, *, allow_exec_auth=False) -> KubeConfig:
    return from_document(local_document(path), context, allow_files=True, allow_exec_auth=allow_exec_auth)
