#include "graphics.h"

#include <mutex>

namespace maimusi::gfx {

namespace {

std::once_flag g_once;
ID2D1Factory *g_d2d = nullptr;
IDWriteFactory2 *g_dwrite = nullptr;
IWICImagingFactory *g_wic = nullptr;
IDWriteFontFallback *g_fallback = nullptr;
// Malgun Gothic: the Windows Korean UI font, hinted for crisp text at small sizes.
const wchar_t *const g_family = L"Malgun Gothic";

DWORD readDword(const wchar_t *key, const wchar_t *value, DWORD fallback) {
    DWORD data = 0, size = sizeof data;
    if (RegGetValueW(HKEY_CURRENT_USER, key, value, RRF_RT_REG_DWORD, nullptr, &data, &size) != ERROR_SUCCESS)
        return fallback;
    return data;
}

void init() {
    D2D1_FACTORY_OPTIONS options{};
    D2D1CreateFactory(D2D1_FACTORY_TYPE_MULTI_THREADED, __uuidof(ID2D1Factory), &options,
                      reinterpret_cast<void **>(&g_d2d));
    DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory2), reinterpret_cast<IUnknown **>(&g_dwrite));
    CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&g_wic));
    if (!g_dwrite) return;
    // Malgun Gothic covers Hangul, Latin and the Korean Hanja set. Rarer Hanja
    // (CJK extensions) fall back to fonts every Windows 10/11 has, Korean
    // locale first, then the system fallback.
    IDWriteFontFallbackBuilder *builder = nullptr;
    IDWriteFontFallback *system = nullptr;
    if (SUCCEEDED(g_dwrite->CreateFontFallbackBuilder(&builder)) && SUCCEEDED(g_dwrite->GetSystemFontFallback(&system))) {
        const DWRITE_UNICODE_RANGE han[] = {{0x2E80, 0x2FDF}, {0x3400, 0x4DBF}, {0x4E00, 0x9FFF},
                                            {0xF900, 0xFAFF}, {0x20000, 0x3FFFF}};
        const wchar_t *hanFonts[] = {L"Malgun Gothic", L"Microsoft YaHei", L"SimSun-ExtB", L"SimSun-ExtG"};
        builder->AddMapping(han, ARRAYSIZE(han), hanFonts, ARRAYSIZE(hanFonts), nullptr, L"ko-KR");
        builder->AddMappings(system);
        builder->CreateFontFallback(&g_fallback);
    }
    if (system) system->Release();
    if (builder) builder->Release();
}

}  // namespace

ID2D1Factory *d2d() {
    std::call_once(g_once, init);
    return g_d2d;
}

IDWriteFactory2 *dwrite() {
    std::call_once(g_once, init);
    return g_dwrite;
}

IWICImagingFactory *wic() {
    std::call_once(g_once, init);
    return g_wic;
}

const wchar_t *uiFamily() { return g_family; }

IDWriteTextFormat *textFormat(float size, DWRITE_FONT_WEIGHT weight, const wchar_t *family) {
    std::call_once(g_once, init);
    if (!g_dwrite) return nullptr;
    IDWriteTextFormat *format = nullptr;
    if (FAILED(g_dwrite->CreateTextFormat(family ? family : g_family, nullptr, weight, DWRITE_FONT_STYLE_NORMAL,
                                          DWRITE_FONT_STRETCH_NORMAL, size, L"ko-KR", &format)))
        return nullptr;
    IDWriteTextFormat1 *format1 = nullptr;
    if (g_fallback && SUCCEEDED(format->QueryInterface(IID_PPV_ARGS(&format1)))) {
        format1->SetFontFallback(g_fallback);
        format1->Release();
    }
    format->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
    return format;
}

bool taskbarLight() {
    return readDword(L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize", L"SystemUsesLightTheme", 0) != 0;
}

UINT systemDpi() {
    // AppliedDPI is the real setting; GetDpiForSystem reports 96 to DPI-unaware processes.
    DWORD applied = 0, size = sizeof applied;
    if (RegGetValueW(HKEY_CURRENT_USER, L"Control Panel\\Desktop\\WindowMetrics", L"AppliedDPI", RRF_RT_REG_DWORD,
                     nullptr, &applied, &size) == ERROR_SUCCESS && applied >= 96 && applied <= 480)
        return applied;
    return GetDpiForSystem();
}

Theme theme() {
    bool dark = readDword(L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize", L"AppsUseLightTheme", 1) == 0;
    // AccentColor is 0xAABBGGRR.
    DWORD abgr = readDword(L"Software\\Microsoft\\Windows\\DWM", L"AccentColor", 0xFFC06700);
    UINT32 rgb = ((abgr & 0xFF) << 16) | (abgr & 0xFF00) | ((abgr >> 16) & 0xFF);
    Theme t{};
    t.dark = dark;
    t.accent = rgba(rgb);
    t.onAccent = rgba(0xFFFFFF);
    if (dark) {
        t.background = rgba(0x2C2C2C);
        t.border = rgba(0x000000, 0.35f);
        t.text = rgba(0xFFFFFF);
        t.secondary = rgba(0xFFFFFF, 0.62f);
        t.hover = rgba(0xFFFFFF, 0.06f);
        t.selected = rgba(0xFFFFFF, 0.09f);
        t.button = rgba(0xFFFFFF, 0.06f);
        t.separator = rgba(0xFFFFFF, 0.09f);
    } else {
        t.background = rgba(0xF9F9F9);
        t.border = rgba(0x000000, 0.10f);
        t.text = rgba(0x1A1A1A);
        t.secondary = rgba(0x000000, 0.56f);
        t.hover = rgba(0x000000, 0.04f);
        t.selected = rgba(0x000000, 0.06f);
        t.button = rgba(0x000000, 0.04f);
        t.separator = rgba(0x000000, 0.08f);
    }
    return t;
}

}  // namespace maimusi::gfx
