#include "wordbook.h"

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <vector>

#include "text.h"

namespace maimusi {
namespace wordbook {

namespace {

const char kFormat[] = "maimusi-wordbook";
constexpr int kVersion = 1;
const wchar_t kSubfolder[] = L"Maimusi";
const wchar_t kPrefix[] = L"maimusi-wordbook-";
constexpr double kPeriod = 300;  // seconds between periodic syncs

// Last attempt in this process, so an unreachable folder is not retried on every focus change.
std::atomic<double> g_lastAttempt{0};

bool readFile(const std::wstring &path, std::string &out) {
    HANDLE f = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER size{};
    bool ok = GetFileSizeEx(f, &size) && size.QuadPart >= 0 && size.QuadPart < (32 << 20);
    if (ok) {
        out.resize(static_cast<size_t>(size.QuadPart));
        DWORD read = 0;
        ok = out.empty() || (ReadFile(f, out.data(), static_cast<DWORD>(out.size()), &read, nullptr) && read == out.size());
    }
    CloseHandle(f);
    return ok;
}

bool writeFileAtomic(const std::wstring &path, const std::string &data) {
    size_t slash = path.find_last_of(L'\\');
    std::wstring tmp = path.substr(0, slash + 1) + L"." + path.substr(slash + 1) + L".tmp";
    HANDLE f = CreateFileW(tmp.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    bool ok = WriteFile(f, data.data(), static_cast<DWORD>(data.size()), &written, nullptr) && written == data.size();
    ok = FlushFileBuffers(f) && ok;
    CloseHandle(f);
    if (!ok || !MoveFileExW(tmp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileW(tmp.c_str());
        return false;
    }
    return true;
}

// Decodes one UTF-8 scalar at `i` (advancing it); U+FFFD on malformed input.
char32_t nextScalar(const std::string &s, size_t &i) {
    unsigned char c = static_cast<unsigned char>(s[i++]);
    int extra = c < 0x80 ? 0 : (c >> 5) == 6 ? 1 : (c >> 4) == 14 ? 2 : (c >> 3) == 30 ? 3 : -1;
    if (extra < 0) return 0xFFFD;
    char32_t cp = extra == 0 ? c : extra == 1 ? (c & 0x1F) : extra == 2 ? (c & 0x0F) : (c & 0x07);
    for (int k = 0; k < extra; ++k) {
        if (i >= s.size() || (static_cast<unsigned char>(s[i]) & 0xC0) != 0x80) return 0xFFFD;
        cp = (cp << 6) | (static_cast<unsigned char>(s[i++]) & 0x3F);
    }
    return cp;
}

// Letters, digits and marks (Swift's CharacterSet.alphanumerics on macOS).
bool alphanumeric(char32_t cp) {
    if (cp < 0x80) return (cp >= '0' && cp <= '9') || (cp >= 'a' && cp <= 'z') || (cp >= 'A' && cp <= 'Z');
    if (cp > 0xFFFF) return (cp >= 0x20000 && cp <= 0x3FFFF) || (cp >= 0x1D400 && cp <= 0x1D7FF);  // CJK ext. B–J, math letters
    wchar_t ch = static_cast<wchar_t>(cp);
    WORD t1 = 0, t3 = 0;
    GetStringTypeW(CT_CTYPE1, &ch, 1, &t1);
    GetStringTypeW(CT_CTYPE3, &ch, 1, &t3);
    return (t1 & (C1_ALPHA | C1_DIGIT)) || (t3 & (C3_NONSPACING | C3_DIACRITIC | C3_VOWELMARK));
}

// 2–40 characters, no spaces, letters and digits with -·’' only (docs/WORDBOOK.md).
bool validWord(const std::string &word) {
    size_t n = 0;
    for (size_t i = 0; i < word.size();) {
        char32_t cp = nextScalar(word, i);
        if (!alphanumeric(cp) && cp != '-' && cp != 0xB7 && cp != 0x2019 && cp != '\'') return false;
        ++n;
    }
    return n >= 2 && n <= 40;
}

bool validBoundary(const std::string &compact, const std::string &spaced) {
    if (!validWord(compact) || spaced.find("  ") != std::string::npos) return false;
    std::string joined;
    for (char c : spaced)
        if (c != ' ') joined += c;
    return joined == compact;
}

std::vector<std::pair<std::string, Item>> byChange(const std::map<std::string, Item> &items) {
    std::vector<std::pair<std::string, Item>> live;
    for (const auto &kv : items)
        if (!kv.second.removed) live.push_back(kv);
    std::sort(live.begin(), live.end(), [](const auto &a, const auto &b) {
        return a.second.at != b.second.at ? a.second.at < b.second.at : a.first < b.first;
    });
    return live;
}

std::wstring syncDir(const std::string &folder) {
    std::wstring dir = widen(folder);
    while (!dir.empty() && (dir.back() == L'\\' || dir.back() == L'/')) dir.pop_back();
    return dir + L"\\" + kSubfolder;
}

}  // namespace

State localState(const Settings &s) {
    std::map<std::string, WordbookStamp> stamps = s.wordbookStamps();
    auto at = [&](const std::string &key) {
        auto it = stamps.find(key);
        return it == stamps.end() ? 0.0 : it->second.at;
    };
    State state;
    for (const auto &w : s.userWords()) state.words[w] = {"", at("w:" + w), false};
    for (const auto &b : s.learned()) state.boundaries[b.compact] = {b.spaced, at("b:" + b.compact), false};
    for (const auto &[key, v] : stamps) {
        if (!v.removed || key.size() < 3) continue;
        std::string name = key.substr(2);
        if (key.compare(0, 2, "w:") == 0 && !state.words.count(name)) state.words[name] = {"", v.at, true};
        if (key.compare(0, 2, "b:") == 0 && !state.boundaries.count(name)) state.boundaries[name] = {"", v.at, true};
    }
    return state;
}

State merge(const State &a, const State &b) {
    auto pick = [](const Item *x, const Item &y) {
        if (!x) return y;
        if (y.at != x->at) return y.at > x->at ? y : *x;
        return x->removed ? y : *x;
    };
    State out = a;
    for (const auto &[k, v] : b.words) {
        auto it = out.words.find(k);
        out.words[k] = pick(it == out.words.end() ? nullptr : &it->second, v);
    }
    for (const auto &[k, v] : b.boundaries) {
        auto it = out.boundaries.find(k);
        out.boundaries[k] = pick(it == out.boundaries.end() ? nullptr : &it->second, v);
    }
    return out;
}

void apply(const State &state, Settings &s) {
    std::vector<std::string> words;
    for (const auto &[k, v] : byChange(state.words)) words.push_back(k);
    std::vector<LearnedBoundary> boundaries;
    for (const auto &[k, v] : byChange(state.boundaries)) boundaries.push_back({k, v.spaced.empty() ? k : v.spaced});
    std::map<std::string, WordbookStamp> stamps;
    for (const auto &[k, v] : state.words) stamps["w:" + k] = {v.at, v.removed};
    for (const auto &[k, v] : state.boundaries) stamps["b:" + k] = {v.at, v.removed};
    s.replaceWordbook(words, boundaries, stamps);
}

std::string isoTime(double seconds) {
    unsigned long long t = static_cast<unsigned long long>(std::floor(std::max(0.0, seconds))) * 10000000ull +
                           116444736000000000ull;
    FILETIME ft{static_cast<DWORD>(t), static_cast<DWORD>(t >> 32)};
    SYSTEMTIME st{};
    FileTimeToSystemTime(&ft, &st);
    char buf[32];
    std::snprintf(buf, sizeof buf, "%04u-%02u-%02uT%02u:%02u:%02uZ", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute,
                  st.wSecond);
    return buf;
}

double parseIsoTime(const std::string &text) {
    unsigned y, mo, d, h, mi, s;
    int used = 0;
    if (sscanf_s(text.c_str(), "%4u-%2u-%2uT%2u:%2u:%2u%n", &y, &mo, &d, &h, &mi, &s, &used) != 6) return 0;
    const char *p = text.c_str() + used;
    double fraction = 0;
    if (*p == '.') {
        double scale = 0.1;
        for (++p; *p >= '0' && *p <= '9'; ++p, scale /= 10) fraction += (*p - '0') * scale;
    }
    int offset = 0;
    if (*p == '+' || *p == '-') {
        unsigned oh = 0, om = 0;
        if (sscanf_s(p + 1, "%2u:%2u", &oh, &om) < 1 && sscanf_s(p + 1, "%2u%2u", &oh, &om) < 1) return 0;
        offset = (*p == '+' ? 1 : -1) * static_cast<int>(oh * 3600 + om * 60);
    } else if (*p != 'Z' && *p != 'z') {
        return 0;
    }
    SYSTEMTIME st{};
    st.wYear = static_cast<WORD>(y);
    st.wMonth = static_cast<WORD>(mo);
    st.wDay = static_cast<WORD>(d);
    st.wHour = static_cast<WORD>(h);
    st.wMinute = static_cast<WORD>(mi);
    st.wSecond = static_cast<WORD>(s);
    FILETIME ft{};
    if (!SystemTimeToFileTime(&st, &ft)) return 0;
    unsigned long long t = static_cast<unsigned long long>(ft.dwHighDateTime) << 32 | ft.dwLowDateTime;
    return (static_cast<double>(t) - 116444736000000000.0) / 1e7 + fraction - offset;
}

std::string encode(const State &state, const std::string &device, bool includeRemoved) {
    std::string out = "{\n  \"format\": " + Json(kFormat).dump() + ",\n  \"version\": " + std::to_string(kVersion) + ",\n";
    if (!device.empty()) out += "  \"device\": " + Json(device).dump() + ",\n";
    out += "  \"updated\": " + Json(isoTime(nowSeconds())).dump() + ",\n  \"words\": [";
    bool first = true;
    for (const auto &[k, v] : state.words) {
        if (v.removed && !includeRemoved) continue;
        Json o = Json::object();
        o.set("word", k);
        o.set("at", isoTime(v.at));
        if (v.removed) o.set("removed", true);
        out += (first ? "\n    " : ",\n    ") + o.dump();
        first = false;
    }
    out += first ? "],\n  \"boundaries\": [" : "\n  ],\n  \"boundaries\": [";
    first = true;
    for (const auto &[k, v] : state.boundaries) {
        if (v.removed && !includeRemoved) continue;
        Json o = Json::object();
        o.set("compact", k);
        o.set("spaced", v.spaced.empty() ? k : v.spaced);
        o.set("at", isoTime(v.at));
        if (v.removed) o.set("removed", true);
        out += (first ? "\n    " : ",\n    ") + o.dump();
        first = false;
    }
    out += first ? "]\n}\n" : "\n  ]\n}\n";
    return out;
}

bool decode(const std::string &text, State &state, std::string *device) {
    std::string body = text.compare(0, 3, "\xEF\xBB\xBF") == 0 ? text.substr(3) : text;
    Json file;
    if (!Json::parse(body, file) || !file.isObject()) return false;
    if (!file["format"].isString() || file["format"].asString() != kFormat) return false;
    if (!file["version"].isNumber() || file["version"].asNumber() > kVersion) return false;
    state = State();
    for (const Json &w : file["words"].items()) {
        if (!w["word"].isString() || !validWord(w["word"].asString())) continue;
        state.words[w["word"].asString()] = {"", parseIsoTime(w["at"].isString() ? w["at"].asString() : ""),
                                             w["removed"].asBool()};
    }
    for (const Json &b : file["boundaries"].items()) {
        if (!b["compact"].isString() || !b["spaced"].isString()) continue;
        const std::string &compact = b["compact"].asString(), &spaced = b["spaced"].asString();
        if (!validBoundary(compact, spaced)) continue;
        state.boundaries[compact] = {spaced, parseIsoTime(b["at"].isString() ? b["at"].asString() : ""),
                                     b["removed"].asBool()};
    }
    if (device) *device = file["device"].isString() ? file["device"].asString() : std::string();
    return true;
}

bool exportTo(const std::wstring &file) {
    Settings s;
    s.load();
    return writeFileAtomic(file, encode(localState(s), "", false));
}

bool importFrom(const std::wstring &file, int &words, int &boundaries) {
    words = boundaries = 0;
    std::string text;
    State incoming;
    if (!readFile(file, text) || !decode(text, incoming)) return false;
    Settings s;
    s.update([&](Settings &edit) {
        State state = localState(edit);
        double now = nowSeconds();
        for (const auto &[k, v] : incoming.words) {
            if (v.removed) continue;
            auto it = state.words.find(k);
            if (it == state.words.end() || it->second.removed) {
                state.words[k] = {"", now, false};
                ++words;
            }
        }
        for (const auto &[k, v] : incoming.boundaries) {
            if (v.removed) continue;
            auto it = state.boundaries.find(k);
            if (it == state.boundaries.end() || it->second.removed || (it->second.spaced != v.spaced && v.at > it->second.at)) {
                state.boundaries[k] = {v.spaced, now, false};
                ++boundaries;
            }
        }
        apply(state, edit);
    });
    return true;
}

bool syncDue(const Settings &s) {
    if (s.getString("syncFolder").empty()) return false;
    double last = std::max(s.getNumber("syncLast"), g_lastAttempt.load());
    return nowSeconds() - last >= kPeriod;
}

bool syncNow(std::string *error) {
    Settings s;
    s.load();
    if (s.getString("syncFolder").empty()) return true;
    g_lastAttempt = nowSeconds();
    HANDLE mutex = CreateMutexW(nullptr, FALSE, L"Local\\MaimusiWordbookSync");
    DWORD wait = mutex ? WaitForSingleObject(mutex, 30000) : WAIT_FAILED;
    if (wait != WAIT_OBJECT_0 && wait != WAIT_ABANDONED) {
        if (mutex) CloseHandle(mutex);
        if (error) *error = "다른 앱이 맞추는 중입니다";
        return false;
    }
    std::string failure;
    for (int pass = 0; pass < 2; ++pass) {
        std::string id, folder;
        State local;
        s.update([&](Settings &edit) {
            folder = edit.getString("syncFolder");
            if (!folder.empty()) id = edit.deviceID();
            local = localState(edit);
        });
        if (folder.empty()) break;  // sync was turned off meanwhile
        std::wstring base = widen(folder), dir = syncDir(folder);
        DWORD attr = GetFileAttributesW(base.c_str());
        if (attr == INVALID_FILE_ATTRIBUTES || !(attr & FILE_ATTRIBUTE_DIRECTORY)) {
            failure = "고른 폴더를 찾을 수 없습니다";
            break;
        }
        CreateDirectoryW(dir.c_str(), nullptr);
        std::wstring own = kPrefix + widen(id) + L".json";
        State merged = local;
        WIN32_FIND_DATAW fd;
        HANDLE find = FindFirstFileW((dir + L"\\" + kPrefix + L"*.json").c_str(), &fd);
        if (find != INVALID_HANDLE_VALUE) {
            do {
                if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
                std::wstring name = fd.cFileName;
                if (_wcsicmp(name.c_str(), own.c_str()) == 0) continue;
                // A file not yet downloaded (OneDrive Files On-Demand) downloads
                // when read; one that cannot be read now is read next time.
                std::string text;
                State other;
                if (readFile(dir + L"\\" + name, text) && decode(text, other)) merged = merge(merged, other);
            } while (FindNextFileW(find, &fd));
            FindClose(find);
        }
        if (!writeFileAtomic(dir + L"\\" + own, encode(merged, id, true))) {
            failure = "단어장 파일을 쓰지 못했습니다";
            break;
        }
        // What changed here while syncing is kept as well; then once more so
        // this device's file has it too.
        bool changed = false;
        s.update([&](Settings &edit) {
            State current = localState(edit);
            State final = merge(merged, current);
            changed = final != merged;
            apply(final, edit);
            edit.set("syncLast", nowSeconds());
            edit.set("syncError", "");
        });
        if (!changed) break;
    }
    if (!failure.empty()) s.update([&](Settings &edit) { edit.set("syncError", failure); });
    ReleaseMutex(mutex);
    CloseHandle(mutex);
    if (error) *error = failure;
    return failure.empty();
}

// MARK: Self-test

int selfTest(const std::wstring &folder) {
    int failures = 0;
    auto check = [&](const char *name, bool ok, const std::string &detail) {
        std::printf("%s  %s: %s\n", ok ? "PASS" : "FAIL", name, detail.c_str());
        if (!ok) ++failures;
    };
    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    std::wstring settingsFile = std::wstring(tmp) + L"maimusi-wordbook-test-" + std::to_wstring(GetCurrentProcessId()) + L".json";
    Settings::usePathForTesting(settingsFile);
    DeleteFileW(settingsFile.c_str());

    State a, b;
    a.words["찰떡엔진"] = {"", 10, false};
    b.words["찰떡엔진"] = {"", 20, true};
    a.words["매무시"] = {"", 30, false};
    b.boundaries["원물로"] = {"원물로", 5, false};
    a.boundaries["원물로"] = {"원 물로", 7, false};
    State m = merge(a, b);
    check("newer removal wins", m.words["찰떡엔진"].removed && !m.words["매무시"].removed, "removed on the other device later");
    check("newer spacing wins", m.boundaries["원물로"].spaced == "원 물로", "per-entry last writer");
    check("merge is symmetric", merge(a, b) == merge(b, a), "same result on both devices");
    State tieA, tieB;
    tieA.words["같은때"] = {"", 50, true};
    tieB.words["같은때"] = {"", 50, false};
    check("tie keeps the entry", !merge(tieA, tieB).words["같은때"].removed && !merge(tieB, tieA).words["같은때"].removed,
          "equal times: the side that keeps it");
    State back;
    std::string device;
    std::string text = encode(m, "abcd1234", true);
    bool decoded = decode(text, back, &device);
    check("file round trip", decoded && back.words.size() == m.words.size() && back.boundaries["원물로"].spaced == "원 물로" &&
                                 back.words["찰떡엔진"].removed && device == "abcd1234",
          std::to_string(text.size()) + " bytes");
    State bad;
    decode("{\"format\":\"maimusi-wordbook\",\"version\":1,\"updated\":\"\",\"words\":[{\"word\":\"띄어 쓴 말\",\"at\":\"\"}],"
           "\"boundaries\":[{\"compact\":\"가나다\",\"spaced\":\"가 다\",\"at\":\"\"}]}",
           bad);
    check("invalid entries dropped", bad.words.empty() && bad.boundaries.empty(), "spaced words and mismatched spacing");
    check("other formats rejected",
          !decode("{\"format\":\"x\",\"version\":1,\"updated\":\"\",\"words\":[],\"boundaries\":[]}", bad) &&
              !decode("{\"format\":\"maimusi-wordbook\",\"version\":2,\"words\":[]}", bad),
          "format must be maimusi-wordbook, version 1");
    check("words of letters and digits", validWord("찰떡엔진") && validWord("學校") && validWord("ㄱㄴ") && validWord("K-팝") &&
                                             validWord("𮕩衰") && !validWord("가") && !validWord("가!") && !validWord("가😀"),
          "Hangul, Hanja, jamo, -·’' only");
    double t = parseIsoTime("2026-11-10T05:30:18Z");
    check("ISO 8601 time", isoTime(t) == "2026-11-10T05:30:18Z" && parseIsoTime("2026-11-10T14:30:18+09:00") == t &&
                               std::fabs(parseIsoTime("2026-11-10T05:30:18.5Z") - t - 0.5) < 1e-6 && parseIsoTime("x") == 0,
          isoTime(t));

    // Settings bookkeeping: stamps, last learned, forgetting.
    Settings s;
    s.update([](Settings &e) {
        e.addWords({"지울단어"});
        e.rememberLearned({{"먹어버렸다", "먹어 버렸다"}}, {"새단어"});
    });
    s.load();
    auto stamps = s.wordbookStamps();
    check("changes are stamped", stamps.count("w:지울단어") && stamps.count("b:먹어버렸다") && stamps.count("w:새단어"),
          std::to_string(stamps.size()) + " stamps");
    check("last learned", s.lastLearnedLabel() == "먹어 버렸다", s.lastLearnedLabel());
    s.update([](Settings &e) { e.forgetLastLearned(); });
    s.load();
    stamps = s.wordbookStamps();
    check("forget last learned", s.learned().empty() && s.userWords() == std::vector<std::string>{"지울단어"} &&
                                     stamps["b:먹어버렸다"].removed && stamps["w:새단어"].removed && s.lastLearnedLabel().empty(),
          "removed and stamped");
    State local = localState(s);
    check("removed entries kept for sync", local.words["새단어"].removed && local.boundaries["먹어버렸다"].removed,
          "so other devices do not bring them back");
    s.update([](Settings &e) { e.removeWord("지울단어"); });

    if (!folder.empty()) {
        // Like the macOS --test-wordbook-sync: the other device removed
        // 「지울단어」 later and added a word and a spacing.
        std::wstring dir = syncDir(narrow(folder));
        CreateDirectoryW(dir.c_str(), nullptr);
        s.update([&](Settings &e) {
            e.addWords({"지울단어", "이기기단어"});
            e.set("syncFolder", narrow(folder));
        });
        std::string later = isoTime(nowSeconds() + 60);
        std::string other = "{\"format\":\"maimusi-wordbook\",\"version\":1,\"device\":\"0ther0ne\",\"updated\":\"" + later +
                            "\",\n \"words\":[{\"word\":\"다른기기단어\",\"at\":\"" + later +
                            "\"},{\"word\":\"지울단어\",\"at\":\"" + later +
                            "\",\"removed\":true}],\n \"boundaries\":[{\"compact\":\"원물로\",\"spaced\":\"원물로\",\"at\":\"" +
                            later + "\"}]}\n";
        bool wrote = writeFileAtomic(dir + L"\\" + kPrefix + L"0ther0ne.json", other);
        std::string failure;
        bool synced = syncNow(&failure);
        s.load();
        std::vector<std::string> words = s.userWords();
        auto has = [&](const std::string &w) { return std::find(words.begin(), words.end(), w) != words.end(); };
        bool learnedOk = false;
        for (const auto &c : s.learned()) learnedOk = learnedOk || c.compact == "원물로";
        std::string id = s.getString("deviceID");
        std::wstring ownPath = dir + L"\\" + kPrefix + widen(id) + L".json";
        std::string ownText;
        State own;
        std::string ownDevice;
        bool ownOk = readFile(ownPath, ownText) && decode(ownText, own, &ownDevice);
        check("sync with another device's file",
              wrote && synced && has("이기기단어") && has("다른기기단어") && !has("지울단어") && learnedOk && ownOk &&
                  own.words["지울단어"].removed && ownDevice == id && s.getNumber("syncLast") > 0,
              "words=" + std::to_string(words.size()) + " own file=" + (ownOk ? narrow(ownPath) : std::string("-")) +
                  " error=" + (failure.empty() ? "-" : failure));
    }
    DeleteFileW(settingsFile.c_str());
    std::printf("%s (%d failed)\n", failures ? "FAIL" : "PASS", failures);
    return failures ? 1 : 0;
}

}  // namespace wordbook
}  // namespace maimusi
