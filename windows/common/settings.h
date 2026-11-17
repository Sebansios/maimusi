// User preferences, shared by the input method (in every application) and the
// settings program. Stored as JSON in %APPDATA%\Maimusi\settings.json; writers
// take a named mutex and replace the file atomically. Typed text is not
// stored, except words the user registers and the few words around a boundary
// the user corrected by hand (only while rememberBoundaries is on).
//
// AppContainer applications cannot read %APPDATA%. For them every save also
// writes a copy of the preferences, without the user's words, learned
// boundaries and wordbook bookkeeping, to HKCU\Software\Maimusi\Sandbox (value
// Settings), a key AppContainers may read.
//
// Keys and defaults match the macOS defaults domain (macos/Sources/Settings.swift).
#pragma once

#include <map>
#include <string>
#include <utility>
#include <vector>

#include "json.h"

namespace maimusi {

struct LearnedBoundary {
    std::string compact;
    std::string spaced;
};

// When a wordbook entry ("w:단어" or "b:compact") last changed, for syncing
// between devices (docs/WORDBOOK.md). Removed entries keep their stamp so
// another device does not bring them back.
struct WordbookStamp {
    double at = 0;  // seconds since 1970 (UTC)
    bool removed = false;
};

class Settings {
public:
    static constexpr size_t kMaxWords = 5000;
    static constexpr size_t kMaxLearned = 2000;

    Settings();

    // Loads the file; missing or unreadable files leave the defaults.
    void load();
    // Writes under the settings mutex. Returns false if the file could not be written.
    bool save() const;
    // Reload, apply `edit`, save, all under the settings mutex (for concurrent writers).
    template <class F> bool update(F edit);

    static std::wstring path();
    // Self-tests only: use this file instead, and never write the sandbox copy.
    static void usePathForTesting(const std::wstring &file);
    // Last-write time of the file, 0 when absent.
    static unsigned long long fileStamp();

    // The copy for sandboxed applications: load it instead of the file, and
    // its last-write time (0 when absent or unreadable).
    void loadShared();
    static unsigned long long sharedStamp();
    // Rewrites the copy from the file if they differ (under the settings mutex).
    static void syncShared();
    static void removeShared();

    bool getBool(const std::string &key) const;
    std::string getString(const std::string &key) const;
    int getInt(const std::string &key) const;
    double getNumber(const std::string &key) const;
    void set(const std::string &key, Json value);

    // Every preference that changes how the input method behaves, without the
    // wordbook bookkeeping and sync state: unchanged when only those change.
    std::string fingerprint() const;

    std::string engine() const;  // "kiwi" or "light"

    std::vector<std::string> userWords() const;
    std::vector<LearnedBoundary> learned() const;
    // Words of 2–40 characters without spaces; returns the ones newly added.
    std::vector<std::string> insertWords(const std::vector<std::string> &words);
    bool addWords(const std::vector<std::string> &words) { return !insertWords(words).empty(); }
    void removeWord(const std::string &word);
    // Replaces the spacing of the same expressions; returns their compact forms.
    std::vector<std::string> remember(const std::vector<LearnedBoundary> &cases);
    // What the engine learned from a hand-corrected boundary: remembered and
    // noted as the last thing learned (for 「방금 기억한 띄어쓰기 잊기」).
    // Returns false when nothing new was kept.
    bool rememberLearned(const std::vector<LearnedBoundary> &cases, const std::vector<std::string> &words);
    // The last learned cases (compact forms) and words that are still kept.
    std::pair<std::vector<std::string>, std::vector<std::string>> lastLearned() const;
    // Display text of the last learned thing: its spacing, or the word.
    std::string lastLearnedLabel() const;
    void forgetLastLearned();
    void forgetBoundary(const std::string &compact);
    void forgetBoundaries();

    std::map<std::string, WordbookStamp> wordbookStamps() const;
    // Sync and import results: words, boundaries and stamps as merged.
    void replaceWordbook(const std::vector<std::string> &words, const std::vector<LearnedBoundary> &boundaries,
                         const std::map<std::string, WordbookStamp> &stamps);
    // Random 8 lowercase hex digits naming this device's sync file (made once).
    std::string deviceID();

    // Options for hc_session_set_option.
    std::vector<std::pair<std::string, std::string>> sessionOptions() const;
    // The engine's spacing rules (`SpacingPreferences` fields, with words and learned boundaries).
    Json spacingRules() const;
    // The engine's `configure` request (without "op"/"id").
    Json engineOptions() const;

private:
    void stamp(const std::vector<std::string> &keys, bool removed);
    void setStamps(const std::map<std::string, WordbookStamp> &stamps);
    bool lockedSave() const;
    Json sharedValues() const;
    bool writeShared() const;
    Json values_;
};

// Seconds since 1970 (UTC), with a fraction.
double nowSeconds();

class SettingsLock {
public:
    SettingsLock();
    ~SettingsLock();
    SettingsLock(const SettingsLock &) = delete;
    SettingsLock &operator=(const SettingsLock &) = delete;

private:
    void *mutex_;
};

template <class F> bool Settings::update(F edit) {
    SettingsLock lock;
    load();
    edit(*this);
    return lockedSave();
}

}  // namespace maimusi
