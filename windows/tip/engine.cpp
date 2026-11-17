#include "engine.h"

#include <objbase.h>

#include <functional>

#include "../common/text.h"
#include "../common/wordbook.h"
#include "globals.h"
#include "log.h"

namespace maimusi {

namespace {

// Request budget while typing, and how long Space may wait for the engine to
// load when there is no light model to answer instead.
constexpr DWORD kTimeoutMs = 600;
constexpr DWORD kStartupWaitMs = 5000;

bool fileExists(const std::wstring &p) {
    DWORD a = GetFileAttributesW(p.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

struct DetachedJob {
    std::function<void()> work;
    HMODULE self;
};

DWORD WINAPI detachedMain(void *param) {
    auto *job = static_cast<DetachedJob *>(param);
    job->work();
    HMODULE self = job->self;
    delete job;
    if (self) FreeLibraryAndExitThread(self, 0);
    return 0;
}

// Runs `work` on a thread of its own that keeps this DLL loaded until it ends
// (the application may release the text service meanwhile).
void runDetached(std::function<void()> work) {
    auto *job = new DetachedJob{std::move(work), nullptr};
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, reinterpret_cast<LPCWSTR>(&detachedMain), &job->self);
    if (HANDLE thread = CreateThread(nullptr, 0, detachedMain, job, 0, nullptr)) {
        CloseHandle(thread);
        return;
    }
    if (job->self) FreeLibrary(job->self);
    delete job;
}

}  // namespace

// MARK: EngineHub

EngineHub &EngineHub::shared() {
    static EngineHub *hub = new EngineHub();  // lives until the process ends
    return *hub;
}

// Folder of the currently registered version (...\Maimusi\<version>\), which
// differs from this DLL's own folder in applications started before an update.
std::wstring EngineHub::registeredDir() {
    wchar_t guid[64];
    StringFromGUID2(CLSID_MaimusiTextService, guid, 64);
    std::wstring key = std::wstring(L"CLSID\\") + guid + L"\\InprocServer32";
    wchar_t path[MAX_PATH];
    DWORD size = sizeof path;
    if (RegGetValueW(HKEY_CLASSES_ROOT, key.c_str(), nullptr, RRF_RT_REG_SZ, nullptr, path, &size) != ERROR_SUCCESS)
        return {};
    std::wstring dll(path);
    std::wstring dir = dll.substr(0, dll.find_last_of(L'\\'));
    return dir.substr(0, dir.find_last_of(L'\\') + 1);
}

std::wstring EngineHub::locate(const std::wstring &relative) {
    if (fileExists(installDir_ + relative)) return installDir_ + relative;
    // An update may have replaced this version's folder while this
    // application kept the old DLL loaded: use the installed version's files.
    std::wstring current = registeredDir();
    if (!current.empty() && fileExists(current + relative)) return current + relative;
    return {};
}

EngineHub::EngineHub() {
    wchar_t module[MAX_PATH];
    DWORD n = GetModuleFileNameW(g_hInst, module, MAX_PATH);
    std::wstring dll(module, n);
    // <version>\x64\MaimusiTIP.dll -> <version>\ ;
    std::wstring dir = dll.substr(0, dll.find_last_of(L'\\'));
    installDir_ = dir.substr(0, dir.find_last_of(L'\\') + 1);
    engineExe_ = locate(L"engine\\MaimusiEngine.exe");
    modelPath_ = locate(L"spacing.hspm");
    // AppContainer processes run as the same user, so they find the same pipe.
    std::wstring sid = currentUserSid();
    pipeName_ = L"\\\\.\\pipe\\Maimusi.Engine." + sid;
    mutexName_ = L"Local\\Maimusi.Engine." + sid;
    sandboxed_ = processSandboxed();
    backend_.ctx = this;
    backend_.space = &EngineHub::spaceCallback;
    backend_.candidates = &EngineHub::candidatesCallback;
    refreshSettings();
}

void EngineHub::refreshSettings() {
    {
        std::lock_guard<std::mutex> lock(settingsMutex_);
        ULONGLONG now = GetTickCount64();
        if (lastCheck_ && now - lastCheck_ < 1000) return;
        lastCheck_ = now;
        // Sandboxed applications cannot read %APPDATA%: they read the copy in the registry.
        unsigned long long stamp = sandboxed_ ? Settings::sharedStamp() : Settings::fileStamp();
        if (stamp == stamp_) return;
        stamp_ = stamp;
        if (sandboxed_) {
            settings_.loadShared();
        } else {
            settings_.load();
        }
        // Wordbook bookkeeping and sync results change the file often without
        // changing what the input method or the engine does.
        std::string fingerprint = settings_.fingerprint();
        if (fingerprint != fingerprint_) {
            fingerprint_ = std::move(fingerprint);
            candidateTheme_ = cand::current(settings_);
            ++generation_;
        }
    }
    // Keep that copy in step with the file, which an older version or an
    // editor may have written without it.
    if (!sandboxed_) Settings::syncShared();
}

Settings EngineHub::settings() {
    refreshSettings();
    std::lock_guard<std::mutex> lock(settingsMutex_);
    return settings_;
}

unsigned EngineHub::generation() {
    refreshSettings();
    std::lock_guard<std::mutex> lock(settingsMutex_);
    return generation_;
}

cand::Theme EngineHub::candidateTheme() {
    refreshSettings();
    std::lock_guard<std::mutex> lock(settingsMutex_);
    return candidateTheme_;
}

bool EngineHub::usesLearned(const std::string &phrase) {
    refreshSettings();
    std::string text = " " + phrase + " ";
    std::lock_guard<std::mutex> lock(settingsMutex_);
    for (const auto &b : settings_.learned())
        if (!b.spaced.empty() && text.find(" " + b.spaced) != std::string::npos) return true;
    return false;
}

bool EngineHub::lightAvailable() {
    std::lock_guard<std::mutex> lock(spacerMutex_);
    if (!spacerTried_) {
        spacerTried_ = true;
        if (!fileExists(modelPath_)) modelPath_ = locate(L"spacing.hspm");
        if (!modelPath_.empty()) spacer_ = hc_spacer_load(narrow(modelPath_).c_str());
        Log::write(spacer_ ? "light model loaded" : "no light model");
    }
    return spacer_ != nullptr;
}

bool EngineHub::connectLocked() {
    if (pipe_.isOpen()) return true;
    // A sandboxed application may not see the engine's folder, but can still
    // use an engine another application started.
    if ((engineExe_.empty() && !sandboxed_) || !pipe_.open(pipeName_)) return false;
    configuredGeneration_ = 0;
    failures_ = 0;
    if (process_) {
        CloseHandle(process_);
        process_ = nullptr;
    }
    Log::write("engine connected");
    return true;
}

void EngineHub::configureLocked() {
    // The engine refuses settings from sandboxed applications; ordinary
    // applications configure it with the user's full settings.
    if (sandboxed_) return;
    unsigned gen = generation();
    if (configuredGeneration_ == gen) return;
    Json req = settings().engineOptions();
    req.set("op", "configure");
    Json reply;
    if (pipe_.request(std::move(req), 2000, reply)) configuredGeneration_ = gen;
}

bool EngineHub::startingLocked() {
    HANDLE m = OpenMutexW(SYNCHRONIZE, FALSE, mutexName_.c_str());
    if (m) {
        CloseHandle(m);
        return true;
    }
    // Started here and still loading (before it takes the mutex).
    return process_ && WaitForSingleObject(process_, 0) == WAIT_TIMEOUT;
}

void EngineHub::startLocked() {
    if (engineExe_.empty() || sandboxed_ || pipe_.isOpen() || startingLocked()) return;
    ULONGLONG now = GetTickCount64();
    if (process_) {
        // The copy started here exited without ever serving.
        CloseHandle(process_);
        process_ = nullptr;
        ++failures_;
        retryAfter_ = now + std::min<ULONGLONG>(300000, 5000ull << std::min(failures_, 6));
        Log::write("engine exited during start");
        return;
    }
    if (now < retryAfter_) return;
    if (!fileExists(engineExe_)) engineExe_ = locate(L"engine\\MaimusiEngine.exe");
    if (engineExe_.empty()) return;
    std::wstring dir = engineExe_.substr(0, engineExe_.find_last_of(L'\\'));
    int idle = std::max(0, settings().getInt("idleUnloadMinutes"));
    std::wstring cmd = L"\"" + engineExe_ + L"\" --pipe \"" + pipeName_ + L"\" --mutex \"" + mutexName_ +
                       L"\" --idle-minutes " + std::to_wstring(idle);
    STARTUPINFOW si{sizeof si};
    PROCESS_INFORMATION pi{};
    DWORD flags = CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | CREATE_BREAKAWAY_FROM_JOB;
    BOOL ok = CreateProcessW(engineExe_.c_str(), cmd.data(), nullptr, nullptr, FALSE, flags, nullptr, dir.c_str(), &si, &pi);
    if (!ok && GetLastError() == ERROR_ACCESS_DENIED) {
        // The job this application runs in forbids breakaway.
        ok = CreateProcessW(engineExe_.c_str(), cmd.data(), nullptr, nullptr, FALSE, flags & ~CREATE_BREAKAWAY_FROM_JOB,
                            nullptr, dir.c_str(), &si, &pi);
    }
    if (!ok) {
        ++failures_;
        retryAfter_ = now + std::min<ULONGLONG>(300000, 5000ull << std::min(failures_, 6));
        Log::write("engine start failed");
        return;
    }
    CloseHandle(pi.hThread);
    process_ = pi.hProcess;
    Log::write("engine started");
}

EngineState EngineHub::stateLocked() {
    if (connectLocked()) return EngineState::Ready;
    if (engineExe_.empty()) return EngineState::Missing;
    if (startingLocked()) return EngineState::Starting;
    if (failures_ > 0) return EngineState::Failed;
    return EngineState::Stopped;
}

EngineState EngineHub::state() {
    std::lock_guard<std::mutex> lock(mutex_);
    return stateLocked();
}

void EngineHub::warmUp() {
    // The periodic wordbook sync (at most every five minutes, in whichever
    // application the user is typing).
    syncWordbook(1000, false);
    if (settings().engine() != "kiwi") return;
    std::lock_guard<std::mutex> lock(mutex_);
    if (!connectLocked()) startLocked();
}

std::wstring EngineHub::statusText() {
    const std::wstring e = L"찰떡";
    bool light = lightAvailable();
    if (settings().engine() == "light" && light) return L"경량 엔진 사용 중";
    switch (state()) {
    case EngineState::Missing: return light ? e + L" 엔진 없음 · 경량 엔진 사용 중" : L"띄어쓰기 엔진 없음";
    case EngineState::Ready: return e + L" 엔진 준비됨";
    case EngineState::Starting: return light ? e + L" 엔진 준비 중 · 그동안 경량 엔진 사용" : e + L" 엔진 준비 중";
    case EngineState::Failed: return light ? e + L" 엔진 시작 실패 · 경량 엔진 사용 중" : e + L" 엔진을 시작하지 못했습니다";
    case EngineState::Stopped:
        // A sandboxed application cannot start the engine; another application can.
        if (sandboxed_)
            return light ? e + L" 엔진 꺼짐 · 경량 엔진 사용 중 (다른 앱에서 입력하면 시작)"
                         : e + L" 엔진 꺼짐 (다른 앱에서 입력하면 시작)";
        return e + L" 엔진 대기 중 (입력하면 시작)";
    }
    return {};
}

std::string EngineHub::lightSpace(const std::string &text, bool &ok) {
    ok = false;
    if (!lightAvailable()) return {};
    std::lock_guard<std::mutex> lock(spacerMutex_);
    char *raw = hc_spacer_space(spacer_, text.c_str());
    if (!raw) return {};
    std::string out(raw);
    hc_string_free(raw);
    ok = true;
    return out;
}

std::string EngineHub::space(const std::string &text, bool &ok) {
    if (settings().engine() == "kiwi" || !lightAvailable()) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!connectLocked()) {
            startLocked();
            if (!lightAvailable() && startingLocked()) {
                ULONGLONG deadline = GetTickCount64() + kStartupWaitMs;
                while (GetTickCount64() < deadline && !connectLocked() && startingLocked()) Sleep(50);
            }
        }
        if (pipe_.isOpen()) {
            configureLocked();
            Json req = Json::object();
            req.set("op", "space");
            req.set("text", text);
            Json reply;
            if (pipe_.request(std::move(req), kTimeoutMs, reply) && reply["text"].isString()) {
                ok = true;
                return reply["text"].asString();
            }
            Log::write("engine space timed out or failed");
        }
    }
    return lightSpace(text, ok);
}

