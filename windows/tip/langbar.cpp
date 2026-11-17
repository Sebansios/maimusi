#include "langbar.h"

#include <olectl.h>

#include <string>

#include <algorithm>
#include <cmath>
#include <vector>

#include "../common/graphics.h"
#include "../common/text.h"
#include "engine.h"
#include "globals.h"
#include "product.h"
#include "textservice.h"

namespace maimusi {

namespace {

// GUID_LBI_INPUTMODE (Windows 8+): the taskbar input mode indicator.
const GUID kLbiInputMode = {0x2c77a81e, 0x41cc, 0x4178, {0xa3, 0xa7, 0x5f, 0x8a, 0x98, 0x75, 0x68, 0xe6}};

constexpr DWORD kSinkCookie = 0x4D41494D;

enum MenuId : UINT {
    kMenuKiwi = 1,
    kMenuLight,
    kMenuAutoSpacing,
    kMenuToggle,
    kMenuSettings,
    kMenuForgetLearned,
};

// The mode letter as a crisp icon in the taskbar's text color, drawn at the
// system DPI (not the application's) and sized by its measured ink so 가 and A
// match the system's own input indicator.
HICON makeModeIcon(const wchar_t *text) {
    UINT dpi = gfx::systemDpi();
    int size = MulDiv(16, dpi, 96);
    IWICImagingFactory *wic = gfx::wic();
    ID2D1Factory *d2d = gfx::d2d();
    IDWriteFactory2 *dw = gfx::dwrite();
    if (!wic || !d2d || !dw) return nullptr;
    IWICBitmap *bitmap = nullptr;
    ID2D1RenderTarget *rt = nullptr;
    ID2D1SolidColorBrush *brush = nullptr;
    IDWriteTextFormat *format = nullptr;
    IDWriteTextLayout *layout = nullptr;
    HICON icon = nullptr;
    bool light = gfx::taskbarLight();
    std::wstring s = text;
    bool hangul = s[0] >= 0xAC00;
    do {
        if (FAILED(wic->CreateBitmap(size, size, GUID_WICPixelFormat32bppPBGRA, WICBitmapCacheOnLoad, &bitmap))) break;
        auto props = D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_SOFTWARE,
                                                  D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED),
                                                  96.f, 96.f);
        if (FAILED(d2d->CreateWicBitmapRenderTarget(bitmap, props, &rt))) break;
        rt->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
        // Snap stems to whole pixels: at 16-24 px the glyph must look as crisp as the system's.
        IDWriteRenderingParams2 *crisp = nullptr;
        if (SUCCEEDED(dw->CreateCustomRenderingParams(1.8f, 0.5f, 1.0f, 0.f, DWRITE_PIXEL_GEOMETRY_FLAT,
                                                      DWRITE_RENDERING_MODE_NATURAL_SYMMETRIC, DWRITE_GRID_FIT_MODE_ENABLED,
                                                      &crisp))) {
            rt->SetTextRenderingParams(crisp);
            crisp->Release();
        }
        rt->CreateSolidColorBrush(light ? D2D1::ColorF(0x1A1A1A) : D2D1::ColorF(D2D1::ColorF::White), &brush);
        // Both letters in Malgun Gothic, the font of the system's own Korean indicator.
        const wchar_t *family = gfx::uiFamily();
        IDWriteFontCollection *fonts = nullptr;
        float em = size * 1.0f;
        if (FAILED(dw->CreateTextFormat(family, fonts, DWRITE_FONT_WEIGHT_MEDIUM, DWRITE_FONT_STYLE_NORMAL,
                                        DWRITE_FONT_STRETCH_NORMAL, em, L"ko-KR", &format)))
            break;
        if (FAILED(dw->CreateTextLayout(s.c_str(), static_cast<UINT32>(s.size()), format, 1000, 1000, &layout))) break;
        // Ink box from the overhang metrics; scale it to the target height.
        DWRITE_TEXT_METRICS tm{};
        DWRITE_OVERHANG_METRICS om{};
        // Overhangs are measured against the layout box: shrink it to the text first.
        auto inkBox = [&](float &w, float &h) {
            layout->GetMetrics(&tm);
            layout->SetMaxWidth(tm.widthIncludingTrailingWhitespace);
            layout->SetMaxHeight(tm.height);
            layout->GetOverhangMetrics(&om);
            w = tm.widthIncludingTrailingWhitespace + om.left + om.right;
            h = tm.height + om.top + om.bottom;
        };
        float inkW = 0, inkH = 0;
        inkBox(inkW, inkH);
        if (inkW <= 0 || inkH <= 0) break;
        float target = size * (hangul ? 0.80f : 0.70f);
        float scale = std::min(target / inkH, size * 0.92f / inkW);
        layout->Release();
        format->Release();
        layout = nullptr;
        format = nullptr;
        dw->CreateTextFormat(family, fonts, DWRITE_FONT_WEIGHT_MEDIUM, DWRITE_FONT_STYLE_NORMAL,
                             DWRITE_FONT_STRETCH_NORMAL, em * scale, L"ko-KR", &format);
        if (!format || FAILED(dw->CreateTextLayout(s.c_str(), static_cast<UINT32>(s.size()), format, 1000, 1000, &layout)))
            break;
        inkBox(inkW, inkH);
        // Ink starts at (-om.left, -om.top) inside the layout box; center it, whole pixels.
        float x = std::round((size - inkW) / 2 + om.left);
        float y = std::round((size - inkH) / 2 + om.top);
        rt->BeginDraw();
        rt->Clear(D2D1::ColorF(0, 0, 0, 0));
        rt->DrawTextLayout(D2D1::Point2F(x, y), layout, brush);
        if (FAILED(rt->EndDraw())) break;
        // Icons take straight (not premultiplied) alpha.
        std::vector<BYTE> px(static_cast<size_t>(size) * size * 4);
        if (FAILED(bitmap->CopyPixels(nullptr, size * 4, static_cast<UINT>(px.size()), px.data()))) break;
        BYTE ink = light ? 0x1A : 0xFF;
        for (size_t i = 0; i < px.size(); i += 4) {
            BYTE a = px[i + 3];
            px[i] = px[i + 1] = px[i + 2] = a ? ink : 0;
        }
        BITMAPV5HEADER bi{};
        bi.bV5Size = sizeof bi;
        bi.bV5Width = size;
        bi.bV5Height = -size;
        bi.bV5Planes = 1;
        bi.bV5BitCount = 32;
        bi.bV5Compression = BI_BITFIELDS;
        bi.bV5RedMask = 0x00FF0000;
        bi.bV5GreenMask = 0x0000FF00;
        bi.bV5BlueMask = 0x000000FF;
        bi.bV5AlphaMask = 0xFF000000;
        void *bits = nullptr;
        HDC screen = GetDC(nullptr);
        HBITMAP color = CreateDIBSection(screen, reinterpret_cast<BITMAPINFO *>(&bi), DIB_RGB_COLORS, &bits, nullptr, 0);
        ReleaseDC(nullptr, screen);
        if (!color) break;
        memcpy(bits, px.data(), px.size());
        HBITMAP mask = CreateBitmap(size, size, 1, 1, nullptr);
        ICONINFO ii{TRUE, 0, 0, mask, color};
        icon = CreateIconIndirect(&ii);
        DeleteObject(mask);
        DeleteObject(color);
    } while (false);
    if (layout) layout->Release();
    if (format) format->Release();
    if (brush) brush->Release();
    if (rt) rt->Release();
    if (bitmap) bitmap->Release();
    return icon;
}

}  // namespace

