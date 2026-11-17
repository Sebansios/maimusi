"""Windows engine server: one Kiwi process shared by every application.

On Windows the input method is a DLL loaded into each application, so the
engine cannot be a child that speaks over stdin/stdout to one front end.
Instead the first input method that needs it starts

    MaimusiEngine.exe --pipe \\\\.\\pipe\\NAME --mutex NAME [--idle-minutes N]

which loads the model, then serves the same JSON requests as ime_service
(one request per pipe message, one reply per request) to any number of
clients of the same user. The mutex keeps a second copy from loading the
model while the first is still starting. The server exits after N idle
minutes (0: never). Typed text is never written to disk, logged or sent
anywhere; errors carry only an error type, never the input.

The pipe is owned by the user, refuses remote clients and, besides the user
and SYSTEM, admits AppContainer applications (ALL APPLICATION PACKAGES and
ALL RESTRICTED APPLICATION PACKAGES), so the input method in Store apps and
the Start menu search box can use the engine too. Sandboxed clients may only
ask for spacing, candidates and ping; they can neither change the shared
settings (configure) nor use learn. Clients check that the pipe's owner is
their user and its integrity label at least medium, which a low-integrity
process cannot give a pipe of the same name.
"""
import argparse
import ctypes
import json
import os
import threading
import time
from ctypes import wintypes

from . import __version__, __engine_version__
from .ime_service import Service

ERROR_ALREADY_EXISTS = 183
ERROR_MORE_DATA = 234
ERROR_PIPE_CONNECTED = 535
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
PIPE_UNLIMITED_INSTANCES = 255
BUFFER_SIZE = 1 << 16
MAX_MESSAGE = 1 << 20

TOKEN_QUERY = 0x0008
TOKEN_USER = 1
TOKEN_INTEGRITY_LEVEL = 25
TOKEN_IS_APP_CONTAINER = 29
SECURITY_MANDATORY_MEDIUM_RID = 0x2000

# What sandboxed clients get: read/write data and attributes, READ_CONTROL
# (to check the owner) and SYNCHRONIZE. Never FILE_CREATE_PIPE_INSTANCE, which
# would let them open a server end of this pipe.
CLIENT_ACCESS = 0x00120183
# Requests a sandboxed client may make.
SANDBOX_OPS = frozenset({"space", "candidates", "ping"})


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


