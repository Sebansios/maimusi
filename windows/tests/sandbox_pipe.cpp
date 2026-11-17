// Sandbox test of the engine server's named pipe (engine/hangul_ime/pipe_service.py)
// and its client (windows/common/enginepipe.cpp). Starts a private server, then
// checks from real child processes that
//   - an AppContainer client, and a less privileged one (LPAC), connects and
//     gets spacing, candidates and ping, while configure and learn are refused;
//   - it can neither open a server end of the engine pipe nor make a pipe of
//     its own outside its namespace;
//   - the AppContainer reads the settings copy in HKCU\Software\Maimusi\Sandbox,
//     which holds no user words or learned boundaries;
//   - a low-integrity process cannot connect, and a pipe it makes (owned by the
//     same user, but labelled low) is not trusted by clients;
//   - a pipe owned by another account (a system pipe) is not trusted.
// Usage:
//   sandbox_pipe.exe <server command...>
//     e.g. build\windows\engine\dist\MaimusiEngine\MaimusiEngine.exe
//     or   build\venv-engine\Scripts\python.exe engine\hangul_engine_main.py
//   sandbox_pipe.exe --launch <program> [arguments]
//     runs a program in the test AppContainer (e.g. tsf_harness.exe --rich)
// Build (x64 Native Tools prompt):
//   cl /utf-8 /std:c++20 /EHsc /O2 /MT /DUNICODE /D_UNICODE /DNOMINMAX windows\tests\sandbox_pipe.cpp
//      windows\common\enginepipe.cpp windows\common\json.cpp windows\common\settings.cpp
//      advapi32.lib userenv.lib ole32.lib shell32.lib
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>
#include <aclapi.h>
#include <sddl.h>
#include <userenv.h>

#include <cstdio>
#include <string>
#include <vector>

#include "../common/enginepipe.h"
#include "../common/settings.h"
#include "../common/text.h"

using namespace maimusi;

namespace {

const wchar_t kContainer[] = L"Maimusi.Test.Sandbox";
int g_failed = 0;
std::string g_who = "parent";

void check(bool ok, const std::string &what, const std::string &detail = {}) {
    g_failed += !ok;
    std::printf("%s %-12s %s%s%s\n", ok ? "PASS" : "FAIL", g_who.c_str(), what.c_str(), detail.empty() ? "" : "  ",
                detail.c_str());
    std::fflush(stdout);
}

std::wstring quote(const std::wstring &s) { return L"\"" + s + L"\""; }

std::wstring selfPath() {
    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(nullptr, path, MAX_PATH);
    return std::wstring(path, n);
}

// Owner and label of a pipe, as SDDL.
std::string securityText(HANDLE h) {
    PSECURITY_DESCRIPTOR sd = nullptr;
    LPWSTR text = nullptr;
    std::string out = "?";
    SECURITY_INFORMATION what = OWNER_SECURITY_INFORMATION | LABEL_SECURITY_INFORMATION;
    if (GetSecurityInfo(h, SE_KERNEL_OBJECT, what, nullptr, nullptr, nullptr, nullptr, &sd) == ERROR_SUCCESS &&
        ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, SDDL_REVISION_1, what, &text, nullptr)) {
        out = narrow(text);
    }
    LocalFree(text);
    LocalFree(sd);
    return out;
}

// The preferences a sandboxed input method uses, in one word.
std::string describe(const Settings &s) {
    return s.engine() + "|" + (s.getBool("convertOnSpace") ? "1" : "0") + "|" + s.getString("spaceInConversion") +
           "|" + s.getString("hanjaForms") + "|" + (s.getBool("rightAltToggles") ? "1" : "0");
}

Json request(const char *op) {
    Json r = Json::object();
    r.set("op", op);
    return r;
}

