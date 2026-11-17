// UTF-8 <-> UTF-16 conversion. The core and the engine speak UTF-8; Win32 and
// TSF speak UTF-16. Offsets reported by the core are already UTF-16 units.
#pragma once

#include <windows.h>

#include <string>

namespace maimusi {

inline std::wstring widen(const std::string &s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring w(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), w.data(), n);
    return w;
}

inline std::wstring widen(const char *s) { return s ? widen(std::string(s)) : std::wstring(); }

inline std::string narrow(const std::wstring &w) {
    if (w.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()), nullptr, 0, nullptr, nullptr);
    std::string s(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()), s.data(), n, nullptr, nullptr);
    return s;
}

}  // namespace maimusi
