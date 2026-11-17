// MaimusiSettings.exe: the settings window (macos/Sources/PreferencesWindow.swift),
// and the per-user steps of installation:
//   --register-user          add 매무시 to the user's input methods (Korean language)
//   --unregister-user        remove it from the user's input methods
//   --test-wordbook [folder] wordbook self-test on a settings file of its own
//   --render-candidates DIR  pictures of every candidate window preset (PNG)
// Changes are saved immediately; running input methods pick them up within a second.
#include <windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <shobjidl.h>
#include <windowsx.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

#include "../common/candidateview.h"
#include "../common/enginepipe.h"
#include "../common/graphics.h"
#include "../common/settings.h"
#include "../common/text.h"
#include "../common/wordbook.h"
#include "product.h"

using namespace maimusi;

namespace {

const wchar_t kTip[] = L"0412:{1A36DDCD-E1AE-4B54-AAF1-EF5418F4B25B}{3BE0990F-7425-4407-81CB-4C4C3CEC4A50}";
// The spacing rules example: auxiliary verbs, a compound noun and a number with its unit.
const wchar_t kSample[] = L"국어사전을펴놓고사과10개를먹어보았다";

enum : int {
    kEngineKiwi = 100, kEngineLight, kIdle, kConvertOnSpace, kSpaceInConversion, kEnterPasses, kImplicit,
    kCandidates, kRightAlt, kCandidatePreset, kCandidateSize, kCandidatePreview, kPresentation, kForms, kGloss,
    kConsonants, kAux, kCompound, kNumberUnits,
    kPreviewEdit, kPreviewResult, kWordEdit, kWordAdd, kWordList, kWordRemove, kRemember, kLearnedList,
    kLearnedRemove, kLearnedCount, kForget, kExport, kImport, kSyncFolderText, kSyncChoose, kSyncNow, kSyncStop,
    kPrivacyOpen, kLicenses, kLink,
};
// Texts in the secondary color: changing ones from kSecondaryBase, fixed notes from kNoteBase.
constexpr int kSecondaryBase = 800, kNoteBase = 900;
enum : int { kWordbookMessage = kSecondaryBase, kSyncStatus, kPreviewNote, kCandidateSummary, kPrivacyStored, kPrivacyOut };

enum : UINT_PTR { kTimerReload = 1, kTimerPreview, kTimerSync };
constexpr UINT kPreviewDone = WM_APP + 1;  // wParam: request number, lParam: std::wstring* or null
constexpr UINT kSyncDone = WM_APP + 2;

struct Choice {
    const char *value;
    const wchar_t *label;
};

const Choice kRuleModes[] = {{"separate", L"띄어 쓰기"}, {"join", L"허용 범위에서 붙이기"}, {"model", L"모델 판단"}};
const Choice kSpaceModes[] = {{"cycle", L"선택 어절의 다음 후보"}, {"commit", L"확정하고 공백 입력"}};
const Choice kPresentations[] = {{"hanja", L"한자 — 學校"},
                                 {"hangul_hanja", L"한글(한자) — 학교(學校)"},
                                 {"hanja_hangul", L"한자(한글) — 學校(학교)"},
                                 {"hangulhanja", L"한글한자 — 학교學校"}};
const Choice kFormChoices[] = {{"education", L"교육용 한자 규범 자형 (強·豐·祕)"}, {"ks", L"KS X 1001 자형 (强·豊·秘)"}};
const int kIdleMinutes[] = {10, 20, 60, 0};
const wchar_t *const kIdleLabels[] = {L"10분 후", L"20분 후", L"60분 후", L"종료하지 않음"};

struct ComboBinding {
    int id;
    const char *key;
    const Choice *choices;
    int count;
    bool rule;  // a spacing rule: the example is spaced again
};

const ComboBinding kCombos[] = {
    {kSpaceInConversion, "spaceInConversion", kSpaceModes, 2, false},
    {kPresentation, "hanjaPresentation", kPresentations, 4, false},
    {kForms, "hanjaForms", kFormChoices, 2, false},
    {kAux, "rule.auxiliaries", kRuleModes, 3, true},
    {kCompound, "rule.compound", kRuleModes, 3, true},
    {kNumberUnits, "rule.number_units", kRuleModes, 3, true},
};

struct CheckBinding {
    int id;
    const char *key;
};

const CheckBinding kChecks[] = {
    {kConvertOnSpace, "convertOnSpace"}, {kEnterPasses, "enterPassesThrough"}, {kImplicit, "spaceImplicitCommits"},
    {kCandidates, "candidatesEnabled"}, {kRightAlt, "rightAltToggles"}, {kConsonants, "symbolConsonants"},
    {kGloss, "hanjaGlossSearch"}, {kRemember, "rememberBoundaries"},
};

HWND g_window = nullptr;
HFONT g_font = nullptr, g_bold = nullptr, g_small = nullptr;
int g_dpi = 96;
Settings g_settings;
unsigned long long g_stamp = 0;
bool g_kiwi = false, g_light = false;
std::wstring g_dir;
std::vector<LearnedBoundary> g_learnedShown;  // list order (latest first)
std::atomic<int> g_previewRequest{0};
bool g_previewShown = false;
std::atomic<bool> g_syncing{false};

int S(int v) { return MulDiv(v, g_dpi, 96); }

bool fileExists(const std::wstring &p) {
    DWORD a = GetFileAttributesW(p.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

HWND add(const wchar_t *cls, const std::wstring &text, DWORD style, int id, int x, int y, int w, int h,
         HFONT font = nullptr) {
    HWND c = CreateWindowExW(0, cls, text.c_str(), WS_CHILD | WS_VISIBLE | style, S(x), S(y), S(w), S(h), g_window,
                             reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), GetModuleHandleW(nullptr), nullptr);
    SendMessageW(c, WM_SETFONT, reinterpret_cast<WPARAM>(font ? font : g_font), TRUE);
    return c;
}

// Layout (DIPs): a header, then two columns of white cards on the Windows 11
// window surface. Controls sit inside the cards; card titles and the header
// are drawn with Direct2D/DirectWrite in WM_PAINT. The window scrolls when
// the cards are taller than the screen.
constexpr int kMargin = 24, kCardW = 392, kGap = 16, kInset = 18, kHeaderH = 92;
constexpr int kColumnX[2] = {kMargin + kInset, kMargin + kCardW + kGap + kInset};
constexpr int kContentW = kCardW - 2 * kInset;

struct Card {
    int x, y, w, h;
    std::wstring title;
};
std::vector<Card> g_cards;
int g_open[2] = {-1, -1};  // open card per column
int g_nextNote = kNoteBase;
int g_scroll = 0, g_contentH = 0, g_viewH = 0;  // pixels

int column(int x) { return x < kColumnX[1] ? 0 : 1; }

void closeCard(int x, int &y) {
    int c = column(x);
    if (g_open[c] < 0) return;
    Card &card = g_cards[g_open[c]];
    card.h = y + 10 - card.y;
    y = card.y + card.h + kGap;
    g_open[c] = -1;
}

// Starts a card titled `text` in the column of x (closing the previous one).
void heading(const std::wstring &text, int x, int &y) {
    closeCard(x, y);
    g_cards.push_back({x - kInset, y, kCardW, 0, text});
    g_open[column(x)] = static_cast<int>(g_cards.size()) - 1;
    y += 46;
}

// Height in DIPs of `text` wrapped to `width` DIPs in `font`.
int textHeight(const std::wstring &text, HFONT font, int width) {
    HDC dc = GetDC(g_window);
    HGDIOBJ old = SelectObject(dc, font);
    RECT rc{0, 0, S(width), 0};
    DrawTextW(dc, text.c_str(), static_cast<int>(text.size()), &rc, DT_CALCRECT | DT_WORDBREAK | DT_NOPREFIX);
    SelectObject(dc, old);
    ReleaseDC(g_window, dc);
    return MulDiv(rc.bottom, 96, g_dpi);
}

void note(const std::wstring &text, int x, int &y, int id = 0) {
    int h = textHeight(text, g_small, kContentW);
    add(L"STATIC", text, SS_NOPREFIX, id ? id : g_nextNote++, x, y, kContentW, h + 2, g_small);
    y += h + 8;
}

void check(int id, const std::wstring &text, int x, int &y) {
    add(L"BUTTON", text, BS_AUTOCHECKBOX | WS_TABSTOP, id, x, y, kContentW, 24);
    y += 28;
}

void combo(int id, const std::wstring &label, int x, int &y) {
    add(L"STATIC", label, SS_CENTERIMAGE, -1, x, y, 150, 26);
    add(WC_COMBOBOXW, L"", CBS_DROPDOWNLIST | WS_TABSTOP | WS_VSCROLL, id, x + 150, y, kContentW - 150, 240);
    y += 34;
}

void button(int id, const std::wstring &text, int x, int y, int w) {
    add(L"BUTTON", text, BS_PUSHBUTTON | WS_TABSTOP, id, x, y, w, 26);
}

void fillCombo(int id, const Choice *choices, int count) {
    HWND c = GetDlgItem(g_window, id);
    for (int i = 0; i < count; ++i) ComboBox_AddString(c, choices[i].label);
}

std::wstring localTime(double seconds) {
    unsigned long long t = static_cast<unsigned long long>(seconds) * 10000000ull + 116444736000000000ull;
    FILETIME ft{static_cast<DWORD>(t), static_cast<DWORD>(t >> 32)};
    SYSTEMTIME utc{}, local{};
    FileTimeToSystemTime(&ft, &utc);
    SystemTimeToTzSpecificLocalTime(nullptr, &utc, &local);
    wchar_t date[64] = L"", time[64] = L"";
    GetDateFormatEx(LOCALE_NAME_USER_DEFAULT, DATE_SHORTDATE, &local, nullptr, date, 64, nullptr);
    GetTimeFormatEx(LOCALE_NAME_USER_DEFAULT, TIME_NOSECONDS, &local, nullptr, time, 64);
    return std::wstring(date) + L" " + time;
}

void updateSyncControls() {
    std::wstring folder = widen(g_settings.getString("syncFolder"));
    std::wstring shown = L"폴더를 고르지 않았습니다";
    if (!folder.empty()) {
        wchar_t compact[MAX_PATH] = L"";
        PathCompactPathExW(compact, folder.c_str(), 52, 0);
        shown = std::wstring(L"폴더: ") + compact;
    }
    SetDlgItemTextW(g_window, kSyncFolderText, shown.c_str());
    std::wstring status = L"꺼져 있음";
    if (!folder.empty()) {
        std::string error = g_settings.getString("syncError");
        double last = g_settings.getNumber("syncLast");
        status = g_syncing ? L"맞추는 중…"
                 : !error.empty() ? L"맞추지 못했습니다: " + widen(error)
                 : last <= 0      ? L"아직 맞추지 않았습니다"
                                  : L"마지막으로 맞춘 때: " + localTime(last);
    }
    SetDlgItemTextW(g_window, kSyncStatus, status.c_str());
    SetDlgItemTextW(g_window, kSyncChoose, folder.empty() ? L"폴더 고르기…" : L"바꾸기…");
    EnableWindow(GetDlgItem(g_window, kSyncNow), !folder.empty() && !g_syncing);
    EnableWindow(GetDlgItem(g_window, kSyncStop), !folder.empty());
}

void loadControls() {
    for (const CheckBinding &b : kChecks) Button_SetCheck(GetDlgItem(g_window, b.id), g_settings.getBool(b.key));
    for (const ComboBinding &b : kCombos) {
        std::string v = g_settings.getString(b.key);
        int sel = 0;
        for (int i = 0; i < b.count; ++i)
            if (v == b.choices[i].value) sel = i;
        ComboBox_SetCurSel(GetDlgItem(g_window, b.id), sel);
    }
    int idle = g_settings.getInt("idleUnloadMinutes"), idleSel = 1;
    for (int i = 0; i < 4; ++i)
        if (kIdleMinutes[i] == idle) idleSel = i;
    ComboBox_SetCurSel(GetDlgItem(g_window, kIdle), idleSel);
    bool kiwi = g_settings.engine() == "kiwi" || !g_light;
    if (HWND r = GetDlgItem(g_window, kEngineKiwi)) Button_SetCheck(r, kiwi);
    if (HWND r = GetDlgItem(g_window, kEngineLight)) Button_SetCheck(r, !kiwi);
    EnableWindow(GetDlgItem(g_window, kIdle), g_kiwi && kiwi);
    bool candidates = g_settings.getBool("candidatesEnabled");
    for (int id : {kPresentation, kForms, kGloss, kConsonants}) EnableWindow(GetDlgItem(g_window, id), candidates);
    std::string presetId = cand::presetId(g_settings);
    const auto &presets = cand::presets();
    for (size_t i = 0; i < presets.size(); ++i)
        if (presetId == presets[i].id) {
            ComboBox_SetCurSel(GetDlgItem(g_window, kCandidatePreset), static_cast<int>(i));
            SetDlgItemTextW(g_window, kCandidateSummary, presets[i].summary);
        }
    std::string size = g_settings.getString("candidateTextSize");
    for (int i = 0; i < 3; ++i)
        if (size == cand::kTextScales[i].id) ComboBox_SetCurSel(GetDlgItem(g_window, kCandidateSize), i);
    InvalidateRect(GetDlgItem(g_window, kCandidatePreview), nullptr, FALSE);

    HWND list = GetDlgItem(g_window, kWordList);
    ListBox_ResetContent(list);
    std::vector<std::string> words = g_settings.userWords();
    for (auto it = words.rbegin(); it != words.rend(); ++it) ListBox_AddString(list, widen(*it).c_str());

    HWND learnedList = GetDlgItem(g_window, kLearnedList);
    int top = ListBox_GetTopIndex(learnedList);
    ListBox_ResetContent(learnedList);
    std::vector<LearnedBoundary> learned = g_settings.learned();
    g_learnedShown.assign(learned.rbegin(), learned.rend());
    for (const auto &c : g_learnedShown) ListBox_AddString(learnedList, widen(c.spaced).c_str());
    ListBox_SetTopIndex(learnedList, top);
    SetDlgItemTextW(g_window, kLearnedCount, (L"기억한 띄어쓰기 " + std::to_wstring(learned.size()) + L"개").c_str());
    EnableWindow(GetDlgItem(g_window, kForget), !learned.empty());

    SetDlgItemTextW(g_window, kPrivacyStored, (L"설정, 단어 " + std::to_wstring(words.size()) + L"개, 기억한 띄어쓰기 " +
                                               std::to_wstring(learned.size()) + L"개")
                                                  .c_str());
    SetDlgItemTextW(g_window, kPrivacyOut, g_settings.getString("syncFolder").empty() ? L"없음" : L"단어장 맞추기: 고른 폴더");
    updateSyncControls();
}

void reload() {
    g_settings.load();
    g_stamp = Settings::fileStamp();
    loadControls();
}

// The wordbook changed in this window: sync it with the other devices three seconds later.
void scheduleSync() {
    if (!g_settings.getString("syncFolder").empty()) SetTimer(g_window, kTimerSync, 3000, nullptr);
}

void startSync() {
    KillTimer(g_window, kTimerSync);
    if (g_settings.getString("syncFolder").empty() || g_syncing.exchange(true)) return;
    updateSyncControls();
    std::thread([] {
        wordbook::syncNow();
        PostMessageW(g_window, kSyncDone, 0, 0);
    }).detach();
}

template <class F> void change(F edit) {
    g_settings.update(edit);
    g_stamp = Settings::fileStamp();
    loadControls();
}

void addWord() {
    wchar_t buf[256];
    GetDlgItemTextW(g_window, kWordEdit, buf, 256);
    std::string word = narrow(buf);
    bool added = false;
    change([&](Settings &s) { added = s.addWords({word}); });
    if (added) {
        SetDlgItemTextW(g_window, kWordEdit, L"");
        scheduleSync();
    }
}

// MARK: Candidate window preview

// Behind the preview: a soft wash, so translucent looks (유리) read as such.
void drawStage(ID2D1RenderTarget *rt, D2D1_RECT_F r, bool dark) {
    ID2D1GradientStopCollection *stops = nullptr;
    D2D1_GRADIENT_STOP light[] = {{0, D2D1::ColorF(0xDCE6F2)}, {0.55f, D2D1::ColorF(0xEEF0F4)}, {1, D2D1::ColorF(0xF4EBDD)}};
    D2D1_GRADIENT_STOP night[] = {{0, D2D1::ColorF(0x1D2533)}, {0.55f, D2D1::ColorF(0x23252B)}, {1, D2D1::ColorF(0x2E2720)}};
    ID2D1LinearGradientBrush *wash = nullptr;
    if (SUCCEEDED(rt->CreateGradientStopCollection(dark ? night : light, 3, &stops)) &&
        SUCCEEDED(rt->CreateLinearGradientBrush(D2D1::LinearGradientBrushProperties(D2D1::Point2F(r.left, r.top),
                                                                                    D2D1::Point2F(r.right, r.bottom)),
                                                stops, &wash)))
        rt->FillRoundedRectangle(D2D1::RoundedRect(r, 8, 8), wash);
    if (wash) wash->Release();
    if (stops) stops->Release();
}

// Preview height: the tallest preset at the chosen text size.
int previewHeight() {
    float size = 0;
    float factor = 1;
    std::string id = g_settings.getString("candidateTextSize");
    for (const auto &s : cand::kTextScales)
        if (id == s.id) factor = s.factor;
    gfx::Theme system = gfx::theme();
    for (const auto &p : cand::presets()) {
        cand::View view;
        view.layout(p.theme.scaled(factor), cand::Content::sample(), false, system.accent);
        size = std::max(size, view.size().height);
    }
    return static_cast<int>(std::ceil(size)) + 8;
}

void drawPreview(HDC dc, const RECT &rc) {
    ID2D1DCRenderTarget *rt = nullptr;
    auto props = D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_DEFAULT,
                                              D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_IGNORE),
                                              static_cast<float>(g_dpi), static_cast<float>(g_dpi));
    if (!gfx::d2d() || FAILED(gfx::d2d()->CreateDCRenderTarget(&props, &rt))) return;
    if (SUCCEEDED(rt->BindDC(dc, &rc))) {
        float w = (rc.right - rc.left) * 96.f / g_dpi, h = (rc.bottom - rc.top) * 96.f / g_dpi;
        cand::View view;
        view.layout(cand::current(g_settings), cand::Content::sample(), false, gfx::theme().accent);
        rt->BeginDraw();
        rt->Clear(D2D1::ColorF(0xFFFFFF));
        drawStage(rt, D2D1::RectF(0, 0, w, h), false);
        D2D1_SIZE_F size = view.size();
        rt->SetTransform(D2D1::Matrix3x2F::Translation(std::floor((w - size.width) / 2), 4.f));
        view.draw(rt, -1);
        rt->EndDraw();
    }
    rt->Release();
}