// Space, candidates and ping, then the two requests only ordinary clients may make.
void exercise(PipeConnection &conn, bool sandboxed) {
    Json reply;
    Json r = request("space");
    r.set("text", "아버지가방에들어가신다");
    bool ok = conn.request(std::move(r), 10000, reply);
    std::string text = reply["text"].isString() ? reply["text"].asString() : reply.dump();
    check(ok && text == "아버지가 방에 들어가신다", "space", text);
    r = request("candidates");
    r.set("word", "학교");
    ok = conn.request(std::move(r), 10000, reply);
    bool found = false;
    for (const Json &item : reply["items"].items()) found |= item.isString() && item.asString() == "學校";
    check(ok && found, "candidates", found ? "學校" : reply.dump());
    check(conn.request(request("ping"), 10000, reply), "ping");
    // Spacing rules for one request (the settings window's example) are refused
    // from a sandbox: an application could otherwise probe the user's rules.
    r = request("space");
    r.set("text", "먹어보았다");
    Json rules = Json::object();
    rules.set("auxiliaries", "join");
    r.set("spacing", std::move(rules));
    reply = Json();
    ok = conn.request(std::move(r), 10000, reply);
    if (sandboxed) {
        check(!ok && reply["error"].isString() && reply["error"].asString() == "PermissionError", "space with rules refused",
              reply.dump());
    } else {
        check(ok && reply["text"].isString(), "space with rules allowed", reply.dump());
    }
    for (const char *op : {"configure", "learn"}) {
        r = request(op);
        if (std::string(op) == "learn") {
            r.set("proposed", "아버지가 방에");
            r.set("accepted", "아버지 가방에");
        }
        reply = Json();
        ok = conn.request(std::move(r), 10000, reply);
        if (sandboxed) {
            check(!ok && reply["error"].isString() && reply["error"].asString() == "PermissionError",
                  std::string(op) + " refused", reply.dump());
        } else {
            check(ok, std::string(op) + " allowed", reply.dump());
        }
    }
}

// MARK: child

int childMain(const std::wstring &kind, const std::wstring &pipe, const std::wstring &extra) {
    g_who = narrow(kind);
    check(processSandboxed(), "sandboxed token");
    PipeConnection conn;
    bool opened = conn.open(pipe);
    if (kind == L"low") {
        check(!opened, "cannot connect (pipe labelled medium)");
        // A pipe of the same user under another name, for the parent to try.
        HANDLE pipes[2];
        for (HANDLE &h : pipes)
            h = CreateNamedPipeW(extra.c_str(), PIPE_ACCESS_DUPLEX, PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE,
                                 PIPE_UNLIMITED_INSTANCES, 4096, 4096, 0, nullptr);
        bool made = pipes[0] != INVALID_HANDLE_VALUE && pipes[1] != INVALID_HANDLE_VALUE;
        check(made, "can make a pipe owned by the user (for the parent to refuse)");
        if (!made) return g_failed;
        std::printf("     %-12s made %s\n", g_who.c_str(), securityText(pipes[0]).c_str());
        std::fflush(stdout);
        // Returns once the parent has connected to both instances.
        for (HANDLE h : pipes) {
            ConnectNamedPipe(h, nullptr);
            CloseHandle(h);
        }
        return g_failed;
    }
    check(opened, "connects to the engine");
    if (opened) exercise(conn, true);
    HANDLE server = CreateNamedPipeW(pipe.c_str(), PIPE_ACCESS_DUPLEX, PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE,
                                     PIPE_UNLIMITED_INSTANCES, 4096, 4096, 0, nullptr);
    DWORD error = GetLastError();
    check(server == INVALID_HANDLE_VALUE, "cannot open a server end of the engine pipe", "error " + std::to_string(error));
    if (server != INVALID_HANDLE_VALUE) CloseHandle(server);
    std::wstring own = pipe + L".own";
    HANDLE squat = CreateNamedPipeW(own.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE, PIPE_TYPE_MESSAGE,
                                    1, 4096, 4096, 0, nullptr);
    error = GetLastError();
    check(squat == INVALID_HANDLE_VALUE, "cannot make a pipe outside its namespace", "error " + std::to_string(error));
    if (squat != INVALID_HANDLE_VALUE) CloseHandle(squat);
    if (extra != L"-") {
        Settings s;
        s.loadShared();
        check(Settings::sharedStamp() != 0 && describe(s) == narrow(extra), "reads the settings copy", describe(s));
        check(s.userWords().empty() && s.learned().empty(), "copy holds no user words or learned boundaries");
        check(s.wordbookStamps().empty() && s.lastLearnedLabel().empty() && s.getString("syncFolder").empty() &&
                  s.getString("deviceID").empty(),
              "copy holds no wordbook bookkeeping or sync folder");
    }
    return g_failed;
}

