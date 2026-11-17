// Development probe: types into another application's window through the real
// keyboard path, to see how the text service behaves there (with DebugLog on).
// Usage: keyinto.exe PID KEYS [SNAP.bmp]
//   KEYS as in tsf_harness ({SPACE}, {ENTER}, {WAIT}, {HANGUL} ...).
// Types only while a window of PID is in the foreground; stops otherwise.
// Build: cl /utf-8 /std:c++20 /EHsc /O2 /DUNICODE /D_UNICODE windows\tests\keyinto.cpp user32.lib gdi32.lib
#include <windows.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace {

DWORD g_pid = 0;
HWND g_target = nullptr;

BOOL CALLBACK findMain(HWND hwnd, LPARAM param) {
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != g_pid || !IsWindowVisible(hwnd) || GetWindow(hwnd, GW_OWNER)) return TRUE;
    RECT r;
    GetWindowRect(hwnd, &r);
    auto *best = reinterpret_cast<std::pair<HWND, long> *>(param);
    long area = (r.right - r.left) * (r.bottom - r.top);
    if (area > best->second) *best = {hwnd, area};
    return TRUE;
}

bool ours(HWND hwnd) {
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    return pid == g_pid;
}

bool ensureForeground() {
    if (ours(GetForegroundWindow())) return true;
    SwitchToThisWindow(g_target, TRUE);
    SetForegroundWindow(g_target);
    for (int i = 0; i < 30 && !ours(GetForegroundWindow()); ++i) Sleep(50);
    return ours(GetForegroundWindow());
}

void key(WORD vk, bool up, bool extended = false) {
    if (!up && !ensureForeground()) {
        std::printf("target is not in the foreground; stopping\n");
        ExitProcess(3);
    }
    INPUT in{};
    in.type = INPUT_KEYBOARD;
    in.ki.wVk = vk;
    in.ki.wScan = static_cast<WORD>(MapVirtualKeyW(vk, MAPVK_VK_TO_VSC));
    in.ki.dwFlags = (up ? KEYEVENTF_KEYUP : 0) | (extended ? KEYEVENTF_EXTENDEDKEY : 0);
    SendInput(1, &in, sizeof in);
}

void tap(WORD vk, bool shift = false, bool extended = false) {
    if (shift) key(VK_SHIFT, false);
    key(vk, false, extended);
    key(vk, true, extended);
    if (shift) key(VK_SHIFT, true);
    Sleep(40);
}

void typeKeys(const std::string &keys) {
    for (size_t i = 0; i < keys.size(); ++i) {
        char c = keys[i];
        if (c == '{') {
            size_t end = keys.find('}', i);
            std::string name = keys.substr(i + 1, end - i - 1);
            i = end;
            if (name == "HANGUL") tap(VK_HANGUL);
            else if (name == "SPACE") tap(VK_SPACE);
            else if (name == "ENTER") tap(VK_RETURN);
            else if (name == "BS") tap(VK_BACK);
            else if (name == "ESC") tap(VK_ESCAPE);
            else if (name == "DOWN") tap(VK_DOWN, false, true);
            else if (name == "WAIT") Sleep(1500);
            else if (name == "CLICK") {
                // Click the middle of the target window (focus a text field).
                if (!ensureForeground()) ExitProcess(3);
                RECT r;
                GetWindowRect(g_target, &r);
                SetCursorPos((r.left + r.right) / 2, r.top + (r.bottom - r.top) / 3);
                INPUT in[2]{};
                in[0].type = in[1].type = INPUT_MOUSE;
                in[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
                in[1].mi.dwFlags = MOUSEEVENTF_LEFTUP;
                SendInput(2, in, sizeof(INPUT));
                Sleep(300);
            }
            continue;
        }
        if (c >= 'a' && c <= 'z') tap(static_cast<WORD>(c - 'a' + 'A'));
        else if (c >= 'A' && c <= 'Z') tap(static_cast<WORD>(c), true);
        else if (c >= '0' && c <= '9') tap(static_cast<WORD>(c));
    }
    Sleep(300);
}

BOOL CALLBACK collect(HWND hwnd, LPARAM param) {
    if (ours(hwnd) && IsWindowVisible(hwnd)) reinterpret_cast<std::vector<HWND> *>(param)->push_back(hwnd);
    return TRUE;
}

// Images only the target application's windows (its main window and popups).
void snap(const char *path) {
    std::vector<HWND> windows;
    EnumWindows(collect, reinterpret_cast<LPARAM>(&windows));  // top of the z-order first
    std::reverse(windows.begin(), windows.end());
    RECT all{};
    for (HWND w : windows) {
        RECT r;
        GetWindowRect(w, &r);
        UnionRect(&all, &all, &r);
    }
    int width = all.right - all.left, height = all.bottom - all.top;
    if (width <= 0 || height <= 0 || width > 8000 || height > 8000) return;
    HDC screen = GetDC(nullptr);
    HDC dc = CreateCompatibleDC(screen);
    BITMAPINFO bi{};
    bi.bmiHeader = {sizeof(BITMAPINFOHEADER), width, -height, 1, 32, BI_RGB};
    void *bits = nullptr;
    HBITMAP bmp = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    HGDIOBJ old = SelectObject(dc, bmp);
    RECT fill{0, 0, width, height};
    FillRect(dc, &fill, static_cast<HBRUSH>(GetStockObject(GRAY_BRUSH)));
    for (HWND w : windows) {
        RECT r;
        GetWindowRect(w, &r);
        HDC wdc = CreateCompatibleDC(screen);
        HBITMAP wb = CreateCompatibleBitmap(screen, r.right - r.left, r.bottom - r.top);
        HGDIOBJ wold = SelectObject(wdc, wb);
        PrintWindow(w, wdc, 2);
        BitBlt(dc, r.left - all.left, r.top - all.top, r.right - r.left, r.bottom - r.top, wdc, 0, 0, SRCCOPY);
        SelectObject(wdc, wold);
        DeleteObject(wb);
        DeleteDC(wdc);
    }
    BITMAPFILEHEADER fh{0x4D42, static_cast<DWORD>(sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER) + width * height * 4), 0, 0,
                        sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER)};
    if (FILE *f = std::fopen(path, "wb")) {
        std::fwrite(&fh, sizeof fh, 1, f);
        std::fwrite(&bi.bmiHeader, sizeof bi.bmiHeader, 1, f);
        std::fwrite(bits, 4, static_cast<size_t>(width) * height, f);
        std::fclose(f);
    }
    SelectObject(dc, old);
    DeleteObject(bmp);
    DeleteDC(dc);
    ReleaseDC(nullptr, screen);
}

}  // namespace

int main(int argc, char **argv) {
    if (argc < 3) {
        std::printf("usage: keyinto PID KEYS [SNAP.bmp]\n");
        return 2;
    }
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    g_pid = static_cast<DWORD>(std::strtoul(argv[1], nullptr, 10));
    std::pair<HWND, long> best{nullptr, 0};
    EnumWindows(findMain, reinterpret_cast<LPARAM>(&best));
    g_target = best.first;
    if (!g_target) {
        std::printf("no window for pid %lu\n", g_pid);
        return 2;
    }
    typeKeys(argv[2]);
    if (argc > 3) snap(argv[3]);
    std::printf("done\n");
    return 0;
}