// --render-candidates DIR: every preset on a light and a dark wash, as PNG files.
int renderCandidates(const std::wstring &dir) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    CreateDirectoryW(dir.c_str(), nullptr);
    IWICImagingFactory *wic = gfx::wic();
    if (!wic || !gfx::d2d()) return 1;
    int failures = 0;
    gfx::Theme system = gfx::theme();
    for (const auto &preset : cand::presets()) {
        for (bool dark : {false, true}) {
            cand::View view;
            view.layout(preset.theme, cand::Content::sample(), dark, system.accent);
            D2D1_SIZE_F size = view.size();
            const float pad = 12, scale = 1.5f;  // 144 DPI pictures
            UINT w = static_cast<UINT>(std::ceil((size.width + 2 * pad) * scale)),
                 h = static_cast<UINT>(std::ceil((size.height + 2 * pad) * scale));
            IWICBitmap *bitmap = nullptr;
            ID2D1RenderTarget *rt = nullptr;
            bool ok = SUCCEEDED(wic->CreateBitmap(w, h, GUID_WICPixelFormat32bppPBGRA, WICBitmapCacheOnLoad, &bitmap)) &&
                      SUCCEEDED(gfx::d2d()->CreateWicBitmapRenderTarget(
                          bitmap,
                          D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_DEFAULT,
                                                       D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED),
                                                       96 * scale, 96 * scale),
                          &rt));
            if (ok) {
                rt->BeginDraw();
                rt->Clear(D2D1::ColorF(dark ? 0x202020 : 0xFFFFFF));
                drawStage(rt, D2D1::RectF(0, 0, size.width + 2 * pad, size.height + 2 * pad), dark);
                rt->SetTransform(D2D1::Matrix3x2F::Translation(pad, pad));
                view.draw(rt, -1);
                ok = SUCCEEDED(rt->EndDraw());
            }
            std::wstring file = dir + L"\\" + widen(preset.id) + (dark ? L"-dark.png" : L"-light.png");
            IWICStream *stream = nullptr;
            IWICBitmapEncoder *encoder = nullptr;
            IWICBitmapFrameEncode *frame = nullptr;
            ok = ok && SUCCEEDED(wic->CreateStream(&stream)) &&
                 SUCCEEDED(stream->InitializeFromFilename(file.c_str(), GENERIC_WRITE)) &&
                 SUCCEEDED(wic->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder)) &&
                 SUCCEEDED(encoder->Initialize(stream, WICBitmapEncoderNoCache)) &&
                 SUCCEEDED(encoder->CreateNewFrame(&frame, nullptr)) && SUCCEEDED(frame->Initialize(nullptr)) &&
                 SUCCEEDED(frame->WriteSource(bitmap, nullptr)) && SUCCEEDED(frame->Commit()) && SUCCEEDED(encoder->Commit());
            for (IUnknown *u : {static_cast<IUnknown *>(frame), static_cast<IUnknown *>(encoder),
                                static_cast<IUnknown *>(stream), static_cast<IUnknown *>(rt), static_cast<IUnknown *>(bitmap)})
                if (u) u->Release();
            if (!ok) ++failures;
        }
    }
    return failures ? 1 : 0;
}

