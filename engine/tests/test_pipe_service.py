"""Request rules of the Windows engine server (hangul_ime/pipe_service.py).

The named pipe itself is exercised on Windows by windows/tests/pipe_smoke.py
and windows/tests/sandbox_pipe.cpp; these tests need no pipe.
"""
import json
import re

from hangul_ime.pipe_service import CLIENT_ACCESS, SANDBOX_OPS, PipeServer, pipe_sddl

FILE_CREATE_PIPE_INSTANCE = 0x0004


class FakeService:
    def __init__(self):
        self.ops = []

    def handle(self, request):
        self.ops.append(request["op"])
        return {"text": "ok"} if request["op"] == "space" else {}


def ask(server, request, sandboxed):
    raw = json.dumps(request, ensure_ascii=False).encode("utf-8")
    return json.loads(server.handle_message(raw, sandboxed).decode("utf-8"))


def test_sandboxed_clients_only_space_candidates_and_ping():
    assert SANDBOX_OPS == {"space", "candidates", "ping"}
    service = FakeService()
    server = PipeServer(service, 20)
    for op in ("space", "candidates", "ping"):
        reply = ask(server, {"id": 1, "op": op, "text": "가나", "word": "가"}, sandboxed=True)
        assert reply["ok"] and reply["id"] == 1
    for op in ("configure", "learn", "unknown", None):
        reply = ask(server, {"id": 2, "op": op, "idle_minutes": 0}, sandboxed=True)
        assert reply == {"id": 2, "ok": False, "error": "PermissionError"}
    assert service.ops == ["space", "candidates", "ping"]
    # 샌드박스 앱은 규칙을 바꿔 띄워 볼 수 없다(설정 창 예문의 `spacing`).
    reply = ask(server, {"id": 3, "op": "space", "text": "가나", "spacing": {"auxiliaries": "join"}}, sandboxed=True)
    assert reply == {"id": 3, "ok": False, "error": "PermissionError"}
    assert ask(server, {"id": 4, "op": "space", "text": "가나", "spacing": {}}, sandboxed=False)["ok"]
    # A refused configure must not change the idle timeout either.
    assert server.idle_seconds == 20 * 60


def test_ordinary_clients_may_configure():
    service = FakeService()
    server = PipeServer(service, 20)
    reply = ask(server, {"id": 3, "op": "configure", "idle_minutes": 5}, sandboxed=False)
    assert reply["ok"] and server.idle_seconds == 5 * 60
    assert ask(server, {"id": 4, "op": "learn"}, sandboxed=False)["ok"]
    assert service.ops == ["configure", "learn"]


def test_pipe_descriptor():
    user = "S-1-5-21-1-2-3-1001"
    sddl = pipe_sddl(user)
    assert sddl.startswith(f"O:{user}D:P")
    aces = re.findall(r"\(A;;([^;]+);;;([^)]+)\)", sddl)
    assert dict((sid, rights) for rights, sid in aces) == {
        user: "GA", "SY": "GA", "AC": f"0x{CLIENT_ACCESS:x}", "S-1-15-2-2": f"0x{CLIENT_ACCESS:x}"}
    # Sandboxed clients must never be able to open a server end of the pipe.
    assert not CLIENT_ACCESS & FILE_CREATE_PIPE_INSTANCE
    assert sddl.endswith("S:(ML;;NW;;;ME)")
