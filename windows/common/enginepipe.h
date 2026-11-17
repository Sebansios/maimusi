// Client side of the engine server's named pipe (engine/hangul_ime/pipe_service.py).
//
// The pipe belongs to the user's own MaimusiEngine.exe. Its security
// descriptor lets AppContainer apps of the same user connect, so a client
// trusts a pipe only if its owner is this user and its integrity label is at
// least medium: a low-integrity process of the same user can create a pipe of
// the same name, but only with a low label.
#pragma once

#include <windows.h>

#include <string>

#include "json.h"

namespace maimusi {

// Access a client asks for. No FILE_CREATE_PIPE_INSTANCE (which GENERIC_WRITE
// would include): sandboxed clients are granted exactly these rights.
constexpr DWORD kPipeClientAccess =
    FILE_READ_DATA | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | FILE_WRITE_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE;

// String SID of the user this process runs as (also inside an AppContainer).
std::wstring currentUserSid();
// AppContainer, below medium integrity, or a restricted token.
bool processSandboxed();
// The pipe's owner is this user and its label is medium or higher.
bool pipeServerTrusted(HANDLE pipe);

// One client connection to the engine server.
class PipeConnection {
public:
    PipeConnection() = default;
    ~PipeConnection();
    PipeConnection(const PipeConnection &) = delete;
    PipeConnection &operator=(const PipeConnection &) = delete;

    // Connects only to a server running as the same user (pipeServerTrusted).
    bool open(const std::wstring &name);
    void close();
    bool isOpen() const { return pipe_ != INVALID_HANDLE_VALUE; }
    // Sends one request and waits for its reply. Returns the reply's "ok";
    // `reply` holds whatever reply arrived. A timeout or error closes the
    // connection so a late reply can never be taken for the next request.
    bool request(Json request, DWORD timeoutMs, Json &reply);

private:
    HANDLE pipe_ = INVALID_HANDLE_VALUE;
    HANDLE event_ = nullptr;
    int nextId_ = 1;
};

}  // namespace maimusi