std::string EngineHub::candidates(const std::string &word) {
    if (!settings().getBool("candidatesEnabled")) return {};
    std::lock_guard<std::mutex> lock(mutex_);
    if (!connectLocked()) return {};
    configureLocked();
    Json req = Json::object();
    req.set("op", "candidates");
    req.set("word", word);
    Json reply;
    if (!pipe_.request(std::move(req), kTimeoutMs, reply)) return {};
    std::string out;
    const auto &items = reply["items"].items();
    const auto &notes = reply["notes"].items();
    for (size_t i = 0; i < items.size(); ++i) {
        if (!items[i].isString()) continue;
        if (!out.empty()) out += '\n';
        out += items[i].asString();
        out += '\t';
        if (i < notes.size()) out += notes[i].asString();
    }
    return out;
}

void EngineHub::learn(const std::string &proposed, const std::string &accepted) {
    // Sandboxed applications can neither ask the engine to learn nor save.
    if (sandboxed_ || !settings().getBool("rememberBoundaries") || engineExe_.empty()) return;
    std::wstring name = pipeName_;
    // Off the typing thread, on a connection of its own.
    runDetached([this, name, proposed, accepted] {
        PipeConnection conn;
        if (!conn.open(name)) return;
        Json req = Json::object();
        req.set("op", "learn");
        req.set("proposed", proposed);
        req.set("accepted", accepted);
        Json reply;
        if (!conn.request(std::move(req), 2000, reply)) return;
        std::vector<LearnedBoundary> cases;
        for (const Json &c : reply["cases"].items())
            if (c["compact"].isString() && c["spaced"].isString())
                cases.push_back({c["compact"].asString(), c["spaced"].asString()});
        std::vector<std::string> words;
        for (const Json &w : reply["words"].items())
            if (w.isString()) words.push_back(w.asString());
        if (cases.empty() && words.empty()) return;
        Settings s;
        bool kept = false;
        s.update([&](Settings &edit) { kept = edit.rememberLearned(cases, words); });
        if (kept) wordbookChanged();
    });
}

