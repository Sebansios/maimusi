// End-to-end test of the installed text service: opens an edit control,
// activates the 매무시 profile for this process, types and checks the text.
// By default keys are injected in-process through ITfKeystrokeMgr (the calls
// the system makes for a key press), so the window need not be in front and
// nothing can reach other applications. --sendinput uses the real keyboard
// path instead (needs the foreground; do not touch the keyboard meanwhile).
// Usage: tsf_harness.exe [--sendinput] [--snap FILE] [--ms] [--imm|--rich] [scenario | --keys KEYS]
// Build (x64 Native Tools prompt; vcvarsall x86 for the 32-bit DLL):
//   cl /utf-8 /std:c++20 /EHsc /O2 /DUNICODE /D_UNICODE windows\tests\tsf_harness.cpp ole32.lib imm32.lib user32.lib gdi32.lib
#include <windows.h>
#include <msctf.h>

#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

namespace {

// --ms: the Microsoft Korean IME, as a reference for the same scenarios.
const CLSID kMsClsid = {0xa028ae76, 0x01b1, 0x46c2, {0x99, 0xc4, 0xac, 0xd9, 0x85, 0x8a, 0xe0, 0x2f}};
const GUID kMsProfile = {0xb5fe1f02, 0xd5f2, 0x4445, {0x9c, 0x03, 0xc5, 0x68, 0xf2, 0x3c, 0x99, 0xa1}};
bool g_ms = false;
const CLSID kClsid = {0x1a36ddcd, 0xe1ae, 0x4b54, {0xaa, 0xf1, 0xef, 0x54, 0x18, 0xf4, 0xb2, 0x5b}};
const GUID kProfile = {0x3be0990f, 0x7425, 0x4407, {0x81, 0xcb, 0x4c, 0x4c, 0x3c, 0xec, 0x4a, 0x50}};

HWND g_main = nullptr, g_edit = nullptr;

void pump(int ms) {
    DWORD end = GetTickCount() + ms;
    MSG msg;
    while (static_cast<int>(end - GetTickCount()) > 0) {
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        Sleep(5);
    }
}

// SendInput goes to whatever window is in front: never type unless it is ours.
bool ensureForeground() {
    if (GetForegroundWindow() == g_main) return true;
    SwitchToThisWindow(g_main, TRUE);
    SetForegroundWindow(g_main);
    SetFocus(g_edit);
    for (int i = 0; i < 20 && GetForegroundWindow() != g_main; ++i) Sleep(50);
    return GetForegroundWindow() == g_main;
}

void key(WORD vk, bool up, bool extended = false) {
    if (!up && !ensureForeground()) {
        std::printf("harness window is not in the foreground; stopping\n");
        ExitProcess(3);
    }
    INPUT in{};
    in.type = INPUT_KEYBOARD;
    in.ki.wVk = vk;
    in.ki.wScan = static_cast<WORD>(MapVirtualKeyW(vk, MAPVK_VK_TO_VSC));
    in.ki.dwFlags = (up ? KEYEVENTF_KEYUP : 0) | (extended ? KEYEVENTF_EXTENDEDKEY : 0);
    SendInput(1, &in, sizeof in);
}

bool g_sendInput = false;

void inject(WORD vk, bool shift, bool extended) {
    ITfThreadMgr *tm = nullptr;
    ITfKeystrokeMgr *km = nullptr;
    if (SUCCEEDED(CoCreateInstance(CLSID_TF_ThreadMgr, nullptr, CLSCTX_INPROC_SERVER, IID_ITfThreadMgr,
                                   reinterpret_cast<void **>(&tm))))
        tm->QueryInterface(IID_ITfKeystrokeMgr, reinterpret_cast<void **>(&km));
    BYTE state[256];
    GetKeyboardState(state);
    state[VK_SHIFT] = state[VK_LSHIFT] = shift ? 0x80 : 0;
    SetKeyboardState(state);
    UINT scan = MapVirtualKeyW(vk, MAPVK_VK_TO_VSC);
    LPARAM down = 1 | (static_cast<LPARAM>(scan) << 16) | (extended ? (1 << 24) : 0);
    LPARAM up = down | (1u << 30) | (1u << 31);
    BOOL eaten = FALSE;
    if (km && SUCCEEDED(km->TestKeyDown(vk, down, &eaten)) && eaten) km->KeyDown(vk, down, &eaten);
    if (!eaten) {
        // Not taken by the input method: deliver it the way the application would get it.
        SendMessageW(g_edit, WM_KEYDOWN, vk, down);
        wchar_t buf[4];
        if (ToUnicode(vk, scan, state, buf, 4, 0) == 1) SendMessageW(g_edit, WM_CHAR, buf[0], down);
    }
    pump(10);
    eaten = FALSE;
    if (km && SUCCEEDED(km->TestKeyUp(vk, up, &eaten)) && eaten) km->KeyUp(vk, up, &eaten);
    if (!eaten) SendMessageW(g_edit, WM_KEYUP, vk, up);
    state[VK_SHIFT] = state[VK_LSHIFT] = 0;
    SetKeyboardState(state);
    if (km) km->Release();
    if (tm) tm->Release();
}

void tap(WORD vk, bool shift = false, bool extended = false) {
    if (!g_sendInput) {
        inject(vk, shift, extended);
        pump(30);
        return;
    }
    if (shift) key(VK_SHIFT, false);
    key(vk, false, extended);
    key(vk, true, extended);
    if (shift) key(VK_SHIFT, true);
    pump(30);
}

// Saves an image of this process's own windows only (the harness and the
// input method's candidate window), never the rest of the screen.
std::string g_snap = "harness_snap.bmp";

BOOL CALLBACK collectWindow(HWND hwnd, LPARAM param) {
    if (IsWindowVisible(hwnd)) reinterpret_cast<std::vector<HWND> *>(param)->push_back(hwnd);
    return TRUE;
}

void snap() {
    std::vector<HWND> windows;
    EnumThreadWindows(GetCurrentThreadId(), collectWindow, reinterpret_cast<LPARAM>(&windows));
    RECT all{};
    for (HWND w : windows) {
        RECT r;
        GetWindowRect(w, &r);
        UnionRect(&all, &all, &r);
    }
    int width = all.right - all.left, height = all.bottom - all.top;
    if (width <= 0 || height <= 0) return;
    HDC screen = GetDC(nullptr);
    HDC dc = CreateCompatibleDC(screen);
    BITMAPINFO bi{};
    bi.bmiHeader = {sizeof(BITMAPINFOHEADER), width, -height, 1, 32, BI_RGB};
    void *bits = nullptr;
    HBITMAP bmp = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    HGDIOBJ old = SelectObject(dc, bmp);
    RECT fill{0, 0, width, height};
    FillRect(dc, &fill, static_cast<HBRUSH>(GetStockObject(GRAY_BRUSH)));
    // Main window first, popups (candidate window) on top.
    std::sort(windows.begin(), windows.end(), [](HWND a, HWND b) { return (a == g_main) > (b == g_main); });
    for (HWND w : windows) {
        RECT r;
        GetWindowRect(w, &r);
        HDC wdc = CreateCompatibleDC(screen);
        HBITMAP wb = CreateCompatibleBitmap(screen, r.right - r.left, r.bottom - r.top);
        HGDIOBJ wold = SelectObject(wdc, wb);
        PrintWindow(w, wdc, 2 /* PW_RENDERFULLCONTENT */);
        BitBlt(dc, r.left - all.left, r.top - all.top, r.right - r.left, r.bottom - r.top, wdc, 0, 0, SRCCOPY);
        SelectObject(wdc, wold);
        DeleteObject(wb);
        DeleteDC(wdc);
    }
    BITMAPFILEHEADER fh{0x4D42, static_cast<DWORD>(sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER) + width * height * 4), 0, 0,
                        sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER)};
    if (FILE *f = std::fopen(g_snap.c_str(), "wb")) {
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

// Saves the input mode icon the text service gives the taskbar, drawn at its
// own size on a dark and a light taskbar color, next to the snapshot file.
void saveModeIcon() {
    const GUID inputMode = {0x2c77a81e, 0x41cc, 0x4178, {0xa3, 0xa7, 0x5f, 0x8a, 0x98, 0x75, 0x68, 0xe6}};
    ITfThreadMgr *tm = nullptr;
    ITfLangBarItemMgr *items = nullptr;
    ITfLangBarItem *item = nullptr;
    ITfLangBarItemButton *button = nullptr;
    HICON icon = nullptr;
    if (SUCCEEDED(CoCreateInstance(CLSID_TF_ThreadMgr, nullptr, CLSCTX_INPROC_SERVER, IID_ITfThreadMgr,
                                   reinterpret_cast<void **>(&tm))) &&
        SUCCEEDED(tm->QueryInterface(IID_ITfLangBarItemMgr, reinterpret_cast<void **>(&items))) &&
        SUCCEEDED(items->GetItem(inputMode, &item)) &&
        SUCCEEDED(item->QueryInterface(IID_ITfLangBarItemButton, reinterpret_cast<void **>(&button))))
        button->GetIcon(&icon);
    if (button) button->Release();
    if (item) item->Release();
    if (items) items->Release();
    if (tm) tm->Release();
    if (!icon) {
        std::printf("no input mode icon\n");
        return;
    }
    ICONINFO ii{};
    GetIconInfo(icon, &ii);
    BITMAP bm{};
    GetObject(ii.hbmColor, sizeof bm, &bm);
    int size = bm.bmWidth, width = size * 2 + 12, height = size + 8;
    std::printf("icon %dx%d\n", bm.bmWidth, bm.bmHeight);
    HDC screen = GetDC(nullptr);
    HDC dc = CreateCompatibleDC(screen);
    BITMAPINFO bi{};
    bi.bmiHeader = {sizeof(BITMAPINFOHEADER), width, -height, 1, 32, BI_RGB};
    void *bits = nullptr;
    HBITMAP bmp = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    HGDIOBJ old = SelectObject(dc, bmp);
    RECT dark{0, 0, size + 6, height}, light{size + 6, 0, width, height};
    HBRUSH db = CreateSolidBrush(RGB(0x20, 0x20, 0x20)), lb = CreateSolidBrush(RGB(0xEE, 0xEE, 0xEE));
    FillRect(dc, &dark, db);
    FillRect(dc, &light, lb);
    DrawIconEx(dc, 3, 4, icon, size, size, 0, nullptr, DI_NORMAL);
    DrawIconEx(dc, size + 9, 4, icon, size, size, 0, nullptr, DI_NORMAL);
    std::string path = g_snap + ".icon.bmp";
    BITMAPFILEHEADER fh{0x4D42, static_cast<DWORD>(sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER) + width * height * 4), 0, 0,
                        sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER)};
    if (FILE *f = std::fopen(path.c_str(), "wb")) {
        std::fwrite(&fh, sizeof fh, 1, f);
        std::fwrite(&bi.bmiHeader, sizeof bi.bmiHeader, 1, f);
        std::fwrite(bits, 4, static_cast<size_t>(width) * height, f);
        std::fclose(f);
    }
    SelectObject(dc, old);
    DeleteObject(bmp);
    DeleteObject(db);
    DeleteObject(lb);
    DeleteDC(dc);
    ReleaseDC(nullptr, screen);
    DeleteObject(ii.hbmColor);
    DeleteObject(ii.hbmMask);
    DestroyIcon(icon);
}

