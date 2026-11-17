// Diagnostic log for debugging the input method, off by default. Enabled only
// when HKCU\Software\Maimusi\DebugLog (DWORD) is 1; written to
// %LOCALAPPDATA%\Maimusi\debug.log. Callers never pass typed text: only
// events, virtual-key codes of non-character keys and states.
#pragma once

namespace maimusi {

class Log {
public:
    static bool enabled();
    static void write(const char *format, ...);
};

}  // namespace maimusi