// MARK: parent

PSID containerSid() {
    PSID sid = nullptr;
    HRESULT hr = CreateAppContainerProfile(kContainer, L"Maimusi test", L"Maimusi sandbox pipe test", nullptr, 0, &sid);
    if (hr == HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)) hr = DeriveAppContainerSidFromAppContainerName(kContainer, &sid);
    return SUCCEEDED(hr) ? sid : nullptr;
}

// Lets the container read and run a file (GRANT_ACCESS), or takes that back (REVOKE_ACCESS).
bool fileAccess(const std::wstring &path, PSID sid, ACCESS_MODE mode) {
    EXPLICIT_ACCESSW ea{};
    ea.grfAccessPermissions = GENERIC_READ | GENERIC_EXECUTE;
    ea.grfAccessMode = mode;
    ea.grfInheritance = NO_INHERITANCE;
    ea.Trustee.TrusteeForm = TRUSTEE_IS_SID;
    ea.Trustee.ptstrName = static_cast<LPWSTR>(sid);
    PACL old = nullptr, acl = nullptr;
    PSECURITY_DESCRIPTOR sd = nullptr;
    bool ok = GetNamedSecurityInfoW(path.c_str(), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr, &old,
                                    nullptr, &sd) == ERROR_SUCCESS &&
              SetEntriesInAclW(1, &ea, old, &acl) == ERROR_SUCCESS &&
              SetNamedSecurityInfoW(const_cast<LPWSTR>(path.c_str()), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                    nullptr, nullptr, acl, nullptr) == ERROR_SUCCESS;
    LocalFree(acl);
    LocalFree(sd);
    return ok;
}

enum class Box { AppContainer, Lpac, Low };

// Starts `cmd` in the test AppContainer (Lpac: without ALL APPLICATION
// PACKAGES) or at low integrity. Returns the process handle.
HANDLE launch(std::wstring cmd, Box box, PSID container) {
    STARTUPINFOEXW si{};
    si.StartupInfo.cb = sizeof si;
    PROCESS_INFORMATION pi{};
    BOOL ok = FALSE;
    if (box == Box::Low) {
        HANDLE token = nullptr, low = nullptr;
        PSID lowSid = nullptr;
        if (OpenProcessToken(GetCurrentProcess(), TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT | TOKEN_ASSIGN_PRIMARY,
                             &token) &&
            DuplicateTokenEx(token, 0, nullptr, SecurityImpersonation, TokenPrimary, &low) &&
            ConvertStringSidToSidW(L"S-1-16-4096", &lowSid)) {
            TOKEN_MANDATORY_LABEL label{};
            label.Label.Attributes = SE_GROUP_INTEGRITY;
            label.Label.Sid = lowSid;
            ok = SetTokenInformation(low, TokenIntegrityLevel, &label, sizeof label + GetLengthSid(lowSid)) &&
                 CreateProcessAsUserW(low, nullptr, cmd.data(), nullptr, nullptr, FALSE, 0, nullptr, nullptr,
                                      &si.StartupInfo, &pi);
        }
        LocalFree(lowSid);
        if (low) CloseHandle(low);
        if (token) CloseHandle(token);
    } else {
        SECURITY_CAPABILITIES caps{};
        caps.AppContainerSid = container;
        DWORD optOut = PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT;
        SIZE_T size = 0;
        InitializeProcThreadAttributeList(nullptr, 2, 0, &size);
        std::vector<BYTE> list(size);
        si.lpAttributeList = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(list.data());
        if (InitializeProcThreadAttributeList(si.lpAttributeList, 2, 0, &size) &&
            UpdateProcThreadAttribute(si.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, &caps,
                                      sizeof caps, nullptr, nullptr) &&
            (box != Box::Lpac || UpdateProcThreadAttribute(si.lpAttributeList, 0,
                                                           PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY,
                                                           &optOut, sizeof optOut, nullptr, nullptr))) {
            ok = CreateProcessW(nullptr, cmd.data(), nullptr, nullptr, FALSE, EXTENDED_STARTUPINFO_PRESENT, nullptr,
                                nullptr, &si.StartupInfo, &pi);
            DeleteProcThreadAttributeList(si.lpAttributeList);
        }
    }
    if (!ok) return nullptr;
    CloseHandle(pi.hThread);
    return pi.hProcess;
}