LangBarButton::LangBarButton(TextService *owner) : owner_(owner) { DllAddRef(); }

LangBarButton::~LangBarButton() {
    if (sink_) sink_->Release();
    DllRelease();
}

STDMETHODIMP LangBarButton::QueryInterface(REFIID riid, void **ppv) {
    if (!ppv) return E_INVALIDARG;
    *ppv = nullptr;
    if (riid == IID_IUnknown || riid == IID_ITfLangBarItem || riid == IID_ITfLangBarItemButton)
        *ppv = static_cast<ITfLangBarItemButton *>(this);
    else if (riid == IID_ITfSource)
        *ppv = static_cast<ITfSource *>(this);
    if (!*ppv) return E_NOINTERFACE;
    AddRef();
    return S_OK;
}

STDMETHODIMP_(ULONG) LangBarButton::AddRef() { return InterlockedIncrement(&refs_); }

STDMETHODIMP_(ULONG) LangBarButton::Release() {
    LONG n = InterlockedDecrement(&refs_);
    if (!n) delete this;
    return n;
}

STDMETHODIMP LangBarButton::GetInfo(TF_LANGBARITEMINFO *info) {
    if (!info) return E_INVALIDARG;
    info->clsidService = CLSID_MaimusiTextService;
    // The system shows this item as the input mode indicator in the taskbar.
    info->guidItem = kLbiInputMode;
    info->dwStyle = TF_LBI_STYLE_BTN_BUTTON | TF_LBI_STYLE_SHOWNINTRAY;
    info->ulSort = 0;
    wcscpy_s(info->szDescription, MAIMUSI_NAME_KO L" 입력 모드");
    return S_OK;
}

STDMETHODIMP LangBarButton::GetStatus(DWORD *status) {
    if (!status) return E_INVALIDARG;
    *status = 0;
    return S_OK;
}

STDMETHODIMP LangBarButton::GetTooltipString(BSTR *tooltip) {
    if (!tooltip) return E_INVALIDARG;
    bool hangul = owner_ && owner_->hangulMode();
    *tooltip = SysAllocString(hangul ? MAIMUSI_NAME_KO L" · 한글 (한/영 키로 전환)" : MAIMUSI_NAME_KO L" · 영문 (한/영 키로 전환)");
    return *tooltip ? S_OK : E_OUTOFMEMORY;
}