// Text size changes the preview's height and so the layout: build the window again.
void rebuild();

// MARK: Spacing example

// Starts the user's engine server (the input method would start it on the first Space anyway).
void startEngine(const std::wstring &exe, const std::wstring &pipe, const std::wstring &mutex, int idle) {
    std::wstring dir = exe.substr(0, exe.find_last_of(L'\\'));
    std::wstring cmd = L"\"" + exe + L"\" --pipe \"" + pipe + L"\" --mutex \"" + mutex + L"\" --idle-minutes " +
                       std::to_wstring(std::max(0, idle));
    STARTUPINFOW si{sizeof si};
    PROCESS_INFORMATION pi{};
    DWORD flags = CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | CREATE_BREAKAWAY_FROM_JOB;
    BOOL ok = CreateProcessW(exe.c_str(), cmd.data(), nullptr, nullptr, FALSE, flags, nullptr, dir.c_str(), &si, &pi);
    if (!ok && GetLastError() == ERROR_ACCESS_DENIED)
        ok = CreateProcessW(exe.c_str(), cmd.data(), nullptr, nullptr, FALSE, flags & ~CREATE_BREAKAWAY_FROM_JOB, nullptr,
                            dir.c_str(), &si, &pi);
    if (ok) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
}

void schedulePreview() { SetTimer(g_window, kTimerPreview, 250, nullptr); }

