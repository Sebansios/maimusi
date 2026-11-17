// Direct2D/DirectWrite helpers shared by the candidate window, the input mode
// icon and the settings window: factories, the system color theme and text
// formats with a font fallback that covers Hangul and Hanja.
#pragma once

#include <windows.h>
#include <d2d1_1.h>
#include <dwrite_3.h>
#include <wincodec.h>

#include <string>

namespace maimusi::gfx {

ID2D1Factory *d2d();
IDWriteFactory2 *dwrite();
IWICImagingFactory *wic();

struct Theme {
    bool dark;
    D2D1_COLOR_F background;  // flyout surface
    D2D1_COLOR_F border;
    D2D1_COLOR_F text;
    D2D1_COLOR_F secondary;   // notes, numbers, hints
    D2D1_COLOR_F hover;       // row and button hover fill
    D2D1_COLOR_F selected;    // selected row fill
    D2D1_COLOR_F button;      // resting button fill
    D2D1_COLOR_F separator;
    D2D1_COLOR_F accent;      // user's accent color
    D2D1_COLOR_F onAccent;    // text on the accent color
};

// Current app theme (light/dark) and accent color.
Theme theme();
// True when the taskbar uses the light theme.
bool taskbarLight();
// Effective system DPI, also from DPI-unaware processes.
UINT systemDpi();

// Text in `family` (default Malgun Gothic), rarer Hanja through Microsoft
// YaHei and SimSun-ExtB/ExtG, then the system fallback. Caller releases.
IDWriteTextFormat *textFormat(float size, DWRITE_FONT_WEIGHT weight = DWRITE_FONT_WEIGHT_NORMAL,
                              const wchar_t *family = nullptr);
// "Malgun Gothic".
const wchar_t *uiFamily();

inline D2D1_COLOR_F rgba(UINT32 rgb, float a = 1.f) {
    return D2D1::ColorF(((rgb >> 16) & 0xFF) / 255.f, ((rgb >> 8) & 0xFF) / 255.f, (rgb & 0xFF) / 255.f, a);
}

}  // namespace maimusi::gfx
