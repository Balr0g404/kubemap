import asyncio
import logging
from uuid import uuid4
import httpx
import websockets
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StrictInt
from .access import connected, require_origin, valid_name, kubernetes_errors

router = APIRouter()
log = logging.getLogger(__name__)


class Forward:
    def __init__(self, client, namespace, pod, uid, port):
        self.client, self.namespace, self.pod, self.uid, self.port = client, namespace, pod, uid, port
        self.server = None
        self.local_port = None
        self.tasks = set()
        self.expiry = None
        self.error = None

    async def start(self):
        self.server = await asyncio.start_server(self.accept, "127.0.0.1", 0)
        self.local_port = self.server.sockets[0].getsockname()[1]
        self.expiry = asyncio.create_task(self.expire())

    async def expire(self):
        await asyncio.sleep(1800)
        self.error = "Tunnel expiré après 30 minutes."
        await self.close()

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        current = asyncio.current_task()
        tasks = [t for t in self.tasks | ({self.expiry} if self.expiry else set()) if t is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def info(self):
        return {"namespace": self.namespace, "pod": self.pod, "port": self.port, "localPort": self.local_port, "active": bool(self.server and self.server.is_serving()), "error": self.error}

    async def accept(self, reader, writer):
        task = asyncio.current_task()
        if len(self.tasks) >= 16:
            writer.close()
            await writer.wait_closed()
            return
        self.tasks.add(task)
        pumps = []
        try:
            obj = await self.client.get(f"/api/v1/namespaces/{self.namespace}/pods/{self.pod}")
            if obj.get("metadata", {}).get("uid") != self.uid:
                raise ValueError("Le pod a été remplacé ; ouvrez un nouveau tunnel.")
            async with self.client.portforward_connect(self.namespace, self.pod, self.port) as ws:
                async def send():
                    while chunk := await reader.read(65536):
                        await ws.send(b"\x00" + chunk)

                async def receive():
                    headers = {0: bytearray(), 1: bytearray()}
                    async for frame in ws:
                        if not isinstance(frame, bytes) or not frame or frame[0] not in headers:
                            raise ValueError("Protocole de port-forward non reconnu.")
                        channel, chunk = frame[0], frame[1:]
                        header = headers[channel]
                        if len(header) < 2:
                            count = min(2 - len(header), len(chunk))
                            header.extend(chunk[:count])
                            chunk = chunk[count:]
                            if len(header) < 2:
                                continue
                            if int.from_bytes(header, "little") != self.port:
                                raise ValueError("Port distant inattendu.")
                        if channel == 1 and chunk:
                            raise ValueError("Le port distant a refusé la connexion.")
                        if channel == 0 and chunk:
                            writer.write(chunk)
                            await writer.drain()

                pumps = [asyncio.create_task(send()), asyncio.create_task(receive())]
                done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                for pump in done:
                    pump.result()
        except (httpx.HTTPError, OSError, ValueError, websockets.WebSocketException) as exc:
            self.error = str(exc) if isinstance(exc, ValueError) else "Tunnel interrompu : vérifiez la connexion, le pod et les droits RBAC pods/portforward."
            log.info("tunnel interrompu : %s/%s", self.namespace, self.pod)
        finally:
            for pump in pumps:
                pump.cancel()
            writer.close()
            try:
                await asyncio.gather(*pumps, return_exceptions=True)
                await writer.wait_closed()
            finally:
                self.tasks.discard(task)


class ForwardRequest(BaseModel):
    port: StrictInt = Field(ge=1, le=65535)
    uid: str = Field(min_length=1, max_length=128)
    connectionId: StrictInt = Field(ge=0)


@router.post("/api/forwards/{namespace}/{pod}")
async def start_forward(request: Request, namespace: str, pod: str, body: ForwardRequest):
    require_origin(request)
    store = connected(request)
    if not store.allow_portforward:
        raise HTTPException(403, "Tunnels désactivés : lancez kubemap avec --allow-portforward.")
    valid_name(namespace)
    valid_name(pod)
    async with store.connection_lock:
        if body.connectionId != store.connection_id:
            raise HTTPException(409, "Le contexte a changé.")
        for key, forward in list(store.forwards.items()):
            if not forward.info()["active"]:
                await forward.close()
                del store.forwards[key]
        if len(store.forwards) >= 5:
            raise HTTPException(429, "Fermez un tunnel avant d’en ouvrir un autre (5 maximum).")
        with kubernetes_errors():
            obj = await store.client.get(f"/api/v1/namespaces/{namespace}/pods/{pod}")
        if obj.get("metadata", {}).get("uid") != body.uid or obj.get("status", {}).get("phase") != "Running":
            raise HTTPException(409, "Le pod a changé ou n’est pas en cours d’exécution.")
        forward = Forward(store.client, namespace, pod, body.uid, body.port)
        await forward.start()
        key = uuid4().hex
        store.forwards[key] = forward
        log.info("tunnel ouvert : %s/%s:%s sur 127.0.0.1:%s", namespace, pod, body.port, forward.local_port)
        return {"id": key, **forward.info()}


@router.get("/api/forwards")
async def list_forwards(request: Request):
    return [{"id": key, **forward.info()} for key, forward in request.state.store.forwards.items()]


@router.delete("/api/forwards/{key}")
async def stop_forward(request: Request, key: str):
    require_origin(request)
    store = request.state.store
    async with store.connection_lock:
        forward = store.forwards.pop(key, None)
        if forward:
            await forward.close()
    return {"closed": True}
