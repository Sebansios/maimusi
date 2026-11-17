#include "settings.h"

#include <windows.h>
#include <aclapi.h>
#include <sddl.h>
#include <shlobj.h>

#include <algorithm>
#include <set>

#include "text.h"

namespace maimusi {

namespace {

const wchar_t kSharedKey[] = L"Software\\Maimusi\\Sandbox";
const wchar_t kSharedValue[] = L"Settings";
std::wstring g_testPath;  // usePathForTesting

// The wordbook and its bookkeeping: never in the sandbox copy, and not part of
// the behavior fingerprint (except the words and boundaries themselves).
const char *const kPrivateKeys[] = {"userWords", "learnedBoundaries", "wordbookStamps", "lastLearned",
                                    "syncFolder", "deviceID", "syncLast", "syncError"};
const char *const kBookkeepingKeys[] = {"wordbookStamps", "lastLearned", "syncFolder", "deviceID", "syncLast",
                                        "syncError"};

template <size_t N> bool listed(const std::string &key, const char *const (&keys)[N]) {
    for (const char *k : keys)
        if (key == k) return true;
    return false;
}

// Removed entries are forgotten after a year (by then every device has synced).
constexpr double kRemovedKeptSeconds = 365 * 86400.0;

Json defaults() {
    Json d = Json::object();
    d.set("engine", "kiwi");
    d.set("convertOnSpace", true);
    d.set("spaceInConversion", "cycle");
    d.set("enterPassesThrough", false);
    d.set("spaceImplicitCommits", true);
    d.set("candidatesEnabled", true);
    d.set("hanjaForms", "education");
    d.set("hanjaPresentation", "hanja");
    d.set("symbolConsonants", false);
    d.set("hanjaGlossSearch", false);
    // Candidate window look, as on macOS (common/candidatetheme.h).
    d.set("candidatePreset", "glass");
    d.set("candidateTextSize", "normal");
    d.set("idleUnloadMinutes", 20);
    d.set("rule.auxiliaries", "separate");
    d.set("rule.compound", "model");
    d.set("rule.number_units", "model");
    d.set("rule.existing_spaces", "preserve");
    d.set("rememberBoundaries", true);
    // Windows only: Right Alt alone also switches Hangul/English (for keyboards
    // whose driver does not report the 한/영 key as VK_HANGUL).
    d.set("rightAltToggles", false);
    d.set("userWords", Json::array());
    d.set("learnedBoundaries", Json::array());
    // Wordbook (docs/WORDBOOK.md): change stamps, the last learned entries,
    // and the sync folder with this device's id and the last sync result.
    d.set("wordbookStamps", Json::object());
    d.set("lastLearned", Json::object());
    d.set("syncFolder", "");
    d.set("deviceID", "");
    d.set("syncLast", 0);
    d.set("syncError", "");
    return d;
}

Json stringArray(const std::vector<std::string> &list) {
    Json arr = Json::array();
    for (const auto &s : list) arr.push(s);
    return arr;
}

Json boundaryArray(const std::vector<LearnedBoundary> &list) {
    Json arr = Json::array();
    for (const auto &c : list) {
        Json o = Json::object();
        o.set("compact", c.compact);
        o.set("spaced", c.spaced);
        arr.push(std::move(o));
    }
    return arr;
}

std::vector<std::string> strings(const Json &arr) {
    std::vector<std::string> out;
    for (const Json &v : arr.items())
        if (v.isString()) out.push_back(v.asString());
    return out;
}

const Json &defaultValues() {
    static const Json d = defaults();
    return d;
}

bool oneOf(const std::string &v, std::initializer_list<const char *> allowed) {
    for (const char *a : allowed)
        if (v == a) return true;
    return false;
}

// Number of Unicode scalar values in a UTF-8 string.
size_t charCount(const std::string &s) {
    size_t n = 0;
    for (unsigned char c : s)
        if ((c & 0xC0) != 0x80) ++n;
    return n;
}

std::string trimSpaces(const std::string &s) {
    size_t b = s.find_first_not_of(" \t"), e = s.find_last_not_of(" \t");
    return b == std::string::npos ? std::string() : s.substr(b, e - b + 1);
}

// Lets ALL APPLICATION PACKAGES and ALL RESTRICTED APPLICATION PACKAGES read the key.
void allowAppContainers(HKEY key) {
    PSID all = nullptr, restricted = nullptr;
    PACL dacl = nullptr, updated = nullptr;
    PSECURITY_DESCRIPTOR sd = nullptr;
    if (ConvertStringSidToSidW(L"S-1-15-2-1", &all) && ConvertStringSidToSidW(L"S-1-15-2-2", &restricted) &&
        GetSecurityInfo(key, SE_REGISTRY_KEY, DACL_SECURITY_INFORMATION, nullptr, nullptr, &dacl, nullptr, &sd) ==
            ERROR_SUCCESS) {
        bool present = false;
        for (DWORD i = 0; dacl && i < dacl->AceCount && !present; ++i) {
            ACE_HEADER *ace = nullptr;
            present = GetAce(dacl, i, reinterpret_cast<void **>(&ace)) && ace->AceType == ACCESS_ALLOWED_ACE_TYPE &&
                      EqualSid(&reinterpret_cast<ACCESS_ALLOWED_ACE *>(ace)->SidStart, all);
        }
        EXPLICIT_ACCESSW grants[2]{};
        PSID sids[2] = {all, restricted};
        for (int i = 0; i < 2; ++i) {
            grants[i].grfAccessPermissions = KEY_READ;
            grants[i].grfAccessMode = GRANT_ACCESS;
            grants[i].grfInheritance = NO_INHERITANCE;
            grants[i].Trustee.TrusteeForm = TRUSTEE_IS_SID;
            grants[i].Trustee.ptstrName = static_cast<LPWSTR>(sids[i]);
        }
        if (!present && SetEntriesInAclW(2, grants, dacl, &updated) == ERROR_SUCCESS)
            SetSecurityInfo(key, SE_REGISTRY_KEY, DACL_SECURITY_INFORMATION, nullptr, nullptr, updated, nullptr);
    }
    LocalFree(updated);
    LocalFree(sd);
    LocalFree(all);
    LocalFree(restricted);
}

std::wstring readShared(HKEY root, const wchar_t *subkey) {
    DWORD size = 0;
    if (RegGetValueW(root, subkey, kSharedValue, RRF_RT_REG_SZ, nullptr, nullptr, &size) != ERROR_SUCCESS ||
        size > (1u << 20))
        return {};
    std::wstring text(size / sizeof(wchar_t) + 1, L'\0');
    size = static_cast<DWORD>(text.size() * sizeof(wchar_t));
    if (RegGetValueW(root, subkey, kSharedValue, RRF_RT_REG_SZ, nullptr, text.data(), &size) != ERROR_SUCCESS)
        return {};
    text.resize(wcsnlen(text.c_str(), text.size()));
    return text;
}

}  // namespace

SettingsLock::SettingsLock() : mutex_(CreateMutexW(nullptr, FALSE, L"Local\\Maimusi.Settings")) {
    if (mutex_) WaitForSingleObject(mutex_, 5000);
}

SettingsLock::~SettingsLock() {
    if (mutex_) {
        ReleaseMutex(mutex_);
        CloseHandle(mutex_);
    }
}

Settings::Settings() : values_(Json::object()) {}

double nowSeconds() {
    FILETIME ft;
    GetSystemTimePreciseAsFileTime(&ft);
    unsigned long long t = static_cast<unsigned long long>(ft.dwHighDateTime) << 32 | ft.dwLowDateTime;
    return (static_cast<double>(t) - 116444736000000000.0) / 1e7;
}

void Settings::usePathForTesting(const std::wstring &file) { g_testPath = file; }

std::wstring Settings::path() {
    if (!g_testPath.empty()) return g_testPath;
    PWSTR base = nullptr;
    std::wstring result;
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_RoamingAppData, KF_FLAG_DONT_VERIFY, nullptr, &base))) {
        result = std::wstring(base) + L"\\Maimusi\\settings.json";
    }
    CoTaskMemFree(base);
    return result;
}