// Keys spelled as on a QWERTY keyboard. {Name} for special keys.
void typeKeys(const std::string &keys) {
    for (size_t i = 0; i < keys.size(); ++i) {
        char c = keys[i];
        if (c == '{') {
            size_t end = keys.find('}', i);
            std::string name = keys.substr(i + 1, end - i - 1);
            i = end;
            if (name == "HANGUL") tap(VK_HANGUL);
            else if (name == "HANJA") tap(VK_HANJA);
            else if (name == "SPACE") tap(VK_SPACE);
            else if (name == "SSPACE") tap(VK_SPACE, true);
            else if (name == "ENTER") tap(VK_RETURN);
            else if (name == "BS") tap(VK_BACK);
            else if (name == "ESC") tap(VK_ESCAPE);
            else if (name == "LEFT") tap(VK_LEFT, false, true);
            else if (name == "RIGHT") tap(VK_RIGHT, false, true);
            else if (name == "SLEFT") tap(VK_LEFT, true, true);
            else if (name == "DOWN") tap(VK_DOWN, false, true);
            else if (name == "UP") tap(VK_UP, false, true);
            else if (name == "TAB") tap(VK_TAB);
            else if (name == "WAIT") pump(1500);
            else if (name == "HOLD") pump(4000);  // time for a screenshot
            else if (name == "PAUSE") pump(60000);  // e.g. to update the installation meanwhile
            else if (name == "SNAP") { pump(300); snap(); }
            else if (name == "ICON") saveModeIcon();
            continue;
        }
        if (c >= 'a' && c <= 'z') tap(static_cast<WORD>(c - 'a' + 'A'));
        else if (c >= 'A' && c <= 'Z') tap(static_cast<WORD>(c), true);
        else if (c >= '0' && c <= '9') tap(static_cast<WORD>(c));
        else if (c == '.') tap(VK_OEM_PERIOD);
        else if (c == ',') tap(VK_OEM_COMMA);
        else if (c == '?') tap(VK_OEM_2, true);
        else if (c == '!') tap('1', true);
    }
    pump(200);
}

