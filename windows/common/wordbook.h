// 단어장: registered words and learned spacing, exported to and imported from
// a file, and kept in step between devices through a folder the user chose
// (OneDrive, Google Drive, Dropbox, a USB disk...). No Sebansios server.
// Same format and rules as macOS (docs/WORDBOOK.md, macos/Sources/Wordbook.swift).
//
// Each device writes only its own file, <folder>\Maimusi\maimusi-wordbook-<id>.json,
// reads the others, and keeps for every entry the side changed last (on a tie,
// the side that keeps it). Every application runs its own input method, so a
// sync takes the named mutex Local\MaimusiWordbookSync and merges into
// settings.json again under the settings mutex just before writing it.
#pragma once

#include <map>
#include <string>

#include "settings.h"

namespace maimusi {
namespace wordbook {

struct Item {
    std::string spaced;  // boundaries only
    double at = 0;       // seconds since 1970 (UTC)
    bool removed = false;
    bool operator==(const Item &o) const { return spaced == o.spaced && at == o.at && removed == o.removed; }
};

struct State {
    std::map<std::string, Item> words, boundaries;
    bool operator==(const State &o) const { return words == o.words && boundaries == o.boundaries; }
    bool operator!=(const State &o) const { return !(*this == o); }
};

State localState(const Settings &s);
// Per entry the later change; on equal times the entry that is kept.
State merge(const State &a, const State &b);
// Writes `state` into the settings (words and boundaries in change order).
void apply(const State &state, Settings &s);

// The file. `device` empty and !includeRemoved for exported files.
std::string encode(const State &state, const std::string &device, bool includeRemoved);
// False if this is not a wordbook (or a newer version). Invalid entries are dropped.
bool decode(const std::string &text, State &state, std::string *device = nullptr);

// ISO 8601 UTC with whole seconds ("2026-11-10T05:30:18Z"), as macOS writes and reads.
std::string isoTime(double seconds);
double parseIsoTime(const std::string &text);  // 0 when malformed

bool exportTo(const std::wstring &file);
// Adds what is missing; never removes (a file the user picked). Returns false
// if the file is not a wordbook; otherwise the counts of words added and of
// spacings added or changed.
bool importFrom(const std::wstring &file, int &words, int &boundaries);

// Reads the other devices' files, merges, writes this device's file and the
// settings. Does nothing (returns true) without a sync folder. On failure
// `error` holds a short Korean reason, also saved as syncError.
bool syncNow(std::string *error = nullptr);
// Whether the periodic sync is due (a folder is set and no process synced in
// the last five minutes).
bool syncDue(const Settings &s);

// `MaimusiSettings.exe --test-wordbook [folder]`: merge, file round trip and,
// with a folder, a sync with another device's file, on a settings file of its
// own (the user's settings are not touched). Prints PASS/FAIL; returns 0 if all pass.
int selfTest(const std::wstring &folder);

}  // namespace wordbook
}  // namespace maimusi