// Spaces the example with the rules as they are now (`spacing` of the
// `space` request, used for this request only), on a thread of its own.
void startPreview() {
    KillTimer(g_window, kTimerPreview);
    wchar_t buf[512];
    GetDlgItemTextW(g_window, kPreviewEdit, buf, 512);
    std::wstring text = buf;
    if (text.find_first_not_of(L" \t") == std::wstring::npos) text = kSample;
    int request = ++g_previewRequest;
    if (!g_kiwi) {
        SetDlgItemTextW(g_window, kPreviewResult, L"이 설치본에는 찰떡 엔진이 없습니다");
        return;
    }
    if (!g_previewShown) SetDlgItemTextW(g_window, kPreviewResult, L"찰떡 엔진이 준비되면 결과가 보입니다");
    Json rules = g_settings.spacingRules();
    std::string utf8 = narrow(text);
    std::wstring exe = g_dir + L"engine\\MaimusiEngine.exe";
    int idle = g_settings.getInt("idleUnloadMinutes");
    std::thread([request, rules, utf8, exe, idle] {
        std::wstring sid = currentUserSid();
        std::wstring pipe = L"\\\\.\\pipe\\Maimusi.Engine." + sid, mutex = L"Local\\Maimusi.Engine." + sid;
        PipeConnection conn;
        bool open = conn.open(pipe);
        if (!open) {
            if (HANDLE m = OpenMutexW(SYNCHRONIZE, FALSE, mutex.c_str())) {
                CloseHandle(m);  // already starting
            } else {
                startEngine(exe, pipe, mutex, idle);
            }
            for (int i = 0; i < 300 && !open && request == g_previewRequest; ++i) {
                Sleep(100);
                open = conn.open(pipe);
            }
        }
        std::wstring *result = nullptr;
        if (open && request == g_previewRequest) {
            Json req = Json::object();
            req.set("op", "space");
            req.set("text", utf8);
            req.set("spacing", rules);
            Json reply;
            if (conn.request(std::move(req), 5000, reply) && reply["text"].isString())
                result = new std::wstring(widen(reply["text"].asString()));
        }
        if (!PostMessageW(g_window, kPreviewDone, static_cast<WPARAM>(request), reinterpret_cast<LPARAM>(result)))
            delete result;
    }).detach();
}

// MARK: Wordbook files and the sync folder

void showWordbookMessage(const std::wstring &text) { SetDlgItemTextW(g_window, kWordbookMessage, text.c_str()); }

const COMDLG_FILTERSPEC kJsonTypes[] = {{L"매무시 단어장 (*.json)", L"*.json"}};

std::wstring pickFile(bool save) {
    IFileDialog *dialog = nullptr;
    std::wstring path;
    if (FAILED(CoCreateInstance(save ? CLSID_FileSaveDialog : CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&dialog))))
        return path;
    DWORD options = 0;
    dialog->GetOptions(&options);
    dialog->SetOptions(options | FOS_FORCEFILESYSTEM | (save ? FOS_OVERWRITEPROMPT : FOS_FILEMUSTEXIST));
    dialog->SetFileTypes(1, kJsonTypes);
    dialog->SetDefaultExtension(L"json");
    if (save) dialog->SetFileName(L"매무시 단어장.json");
    IShellItem *item = nullptr;
    PWSTR name = nullptr;
    if (dialog->Show(g_window) == S_OK && SUCCEEDED(dialog->GetResult(&item)) &&
        SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &name))) {
        path = name;
        CoTaskMemFree(name);
    }
    if (item) item->Release();
    dialog->Release();
    return path;
}

void exportWordbook() {
    std::wstring file = pickFile(true);
    if (file.empty()) return;
    if (wordbook::exportTo(file)) {
        showWordbookMessage(L"단어 " + std::to_wstring(g_settings.userWords().size()) + L"개, 띄어쓰기 " +
                            std::to_wstring(g_settings.learned().size()) + L"개를 내보냈습니다.");
    } else {
        showWordbookMessage(L"내보내지 못했습니다.");
    }
}

void importWordbook() {
    std::wstring file = pickFile(false);
    if (file.empty()) return;
    int words = 0, boundaries = 0;
    if (!wordbook::importFrom(file, words, boundaries)) {
        showWordbookMessage(L"매무시 단어장 파일이 아닙니다.");
        return;
    }
    reload();
    showWordbookMessage(L"단어 " + std::to_wstring(words) + L"개, 띄어쓰기 " + std::to_wstring(boundaries) + L"개를 더했습니다.");
    if (words || boundaries) scheduleSync();
}

void chooseSyncFolder() {
    IFileOpenDialog *dialog = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dialog)))) return;
    DWORD options = 0;
    dialog->GetOptions(&options);
    dialog->SetOptions(options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
    dialog->SetTitle(L"고른 폴더 안의 ‘Maimusi’ 폴더에 단어장 파일을 둡니다");
    dialog->SetOkButtonLabel(L"이 폴더로 맞추기");
    IShellItem *item = nullptr;
    PWSTR name = nullptr;
    std::string folder;
    if (dialog->Show(g_window) == S_OK && SUCCEEDED(dialog->GetResult(&item)) &&
        SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &name))) {
        folder = narrow(name);
        CoTaskMemFree(name);
    }
    if (item) item->Release();
    dialog->Release();
    if (folder.empty()) return;
    change([&](Settings &s) {
        s.set("syncFolder", folder);
        s.set("syncLast", 0);
        s.set("syncError", "");
    });
    startSync();
}

void stopSync() {
    KillTimer(g_window, kTimerSync);
    change([](Settings &s) {
        s.set("syncFolder", "");
        s.set("syncError", "");
    });
}