STDMETHODIMP LangBarButton::OnClick(TfLBIClick click, POINT pt, const RECT *) {
    if (!owner_) return S_OK;
    if (click == TF_LBI_CLK_LEFT) owner_->toggleMode();
    else showMenu(pt);
    return S_OK;
}

void LangBarButton::showMenu(POINT pt) {
    EngineHub &hub = EngineHub::shared();
    Settings s = hub.settings();
    HMENU menu = CreatePopupMenu();
    std::wstring status = hub.statusText();
    AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, status.c_str());
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    // A sandboxed application cannot save settings: show them, read-only.
    UINT editable = hub.sandboxed() ? MF_GRAYED : 0;
    if (hub.lightAvailable() && hub.kiwiInstalled()) {
        bool kiwi = s.engine() == "kiwi";
        AppendMenuW(menu, MF_STRING | editable | (kiwi ? MF_CHECKED : 0), kMenuKiwi, L"찰떡 엔진 (고정확도)");
        AppendMenuW(menu, MF_STRING | editable | (!kiwi ? MF_CHECKED : 0), kMenuLight, L"경량 엔진 (내장)");
    }
    AppendMenuW(menu, MF_STRING | editable | (s.getBool("convertOnSpace") ? MF_CHECKED : 0), kMenuAutoSpacing,
                L"스페이스로 자동 띄어쓰기");
    // Only when something was just learned (no shortcut: macOS does the same).
    std::string learned = hub.sandboxed() ? std::string() : s.lastLearnedLabel();
    if (!learned.empty()) {
        std::wstring label = L"방금 기억한 띄어쓰기 잊기 (" + widen(learned) + L")";
        AppendMenuW(menu, MF_STRING, kMenuForgetLearned, label.c_str());
    }
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, kMenuToggle,
                owner_->hangulMode() ? L"영문으로 전환\t한/영" : L"한글로 전환\t한/영");
    AppendMenuW(menu, MF_STRING, kMenuSettings, L"설정…");
    // A popup menu needs an owner window on this thread.
    HWND owner = CreateWindowExW(WS_EX_TOOLWINDOW, L"STATIC", L"", WS_POPUP, pt.x, pt.y, 0, 0, nullptr, nullptr,
                                 g_hInst, nullptr);
    if (owner) SetForegroundWindow(owner);
    UINT cmd = TrackPopupMenuEx(menu, TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, pt.x, pt.y,
                                owner, nullptr);
    DestroyMenu(menu);
    if (owner) DestroyWindow(owner);
    if (!owner_) return;
    switch (cmd) {
    case kMenuKiwi: owner_->selectEngine("kiwi"); break;
    case kMenuLight: owner_->selectEngine("light"); break;
    case kMenuAutoSpacing: owner_->toggleAutoSpacing(); break;
    case kMenuToggle: owner_->toggleMode(); break;
    case kMenuSettings: owner_->openSettings(); break;
    case kMenuForgetLearned: owner_->forgetLastLearned(); break;
    }
}

STDMETHODIMP LangBarButton::GetIcon(HICON *icon) {
    if (!icon) return E_INVALIDARG;
    *icon = makeModeIcon(owner_ && owner_->hangulMode() ? L"가" : L"A");
    return *icon ? S_OK : E_FAIL;
}

STDMETHODIMP LangBarButton::GetText(BSTR *text) {
    if (!text) return E_INVALIDARG;
    *text = SysAllocString(owner_ && owner_->hangulMode() ? L"가" : L"A");
    return *text ? S_OK : E_OUTOFMEMORY;
}

STDMETHODIMP LangBarButton::AdviseSink(REFIID riid, IUnknown *sink, DWORD *cookie) {
    if (!sink || !cookie) return E_INVALIDARG;
    if (riid != IID_ITfLangBarItemSink) return CONNECT_E_CANNOTCONNECT;
    if (sink_) return CONNECT_E_ADVISELIMIT;
    if (FAILED(sink->QueryInterface(IID_ITfLangBarItemSink, reinterpret_cast<void **>(&sink_)))) {
        sink_ = nullptr;
        return E_NOINTERFACE;
    }
    *cookie = kSinkCookie;
    return S_OK;
}

STDMETHODIMP LangBarButton::UnadviseSink(DWORD cookie) {
    if (cookie != kSinkCookie || !sink_) return CONNECT_E_NOCONNECTION;
    sink_->Release();
    sink_ = nullptr;
    return S_OK;
}

void LangBarButton::update() {
    if (sink_) sink_->OnUpdate(TF_LBI_ICON | TF_LBI_TEXT | TF_LBI_TOOLTIP);
}

}  // namespace maimusi