def _api():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    HANDLE, DWORD, BOOL, LPVOID = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.c_void_p
    for dll, name, restype, argtypes in [
        (kernel32, "CreateMutexW", HANDLE, [LPVOID, BOOL, wintypes.LPCWSTR]),
        (kernel32, "CreateNamedPipeW", HANDLE,
         [wintypes.LPCWSTR, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, LPVOID]),
        (kernel32, "ConnectNamedPipe", BOOL, [HANDLE, LPVOID]),
        (kernel32, "ReadFile", BOOL, [HANDLE, LPVOID, DWORD, ctypes.POINTER(DWORD), LPVOID]),
        (kernel32, "WriteFile", BOOL, [HANDLE, LPVOID, DWORD, ctypes.POINTER(DWORD), LPVOID]),
        (kernel32, "CloseHandle", BOOL, [HANDLE]),
        (kernel32, "GetCurrentProcess", HANDLE, []),
        (kernel32, "GetCurrentThread", HANDLE, []),
        (kernel32, "LocalFree", LPVOID, [LPVOID]),
        (advapi32, "OpenProcessToken", BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
        (advapi32, "OpenThreadToken", BOOL, [HANDLE, DWORD, BOOL, ctypes.POINTER(HANDLE)]),
        (advapi32, "GetTokenInformation", BOOL, [HANDLE, ctypes.c_int, LPVOID, DWORD, ctypes.POINTER(DWORD)]),
        (advapi32, "IsTokenRestricted", BOOL, [HANDLE]),
        (advapi32, "ImpersonateNamedPipeClient", BOOL, [HANDLE]),
        (advapi32, "RevertToSelf", BOOL, []),
        (advapi32, "ConvertSidToStringSidW", BOOL, [LPVOID, ctypes.POINTER(wintypes.LPWSTR)]),
        (advapi32, "ConvertStringSecurityDescriptorToSecurityDescriptorW", BOOL,
         [wintypes.LPCWSTR, DWORD, ctypes.POINTER(LPVOID), ctypes.POINTER(DWORD)]),
        (advapi32, "GetSidSubAuthority", ctypes.POINTER(DWORD), [LPVOID, DWORD]),
        (advapi32, "GetSidSubAuthorityCount", ctypes.POINTER(ctypes.c_ubyte), [LPVOID]),
    ]:
        function = getattr(dll, name)
        function.restype = restype
        function.argtypes = argtypes
    return kernel32, advapi32


kernel32, advapi32 = _api() if os.name == "nt" else (None, None)


def _single_instance(name):
    """Hold a named mutex for the life of the process; None if another has it."""
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def _token_info(token, kind):
    size = wintypes.DWORD()
    advapi32.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not size.value or not advapi32.GetTokenInformation(token, kind, buf, size, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buf


def _user_sid():
    """String SID of the user this process runs as."""
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        user = _SidAndAttributes.from_buffer(_token_info(token, TOKEN_USER))
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(user.Sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.CloseHandle(token)


def pipe_sddl(user_sid):
    """Owner: the user. DACL: the user and SYSTEM, plus AppContainers with
    CLIENT_ACCESS. Medium label: low-integrity processes that are not
    AppContainers stay out, and none can forge a pipe that clients trust."""
    access = f"0x{CLIENT_ACCESS:x}"
    return (f"O:{user_sid}D:P(A;;GA;;;{user_sid})(A;;GA;;;SY)(A;;{access};;;AC)(A;;{access};;;S-1-15-2-2)"
            "S:(ML;;NW;;;ME)")


def _security_attributes(sddl):
    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    # Kept for the life of the process: every pipe instance uses it.
    return _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)


def _client_sandboxed(pipe):
    """Whether the client is an AppContainer, below medium integrity or
    restricted. Anything that cannot be determined counts as sandboxed."""
    if not advapi32.ImpersonateNamedPipeClient(pipe):
        return True
    token = wintypes.HANDLE()
    try:
        opened = advapi32.OpenThreadToken(kernel32.GetCurrentThread(), TOKEN_QUERY, True, ctypes.byref(token))
    finally:
        if not advapi32.RevertToSelf():
            os._exit(1)  # never go on serving under the client's identity
    if not opened:
        return True
    try:
        container = wintypes.DWORD.from_buffer(_token_info(token, TOKEN_IS_APP_CONTAINER)).value
        label = _SidAndAttributes.from_buffer(_token_info(token, TOKEN_INTEGRITY_LEVEL))
        count = advapi32.GetSidSubAuthorityCount(label.Sid).contents.value
        level = advapi32.GetSidSubAuthority(label.Sid, count - 1).contents.value
        return bool(container) or level < SECURITY_MANDATORY_MEDIUM_RID or bool(advapi32.IsTokenRestricted(token))
    except OSError:
        return True
    finally:
        kernel32.CloseHandle(token)


def _read_message(pipe):
    """One whole message, or None when the client is gone or sends too much."""
    buf = ctypes.create_string_buffer(BUFFER_SIZE)
    parts, total = [], 0
    while True:
        count = wintypes.DWORD()
        done = kernel32.ReadFile(pipe, buf, BUFFER_SIZE, ctypes.byref(count), None)
        if not done and ctypes.get_last_error() != ERROR_MORE_DATA:
            return None
        parts.append(buf.raw[:count.value])
        total += count.value
        if total > MAX_MESSAGE:
            return None
        if done:
            return b"".join(parts)


def _write_message(pipe, data):
    count = wintypes.DWORD()
    return bool(kernel32.WriteFile(pipe, data, len(data), ctypes.byref(count), None)) and count.value == len(data)


class PipeServer:
    def __init__(self, service, idle_minutes):
        self.service = service
        self.lock = threading.Lock()
        self.idle_seconds = max(0, idle_minutes) * 60
        self.last_use = time.monotonic()

    def handle_message(self, raw, sandboxed=False):
        request_id = None
        try:
            request = json.loads(raw.decode("utf-8"))
            request_id = request.get("id")
            if sandboxed and request.get("op") not in SANDBOX_OPS:
                raise PermissionError("op")
            # 설정 창 예문용 규칙(`spacing`)은 샌드박스 앱이 보낼 수 없다.
            if sandboxed and "spacing" in request:
                raise PermissionError("spacing")
            if request.get("op") == "configure" and "idle_minutes" in request:
                minutes = request["idle_minutes"]
                if type(minutes) is int and minutes >= 0:
                    self.idle_seconds = minutes * 60
            with self.lock:
                response = self.service.handle(request)
            response.update(id=request_id, ok=True)
        except Exception as exc:
            response = {"id": request_id, "ok": False, "error": type(exc).__name__}
        self.last_use = time.monotonic()
        return json.dumps(response, ensure_ascii=False).encode("utf-8")

    def serve_client(self, pipe):
        try:
            sandboxed = None
            while True:
                raw = _read_message(pipe)
                if raw is None:
                    break
                if sandboxed is None:
                    # The client's identity is known once it has written.
                    sandboxed = _client_sandboxed(pipe)
                if not _write_message(pipe, self.handle_message(raw, sandboxed)):
                    break
        finally:
            kernel32.CloseHandle(pipe)

    def watch_idle(self):
        while True:
            time.sleep(30)
            if self.idle_seconds and time.monotonic() - self.last_use > self.idle_seconds:
                os._exit(0)


def serve(name, server, attributes):
    """Accepts clients forever; returns at once if another server has the name."""
    first = True
    while True:
        mode = PIPE_ACCESS_DUPLEX | (FILE_FLAG_FIRST_PIPE_INSTANCE if first else 0)
        pipe = kernel32.CreateNamedPipeW(name, mode,
                                         PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_REJECT_REMOTE_CLIENTS,
                                         PIPE_UNLIMITED_INSTANCES, BUFFER_SIZE, BUFFER_SIZE, 0,
                                         ctypes.byref(attributes))
        if pipe == INVALID_HANDLE_VALUE or not pipe:
            if first:
                return
            time.sleep(0.1)
            continue
        first = False
        if not kernel32.ConnectNamedPipe(pipe, None) and ctypes.get_last_error() != ERROR_PIPE_CONNECTED:
            kernel32.CloseHandle(pipe)
            continue
        threading.Thread(target=server.serve_client, args=(pipe,), daemon=True).start()


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--mutex", required=True)
    parser.add_argument("--idle-minutes", type=int, default=20)
    args = parser.parse_args(argv)
    if not args.pipe.startswith("\\\\.\\pipe\\"):
        return 2
    guard = _single_instance(args.mutex)
    if guard is None:
        return 0
    try:
        attributes = _security_attributes(pipe_sddl(_user_sid()))
        service = Service()
        # Candidate tables load lazily; warm them with fixed public text so the
        # first real conversion gets the usual time budget.
        service.handle({"op": "candidates", "word": "학교"})
    except Exception:
        return 1
    server = PipeServer(service, args.idle_minutes)
    threading.Thread(target=server.watch_idle, daemon=True).start()
    # The first instance refuses to start when another server already has the name.
    serve(args.pipe, server, attributes)
    return 0


__all__ = ["main", "PipeServer", "pipe_sddl", "SANDBOX_OPS", "__version__", "__engine_version__"]