// --imm: an IME-aware IMM32 window that draws nothing and records what it
// receives, like messengers and word processors that handle WM_IME_* themselves.
bool g_imm = false;
std::wstring g_committed, g_comp;

LRESULT CALLBACK immProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_IME_STARTCOMPOSITION:
        return 0;
    case WM_IME_COMPOSITION: {
        HIMC imc = ImmGetContext(h);
        if (l & GCS_RESULTSTR) {
            LONG bytes = ImmGetCompositionStringW(imc, GCS_RESULTSTR, nullptr, 0);
            std::wstring r(bytes / 2, L'\0');
            ImmGetCompositionStringW(imc, GCS_RESULTSTR, r.data(), bytes);
            g_committed += r;
        }
        LONG bytes = ImmGetCompositionStringW(imc, GCS_COMPSTR, nullptr, 0);
        g_comp.assign(bytes > 0 ? bytes / 2 : 0, L'\0');
        if (bytes > 0) ImmGetCompositionStringW(imc, GCS_COMPSTR, g_comp.data(), bytes);
        ImmReleaseContext(h, imc);
        return 0;
    }
    case WM_IME_ENDCOMPOSITION:
        g_comp.clear();
        return 0;
    case WM_CHAR:
        if (w == VK_BACK) {
            if (!g_committed.empty()) g_committed.pop_back();
        } else if (w == L'\n') {
            g_committed += L'\n';
        } else if (w >= 0x20) {
            g_committed += static_cast<wchar_t>(w);
        }
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