unsigned long long Settings::fileStamp() {
    WIN32_FILE_ATTRIBUTE_DATA data;
    std::wstring p = path();
    if (p.empty() || !GetFileAttributesExW(p.c_str(), GetFileExInfoStandard, &data)) return 0;
    return (static_cast<unsigned long long>(data.ftLastWriteTime.dwHighDateTime) << 32 |
            data.ftLastWriteTime.dwLowDateTime) ^ data.nFileSizeLow;
}

void Settings::load() {
    values_ = Json::object();
    std::wstring p = path();
    if (p.empty()) return;
    HANDLE f = CreateFileW(p.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                           nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return;
    LARGE_INTEGER size;
    std::string text;
    if (GetFileSizeEx(f, &size) && size.QuadPart > 0 && size.QuadPart < (16 << 20)) {
        text.resize(static_cast<size_t>(size.QuadPart));
        DWORD read = 0;
        if (!ReadFile(f, text.data(), static_cast<DWORD>(text.size()), &read, nullptr)) read = 0;
        text.resize(read);
    }
    CloseHandle(f);
    Json parsed;
    if (Json::parse(text, parsed) && parsed.isObject()) values_ = std::move(parsed);
}

bool Settings::save() const {
    SettingsLock lock;
    return lockedSave();
}

bool Settings::lockedSave() const {
    std::wstring p = path();
    if (p.empty()) return false;
    std::wstring dir = p.substr(0, p.find_last_of(L'\\'));
    CreateDirectoryW(dir.c_str(), nullptr);
    std::wstring tmp = p + L".tmp";
    HANDLE f = CreateFileW(tmp.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    std::string text = values_.dump();
    DWORD written = 0;
    bool ok = WriteFile(f, text.data(), static_cast<DWORD>(text.size()), &written, nullptr) && written == text.size();
    ok = FlushFileBuffers(f) && ok;
    CloseHandle(f);
    if (!ok || !MoveFileExW(tmp.c_str(), p.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileW(tmp.c_str());
        return false;
    }
    writeShared();
    return true;
}

Json Settings::sharedValues() const {
    Json out = Json::object();
    for (const auto &[key, value] : values_.members())
        if (!listed(key, kPrivateKeys) && defaultValues().find(key)) out.set(key, value);
    return out;
}

std::string Settings::fingerprint() const {
    Json out = Json::object();
    for (const auto &[key, value] : values_.members())
        if (!listed(key, kBookkeepingKeys)) out.set(key, value);
    return out.dump();
}

bool Settings::writeShared() const {
    if (!g_testPath.empty()) return true;
    std::wstring text = widen(sharedValues().dump());
    if (readShared(HKEY_CURRENT_USER, kSharedKey) == text) return true;
    HKEY key = nullptr;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, kSharedKey, 0, nullptr, 0, KEY_QUERY_VALUE | KEY_SET_VALUE | READ_CONTROL | WRITE_DAC,
                        nullptr, &key, nullptr) != ERROR_SUCCESS)
        return false;
    allowAppContainers(key);
    bool ok = RegSetValueExW(key, kSharedValue, 0, REG_SZ, reinterpret_cast<const BYTE *>(text.c_str()),
                             static_cast<DWORD>((text.size() + 1) * sizeof(wchar_t))) == ERROR_SUCCESS;
    RegCloseKey(key);
    return ok;
}

void Settings::loadShared() {
    values_ = Json::object();
    Json parsed;
    if (Json::parse(narrow(readShared(HKEY_CURRENT_USER, kSharedKey)), parsed) && parsed.isObject())
        values_ = std::move(parsed);
}

unsigned long long Settings::sharedStamp() {
    HKEY key = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, kSharedKey, 0, KEY_QUERY_VALUE, &key) != ERROR_SUCCESS) return 0;
    FILETIME time{};
    LSTATUS status = RegQueryInfoKeyW(key, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,
                                      nullptr, &time);
    RegCloseKey(key);
    if (status != ERROR_SUCCESS) return 0;
    return static_cast<unsigned long long>(time.dwHighDateTime) << 32 | time.dwLowDateTime;
}