void showSettingsFile() {
    std::wstring file = Settings::path();
    std::wstring args = L"/select,\"" + file + L"\"";
    if (fileExists(file)) {
        ShellExecuteW(g_window, L"open", L"explorer.exe", args.c_str(), nullptr, SW_SHOWNORMAL);
    } else {
        std::wstring dir = file.substr(0, file.find_last_of(L'\\'));
        CreateDirectoryW(dir.c_str(), nullptr);
        ShellExecuteW(g_window, L"open", dir.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
    }
}

// MARK: Layout

void build() {
    int x = kColumnX[0], y = kHeaderH;
    heading(L"띄어쓰기 엔진", x, y);
    if (g_kiwi && g_light) {
        add(L"BUTTON", MAIMUSI_ENGINE_KO L" (고정확도, Kiwi 기반)", BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP, kEngineKiwi,
            x, y, kContentW, 24);
        y += 28;
        add(L"BUTTON", L"경량 (내장)", BS_AUTORADIOBUTTON, kEngineLight, x, y, kContentW, 24);
        y += 32;
    }
    std::wstring e = MAIMUSI_ENGINE_KO;
    note(!g_light ? e + L" 엔진은 Kiwi 형태소 분석기를 바탕으로 띄어씁니다. 실행 중에는 메모리를 600MB 정도 "
                         L"사용하며, 일정 시간 쓰지 않으면 자동으로 종료됩니다."
         : g_kiwi ? e + L" 엔진은 정확도가 높지만 실행 중 메모리를 600MB 이상 씁니다. 준비되기 전이나 응답이 "
                         L"늦으면 경량 엔진이 대신 처리합니다."
                  : std::wstring(L"이 설치본에는 찰떡 엔진이 없어 경량 엔진만 사용합니다."),
         x, y);
    combo(kIdle, L"쓰지 않을 때 엔진 종료", x, y);
    for (const wchar_t *l : kIdleLabels) ComboBox_AddString(GetDlgItem(g_window, kIdle), l);

    heading(L"키 동작", x, y);
    check(kConvertOnSpace, L"스페이스로 자동 띄어쓰기", x, y);
    combo(kSpaceInConversion, L"변환 중 스페이스", x, y);
    check(kEnterPasses, L"조합 중 Enter는 확정 후 줄바꿈·전송까지", x, y);
    check(kImplicit, L"방향키·Tab·클릭으로 확정할 때도 띄어쓰기", x, y);
    check(kCandidates, L"↑↓ 후보 (한자·기호·이모지·단위·날짜)", x, y);
    check(kRightAlt, L"오른쪽 Alt로도 한/영 전환", x, y);
    note(L"한/영 키로 한글과 영문을 바꿉니다. 한/영 키가 없는 키보드에서는 오른쪽 Alt를 쓸 수 있습니다.", x, y);

    heading(L"후보 창", x, y);
    combo(kCandidatePreset, L"모양", x, y);
    for (const auto &preset : cand::presets())
        ComboBox_AddString(GetDlgItem(g_window, kCandidatePreset), preset.name);
    // The chosen preset's description, as tall as the longest one.
    int summaryH = 0;
    for (const auto &preset : cand::presets()) summaryH = std::max(summaryH, textHeight(preset.summary, g_small, kContentW));
    add(L"STATIC", L"", SS_NOPREFIX, kCandidateSummary, x, y, kContentW, summaryH + 2, g_small);
    y += summaryH + 8;
    combo(kCandidateSize, L"글자 크기", x, y);
    for (const auto &scale : cand::kTextScales) ComboBox_AddString(GetDlgItem(g_window, kCandidateSize), scale.name);
    int previewH = previewHeight();
    add(L"STATIC", L"", SS_OWNERDRAW, kCandidatePreview, x, y, kContentW, previewH);
    y += previewH + 8;
    note(L"macOS 판과 같은 모양입니다. Windows에서는 「유리」가 뒤 화면을 흐리게 비추지 않고 밝은 반투명 바탕으로 "
         L"보이며, 글꼴은 맑은 고딕(한지는 바탕)을 씁니다.",
         x, y);

    heading(L"한자 변환", x, y);
    combo(kPresentation, L"변환 표기", x, y);
    combo(kForms, L"한자 자형", x, y);
    note(L"고른 자형만 후보에 나옵니다. 교육용 자형 𮕩(衰)는 맞는 글꼴이 드물어 KS 자형 衰도 함께 나옵니다.", x, y);
    check(kGloss, L"훈음으로 한자 찾기 (살찔비 → 肥)", x, y);
    note(L"뜻과 소리를 붙여 입력하고 Space를 누르면 그 한자가 후보 맨 앞에 나옵니다. 배울학학교교처럼 이어 쓰면 "
         L"學校. 켜 두면 이런 입력은 띄어 쓰지 않습니다.",
         x, y);
    heading(L"기호 변환", x, y);
    note(L"/ → ·, [ ] → 다른 괄호, 알파 → α처럼 변환 후보에서 선택합니다. ‘괄호’로 괄호 쌍도 찾을 수 있습니다.", x, y);
    check(kConsonants, L"자음으로도 특수문자 목록 열기 (ㅁ·ㄷ·ㅎ 등)", x, y);

    heading(L"사용자 단어 (" + e + L" 엔진)", x, y);
    HWND edit = add(WC_EDITW, L"", WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP, kWordEdit, x, y, kContentW - 76, 26);
    SendMessageW(edit, EM_SETCUEBANNER, TRUE, reinterpret_cast<LPARAM>(L"예: 찰떡엔진"));
    button(kWordAdd, L"추가", x + kContentW - 68, y, 68);
    y += 32;
    add(WC_LISTBOXW, L"", WS_BORDER | WS_VSCROLL | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT | WS_TABSTOP, kWordList, x, y,
        kContentW - 76, 104);
    button(kWordRemove, L"지우기", x + kContentW - 68, y, 68);
    y += 112;
    note(L"등록한 단어 안에는 띄어쓰기를 넣지 않습니다. 단어 뒤에 붙는 조사는 그대로 붙여 씁니다.", x, y);
    closeCard(x, y);
    int leftBottom = y;

    x = kColumnX[1], y = kHeaderH;
    heading(L"띄어쓰기 규칙 (" + e + L" 엔진)", x, y);
    combo(kAux, L"보조 용언 (먹어 보다)", x, y);
    combo(kCompound, L"복합명사 (국어 사전)", x, y);
    combo(kNumberUnits, L"숫자 + 단위 (10 개)", x, y);
    note(L"Shift+Space는 일반 두벌식처럼 친 그대로 확정하고 띄웁니다. 자동 띄어쓰기를 잠시 쓰지 않을 때.", x, y);
    HWND sample = add(WC_EDITW, kSample, WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP, kPreviewEdit, x, y, kContentW, 26);
    SendMessageW(sample, EM_SETCUEBANNER, TRUE, reinterpret_cast<LPARAM>(kSample));
    SendMessageW(sample, EM_SETLIMITTEXT, 500, 0);
    y += 32;
    add(L"STATIC", L"", SS_NOPREFIX | SS_ENDELLIPSIS, kPreviewResult, x, y, kContentW, 24);
    y += 28;
    note(L"규칙을 바꾸면 위 문장이 어떻게 띄어지는지 바로 보입니다. 다른 문장을 넣어 볼 수도 있습니다.", x, y);

    heading(L"경계 기억", x, y);
    check(kRemember, L"직접 고친 경계 기억하기", x, y);
    note(L"변환 중에 경계를 직접 고쳐 확정하면 한 번에 기억해 다음부터 같은 표현을 그렇게 띄어 씁니다. 합친 어절에서는 "
         L"조사를 뗀 단어를 사용자 단어에 더합니다. 암호·메일·주소·숫자를 넣는 칸, 주소·메일·경로가 섞인 글, 한글이 "
         L"없는 말은 기억하지 않습니다. 잘못 기억했으면 입력 표시기(가/A)를 오른쪽 클릭한 메뉴의 ‘방금 기억한 "
         L"띄어쓰기 잊기’나 아래 목록에서 지웁니다.",
         x, y);
    add(WC_LISTBOXW, L"", WS_BORDER | WS_VSCROLL | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT | WS_TABSTOP, kLearnedList, x, y,
        kContentW - 76, 104);
    button(kLearnedRemove, L"지우기", x + kContentW - 68, y, 68);
    y += 112;
    add(L"STATIC", L"", SS_CENTERIMAGE, kLearnedCount, x, y, 200, 26);
    button(kForget, L"모두 지우기", x + kContentW - 104, y, 104);
    y += 34;

    heading(L"단어장", x, y);
    button(kExport, L"단어장 내보내기…", x, y, 140);
    button(kImport, L"가져오기…", x + 148, y, 100);
    y += 34;
    note(L"등록한 단어와 기억한 띄어쓰기를 파일로 옮깁니다. 가져오기는 지금 있는 것을 지우지 않고 더하기만 합니다.", x, y,
         kWordbookMessage);

    heading(L"기기 사이에 단어장 맞추기", x, y);
    add(L"STATIC", L"", SS_NOPREFIX | SS_PATHELLIPSIS, kSyncFolderText, x, y, kContentW, 22);
    y += 24;
    add(L"STATIC", L"", SS_NOPREFIX, kSyncStatus, x, y, kContentW, 20, g_small);
    y += 26;
    button(kSyncChoose, L"폴더 고르기…", x, y, 112);
    button(kSyncNow, L"지금 맞추기", x + 120, y, 104);
    button(kSyncStop, L"그만", x + 232, y, 64);
    y += 34;
    note(L"고른 폴더 안의 ‘Maimusi’ 폴더에 이 PC의 단어장 파일을 두고, 다른 기기의 파일을 읽어 합칩니다. OneDrive·"
         L"Google Drive·Dropbox·iCloud Drive처럼 폴더를 맞춰 주는 곳이나 외장 디스크 어디든 됩니다. 세반시옷 서버는 "
         L"거치지 않습니다. 단어장에는 등록한 단어와 기억한 띄어쓰기가 들어 있으니 믿을 수 있는 곳을 고르세요.",
         x, y);

    heading(L"개인정보", x, y);
    note(L"입력한 글은 기록하지 않습니다. 모든 처리는 이 PC 안에서 합니다.", x, y);
    // Each item: its name, and below it what it is now (in the secondary color).
    add(L"STATIC", L"이 PC에 남는 것", SS_NOPREFIX | SS_CENTERIMAGE, -1, x, y, kContentW - 128, 26);
    button(kPrivacyOpen, L"설정 파일 보기", x + kContentW - 120, y, 120);
    y += 28;
    add(L"STATIC", L"", SS_NOPREFIX | SS_ENDELLIPSIS, kPrivacyStored, x, y, kContentW, 20, g_small);
    y += 26;
    add(L"STATIC", L"기기 밖으로 나가는 것", SS_NOPREFIX, -1, x, y, kContentW, 22);
    y += 24;
    add(L"STATIC", L"", SS_NOPREFIX | SS_ENDELLIPSIS, kPrivacyOut, x, y, kContentW, 20, g_small);
    y += 28;
    note(L"설정 파일(%APPDATA%\\Maimusi)은 파일 기록·OneDrive 폴더 백업·Windows 백업이 기본으로 백업하는 폴더에 "
         L"들지 않습니다. 디스크 전체를 백업하면 함께 백업됩니다. 단어장을 맞추는 폴더는 그 폴더를 맞추거나 "
         L"백업하는 곳(예: OneDrive)에 함께 올라갑니다.",
         x, y);

    heading(L"정보", x, y);
    std::wstring site = MAIMUSI_WEBSITE, mail = MAIMUSI_SUPPORT_EMAIL;
    std::wstring links = L"<a href=\"" + site + L"\">" + site.substr(site.find(L"//") + 2) + L"</a> · 문의 <a href=\"mailto:" +
                         mail + L"\">" + mail + L"</a>";
    add(WC_LINK, links, WS_TABSTOP, kLink, x, y, kContentW, 22);
    y += 30;
    add(L"STATIC", MAIMUSI_COPYRIGHT, 0, g_nextNote++, x, y + 5, kContentW - 120, 20, g_small);
    add(L"BUTTON", L"라이선스 보기", BS_PUSHBUTTON | WS_TABSTOP, kLicenses, x + kContentW - 112, y, 112, 28);
    y += 34;
    closeCard(x, y);

    for (const ComboBinding &b : kCombos) fillCombo(b.id, b.choices, b.count);
    int height = std::max(leftBottom, y) - kGap + kMargin;
    g_contentH = S(height);
    // As tall as the cards, at most the screen's work area; scroll the rest.
    MONITORINFO mi{sizeof mi};
    GetMonitorInfoW(MonitorFromWindow(g_window, MONITOR_DEFAULTTONEAREST), &mi);
    RECT frame{0, 0, 0, 0};
    AdjustWindowRectExForDpi(&frame, WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_VSCROLL, FALSE, 0, g_dpi);
    int available = (mi.rcWork.bottom - mi.rcWork.top) - (frame.bottom - frame.top) - S(16);
    g_viewH = std::min(g_contentH, std::max(S(300), available));
    bool scrolls = g_viewH < g_contentH;
    int bar = scrolls ? GetSystemMetricsForDpi(SM_CXVSCROLL, g_dpi) : 0;  // not counted by AdjustWindowRectEx
    RECT rc{0, 0, S(2 * kMargin + 2 * kCardW + kGap) + bar, g_viewH};
    DWORD visible = static_cast<DWORD>(GetWindowLongPtrW(g_window, GWL_STYLE)) & WS_VISIBLE;  // when built again
    DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN | (scrolls ? WS_VSCROLL : 0) | visible;
    SetWindowLongPtrW(g_window, GWL_STYLE, style);
    AdjustWindowRectExForDpi(&rc, style & ~WS_VISIBLE, FALSE, 0, g_dpi);
    // On the work area: not under the taskbar.
    RECT now;
    GetWindowRect(g_window, &now);
    int winW = rc.right - rc.left, winH = rc.bottom - rc.top;
    int left = std::clamp<int>(now.left, mi.rcWork.left, std::max<int>(mi.rcWork.left, mi.rcWork.right - winW));
    int top = std::clamp<int>(now.top, mi.rcWork.top, std::max<int>(mi.rcWork.top, mi.rcWork.bottom - winH));
    SetWindowPos(g_window, nullptr, left, top, winW, winH, SWP_NOZORDER | SWP_FRAMECHANGED);
    if (scrolls) {
        SCROLLINFO si{sizeof si, SIF_RANGE | SIF_PAGE | SIF_POS};
        si.nMin = 0;
        si.nMax = g_contentH - 1;
        si.nPage = static_cast<UINT>(g_viewH);
        si.nPos = 0;
        SetScrollInfo(g_window, SB_VERT, &si, TRUE);
    }
}

void rebuild() {
    for (HWND child = GetWindow(g_window, GW_CHILD); child; child = GetWindow(g_window, GW_CHILD)) DestroyWindow(child);
    g_cards.clear();
    g_open[0] = g_open[1] = -1;
    g_nextNote = kNoteBase;
    g_scroll = 0;
    g_previewShown = false;
    build();
    reload();
    InvalidateRect(g_window, nullptr, TRUE);
    startPreview();
}

void scrollTo(int pos) {
    pos = std::clamp(pos, 0, std::max(0, g_contentH - g_viewH));
    if (pos == g_scroll) return;
    ScrollWindowEx(g_window, 0, g_scroll - pos, nullptr, nullptr, nullptr, nullptr, SW_SCROLLCHILDREN);
    g_scroll = pos;
    SCROLLINFO si{sizeof si, SIF_POS};
    si.nPos = pos;
    SetScrollInfo(g_window, SB_VERT, &si, TRUE);
    RedrawWindow(g_window, nullptr, nullptr, RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN);
}

// Keyboard focus moved to a control outside the visible part: scroll it in.
void ensureVisible(HWND control) {
    if (!control || GetParent(control) != g_window) return;
    RECT rc;
    GetWindowRect(control, &rc);
    MapWindowPoints(nullptr, g_window, reinterpret_cast<POINT *>(&rc), 2);
    if (rc.top < S(8)) scrollTo(g_scroll + rc.top - S(48));
    else if (rc.bottom > g_viewH - S(8)) scrollTo(g_scroll + rc.bottom - g_viewH + S(48));
}

void makeFonts() {
    // Malgun Gothic, the Windows Korean UI font.
    LOGFONTW lf{};
    lf.lfHeight = -MulDiv(13, g_dpi, 96);
    lf.lfWeight = FW_NORMAL;
    lf.lfCharSet = DEFAULT_CHARSET;
    lf.lfQuality = CLEARTYPE_QUALITY;
    wcscpy_s(lf.lfFaceName, L"Malgun Gothic");
    g_font = CreateFontIndirectW(&lf);
    lf.lfWeight = FW_SEMIBOLD;
    g_bold = CreateFontIndirectW(&lf);
    lf.lfWeight = FW_NORMAL;
    lf.lfHeight = -MulDiv(11, g_dpi, 96);
    g_small = CreateFontIndirectW(&lf);
}

// Window surface, cards and header (Windows 11 light settings look).
const UINT32 kSurface = 0xF3F3F3, kCard = 0xFFFFFF, kCardBorder = 0xE5E5E5, kText = 0x1A1A1A, kSecondary = 0x5F5F5F;
HBRUSH g_cardBrush = nullptr;

void paint(HWND hwnd) {
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(hwnd, &ps);
    RECT client;
    GetClientRect(hwnd, &client);
    float offset = g_scroll * 96.f / g_dpi;  // DIPs scrolled
    ID2D1DCRenderTarget *rt = nullptr;
    auto props = D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_DEFAULT,
                                              D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_IGNORE),
                                              static_cast<float>(g_dpi), static_cast<float>(g_dpi));
    if (gfx::d2d() && SUCCEEDED(gfx::d2d()->CreateDCRenderTarget(&props, &rt)) && SUCCEEDED(rt->BindDC(dc, &client))) {
        ID2D1SolidColorBrush *brush = nullptr;
        rt->CreateSolidColorBrush(gfx::rgba(kText), &brush);
        IDWriteTextFormat *title = gfx::textFormat(24, DWRITE_FONT_WEIGHT_SEMI_BOLD);
        IDWriteTextFormat *sub = gfx::textFormat(12.5f);
        IDWriteTextFormat *cardTitle = gfx::textFormat(14, DWRITE_FONT_WEIGHT_SEMI_BOLD);
        rt->BeginDraw();
        rt->Clear(gfx::rgba(kSurface));
        rt->SetTransform(D2D1::Matrix3x2F::Translation(0, -offset));
        auto draw = [&](IDWriteTextFormat *f, const std::wstring &s, float x, float y, float w, float h, UINT32 color) {
            if (!f || !brush) return;
            brush->SetColor(gfx::rgba(color));
            rt->DrawText(s.c_str(), static_cast<UINT32>(s.size()), f, D2D1::RectF(x, y, x + w, y + h), brush);
        };
        // Header: icon, name, tagline and version.
        draw(title, MAIMUSI_NAME_KO, kMargin + 56.f, 18, 400, 34, kText);
        std::wstring tagline = std::wstring(MAIMUSI_TAGLINE_KO) + L"  ·  버전 " + MAIMUSI_VERSION + L" (" +
                               std::to_wstring(MAIMUSI_BUILD) + L")";
        draw(sub, tagline, kMargin + 57.f, 52, 600, 20, kSecondary);
        for (const Card &c : g_cards) {
            D2D1_ROUNDED_RECT r = D2D1::RoundedRect(D2D1::RectF(c.x + 0.5f, c.y + 0.5f, c.x + c.w - 0.5f, c.y + c.h - 0.5f), 8, 8);
            brush->SetColor(gfx::rgba(kCard));
            rt->FillRoundedRectangle(r, brush);
            brush->SetColor(gfx::rgba(kCardBorder));
            rt->DrawRoundedRectangle(r, brush, 1.f);
            draw(cardTitle, c.title, c.x + static_cast<float>(kInset), c.y + 14.f, c.w - 2.f * kInset, 22, kText);
        }
        rt->EndDraw();
        if (cardTitle) cardTitle->Release();
        if (sub) sub->Release();
        if (title) title->Release();
        if (brush) brush->Release();
    }
    if (rt) rt->Release();
    HICON icon = static_cast<HICON>(LoadImageW(GetModuleHandleW(nullptr), MAKEINTRESOURCEW(IDI_MAIMUSI), IMAGE_ICON,
                                               S(44), S(44), LR_DEFAULTCOLOR));
    if (icon) {
        DrawIconEx(dc, S(kMargin - 2), S(22) - g_scroll, icon, S(44), S(44), 0, nullptr, DI_NORMAL);
        DestroyIcon(icon);
    }
    EndPaint(hwnd, &ps);
}

