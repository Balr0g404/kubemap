import asyncio
import pytest
from fastapi.testclient import TestClient
from kubemap.api import create_app
from kubemap.store import Store


def test_portforward_requires_flag_same_origin_and_current_context():
    client = TestClient(create_app(Store(None)))
    body = {"port": 8080, "uid": "pod-uid", "connectionId": 0}
    assert client.post("/api/forwards/team/api", json=body).status_code == 403
    assert client.post("/api/forwards/team/api", json=body, headers={"Origin": "http://testserver"}).status_code in (403, 409)


async def test_tcp_tunnel_strips_port_headers_and_relays_binary_data():
    from kubemap.portforward import Forward
    class Upstream:
        def __init__(self):
            self.sent = asyncio.Queue()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def send(self, data):
            await self.sent.put(data)
        async def __aiter__(self):
            yield b"\x00\x90\x1f"
            yield b"\x01\x90\x1f"
            data = await self.sent.get()
            assert data == b"\x00request"
            yield b"\x00response"
    class Client:
        async def get(self, path):
            return {"metadata": {"uid": "pod-uid"}}
        def portforward_connect(self, *args):
            return Upstream()
    forward = Forward(Client(), "team", "api", "pod-uid", 8080)
    await forward.start()
    try:
        assert forward.server.sockets[0].getsockname()[0] == "127.0.0.1"
        reader, writer = await asyncio.open_connection("127.0.0.1", forward.local_port)
        writer.write(b"request")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(1024), 2) == b"response"
        writer.close()
        await writer.wait_closed()
    finally:
        await forward.close()
    assert not forward.tasks


async def test_cancelling_a_tunnel_during_writer_cleanup_releases_the_task():
    from contextlib import asynccontextmanager
    from kubemap.portforward import Forward
    closing = asyncio.Event()
    class Client:
        async def get(self, path):
            return {"metadata": {"uid": "u"}}
        @asynccontextmanager
        async def portforward_connect(self, *args):
            yield self
        async def __aiter__(self):
            for frame in ():
                yield frame
    class Writer:
        closed = False
        def close(self):
            self.closed = True
        async def wait_closed(self):
            closing.set()
            await asyncio.Event().wait()
    forward = Forward(Client(), "team", "api", "u", 8080)
    writer = Writer()
    task = asyncio.create_task(forward.accept(asyncio.StreamReader(), writer))
    await asyncio.wait_for(closing.wait(), 2)
    await forward.close()
    assert task.done() and writer.closed
    assert not forward.tasks