std::wstring text() {
    if (g_imm) return g_comp.empty() ? g_committed : g_committed + L"[" + g_comp + L"]";
    int n = GetWindowTextLengthW(g_edit);
    std::wstring s(n, L'\0');
    GetWindowTextW(g_edit, s.data(), n + 1);
    return s;
}

std::string utf8(const std::wstring &w) {
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, nullptr, 0, nullptr, nullptr);
    std::string s(n > 0 ? n - 1 : 0, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, s.data(), n, nullptr, nullptr);
    return s;
}

struct Scenario {
    const char *name;
    const char *keys;
    const wchar_t *expected;
};

// Starts in Hangul mode. {WAIT} lets the engine answer.
const Scenario kScenarios[] = {
    {"compose-enter", "dkssudgktpdy{ENTER}", L"안녕하세요"},
    {"backspace-jamo", "rkr{BS}s{ENTER}", L"간"},
    {"backspace-to-jamo", "rkr{BS}{BS}s{ENTER}", L"ㄱㄴ"},
    {"hangul-key-english", "{HANGUL}abc{SPACE}{HANGUL}rk{ENTER}", L"abc 가"},
    {"hangul-key-commits", "dk{HANGUL}b{HANGUL}", L"아b"},
    {"shift-double", "Rkr{ENTER}", L"깍"},
    {"space-converts", "dkqjwlrkqkddpemfdjrktlsek{SPACE}{WAIT}{ENTER}", L"아버지가 방에 들어가신다"},
    {"escape-restores", "skvkfrk{SPACE}{WAIT}{ESC}{ENTER}", L"나팔가"},
    {"long-compose", "dkqjwlrkqkddpemfdjrktlsek{ENTER}", L"아버지가방에들어가신다"},
    {"punct-then-space", "dkssud.{SPACE}{WAIT}{ENTER}", L"안녕."},
    {"digits", "123{ENTER}", L"123"},
    {"candidate-down", "gkrry{SPACE}{WAIT}{DOWN}{ENTER}", L"學校"},
    {"space-cycles", "gkrry{SPACE}{WAIT}{SPACE}{ENTER}", L"學校"},
    {"hanja-key", "gkrry{HANJA}{WAIT}{HANJA}{ENTER}", L"學校"},
    {"candidate-escape", "gkrry{SPACE}{WAIT}{DOWN}{ESC}{ENTER}", L"학교"},
    {"typing-commits-conversion", "dkssud{SPACE}{WAIT}gktpdy{ENTER}", L"안녕 하세요"},
    // Shift+Space commits what was typed, without automatic spacing, and adds a space (0.5.3).
    {"shift-space-as-typed", "dkqjwlrkqkddp{SSPACE}rk{ENTER}", L"아버지가방에 가"},
};