LRESULT CALLBACK wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_PAINT:
        paint(hwnd);
        return 0;
    case WM_ERASEBKGND:
        return 1;
    case WM_CTLCOLORSTATIC:
    case WM_CTLCOLORBTN: {
        // Every control sits on a white card; notes use the secondary color.
        HDC dc = reinterpret_cast<HDC>(wParam);
        int id = GetDlgCtrlID(reinterpret_cast<HWND>(lParam));
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, id >= kSecondaryBase ? RGB(0x5F, 0x5F, 0x5F) : RGB(0x1A, 0x1A, 0x1A));
        if (!g_cardBrush) g_cardBrush = CreateSolidBrush(RGB(0xFF, 0xFF, 0xFF));
        return reinterpret_cast<LRESULT>(g_cardBrush);
    }
    case WM_VSCROLL: {
        SCROLLINFO si{sizeof si, SIF_ALL};
        GetScrollInfo(hwnd, SB_VERT, &si);
        int pos = g_scroll, line = S(40);
        switch (LOWORD(wParam)) {
        case SB_LINEUP: pos -= line; break;
        case SB_LINEDOWN: pos += line; break;
        case SB_PAGEUP: pos -= g_viewH - line; break;
        case SB_PAGEDOWN: pos += g_viewH - line; break;
        case SB_THUMBTRACK:
        case SB_THUMBPOSITION: pos = si.nTrackPos; break;
        case SB_TOP: pos = 0; break;
        case SB_BOTTOM: pos = g_contentH; break;
        }
        scrollTo(pos);
        return 0;
    }
    case WM_MOUSEWHEEL:
        scrollTo(g_scroll - MulDiv(GET_WHEEL_DELTA_WPARAM(wParam), S(120), WHEEL_DELTA));
        return 0;
    case WM_COMMAND: {
        int id = LOWORD(wParam), code = HIWORD(wParam);
        for (const CheckBinding &b : kChecks) {
            if (b.id == id && code == BN_CLICKED) {
                bool on = Button_GetCheck(reinterpret_cast<HWND>(lParam)) == BST_CHECKED;
                change([&](Settings &s) { s.set(b.key, on); });
                return 0;
            }
        }
        for (const ComboBinding &b : kCombos) {
            if (b.id == id && code == CBN_SELCHANGE) {
                int sel = ComboBox_GetCurSel(reinterpret_cast<HWND>(lParam));
                if (sel >= 0 && sel < b.count) change([&](Settings &s) { s.set(b.key, b.choices[sel].value); });
                if (b.rule) startPreview();
                return 0;
            }
        }
        switch (id) {
        case kEngineKiwi:
        case kEngineLight:
            if (code == BN_CLICKED) change([&](Settings &s) { s.set("engine", id == kEngineKiwi ? "kiwi" : "light"); });
            return 0;
        case kIdle:
            if (code == CBN_SELCHANGE) {
                int sel = ComboBox_GetCurSel(reinterpret_cast<HWND>(lParam));
                if (sel >= 0 && sel < 4) change([&](Settings &s) { s.set("idleUnloadMinutes", kIdleMinutes[sel]); });
            }
            return 0;
        case kPreviewEdit:
            if (code == EN_CHANGE) schedulePreview();
            return 0;
        case kCandidatePreset:
            if (code == CBN_SELCHANGE) {
                int sel = ComboBox_GetCurSel(reinterpret_cast<HWND>(lParam));
                const auto &presets = cand::presets();
                if (sel >= 0 && sel < static_cast<int>(presets.size()))
                    change([&](Settings &s) { s.set("candidatePreset", presets[sel].id); });
            }
            return 0;
        case kCandidateSize:
            if (code == CBN_SELCHANGE) {
                int sel = ComboBox_GetCurSel(reinterpret_cast<HWND>(lParam));
                if (sel >= 0 && sel < 3) {
                    change([&](Settings &s) { s.set("candidateTextSize", cand::kTextScales[sel].id); });
                    rebuild();
                }
            }
            return 0;
        case kWordAdd:
            addWord();
            return 0;
        case IDOK:  // Enter in a text field
            if (GetFocus() == GetDlgItem(hwnd, kWordEdit)) addWord();
            if (GetFocus() == GetDlgItem(hwnd, kPreviewEdit)) startPreview();
            return 0;
        case kWordRemove: {
            HWND list = GetDlgItem(hwnd, kWordList);
            int sel = ListBox_GetCurSel(list);
            if (sel >= 0) {
                wchar_t buf[256];
                ListBox_GetText(list, sel, buf);
                std::string word = narrow(buf);
                change([&](Settings &s) { s.removeWord(word); });
                scheduleSync();
            }
            return 0;
        }
        case kLearnedRemove: {
            int sel = ListBox_GetCurSel(GetDlgItem(hwnd, kLearnedList));
            if (sel >= 0 && sel < static_cast<int>(g_learnedShown.size())) {
                std::string compact = g_learnedShown[sel].compact;
                change([&](Settings &s) { s.forgetBoundary(compact); });
                ListBox_SetCurSel(GetDlgItem(hwnd, kLearnedList), std::min(sel, ListBox_GetCount(GetDlgItem(hwnd, kLearnedList)) - 1));
                scheduleSync();
            }
            return 0;
        }
        case kForget:
            change([](Settings &s) { s.forgetBoundaries(); });
            scheduleSync();
            return 0;
        case kExport:
            exportWordbook();
            return 0;
        case kImport:
            importWordbook();
            return 0;
        case kSyncChoose:
            chooseSyncFolder();
            return 0;
        case kSyncNow:
            startSync();
            return 0;
        case kSyncStop:
            stopSync();
            return 0;
        case kPrivacyOpen:
            showSettingsFile();
            return 0;
        case kLicenses:
            ShellExecuteW(hwnd, L"open", (g_dir + L"Licenses").c_str(), nullptr, nullptr, SW_SHOWNORMAL);
            return 0;
        }
        break;
    }
    case WM_DRAWITEM: {
        auto *item = reinterpret_cast<DRAWITEMSTRUCT *>(lParam);
        if (item->CtlID == kCandidatePreview) {
            drawPreview(item->hDC, item->rcItem);
            return TRUE;
        }
        break;
    }
    case WM_NOTIFY: {
        auto *hdr = reinterpret_cast<NMHDR *>(lParam);
        if (hdr->idFrom == kLink && (hdr->code == NM_CLICK || hdr->code == NM_RETURN)) {
            auto *link = reinterpret_cast<NMLINK *>(lParam);
            ShellExecuteW(hwnd, L"open", link->item.szUrl, nullptr, nullptr, SW_SHOWNORMAL);
        }
        break;
    }
    case WM_TIMER:
        switch (wParam) {
        case kTimerReload:
            // The input method adds learned boundaries and words while typing.
            if (Settings::fileStamp() != g_stamp) reload();
            break;
        case kTimerPreview:
            startPreview();
            break;
        case kTimerSync:
            startSync();
            break;
        }
        return 0;
    case kPreviewDone: {
        auto *result = reinterpret_cast<std::wstring *>(lParam);
        if (static_cast<int>(wParam) == g_previewRequest) {
            g_previewShown = result != nullptr;
            SetDlgItemTextW(hwnd, kPreviewResult, result ? result->c_str() : L"찰떡 엔진이 준비되면 결과가 보입니다");
        }
        delete result;
        return 0;
    }
    case kSyncDone:
        g_syncing = false;
        reload();
        return 0;
    case WM_DPICHANGED: {
        auto *rc = reinterpret_cast<RECT *>(lParam);
        SetWindowPos(hwnd, nullptr, rc->left, rc->top, rc->right - rc->left, rc->bottom - rc->top, SWP_NOZORDER);
        return 0;
    }
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

