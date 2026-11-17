// Spacing and candidate services shared by every input context in this process.
//
// The CharTec (Kiwi) engine is one process per user, MaimusiEngine.exe, shared
// by all applications over a named pipe (engine/hangul_ime/pipe_service.py).
// The first input method that needs it starts it; in AppContainer and
// low-integrity applications the input method only uses an engine that is
// already running, for spacing and candidates. Requests wait at most a
// short timeout; the built-in light model answers when the engine is not
// ready, so a slow or missing engine never blocks typing for long.
#pragma once

#include <windows.h>

#include <atomic>
#include <mutex>
#include <string>
#include <vector>

#include "../../core/include/hangul_core.h"
#include "../common/candidatetheme.h"
#include "../common/enginepipe.h"
#include "../common/json.h"
#include "../common/settings.h"

namespace maimusi {

enum class EngineState { Missing, Stopped, Starting, Ready, Failed };

class EngineHub {
public:
    static EngineHub &shared();

    // Settings as last read from disk (in a sandboxed application, from the
    // copy in the registry); reloaded at most once a second.
    Settings settings();
    // Increases whenever the settings file changes.
    unsigned generation();

    bool lightAvailable();
    bool kiwiInstalled() const { return !engineExe_.empty(); }
    // AppContainer or low integrity: uses an engine that is already running
    // but never starts or configures it, and cannot save settings.
    bool sandboxed() const { return sandboxed_; }
    EngineState state();
    std::wstring statusText();

    // Called when an input context gains focus.
    void warmUp();

    // Backend for hc_session_* calls; callbacks reach this hub.
    const hc_backend *backend() { return &backend_; }

    // A hand-corrected boundary was committed: learn from it in the background.
    void learn(const std::string &proposed, const std::string &accepted);
    // The wordbook changed here: sync it with the other devices three seconds later.
    void wordbookChanged() { syncWordbook(3000, true); }
    // Whether a remembered spacing appears in this phrase (UTF-8) at a word boundary.
    bool usesLearned(const std::string &phrase);
    // The candidate window's look from the settings (preset and text size).
    cand::Theme candidateTheme();

    // Folder of this version: ...\Maimusi\<version>\ (holds x64\, x86\, arm64\, engine\).
    std::wstring installDir() const { return installDir_; }
    // A file of this version, or of the currently installed one when an
    // update replaced this version's folder; empty when neither has it.
    std::wstring locate(const std::wstring &relative);

private:
    EngineHub();
    static std::wstring registeredDir();
    void refreshSettings();
    // Syncs the wordbook after `delayMs` on a background thread: when `changed`,
    // whenever a sync folder is set; otherwise only if the periodic sync is due.
    void syncWordbook(DWORD delayMs, bool changed);

    std::string space(const std::string &text, bool &ok);
    std::string candidates(const std::string &word);
    std::string lightSpace(const std::string &text, bool &ok);

    // All under mutex_.
    bool connectLocked();
    void configureLocked();
    void startLocked();
    bool startingLocked();
    EngineState stateLocked();

    static const char *spaceCallback(void *ctx, const char *text);
    static const char *candidatesCallback(void *ctx, const char *word);

    std::mutex mutex_;
    std::wstring installDir_;
    std::wstring engineExe_;
    std::wstring modelPath_;
    std::wstring pipeName_;
    std::wstring mutexName_;
    bool sandboxed_ = false;

    std::mutex spacerMutex_;
    hc_spacer *spacer_ = nullptr;
    bool spacerTried_ = false;

    PipeConnection pipe_;
    unsigned configuredGeneration_ = 0;
    HANDLE process_ = nullptr;  // engine started by this process, until it serves
    ULONGLONG retryAfter_ = 0;
    int failures_ = 0;

    std::mutex settingsMutex_;
    Settings settings_;
    unsigned generation_ = 1;
    unsigned long long stamp_ = ~0ull;
    std::string fingerprint_;
    cand::Theme candidateTheme_;
    ULONGLONG lastCheck_ = 0;

    std::atomic<bool> syncRunning_{false}, syncChanged_{false};

    hc_backend backend_{};
};

}  // namespace maimusi