void EngineHub::syncWordbook(DWORD delayMs, bool changed) {
    // Sandboxed applications cannot reach the settings file or the folder.
    if (sandboxed_) return;
    if (changed) {
        syncChanged_ = true;
    } else if (!wordbook::syncDue(settings())) {
        return;
    }
    if (syncRunning_.exchange(true)) return;  // the running sync picks up the change
    runDetached([this, delayMs] {
        Sleep(delayMs);
        for (;;) {
            bool changed = syncChanged_.exchange(false);
            Settings s;
            s.load();
            if (changed ? !s.getString("syncFolder").empty() : wordbook::syncDue(s)) {
                std::string error;
                bool ok = wordbook::syncNow(&error);
                Log::write(ok ? "wordbook synced" : "wordbook sync failed");
            }
            syncRunning_ = false;
            if (!syncChanged_ || syncRunning_.exchange(true)) break;
            Sleep(1000);
        }
    });
}

const char *EngineHub::spaceCallback(void *ctx, const char *text) {
    // The core reads the result before the next call on this thread.
    thread_local std::string result;
    bool ok = false;
    result = static_cast<EngineHub *>(ctx)->space(text ? text : "", ok);
    return ok ? result.c_str() : nullptr;
}

const char *EngineHub::candidatesCallback(void *ctx, const char *word) {
    thread_local std::string result;
    result = static_cast<EngineHub *>(ctx)->candidates(word ? word : "");
    return result.c_str();
}

}  // namespace maimusi
