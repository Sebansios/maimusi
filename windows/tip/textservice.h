// The text input processor: one per thread that uses the input method.
// It forwards keys to a core session (core/include/hangul_core.h) and mirrors
// the session output into the document: committed text is inserted, the
// composition is a TSF composition with display attributes.
#pragma once

#include <windows.h>
#include <msctf.h>

#include <functional>
#include <string>

#include "../../core/include/hangul_core.h"

namespace maimusi {

class CandidateWindow;
class LangBarButton;

class TextService final : public ITfTextInputProcessorEx,
                          public ITfThreadMgrEventSink,
                          public ITfKeyEventSink,
                          public ITfCompositionSink,
                          public ITfDisplayAttributeProvider,
                          public ITfCompartmentEventSink,
                          public ITfThreadFocusSink {
public:
    TextService();

    // IUnknown
    STDMETHODIMP QueryInterface(REFIID riid, void **ppv) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    // ITfTextInputProcessor(Ex)
    STDMETHODIMP Activate(ITfThreadMgr *threadMgr, TfClientId clientId) override;
    STDMETHODIMP Deactivate() override;
    STDMETHODIMP ActivateEx(ITfThreadMgr *threadMgr, TfClientId clientId, DWORD flags) override;

    // ITfThreadMgrEventSink
    STDMETHODIMP OnInitDocumentMgr(ITfDocumentMgr *) override { return S_OK; }
    STDMETHODIMP OnUninitDocumentMgr(ITfDocumentMgr *) override { return S_OK; }
    STDMETHODIMP OnSetFocus(ITfDocumentMgr *focus, ITfDocumentMgr *previous) override;
    STDMETHODIMP OnPushContext(ITfContext *) override { return S_OK; }
    STDMETHODIMP OnPopContext(ITfContext *) override { return S_OK; }

    // ITfKeyEventSink
    STDMETHODIMP OnSetFocus(BOOL foreground) override;
    STDMETHODIMP OnTestKeyDown(ITfContext *context, WPARAM wParam, LPARAM lParam, BOOL *eaten) override;
    STDMETHODIMP OnKeyDown(ITfContext *context, WPARAM wParam, LPARAM lParam, BOOL *eaten) override;
    STDMETHODIMP OnTestKeyUp(ITfContext *context, WPARAM wParam, LPARAM lParam, BOOL *eaten) override;
    STDMETHODIMP OnKeyUp(ITfContext *context, WPARAM wParam, LPARAM lParam, BOOL *eaten) override;
    STDMETHODIMP OnPreservedKey(ITfContext *, REFGUID, BOOL *eaten) override {
        *eaten = FALSE;
        return S_OK;
    }

    // ITfCompositionSink
    STDMETHODIMP OnCompositionTerminated(TfEditCookie ec, ITfComposition *composition) override;

    // ITfDisplayAttributeProvider
    STDMETHODIMP EnumDisplayAttributeInfo(IEnumTfDisplayAttributeInfo **ppEnum) override;
    STDMETHODIMP GetDisplayAttributeInfo(REFGUID guid, ITfDisplayAttributeInfo **ppInfo) override;

    // ITfCompartmentEventSink
    STDMETHODIMP OnChange(REFGUID guid) override;

    // ITfThreadFocusSink
    STDMETHODIMP OnSetThreadFocus() override;
    STDMETHODIMP OnKillThreadFocus() override;

    // Hangul (true) or English input.
    bool hangulMode() const { return hangul_; }
    void toggleMode();
    void setMode(bool hangul, bool publishGlobal);

    // From the candidate window and the language bar menu.
    void chooseCandidate(int index);
    void segmentAction(uint32_t key);
    void openSettings();
    void toggleAutoSpacing();
    void selectEngine(const char *engine);
    void forgetLastLearned();

private:
    ~TextService();

    enum class Key { None, Char, Toggle, Hanja, EditSelection };
    struct Mapped {
        Key kind = Key::None;
        uint32_t coreKey = HC_KEY_OTHER;
        uint32_t ch = 0;
    };
    Mapped mapKey(WPARAM vk, LPARAM lParam) const;
    // True when the focused context takes no text (TSF keyboard disabled,
    // empty context or read-only): keys then stay the application's shortcuts.
    static bool keyboardDisabled(ITfContext *context);
    bool wouldEat(ITfContext *context, WPARAM vk, LPARAM lParam);

    bool active() const { return composition_ != nullptr || converting_ || floating_; }
    void applySettingsIfChanged();
    // Runs `body` in a read-write edit session (synchronous when possible).
    HRESULT editSession(ITfContext *context, std::function<HRESULT(TfEditCookie)> body, bool sync);
    void apply(ITfContext *context, const hc_output &out, bool sync = true);
    HRESULT applyIn(TfEditCookie ec, ITfContext *context, const std::wstring &commit, const std::wstring &preedit,
                    int highlightStart, int highlightLen, bool converting);
    void setAttribute(TfEditCookie ec, ITfContext *context, ITfRange *range, TfGuidAtom atom);
    // Applications reached through the IMM32 bridge: the phrase is shown in the floating window.
    bool needsFloating(ITfContext *context);
    void positionCandidates(TfEditCookie ec, ITfContext *context, ITfRange *range);
    void updateCandidates(const hc_output &out);
    void commitAll(ITfContext *context, bool sync);
    bool editSelection(ITfContext *context);
    void takeLearning();
    // Reads the input scope where a composition starts: passwords, addresses,
    // numbers and the like are never learned from (noLearning_).
    void readInputScope(TfEditCookie ec, ITfContext *context, ITfRange *range);

    bool initCompartments();
    void uninitCompartments();
    DWORD compartmentValue(REFGUID guid, bool global);
    void setCompartmentValue(REFGUID guid, DWORD value, bool global);

    LONG refs_ = 1;
    ITfThreadMgr *threadMgr_ = nullptr;
    TfClientId clientId_ = TF_CLIENTID_NULL;
    DWORD threadMgrCookie_ = TF_INVALID_COOKIE;
    DWORD threadFocusCookie_ = TF_INVALID_COOKIE;
    DWORD openCookie_ = TF_INVALID_COOKIE;
    DWORD conversionCookie_ = TF_INVALID_COOKIE;
    DWORD globalCookie_ = TF_INVALID_COOKIE;
    bool keySinkAdvised_ = false;

    hc_session *session_ = nullptr;
    unsigned settingsGeneration_ = 0;
    bool rightAltToggles_ = false;

    ITfComposition *composition_ = nullptr;
    ITfContext *compositionContext_ = nullptr;
    bool converting_ = false;
    // The phrase is shown in the candidate window instead of the document
    // (applications without inline Korean composition, see applyIn).
    bool floating_ = false;
    bool noLearning_ = false;
    bool hangul_ = true;
    bool settingMode_ = false;
    // Keys eaten on key down, so their key up is eaten too.
    bool eatenDown_[256] = {};
    bool rightAltDown_ = false;
    bool rightAltClean_ = false;

    TfGuidAtom atomInput_ = TF_INVALID_GUIDATOM;
    TfGuidAtom atomConverted_ = TF_INVALID_GUIDATOM;
    TfGuidAtom atomTarget_ = TF_INVALID_GUIDATOM;

    CandidateWindow *candidates_ = nullptr;
    LangBarButton *langBar_ = nullptr;
};

}  // namespace maimusi
