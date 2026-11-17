#include "log.h"

#include <windows.h>
#include <shlobj.h>

#include <cstdarg>
#include <cstdio>
#include <mutex>

namespace maimusi {

bool Log::enabled() {
    static int state = -1;
    if (state < 0) {
        DWORD value = 0, size = sizeof value;
        state = RegGetValueW(HKEY_CURRENT_USER, L"Software\\Maimusi", L"DebugLog", RRF_RT_REG_DWORD, nullptr, &value,
                             &size) == ERROR_SUCCESS && value == 1;
    }
    return state == 1;
}

void Log::write(const char *format, ...) {
    if (!enabled()) return;
    static std::mutex mutex;
    std::lock_guard<std::mutex> lock(mutex);
    PWSTR base = nullptr;
    if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &base))) return;
    wchar_t path[MAX_PATH];
    swprintf_s(path, L"%s\\Maimusi", base);
    CreateDirectoryW(path, nullptr);
    wcscat_s(path, L"\\debug.log");
    CoTaskMemFree(base);
    FILE *f = nullptr;
    if (_wfopen_s(&f, path, L"a") != 0 || !f) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    std::fprintf(f, "%02d:%02d:%02d.%03d pid %lu tid %lu  ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds,
                 GetCurrentProcessId(), GetCurrentThreadId());
    va_list args;
    va_start(args, format);
    std::vfprintf(f, format, args);
    va_end(args);
    std::fputc('\n', f);
    std::fclose(f);
}

}  // namespace maimusi
