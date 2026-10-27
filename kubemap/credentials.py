import asyncio
import base64
import json
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
import httpx


class ExecCredentials:
    def __init__(self, config, cluster, ssl_context):
        self.config, self.cluster, self.ssl_context = config, cluster, ssl_context
        self.token = None
        self.expiration = None
        self.loaded = False
        self.lock = threading.Lock()

    def refresh(self, force=False):
        with self.lock:
            now = datetime.now(timezone.utc)
            if self.loaded and not force and (self.expiration is None or self.expiration > now + timedelta(seconds=30)):
                return
            try:
                cfg = self.config
                version = cfg.get("apiVersion")
                if version not in ("client.authentication.k8s.io/v1", "client.authentication.k8s.io/v1beta1"):
                    raise ValueError
                mode = cfg.get("interactiveMode", "IfAvailable" if version.endswith("v1beta1") else None)
                if mode not in ("Never", "IfAvailable"):
                    raise ValueError
                command, args = cfg["command"], cfg.get("args", [])
                if not isinstance(command, str) or not command or not isinstance(args, list) or any(not isinstance(a, str) for a in args):
                    raise ValueError
                env = os.environ.copy()
                for entry in cfg.get("env") or []:
                    if not isinstance(entry.get("name"), str) or not isinstance(entry.get("value"), str):
                        raise ValueError
                    env[entry["name"]] = entry["value"]
                info = {"apiVersion": version, "kind": "ExecCredential", "spec": {"interactive": False}}
                if cfg.get("provideClusterInfo"):
                    info["spec"]["cluster"] = {k: v for k, v in self.cluster.items() if k in ("server", "certificate-authority-data", "tls-server-name")}
                    for extension in self.cluster.get("extensions") or []:
                        if extension.get("name") == "client.authentication.k8s.io/exec":
                            info["spec"]["cluster"]["config"] = extension.get("extension")
                env["KUBERNETES_EXEC_INFO"] = json.dumps(info)
                result = subprocess.run([command, *args], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30, check=True, shell=False)
                if len(result.stdout) > 1_048_576:
                    raise ValueError
                document = json.loads(result.stdout)
                if document.get("apiVersion") != version or document.get("kind") != "ExecCredential":
                    raise ValueError
                status = document["status"]
                token = status.get("token")
                if token is not None and (not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token)):
                    raise ValueError
                cert, key = status.get("clientCertificateData"), status.get("clientKeyData")
                if bool(cert) != bool(key) or (not token and not cert):
                    raise ValueError
                if cert:
                    from .kubeconfig import _load_chain
                    _load_chain(self.ssl_context, base64.b64encode(cert.encode()).decode(), base64.b64encode(key.encode()).decode())
                expiry = status.get("expirationTimestamp")
                expiration = datetime.fromisoformat(expiry.replace("Z", "+00:00")) if expiry else None
                if expiration is not None and (expiration.tzinfo is None or expiration <= now):
                    raise ValueError
                self.token, self.expiration, self.loaded = token, expiration, True
            except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
                raise ValueError("Plugin d’authentification indisponible ou réponse ExecCredential invalide ; vérifiez son installation et votre connexion cloud.") from None


class ExecAuth(httpx.Auth):
    def __init__(self, credentials):
        self.credentials = credentials

    async def async_auth_flow(self, request):
        for attempt in range(2):
            try:
                await asyncio.to_thread(self.credentials.refresh, force=attempt > 0)
            except ValueError as exc:
                raise httpx.RequestError(str(exc), request=request) from None
            if self.credentials.token:
                request.headers["Authorization"] = "Bearer " + self.credentials.token
            else:
                request.headers.pop("Authorization", None)
            response = yield request
            if response.status_code != 401 or attempt:
                return
            await response.aread()
