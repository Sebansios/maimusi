#include "candidatewindow.h"

#include <windowsx.h>

#include <algorithm>
#include <cmath>

#include "../common/graphics.h"
#include "globals.h"
#include "textservice.h"

namespace maimusi {

namespace {

const wchar_t kClassName[] = L"MaimusiCandidateWindow";
bool g_registered = false;

}  // namespace

void CandidateWindow::unregisterClass() {
    if (g_registered) UnregisterClassW(kClassName, g_hInst);
    g_registered = false;
}

void CandidateWindow::releaseSurface() {
    if (target_) {
        target_->Release();
        target_ = nullptr;
    }
    if (memDC_) {
        if (oldBitmap_) SelectObject(memDC_, oldBitmap_);
        DeleteDC(memDC_);
        memDC_ = nullptr;
    }
    if (bitmap_) {
        DeleteObject(bitmap_);
        bitmap_ = nullptr;
    }
    oldBitmap_ = nullptr;
    surface_ = {};
    surfaceDpi_ = 0;
}

void CandidateWindow::destroy() {
    if (hwnd_) DestroyWindow(hwnd_);
    releaseSurface();
    delete this;
}

bool CandidateWindow::ensureWindow() {
    if (hwnd_) return true;
    if (!g_registered) {
        WNDCLASSEXW wc{sizeof wc};
        wc.style = CS_IME;
        wc.lpfnWndProc = wndProc;
        wc.hInstance = g_hInst;
        wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
        wc.lpszClassName = kClassName;
        g_registered = RegisterClassExW(&wc) != 0 || GetLastError() == ERROR_CLASS_ALREADY_EXISTS;
    }
    // Layered: the panel's shape and shadow come from the alpha of what is drawn.
    hwnd_ = CreateWindowExW(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE, kClassName, L"", WS_POPUP,
                            0, 0, 1, 1, nullptr, nullptr, g_hInst, this);
    return hwnd_ != nullptr;
}

void CandidateWindow::show(const cand::Theme &theme, const cand::Content &content) {
    if (!ensureWindow()) return;
    // Scale for the monitor under the composition when this application is
    // per-monitor aware; otherwise the system scales the window for us.
    HMONITOR monitor = MonitorFromRect(&anchor_, MONITOR_DEFAULTTONEAREST);
    int dpi = static_cast<int>(GetDpiForWindow(hwnd_));
    using GetDpiForMonitorFn = HRESULT(WINAPI *)(HMONITOR, int, UINT *, UINT *);
    static auto getDpi = reinterpret_cast<GetDpiForMonitorFn>(GetProcAddress(LoadLibraryW(L"shcore.dll"), "GetDpiForMonitor"));
    UINT dx = 96, dy = 96;
    if (getDpi && GetAwarenessFromDpiAwarenessContext(GetThreadDpiAwarenessContext()) == DPI_AWARENESS_PER_MONITOR_AWARE &&
        SUCCEEDED(getDpi(monitor, 0, &dx, &dy)))
        dpi = static_cast<int>(dy);
    dpi_ = dpi > 0 ? dpi : 96;

    gfx::Theme system = gfx::theme();
    view_.layout(theme, content, system.dark, system.accent);
    if (view_.empty()) {
        hide();
        return;
    }
    hover_ = -1;
    float scale = dpi_ / 96.f;
    D2D1_SIZE_F size = view_.size();
    int w = static_cast<int>(std::ceil(size.width * scale)), h = static_cast<int>(std::ceil(size.height * scale));
    int margin = static_cast<int>(std::lround(cand::View::kShadow * scale));
    int panelW = w - 2 * margin, panelH = h - 2 * margin;
    MONITORINFO mi{sizeof mi};
    GetMonitorInfoW(monitor, &mi);
    RECT work = mi.rcWork;
    // Under the composition, its left edge with the panel's (as on macOS); above it near the bottom.
    int gap = MulDiv(4, dpi_, 96);
    int x = anchor_.left, y = anchor_.bottom + gap;
    if (y + panelH > work.bottom) y = anchor_.top - panelH - gap;
    x = std::min<int>(std::max<int>(x, work.left), work.right - panelW);
    y = std::max<int>(y, work.top);
    origin_ = {x - margin, y - margin};
    pixels_ = {w, h};
    render();
    SetWindowPos(hwnd_, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
}

void CandidateWindow::render() {
    if (!hwnd_ || pixels_.cx <= 0 || pixels_.cy <= 0) return;
    if (!memDC_ || surface_.cx != pixels_.cx || surface_.cy != pixels_.cy || surfaceDpi_ != dpi_) {
        releaseSurface();
        HDC screen = GetDC(nullptr);
        memDC_ = CreateCompatibleDC(screen);
        ReleaseDC(nullptr, screen);
        BITMAPINFO bi{};
        bi.bmiHeader = {sizeof(BITMAPINFOHEADER), pixels_.cx, -pixels_.cy, 1, 32, BI_RGB};
        void *bits = nullptr;
        bitmap_ = memDC_ ? CreateDIBSection(memDC_, &bi, DIB_RGB_COLORS, &bits, nullptr, 0) : nullptr;
        if (!bitmap_) {
            releaseSurface();
            return;
        }
        oldBitmap_ = SelectObject(memDC_, bitmap_);
        auto props = D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_DEFAULT,
                                                  D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED),
                                                  static_cast<float>(dpi_), static_cast<float>(dpi_));
        if (!gfx::d2d() || FAILED(gfx::d2d()->CreateDCRenderTarget(&props, &target_))) {
            releaseSurface();
            return;
        }
        surface_ = pixels_;
        surfaceDpi_ = dpi_;
    }
    RECT rc{0, 0, pixels_.cx, pixels_.cy};
    if (FAILED(target_->BindDC(memDC_, &rc))) return;
    target_->BeginDraw();
    target_->Clear(D2D1::ColorF(0, 0, 0, 0));
    view_.draw(target_, hover_);
    if (target_->EndDraw() == D2DERR_RECREATE_TARGET) {
        releaseSurface();
        return;
    }
    POINT source{0, 0};
    BLENDFUNCTION blend{AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    UpdateLayeredWindow(hwnd_, nullptr, &origin_, &pixels_, memDC_, &source, 0, &blend, ULW_ALPHA);
}

void CandidateWindow::hide() {
    if (hwnd_) ShowWindow(hwnd_, SW_HIDE);
}

int CandidateWindow::hitAt(LPARAM lParam) const {
    float x = GET_X_LPARAM(lParam) * 96.f / dpi_, y = GET_Y_LPARAM(lParam) * 96.f / dpi_;
    return view_.hitAt(x, y);
}

LRESULT CALLBACK CandidateWindow::wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    auto *self = reinterpret_cast<CandidateWindow *>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    switch (msg) {
    case WM_NCCREATE: {
        auto *cs = reinterpret_cast<CREATESTRUCTW *>(lParam);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(cs->lpCreateParams));
        break;
    }
    case WM_MOUSEACTIVATE:
        return MA_NOACTIVATE;
    case WM_MOUSEMOVE:
        if (self) {
            int hit = self->hitAt(lParam);
            if (hit != self->hover_) {
                self->hover_ = hit;
                self->render();
            }
            TRACKMOUSEEVENT tme{sizeof tme, TME_LEAVE, hwnd, 0};
            TrackMouseEvent(&tme);
        }
        return 0;
    case WM_MOUSELEAVE:
        if (self && self->hover_ >= 0) {
            self->hover_ = -1;
            self->render();
        }
        return 0;
    case WM_LBUTTONUP:
        if (self) {
            int hit = self->hitAt(lParam);
            if (hit >= 0 && self->view_.hits()[hit].enabled) {
                const cand::Hit h = self->view_.hits()[hit];
                if (h.candidate >= 0) self->owner_->chooseCandidate(h.candidate);
                else self->owner_->segmentAction(h.key);
            }
        }
        return 0;
    case WM_NCDESTROY:
        if (self) self->hwnd_ = nullptr;
        break;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

}  // namespace maimusi