void Settings::syncShared() {
    SettingsLock lock;
    Settings s;
    s.load();
    s.writeShared();
}

void Settings::removeShared() { RegDeleteKeyW(HKEY_CURRENT_USER, kSharedKey); }

bool Settings::getBool(const std::string &key) const {
    const Json *v = values_.find(key);
    if (v && v->isBool()) return v->asBool();
    return defaultValues()[key].asBool();
}

std::string Settings::getString(const std::string &key) const {
    const Json *v = values_.find(key);
    if (v && v->isString()) return v->asString();
    return defaultValues()[key].asString();
}

int Settings::getInt(const std::string &key) const {
    const Json *v = values_.find(key);
    if (v && v->isNumber()) return v->asInt();
    return defaultValues()[key].asInt();
}

double Settings::getNumber(const std::string &key) const {
    const Json *v = values_.find(key);
    if (v && v->isNumber()) return v->asNumber();
    return defaultValues()[key].asNumber();
}

void Settings::set(const std::string &key, Json value) { values_.set(key, std::move(value)); }

std::string Settings::engine() const { return getString("engine") == "light" ? "light" : "kiwi"; }

std::vector<std::string> Settings::userWords() const { return strings(values_["userWords"]); }

std::vector<LearnedBoundary> Settings::learned() const {
    std::vector<LearnedBoundary> out;
    for (const Json &c : values_["learnedBoundaries"].items()) {
        if (c["compact"].isString() && c["spaced"].isString())
            out.push_back({c["compact"].asString(), c["spaced"].asString()});
    }
    return out;
}