// Waits for a child; its own PASS/FAIL lines are already printed. Returns its failures.
int finish(HANDLE child, const char *name, DWORD timeoutMs = 60000) {
    if (!child) {
        check(false, std::string("start ") + name + " child", "error " + std::to_string(GetLastError()));
        return 0;
    }
    DWORD code = 1;
    if (WaitForSingleObject(child, timeoutMs) != WAIT_OBJECT_0) {
        TerminateProcess(child, 1);
        check(false, std::string(name) + " child timed out");
    } else {
        GetExitCodeProcess(child, &code);
    }
    CloseHandle(child);
    return static_cast<int>(code);
}

// A pipe that belongs to another account (a system service) is never trusted.
void otherOwner() {
    for (const wchar_t *name : {L"\\\\.\\pipe\\InitShutdown", L"\\\\.\\pipe\\ntsvcs", L"\\\\.\\pipe\\epmapper"}) {
        HANDLE h = CreateFileW(name, kPipeClientAccess, 0, nullptr, OPEN_EXISTING,
                               SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr);
        if (h == INVALID_HANDLE_VALUE) continue;
        std::string owner = securityText(h);
        bool trusted = pipeServerTrusted(h);
        CloseHandle(h);
        PipeConnection conn;
        check(!trusted && !conn.open(name), "pipe of another account is not trusted", narrow(name) + " " + owner);
        return;
    }
    check(false, "no system pipe to compare with");
}

// A low-integrity process of the same user makes a pipe: clients refuse it.
void lowIntegrity(const std::wstring &self, const std::wstring &pipe) {
    std::wstring squat = pipe + L".low";
    HANDLE child = launch(quote(self) + L" --child low " + quote(pipe) + L" " + quote(squat), Box::Low, nullptr);
    HANDLE h = INVALID_HANDLE_VALUE;
    ULONGLONG deadline = GetTickCount64() + 20000;
    while (child && h == INVALID_HANDLE_VALUE && GetTickCount64() < deadline && WaitForSingleObject(child, 0) == WAIT_TIMEOUT) {
        h = CreateFileW(squat.c_str(), kPipeClientAccess, 0, nullptr, OPEN_EXISTING,
                        SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr);
        if (h == INVALID_HANDLE_VALUE) Sleep(50);
    }
    if (h != INVALID_HANDLE_VALUE) {
        check(!pipeServerTrusted(h), "pipe made at low integrity is not trusted", securityText(h));
        CloseHandle(h);
        PipeConnection conn;
        check(!conn.open(squat), "client refuses to connect to it");
    } else if (child && WaitForSingleObject(child, 0) == WAIT_TIMEOUT) {
        check(false, "low-integrity pipe not found");
    }
    g_failed += finish(child, "low");
}