int registerUser(bool install) {
    // A per-user COM registration (left by a development copy) would shadow
    // the installed text service; only the machine-wide one may remain.
    SHDeleteKeyW(HKEY_CURRENT_USER, L"Software\\Classes\\CLSID\\{1A36DDCD-E1AE-4B54-AAF1-EF5418F4B25B}");
    SHDeleteKeyW(HKEY_CURRENT_USER, L"Software\\Classes\\WOW6432Node\\CLSID\\{1A36DDCD-E1AE-4B54-AAF1-EF5418F4B25B}");
    // The copy of the settings that AppContainer applications read. Removed
    // with the input method; the settings file itself stays.
    if (install) {
        Settings::syncShared();
    } else {
        Settings::removeShared();
    }
    using InstallFn = BOOL(WINAPI *)(LPCWSTR, DWORD);
    HMODULE input = LoadLibraryW(L"input.dll");
    auto fn = input ? reinterpret_cast<InstallFn>(GetProcAddress(input, "InstallLayoutOrTip")) : nullptr;
    if (!fn) return 1;
    // ILOT_UNINSTALL = 0x1
    return fn(kTip, install ? 0 : 0x1) ? 0 : 1;
}

// --test-wordbook [folder]: output to the console or file it was started with.
int testWordbook(const std::wstring &args) {
    HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    if ((!out || out == INVALID_HANDLE_VALUE) && AttachConsole(ATTACH_PARENT_PROCESS)) {
        FILE *f = nullptr;
        freopen_s(&f, "CONOUT$", "w", stdout);
    }
    SetConsoleOutputCP(CP_UTF8);
    std::wstring folder;
    size_t at = args.find(L"--test-wordbook");
    std::wstring rest = args.substr(at + wcslen(L"--test-wordbook"));
    size_t b = rest.find_first_not_of(L" \t\"");
    if (b != std::wstring::npos) {
        size_t e = rest.find_last_not_of(L" \t\"");
        folder = rest.substr(b, e - b + 1);
    }
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    int result = wordbook::selfTest(folder);
    std::fflush(stdout);
    return result;
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, LPWSTR cmdLine, int show) {
    std::wstring args = cmdLine ? cmdLine : L"";
    if (args.find(L"--register-user") != std::wstring::npos) return registerUser(true);
    if (args.find(L"--unregister-user") != std::wstring::npos) return registerUser(false);
    if (args.find(L"--test-wordbook") != std::wstring::npos) return testWordbook(args);
    if (size_t at = args.find(L"--render-candidates"); at != std::wstring::npos) {
        std::wstring dir = args.substr(at + wcslen(L"--render-candidates"));
        dir.erase(0, dir.find_first_not_of(L" \t\""));
        dir.erase(dir.find_last_not_of(L" \t\"") + 1);
        return renderCandidates(dir.empty() ? std::wstring(L".") : dir);
    }

    HANDLE single = CreateMutexW(nullptr, FALSE, L"Local\\Maimusi.SettingsWindow");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        if (HWND existing = FindWindowW(L"MaimusiSettings", nullptr)) {
            ShowWindow(existing, SW_RESTORE);
            SetForegroundWindow(existing);
        }
        return 0;
    }

    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(nullptr, path, MAX_PATH);
    g_dir = std::wstring(path, n);
    g_dir = g_dir.substr(0, g_dir.find_last_of(L'\\') + 1);
    g_kiwi = fileExists(g_dir + L"engine\\MaimusiEngine.exe");
    g_light = fileExists(g_dir + L"spacing.hspm");

    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    INITCOMMONCONTROLSEX icc{sizeof icc, ICC_STANDARD_CLASSES | ICC_LINK_CLASS};
    InitCommonControlsEx(&icc);
    WNDCLASSEXW wc{sizeof wc};
    wc.lpfnWndProc = wndProc;
    wc.hInstance = instance;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = GetSysColorBrush(COLOR_WINDOW);
    wc.lpszClassName = L"MaimusiSettings";
    wc.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(IDI_MAIMUSI));
    RegisterClassExW(&wc);
    std::wstring title = std::wstring(MAIMUSI_NAME_KO) + L" 설정";
    g_window = CreateWindowExW(0, wc.lpszClassName, title.c_str(),
                               WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN, CW_USEDEFAULT,
                               CW_USEDEFAULT, 800, 700, nullptr, nullptr, instance, nullptr);
    g_dpi = GetDpiForWindow(g_window);
    makeFonts();
    build();
    reload();
    SetTimer(g_window, kTimerReload, 1500, nullptr);
    ShowWindow(g_window, show);
    startPreview();
    if (wordbook::syncDue(g_settings)) startSync();
    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0)) {
        if (!IsDialogMessageW(g_window, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        } else if (msg.message == WM_KEYDOWN && msg.wParam == VK_TAB) {
            ensureVisible(GetFocus());
        }
    }
    CloseHandle(single);
    return 0;
}
