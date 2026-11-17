#include "enginepipe.h"

#include <aclapi.h>
#include <sddl.h>

#include <vector>

namespace maimusi {

namespace {

std::vector<BYTE> tokenInfo(TOKEN_INFORMATION_CLASS kind) {
    std::vector<BYTE> buf;
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return buf;
    DWORD size = 0;
    GetTokenInformation(token, kind, nullptr, 0, &size);
    buf.resize(size);
    if (!size || !GetTokenInformation(token, kind, buf.data(), size, &size)) buf.clear();
    CloseHandle(token);
    return buf;
}

PSID userSid() {
    static const std::vector<BYTE> user = tokenInfo(TokenUser);
    return user.empty() ? nullptr : reinterpret_cast<const TOKEN_USER *>(user.data())->User.Sid;
}

DWORD sidLevel(PSID sid) { return *GetSidSubAuthority(sid, *GetSidSubAuthorityCount(sid) - 1); }

// Waits for an overlapped operation until the deadline; cancels it on timeout.
bool finish(HANDLE h, OVERLAPPED &ov, BOOL started, ULONGLONG deadline, DWORD &bytes, bool &moreData) {
    moreData = false;
    if (!started) {
        DWORD err = GetLastError();
        if (err == ERROR_MORE_DATA) {
            moreData = true;
        } else if (err != ERROR_IO_PENDING) {
            return false;
        }
    }
    ULONGLONG now = GetTickCount64();
    DWORD wait = now >= deadline ? 0 : static_cast<DWORD>(deadline - now);
    if (WaitForSingleObject(ov.hEvent, wait) != WAIT_OBJECT_0) {
        CancelIoEx(h, &ov);
        GetOverlappedResult(h, &ov, &bytes, TRUE);
        return false;
    }
    if (!GetOverlappedResult(h, &ov, &bytes, FALSE)) {
        if (GetLastError() != ERROR_MORE_DATA) return false;
        moreData = true;
    }
    return true;
}

}  // namespace

std::wstring currentUserSid() {
    std::wstring result;
    LPWSTR text = nullptr;
    PSID sid = userSid();
    if (sid && ConvertSidToStringSidW(sid, &text)) {
        result = text;
        LocalFree(text);
    }
    return result;
}

bool processSandboxed() {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return true;
    DWORD appContainer = 0, size = 0;
    GetTokenInformation(token, TokenIsAppContainer, &appContainer, sizeof appContainer, &size);
    bool restricted = IsTokenRestricted(token);
    CloseHandle(token);
    std::vector<BYTE> label = tokenInfo(TokenIntegrityLevel);
    bool low = label.empty() ||
               sidLevel(reinterpret_cast<const TOKEN_MANDATORY_LABEL *>(label.data())->Label.Sid) < SECURITY_MANDATORY_MEDIUM_RID;
    return appContainer || low || restricted;
}

bool pipeServerTrusted(HANDLE pipe) {
    PSID owner = nullptr;
    PACL sacl = nullptr;
    PSECURITY_DESCRIPTOR sd = nullptr;
    if (GetSecurityInfo(pipe, SE_KERNEL_OBJECT, OWNER_SECURITY_INFORMATION | LABEL_SECURITY_INFORMATION, &owner,
                        nullptr, nullptr, &sacl, &sd) != ERROR_SUCCESS)
        return false;
    bool trusted = false;
    PSID user = userSid();
    if (owner && user && EqualSid(owner, user)) {
        // Objects without a label count as medium. Objects a low-integrity
        // process creates always carry its low label.
        DWORD level = SECURITY_MANDATORY_MEDIUM_RID;
        for (DWORD i = 0; sacl && i < sacl->AceCount; ++i) {
            ACE_HEADER *ace = nullptr;
            if (GetAce(sacl, i, reinterpret_cast<void **>(&ace)) && ace->AceType == SYSTEM_MANDATORY_LABEL_ACE_TYPE) {
                level = sidLevel(&reinterpret_cast<SYSTEM_MANDATORY_LABEL_ACE *>(ace)->SidStart);
                break;
            }
        }
        trusted = level >= SECURITY_MANDATORY_MEDIUM_RID;
    }
    LocalFree(sd);
    return trusted;
}

// MARK: PipeConnection

PipeConnection::~PipeConnection() {
    close();
    if (event_) CloseHandle(event_);
}

bool PipeConnection::open(const std::wstring &name) {
    close();
    HANDLE h = INVALID_HANDLE_VALUE;
    for (int attempt = 0; attempt < 2; ++attempt) {
        h = CreateFileW(name.c_str(), kPipeClientAccess, 0, nullptr, OPEN_EXISTING,
                        FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr);
        if (h != INVALID_HANDLE_VALUE || GetLastError() != ERROR_PIPE_BUSY) break;
        WaitNamedPipeW(name.c_str(), 100);
    }
    if (h == INVALID_HANDLE_VALUE) return false;
    // Typed text goes to this server: make sure it is our own user's engine,
    // not another account or a sandboxed process squatting on the name.
    DWORD mode = PIPE_READMODE_MESSAGE;
    if (!pipeServerTrusted(h) || !SetNamedPipeHandleState(h, &mode, nullptr, nullptr)) {
        CloseHandle(h);
        return false;
    }
    if (!event_) event_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    pipe_ = h;
    return true;
}

void PipeConnection::close() {
    if (pipe_ != INVALID_HANDLE_VALUE) {
        CloseHandle(pipe_);
        pipe_ = INVALID_HANDLE_VALUE;
    }
}

bool PipeConnection::request(Json req, DWORD timeoutMs, Json &reply) {
    if (!isOpen() || !event_) return false;
    int id = nextId_++;
    req.set("id", id);
    std::string data = req.dump();
    ULONGLONG deadline = GetTickCount64() + timeoutMs;

    OVERLAPPED ov{};
    ov.hEvent = event_;
    ResetEvent(event_);
    DWORD bytes = 0;
    bool more = false;
    BOOL started = WriteFile(pipe_, data.data(), static_cast<DWORD>(data.size()), nullptr, &ov);
    if (!finish(pipe_, ov, started, deadline, bytes, more) || bytes != data.size()) {
        close();
        return false;
    }
    std::string message;
    char buf[16384];
    for (;;) {
        ov = OVERLAPPED{};
        ov.hEvent = event_;
        ResetEvent(event_);
        started = ReadFile(pipe_, buf, sizeof buf, nullptr, &ov);
        if (!finish(pipe_, ov, started, deadline, bytes, more)) {
            close();
            return false;
        }
        message.append(buf, bytes);
        if (!more) break;
        if (message.size() > (4u << 20)) {
            close();
            return false;
        }
    }
    Json parsed;
    if (!Json::parse(message, parsed) || parsed["id"].asInt(-1) != id) {
        close();
        return false;
    }
    bool ok = parsed["ok"].asBool();
    reply = std::move(parsed);
    return ok;
}

}  // namespace maimusi
