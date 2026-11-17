// The input mode indicator (가 / A) in the taskbar. A left click switches
// Hangul/English; a right click opens the input method menu (engine status,
// engine choice, automatic spacing, forgetting what was just learned,
// settings), like the macOS input menu.
#pragma once

#include <windows.h>
#include <msctf.h>

namespace maimusi {

class TextService;

class LangBarButton final : public ITfLangBarItemButton, public ITfSource {
public:
    explicit LangBarButton(TextService *owner);

    // Owner going away: stop calling it.
    void detach() { owner_ = nullptr; }
    // Mode changed: ask the system to redraw the icon.
    void update();

    STDMETHODIMP QueryInterface(REFIID riid, void **ppv) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    // ITfLangBarItem
    STDMETHODIMP GetInfo(TF_LANGBARITEMINFO *info) override;
    STDMETHODIMP GetStatus(DWORD *status) override;
    STDMETHODIMP Show(BOOL) override { return E_NOTIMPL; }
    STDMETHODIMP GetTooltipString(BSTR *tooltip) override;

    // ITfLangBarItemButton
    STDMETHODIMP OnClick(TfLBIClick click, POINT pt, const RECT *area) override;
    STDMETHODIMP InitMenu(ITfMenu *) override { return S_OK; }
    STDMETHODIMP OnMenuSelect(UINT) override { return S_OK; }
    STDMETHODIMP GetIcon(HICON *icon) override;
    STDMETHODIMP GetText(BSTR *text) override;

    // ITfSource
    STDMETHODIMP AdviseSink(REFIID riid, IUnknown *sink, DWORD *cookie) override;
    STDMETHODIMP UnadviseSink(DWORD cookie) override;

private:
    ~LangBarButton();
    void showMenu(POINT pt);

    LONG refs_ = 1;
    TextService *owner_;
    ITfLangBarItemSink *sink_ = nullptr;
};

}  // namespace maimusi