int parentMain(int argc, wchar_t **argv) {
    std::wstring id = std::to_wstring(GetCurrentProcessId()) + L"." + std::to_wstring(GetTickCount64());
    std::wstring pipe = L"\\\\.\\pipe\\Maimusi.Test." + id;
    std::wstring mutex = L"Local\\Maimusi.Test." + id;
    std::wstring cmd;
    for (int i = 1; i < argc; ++i) cmd += quote(argv[i]) + L" ";
    cmd += L"--pipe " + quote(pipe) + L" --mutex " + quote(mutex) + L" --idle-minutes 2";
    STARTUPINFOW si{sizeof si};
    PROCESS_INFORMATION server{};
    if (!CreateProcessW(nullptr, cmd.data(), nullptr, nullptr, FALSE, 0, nullptr, nullptr, &si, &server)) {
        std::printf("cannot start the server (error %lu)\n", GetLastError());
        return 2;
    }
    CloseHandle(server.hThread);
    ULONGLONG start = GetTickCount64();
    PipeConnection conn;
    while (!conn.open(pipe)) {
        if (GetTickCount64() - start > 120000 || WaitForSingleObject(server.hProcess, 0) == WAIT_OBJECT_0) {
            std::printf("no pipe from the server\n");
            TerminateProcess(server.hProcess, 1);
            return 2;
        }
        Sleep(200);
    }
    std::printf("ready after %.1fs\n", (GetTickCount64() - start) / 1000.0);
    check(true, "connects to its own engine (owner and label checked)");
    exercise(conn, false);
    otherOwner();

    // The copy AppContainers read, written from the user's own settings file
    // (as the input method in any ordinary application does).
    Settings::syncShared();
    Settings mine;
    mine.load();
    check(Settings::sharedStamp() != 0, "settings copy written");

    std::wstring self = selfPath();
    PSID container = containerSid();
    check(container && fileAccess(self, container, GRANT_ACCESS), "AppContainer profile");
    if (container) {
        std::wstring child = quote(self) + L" --child ";
        g_failed += finish(launch(child + L"appcontainer " + quote(pipe) + L" " + widen(describe(mine)),
                                  Box::AppContainer, container),
                           "appcontainer");
        g_failed += finish(launch(child + L"lpac " + quote(pipe) + L" -", Box::Lpac, container), "lpac");
    }
    lowIntegrity(self, pipe);

    if (container) {
        fileAccess(self, container, REVOKE_ACCESS);
        FreeSid(container);
    }
    DeleteAppContainerProfile(kContainer);
    conn.close();
    TerminateProcess(server.hProcess, 0);
    CloseHandle(server.hProcess);
    std::printf("%s (%d failed)\n", g_failed ? "FAILED" : "ALL PASSED", g_failed);
    return g_failed ? 1 : 0;
}

// Runs a program in the test AppContainer and returns its exit code.
int launchMain(int argc, wchar_t **argv) {
    wchar_t full[MAX_PATH];
    if (!GetFullPathNameW(argv[2], MAX_PATH, full, nullptr)) return 2;
    std::wstring cmd = quote(full);
    for (int i = 3; i < argc; ++i) cmd += L" " + quote(argv[i]);
    PSID container = containerSid();
    if (!container || !fileAccess(full, container, GRANT_ACCESS)) {
        std::printf("cannot prepare the AppContainer\n");
        return 2;
    }
    HANDLE child = launch(cmd, Box::AppContainer, container);
    DWORD code = 2;
    if (child) {
        WaitForSingleObject(child, INFINITE);
        GetExitCodeProcess(child, &code);
        CloseHandle(child);
    } else {
        std::printf("cannot start %ls (error %lu)\n", full, GetLastError());
    }
    fileAccess(full, container, REVOKE_ACCESS);
    FreeSid(container);
    DeleteAppContainerProfile(kContainer);
    return static_cast<int>(code);
}

}  // namespace

int wmain(int argc, wchar_t **argv) {
    SetConsoleOutputCP(CP_UTF8);
    if (argc > 4 && std::wstring(argv[1]) == L"--child") return childMain(argv[2], argv[3], argv[4]);
    if (argc > 2 && std::wstring(argv[1]) == L"--launch") return launchMain(argc, argv);
    if (argc < 2) {
        std::printf("usage: sandbox_pipe.exe <server command...> | --launch <program> [arguments]\n");
        return 2;
    }
    return parentMain(argc, argv);
}