std::vector<std::string> Settings::insertWords(const std::vector<std::string> &words) {
    std::vector<std::string> list = userWords(), added;
    for (const std::string &raw : words) {
        std::string word = trimSpaces(raw);
        size_t n = charCount(word);
        if (n < 2 || n > 40 || word.find(' ') != std::string::npos) continue;
        if (std::find(list.begin(), list.end(), word) != list.end()) continue;
        list.push_back(word);
        added.push_back(word);
    }
    if (added.empty()) return added;
    if (list.size() > kMaxWords) list.erase(list.begin(), list.end() - kMaxWords);
    set("userWords", stringArray(list));
    std::vector<std::string> keys;
    for (const auto &w : added) keys.push_back("w:" + w);
    stamp(keys, false);
    return added;
}

void Settings::removeWord(const std::string &word) {
    std::vector<std::string> list = userWords();
    list.erase(std::remove(list.begin(), list.end(), word), list.end());
    set("userWords", stringArray(list));
    stamp({"w:" + word}, true);
}

std::vector<std::string> Settings::remember(const std::vector<LearnedBoundary> &cases) {
    std::vector<std::string> keys;
    if (!getBool("rememberBoundaries") || cases.empty()) return keys;
    std::vector<LearnedBoundary> list = learned();
    for (const auto &c : cases) {
        list.erase(std::remove_if(list.begin(), list.end(), [&](const LearnedBoundary &o) { return o.compact == c.compact; }),
                   list.end());
        list.push_back(c);
        keys.push_back(c.compact);
    }
    if (list.size() > kMaxLearned) list.erase(list.begin(), list.end() - kMaxLearned);
    set("learnedBoundaries", boundaryArray(list));
    std::vector<std::string> stampKeys;
    for (const auto &k : keys) stampKeys.push_back("b:" + k);
    stamp(stampKeys, false);
    return keys;
}

bool Settings::rememberLearned(const std::vector<LearnedBoundary> &cases, const std::vector<std::string> &words) {
    if (!getBool("rememberBoundaries")) return false;
    std::vector<std::string> compacts = remember(cases);
    std::vector<std::string> added = insertWords(words);
    if (compacts.empty() && added.empty()) return false;
    Json last = Json::object();
    last.set("cases", stringArray(compacts));
    last.set("words", stringArray(added));
    set("lastLearned", std::move(last));
    return true;
}

std::pair<std::vector<std::string>, std::vector<std::string>> Settings::lastLearned() const {
    const Json &last = values_["lastLearned"];
    std::set<std::string> kept, words;
    for (const auto &c : learned()) kept.insert(c.compact);
    for (const auto &w : userWords()) words.insert(w);
    std::pair<std::vector<std::string>, std::vector<std::string>> out;
    for (const auto &c : strings(last["cases"]))
        if (kept.count(c)) out.first.push_back(c);
    for (const auto &w : strings(last["words"]))
        if (words.count(w)) out.second.push_back(w);
    return out;
}

std::string Settings::lastLearnedLabel() const {
    auto last = lastLearned();
    if (!last.first.empty()) {
        for (const auto &c : learned())
            if (c.compact == last.first.front()) return c.spaced;
    }
    return last.second.empty() ? std::string() : last.second.front();
}

void Settings::forgetLastLearned() {
    auto last = lastLearned();
    set("lastLearned", Json::object());
    if (last.first.empty() && last.second.empty()) return;
    std::set<std::string> cases(last.first.begin(), last.first.end()), words(last.second.begin(), last.second.end());
    std::vector<LearnedBoundary> list = learned();
    list.erase(std::remove_if(list.begin(), list.end(), [&](const LearnedBoundary &c) { return cases.count(c.compact) > 0; }),
               list.end());
    set("learnedBoundaries", boundaryArray(list));
    std::vector<std::string> kept = userWords();
    kept.erase(std::remove_if(kept.begin(), kept.end(), [&](const std::string &w) { return words.count(w) > 0; }), kept.end());
    set("userWords", stringArray(kept));
    std::vector<std::string> keys;
    for (const auto &c : last.first) keys.push_back("b:" + c);
    for (const auto &w : last.second) keys.push_back("w:" + w);
    stamp(keys, true);
}