LRESULT CALLBACK wndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_SIZE && g_edit) MoveWindow(g_edit, 0, 0, LOWORD(l), HIWORD(l), TRUE);
    if (m == WM_DESTROY) PostQuitMessage(0);
    return DefWindowProcW(h, m, w, l);
}

// Scenarios start in Hangul mode: reset the mode 매무시 shares between applications.
void startInHangul() {
    const GUID global = {0x19d424c3, 0xc4aa, 0x4c20, {0xb6, 0x6d, 0x82, 0x74, 0xad, 0x3b, 0x0c, 0x5e}};
    ITfThreadMgr *tm = nullptr;
    if (FAILED(CoCreateInstance(CLSID_TF_ThreadMgr, nullptr, CLSCTX_INPROC_SERVER, IID_ITfThreadMgr,
                                reinterpret_cast<void **>(&tm))))
        return;
    TfClientId id = TF_CLIENTID_NULL;
    ITfCompartmentMgr *mgr = nullptr;
    ITfCompartment *c = nullptr;
    if (SUCCEEDED(tm->Activate(&id)) && SUCCEEDED(tm->GetGlobalCompartment(&mgr)) &&
        SUCCEEDED(mgr->GetCompartment(global, &c))) {
        VARIANT v;
        v.vt = VT_I4;
        v.lVal = 2;
        HRESULT hr = c->SetValue(id, &v);
        if (FAILED(hr)) std::printf("set global mode: %#lx\n", hr);
    } else {
        std::printf("global compartment unavailable\n");
    }
    if (c) c->Release();
    if (mgr) mgr->Release();
    if (id != TF_CLIENTID_NULL) tm->Deactivate();
    tm->Release();
}

bool activate() {
    if (!g_ms) startInHangul();
    ITfInputProcessorProfileMgr *mgr = nullptr;
    if (FAILED(CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr, CLSCTX_INPROC_SERVER,
                                IID_ITfInputProcessorProfileMgr, reinterpret_cast<void **>(&mgr))))
        return false;
    HRESULT hr = mgr->ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR, MAKELANGID(LANG_KOREAN, SUBLANG_KOREAN), g_ms ? kMsClsid : kClsid,
                                      g_ms ? kMsProfile : kProfile, nullptr, TF_IPPMF_FORPROCESS | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE);
    mgr->Release();
    std::printf("activate profile: %#lx\n", hr);
    return SUCCEEDED(hr);
}

}  // namespace

