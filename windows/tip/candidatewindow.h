// A small non-activating flyout under the composition with the candidates of
// the selected word, nine per page (number keys pick within the page), the
// boundary keys and a footer, drawn by cand::View in the look chosen in the
// settings: the same presets as the macOS candidate window. It is a layered
// window with per-pixel alpha, so the panel has the theme's own shape and a
// soft shadow. Space or ↑/↓ move through it from the keyboard (handled by the
// core); a click chooses a row or a boundary key. In applications without
// inline composition it also shows the phrase being typed.
#pragma once

#include <windows.h>
#include <d2d1.h>

#include "../common/candidateview.h"

namespace maimusi {

class TextService;

class CandidateWindow {
public:
    explicit CandidateWindow(TextService *owner) : owner_(owner) {}
    // Destroys the window and this object.
    void destroy();

    // Composition (or selected word) rectangle in screen coordinates.
    void setAnchor(const RECT &rc) { anchor_ = rc; }
    void show(const cand::Theme &theme, const cand::Content &content);
    void hide();

    static void unregisterClass();

private:
    bool ensureWindow();
    // Draws the view onto the surface and puts it on the screen.
    void render();
    void releaseSurface();
    int hitAt(LPARAM lParam) const;
    static LRESULT CALLBACK wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam);

    TextService *owner_;
    HWND hwnd_ = nullptr;
    RECT anchor_{};
    int dpi_ = 96;
    cand::View view_;
    int hover_ = -1;  // index into view_.hits()
    POINT origin_{};  // window position and size in pixels
    SIZE pixels_{};
    // A premultiplied 32-bit DIB and a Direct2D target bound to it.
    HDC memDC_ = nullptr;
    HBITMAP bitmap_ = nullptr;
    HGDIOBJ oldBitmap_ = nullptr;
    ID2D1DCRenderTarget *target_ = nullptr;
    SIZE surface_{};
    int surfaceDpi_ = 0;
};

}  // namespace maimusi