void Settings::forgetBoundary(const std::string &compact) {
    std::vector<LearnedBoundary> list = learned();
    list.erase(std::remove_if(list.begin(), list.end(), [&](const LearnedBoundary &c) { return c.compact == compact; }),
               list.end());
    set("learnedBoundaries", boundaryArray(list));
    stamp({"b:" + compact}, true);
}

void Settings::forgetBoundaries() {
    std::vector<std::string> keys;
    for (const auto &c : learned()) keys.push_back("b:" + c.compact);
    stamp(keys, true);
    set("learnedBoundaries", Json::array());
    set("lastLearned", Json::object());
}

std::map<std::string, WordbookStamp> Settings::wordbookStamps() const {
    std::map<std::string, WordbookStamp> out;
    for (const auto &[key, value] : values_["wordbookStamps"].members())
        out[key] = {value["at"].asNumber(), value["removed"].asBool()};
    return out;
}

void Settings::setStamps(const std::map<std::string, WordbookStamp> &stamps) {
    Json o = Json::object();
    for (const auto &[key, s] : stamps) {
        Json v = Json::object();
        v.set("at", s.at);
        v.set("removed", s.removed);
        o.add(key, std::move(v));
    }
    set("wordbookStamps", std::move(o));
}

void Settings::stamp(const std::vector<std::string> &keys, bool removed) {
    if (keys.empty()) return;
    std::map<std::string, WordbookStamp> stamps = wordbookStamps();
    double now = nowSeconds();
    for (const auto &k : keys) stamps[k] = {now, removed};
    for (auto it = stamps.begin(); it != stamps.end();)
        it = it->second.removed && it->second.at < now - kRemovedKeptSeconds ? stamps.erase(it) : std::next(it);
    setStamps(stamps);
}

void Settings::replaceWordbook(const std::vector<std::string> &words, const std::vector<LearnedBoundary> &boundaries,
                               const std::map<std::string, WordbookStamp> &stamps) {
    std::vector<std::string> w = words;
    std::vector<LearnedBoundary> b = boundaries;
    if (w.size() > kMaxWords) w.erase(w.begin(), w.end() - kMaxWords);
    if (b.size() > kMaxLearned) b.erase(b.begin(), b.end() - kMaxLearned);
    setStamps(stamps);
    set("userWords", stringArray(w));
    set("learnedBoundaries", boundaryArray(b));
}

std::string Settings::deviceID() {
    std::string id = getString("deviceID");
    bool valid = id.size() == 8 && std::all_of(id.begin(), id.end(), [](char c) {
                     return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
                 });
    if (valid) return id;
    GUID g{};
    CoCreateGuid(&g);
    char buf[16];
    snprintf(buf, sizeof buf, "%08lx", static_cast<unsigned long>(g.Data1));
    id = buf;
    set("deviceID", id);
    return id;
}

std::vector<std::pair<std::string, std::string>> Settings::sessionOptions() const {
    return {
        {"layout", "dubeolsik"},
        {"convert_on_space", getBool("convertOnSpace") ? "1" : "0"},
        {"space_in_conversion", getString("spaceInConversion") == "commit" ? "commit" : "cycle"},
        {"enter_passes_through", getBool("enterPassesThrough") ? "1" : "0"},
        {"space_implicit_commits", getBool("spaceImplicitCommits") ? "1" : "0"},
    };
}

Json Settings::spacingRules() const {
    Json spacing = Json::object();
    spacing.set("auxiliaries", getString("rule.auxiliaries"));
    spacing.set("compound", getString("rule.compound"));
    spacing.set("number_units", getString("rule.number_units"));
    // No longer shown in the settings (Shift+Space commits as typed instead),
    // but still sent so an edited file keeps working.
    spacing.set("existing_spaces", getString("rule.existing_spaces"));
    spacing.set("words", stringArray(userWords()));
    spacing.set("learned", boundaryArray(learned()));
    return spacing;
}

Json Settings::engineOptions() const {
    Json o = Json::object();
    o.set("spacing", spacingRules());
    o.set("hanja_forms", getString("hanjaForms") == "ks" ? "ks" : "education");
    std::string presentation = getString("hanjaPresentation");
    o.set("hanja_presentation",
          oneOf(presentation, {"hanja", "hangul_hanja", "hanja_hangul", "hangulhanja"}) ? presentation : "hanja");
    o.set("symbol_consonants", getBool("symbolConsonants"));
    o.set("hanja_gloss", getBool("hanjaGlossSearch"));
    o.set("idle_minutes", std::max(0, getInt("idleUnloadMinutes")));
    return o;
}

}  // namespace maimusi