int main(int argc, char **argv) {
    if (argc > 1 && std::string(argv[1]) == "--activate-session") {
        // For probing other applications (keyinto.exe): make 매무시, in Hangul
        // mode, the input method of the whole session, as choosing it does.
        CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
        startInHangul();
        ITfInputProcessorProfileMgr *mgr = nullptr;
        HRESULT hr = CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr, CLSCTX_INPROC_SERVER,
                                      IID_ITfInputProcessorProfileMgr, reinterpret_cast<void **>(&mgr));
        if (SUCCEEDED(hr)) {
            hr = mgr->ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR, MAKELANGID(LANG_KOREAN, SUBLANG_KOREAN), kClsid,
                                      kProfile, nullptr, TF_IPPMF_FORSESSION | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE);
            mgr->Release();
        }
        std::printf("activate for session: %#lx\n", hr);
        CoUninitialize();
        return FAILED(hr);
    }
    // --rich: a TSF-aware RichEdit instead of the classic EDIT control (IMM bridge).
    bool rich = false;
    if (argc > 1 && std::string(argv[1]) == "--sendinput") {
        g_sendInput = true;
        --argc;
        ++argv;
    }
    if (argc > 1 && std::string(argv[1]) == "--ms") {
        g_ms = true;
        --argc;
        ++argv;
    }
    if (argc > 2 && std::string(argv[1]) == "--snap") {
        g_snap = argv[2];
        argc -= 2;
        argv += 2;
    }
    if (argc > 1 && std::string(argv[1]) == "--imm") {
        g_imm = true;
        --argc;
        ++argv;
    }
    if (argc > 1 && std::string(argv[1]) == "--rich") {
        rich = true;
        --argc;
        ++argv;
    }
    SetConsoleOutputCP(CP_UTF8);
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    WNDCLASSW wc{};
    wc.lpfnWndProc = wndProc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"MaimusiHarness";
    RegisterClassW(&wc);
    g_main = CreateWindowW(L"MaimusiHarness", L"Maimusi TSF harness", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 100, 100, 700,
                           300, nullptr, nullptr, wc.hInstance, nullptr);
    if (rich) LoadLibraryW(L"msftedit.dll");
    WNDCLASSW iwc{};
    iwc.lpfnWndProc = immProc;
    iwc.hInstance = wc.hInstance;
    iwc.lpszClassName = L"MaimusiImmView";
    RegisterClassW(&iwc);
    g_edit = CreateWindowW(g_imm ? L"MaimusiImmView" : rich ? L"RICHEDIT50W" : L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL,
                           0, 0, 700, 300, g_main, nullptr, wc.hInstance, nullptr);
    if (rich) SendMessageW(g_edit, WM_USER + 204 /* EM_SETEDITSTYLE */, 0x00010000 /* SES_USECTF */, 0x00010000);
    HFONT font = CreateFontW(-24, 0, 0, 0, 0, 0, 0, 0, DEFAULT_CHARSET, 0, 0, 0, 0, L"Malgun Gothic");
    SendMessageW(g_edit, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
    if (g_sendInput) SetForegroundWindow(g_main);
    SetFocus(g_edit);
    pump(300);
    if (!activate()) return 2;
    pump(500);
    int failed = 0;
    if (argc > 2 && std::string(argv[1]) == "--keys") {
        // Ad hoc: type the given keys and print the text.
        if (g_sendInput) SetForegroundWindow(g_main);
        SetFocus(g_edit);
        typeKeys(argv[2]);
        std::printf("text [%s]\n", utf8(text()).c_str());
        DestroyWindow(g_main);
        return 0;
    }
    for (const Scenario &s : kScenarios) {
        if (argc > 1 && std::string(argv[1]) != s.name) continue;
        if (g_sendInput) SetForegroundWindow(g_main);
        SetFocus(g_edit);
        SetWindowTextW(g_edit, L"");
        g_committed.clear();
        g_comp.clear();
        pump(100);
        typeKeys(s.keys);
        std::wstring got = text();
        // Leave Hangul mode on for the next scenario.
        bool ok = got == s.expected;
        failed += !ok;
        std::printf("%s %-20s got [%s] expected [%s]\n", ok ? "PASS" : "FAIL", s.name, utf8(got).c_str(),
                    utf8(s.expected).c_str());
    }
    DestroyWindow(g_main);
    CoUninitialize();
    return failed ? 1 : 0;
}
