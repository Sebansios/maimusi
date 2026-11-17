#include "textservice.h"

#include <ctffunc.h>
#include <imm.h>
#include <inputscope.h>
#include <shellapi.h>

#include <new>
#include <vector>

#include "../common/text.h"
#include "candidatewindow.h"
#include "displayattr.h"
#include "engine.h"
#include "globals.h"
#include "langbar.h"
#include "log.h"

namespace maimusi {

namespace {

// Global Hangul/English value: 0 unset, 1 English, 2 Hangul.
constexpr DWORD kGlobalEnglish = 1, kGlobalHangul = 2;

// GUID_PROP_INPUTSCOPE (InputScope.h declares it; no import library defines it).
const GUID kPropInputScope = {0x1713dd5a, 0x68e7, 0x4a5b, {0x9a, 0xf6, 0x59, 0x2a, 0x59, 0x5c, 0x77, 0x8d}};

// Fields whose text is never learned from: passwords and private text,
// addresses and login names, numbers, telephone numbers, single characters.
bool privateScope(InputScope scope) {
    switch (scope) {
    case IS_PASSWORD:
    case IS_PRIVATE:
    case IS_NUMERIC_PASSWORD:
    case IS_NUMERIC_PIN:
    case IS_ALPHANUMERIC_PIN:
    case IS_ALPHANUMERIC_PIN_SET:
    case IS_EMAIL_SMTPEMAILADDRESS:
    case IS_EMAIL_USERNAME:
    case IS_URL:
    case IS_LOGINNAME:
    case IS_NUMBER:
    case IS_DIGITS:
    case IS_TELEPHONE_FULLTELEPHONENUMBER:
    case IS_TELEPHONE_COUNTRYCODE:
    case IS_TELEPHONE_AREACODE:
    case IS_TELEPHONE_LOCALNUMBER:
    case IS_ONECHAR:
        return true;
    default:
        return false;
    }
}

class EditSession final : public ITfEditSession {
public:
    explicit EditSession(std::function<HRESULT(TfEditCookie)> body) : body_(std::move(body)) {}
    STDMETHODIMP QueryInterface(REFIID riid, void **ppv) override {
        if (!ppv) return E_INVALIDARG;
        if (riid == IID_IUnknown || riid == IID_ITfEditSession) {
            *ppv = static_cast<ITfEditSession *>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    STDMETHODIMP_(ULONG) Release() override {
        LONG n = InterlockedDecrement(&refs_);
        if (!n) delete this;
        return n;
    }
    STDMETHODIMP DoEditSession(TfEditCookie ec) override { return body_(ec); }

private:
    LONG refs_ = 1;
    std::function<HRESULT(TfEditCookie)> body_;
};

template <class T> void release(T *&p) {
    if (p) {
        p->Release();
        p = nullptr;
    }
}

bool down(int vk) { return (GetKeyState(vk) & 0x8000) != 0; }

bool isModifierOnly(WPARAM vk) {
    switch (vk) {
    case VK_SHIFT: case VK_LSHIFT: case VK_RSHIFT:
    case VK_CONTROL: case VK_LCONTROL: case VK_RCONTROL:
    case VK_MENU: case VK_LMENU: case VK_RMENU:
    case VK_LWIN: case VK_RWIN: case VK_CAPITAL: case VK_NUMLOCK: case VK_SCROLL:
    case VK_PROCESSKEY: case VK_PACKET:
        return true;
    }
    return false;
}

}  // namespace

TextService::TextService() { DllAddRef(); }

TextService::~TextService() { DllRelease(); }

STDMETHODIMP TextService::QueryInterface(REFIID riid, void **ppv) {
    if (!ppv) return E_INVALIDARG;
    *ppv = nullptr;
    if (riid == IID_IUnknown || riid == IID_ITfTextInputProcessor || riid == IID_ITfTextInputProcessorEx)
        *ppv = static_cast<ITfTextInputProcessorEx *>(this);
    else if (riid == IID_ITfThreadMgrEventSink)
        *ppv = static_cast<ITfThreadMgrEventSink *>(this);
    else if (riid == IID_ITfKeyEventSink)
        *ppv = static_cast<ITfKeyEventSink *>(this);
    else if (riid == IID_ITfCompositionSink)
        *ppv = static_cast<ITfCompositionSink *>(this);
    else if (riid == IID_ITfDisplayAttributeProvider)
        *ppv = static_cast<ITfDisplayAttributeProvider *>(this);
    else if (riid == IID_ITfCompartmentEventSink)
        *ppv = static_cast<ITfCompartmentEventSink *>(this);
    else if (riid == IID_ITfThreadFocusSink)
        *ppv = static_cast<ITfThreadFocusSink *>(this);
    if (!*ppv) return E_NOINTERFACE;
    AddRef();
    return S_OK;
}

STDMETHODIMP_(ULONG) TextService::AddRef() { return InterlockedIncrement(&refs_); }

STDMETHODIMP_(ULONG) TextService::Release() {
    LONG n = InterlockedDecrement(&refs_);
    if (!n) delete this;
    return n;
}

// MARK: Activation

STDMETHODIMP TextService::Activate(ITfThreadMgr *threadMgr, TfClientId clientId) {
    return ActivateEx(threadMgr, clientId, 0);
}

STDMETHODIMP TextService::ActivateEx(ITfThreadMgr *threadMgr, TfClientId clientId, DWORD) {
    Log::write("activate");
    threadMgr_ = threadMgr;
    threadMgr_->AddRef();
    clientId_ = clientId;
    session_ = hc_session_new();
    applySettingsIfChanged();

    ITfSource *source = nullptr;
    if (SUCCEEDED(threadMgr_->QueryInterface(IID_ITfSource, reinterpret_cast<void **>(&source)))) {
        source->AdviseSink(IID_ITfThreadMgrEventSink, static_cast<ITfThreadMgrEventSink *>(this), &threadMgrCookie_);
        source->AdviseSink(IID_ITfThreadFocusSink, static_cast<ITfThreadFocusSink *>(this), &threadFocusCookie_);
        source->Release();
    }
    ITfKeystrokeMgr *keys = nullptr;
    if (SUCCEEDED(threadMgr_->QueryInterface(IID_ITfKeystrokeMgr, reinterpret_cast<void **>(&keys)))) {
        keySinkAdvised_ = SUCCEEDED(keys->AdviseKeyEventSink(clientId_, static_cast<ITfKeyEventSink *>(this), TRUE));
        keys->Release();
    }
    ITfCategoryMgr *cats = nullptr;
    if (SUCCEEDED(CoCreateInstance(CLSID_TF_CategoryMgr, nullptr, CLSCTX_INPROC_SERVER, IID_ITfCategoryMgr,
                                   reinterpret_cast<void **>(&cats)))) {
        cats->RegisterGUID(GUID_MaimusiAttrInput, &atomInput_);
        cats->RegisterGUID(GUID_MaimusiAttrConverted, &atomConverted_);
        cats->RegisterGUID(GUID_MaimusiAttrTarget, &atomTarget_);
        cats->Release();
    }
    candidates_ = new (std::nothrow) CandidateWindow(this);
    langBar_ = new (std::nothrow) LangBarButton(this);
    if (langBar_) {
        ITfLangBarItemMgr *items = nullptr;
        if (SUCCEEDED(threadMgr_->QueryInterface(IID_ITfLangBarItemMgr, reinterpret_cast<void **>(&items)))) {
            items->AddItem(langBar_);
            items->Release();
        }
    }
    initCompartments();
    DWORD global = compartmentValue(GUID_MaimusiGlobalHangul, true);
    setMode(global != kGlobalEnglish, false);
    EngineHub::shared().warmUp();
    return S_OK;
}

STDMETHODIMP TextService::Deactivate() {
    Log::write("deactivate");
    if (active() && compositionContext_) commitAll(compositionContext_, true);
    if (candidates_) {
        candidates_->destroy();
        candidates_ = nullptr;
    }
    if (langBar_) {
        ITfLangBarItemMgr *items = nullptr;
        if (SUCCEEDED(threadMgr_->QueryInterface(IID_ITfLangBarItemMgr, reinterpret_cast<void **>(&items)))) {
            items->RemoveItem(langBar_);
            items->Release();
        }
        langBar_->detach();
        release(langBar_);
    }
    uninitCompartments();
    if (keySinkAdvised_) {
        ITfKeystrokeMgr *keys = nullptr;
        if (SUCCEEDED(threadMgr_->QueryInterface(IID_ITfKeystrokeMgr, reinterpret_cast<void **>(&keys)))) {
            keys->UnadviseKeyEventSink(clientId_);
            keys->Release();
        }
        keySinkAdvised_ = false;
    }
    ITfSource *source = nullptr;
    if (SUCCEEDED(threadMgr_->QueryInterface(IID_ITfSource, reinterpret_cast<void **>(&source)))) {
        if (threadMgrCookie_ != TF_INVALID_COOKIE) source->UnadviseSink(threadMgrCookie_);
        if (threadFocusCookie_ != TF_INVALID_COOKIE) source->UnadviseSink(threadFocusCookie_);
        source->Release();
    }
    threadMgrCookie_ = threadFocusCookie_ = TF_INVALID_COOKIE;
    release(composition_);
    release(compositionContext_);
    converting_ = floating_ = false;
    if (session_) {
        hc_session_free(session_);
        session_ = nullptr;
    }
    release(threadMgr_);
    clientId_ = TF_CLIENTID_NULL;
    return S_OK;
}

void TextService::applySettingsIfChanged() {
    EngineHub &hub = EngineHub::shared();
    unsigned gen = hub.generation();
    if (gen == settingsGeneration_ || !session_) return;
    settingsGeneration_ = gen;
    Settings s = hub.settings();
    for (auto &[key, value] : s.sessionOptions()) hc_session_set_option(session_, key.c_str(), value.c_str());
    rightAltToggles_ = s.getBool("rightAltToggles");
}

// MARK: Hangul/English mode

bool TextService::initCompartments() {
    ITfCompartmentMgr *mgr = nullptr;
    if (FAILED(threadMgr_->QueryInterface(IID_ITfCompartmentMgr, reinterpret_cast<void **>(&mgr)))) return false;
    auto advise = [&](ITfCompartmentMgr *m, REFGUID guid, DWORD &cookie) {
        ITfCompartment *c = nullptr;
        if (SUCCEEDED(m->GetCompartment(guid, &c))) {
            ITfSource *source = nullptr;
            if (SUCCEEDED(c->QueryInterface(IID_ITfSource, reinterpret_cast<void **>(&source)))) {
                source->AdviseSink(IID_ITfCompartmentEventSink, static_cast<ITfCompartmentEventSink *>(this), &cookie);
                source->Release();
            }
            c->Release();
        }
    };
    advise(mgr, GUID_COMPARTMENT_KEYBOARD_OPENCLOSE, openCookie_);
    advise(mgr, GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION, conversionCookie_);
    mgr->Release();
    // The Hangul/English mode shared by all applications: follow it live.
    ITfCompartmentMgr *global = nullptr;
    if (SUCCEEDED(threadMgr_->GetGlobalCompartment(&global))) {
        advise(global, GUID_MaimusiGlobalHangul, globalCookie_);
        global->Release();
    }
    return true;
}

void TextService::uninitCompartments() {
    ITfCompartmentMgr *mgr = nullptr;
    if (FAILED(threadMgr_->QueryInterface(IID_ITfCompartmentMgr, reinterpret_cast<void **>(&mgr)))) return;
    auto unadvise = [&](ITfCompartmentMgr *m, REFGUID guid, DWORD &cookie) {
        if (cookie == TF_INVALID_COOKIE) return;
        ITfCompartment *c = nullptr;
        if (SUCCEEDED(m->GetCompartment(guid, &c))) {
            ITfSource *source = nullptr;
            if (SUCCEEDED(c->QueryInterface(IID_ITfSource, reinterpret_cast<void **>(&source)))) {
                source->UnadviseSink(cookie);
                source->Release();
            }
            c->Release();
        }
        cookie = TF_INVALID_COOKIE;
    };
    unadvise(mgr, GUID_COMPARTMENT_KEYBOARD_OPENCLOSE, openCookie_);
    unadvise(mgr, GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION, conversionCookie_);
    mgr->Release();
    ITfCompartmentMgr *global = nullptr;
    if (SUCCEEDED(threadMgr_->GetGlobalCompartment(&global))) {
        unadvise(global, GUID_MaimusiGlobalHangul, globalCookie_);
        global->Release();
    }
}

DWORD TextService::compartmentValue(REFGUID guid, bool global) {
    ITfCompartmentMgr *mgr = nullptr;
    HRESULT hr = global ? threadMgr_->GetGlobalCompartment(&mgr)
                        : threadMgr_->QueryInterface(IID_ITfCompartmentMgr, reinterpret_cast<void **>(&mgr));
    if (FAILED(hr)) return 0;
    DWORD result = 0;
    ITfCompartment *c = nullptr;
    if (SUCCEEDED(mgr->GetCompartment(guid, &c))) {
        VARIANT v;
        VariantInit(&v);
        if (c->GetValue(&v) == S_OK && v.vt == VT_I4) result = static_cast<DWORD>(v.lVal);
        c->Release();
    }
    mgr->Release();
    return result;
}

void TextService::setCompartmentValue(REFGUID guid, DWORD value, bool global) {
    ITfCompartmentMgr *mgr = nullptr;
    HRESULT hr = global ? threadMgr_->GetGlobalCompartment(&mgr)
                        : threadMgr_->QueryInterface(IID_ITfCompartmentMgr, reinterpret_cast<void **>(&mgr));
    if (FAILED(hr)) return;
    ITfCompartment *c = nullptr;
    if (SUCCEEDED(mgr->GetCompartment(guid, &c))) {
        VARIANT v;
        v.vt = VT_I4;
        v.lVal = static_cast<LONG>(value);
        c->SetValue(clientId_, &v);
        c->Release();
    }
    mgr->Release();
}

void TextService::setMode(bool hangul, bool publishGlobal) {
    hangul_ = hangul;
    settingMode_ = true;
    // Korean IMM applications read the conversion mode (IME_CMODE_HANGUL is
    // TF_CONVERSIONMODE_NATIVE); keep the keyboard open in both modes, the way
    // the Microsoft Korean IME does, so the 한/영 key keeps reaching us.
    setCompartmentValue(GUID_COMPARTMENT_KEYBOARD_OPENCLOSE, TRUE, false);
    DWORD conv = compartmentValue(GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION, false);
    conv = hangul ? (conv | TF_CONVERSIONMODE_NATIVE) : (conv & ~TF_CONVERSIONMODE_NATIVE);
    setCompartmentValue(GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION, conv, false);
    if (publishGlobal) setCompartmentValue(GUID_MaimusiGlobalHangul, hangul ? kGlobalHangul : kGlobalEnglish, true);
    settingMode_ = false;
    if (langBar_) langBar_->update();
    Log::write("mode %s", hangul ? "hangul" : "english");
}

void TextService::toggleMode() { setMode(!hangul_, true); }

STDMETHODIMP TextService::OnChange(REFGUID guid) {
    if (settingMode_ || !threadMgr_) return S_OK;
    if (guid == GUID_MaimusiGlobalHangul) {
        DWORD global = compartmentValue(GUID_MaimusiGlobalHangul, true);
        if (global && (global == kGlobalHangul) != hangul_) {
            if (global != kGlobalHangul && compositionContext_) commitAll(compositionContext_, false);
            setMode(global == kGlobalHangul, false);
        }
        return S_OK;
    }
    if (guid == GUID_COMPARTMENT_KEYBOARD_OPENCLOSE || guid == GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION) {
        DWORD open = compartmentValue(GUID_COMPARTMENT_KEYBOARD_OPENCLOSE, false);
        DWORD conv = compartmentValue(GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION, false);
        bool hangul = open && (conv & TF_CONVERSIONMODE_NATIVE);
        Log::write("compartment change: open %lu conversion %#lx", open, conv);
        if (hangul != hangul_) {
            if (!hangul && compositionContext_) commitAll(compositionContext_, false);
            // Set by the application (IMM conversion mode, a field that wants
            // Latin input): follow it here only. The mode shared by all
            // applications changes only with the user's 한/영 key or the indicator.
            setMode(hangul, false);
        }
    }
    return S_OK;
}

// MARK: Focus

STDMETHODIMP TextService::OnSetFocus(ITfDocumentMgr *focus, ITfDocumentMgr *) {
    if (active() && compositionContext_) commitAll(compositionContext_, false);
    if (candidates_) candidates_->hide();
    if (focus && threadMgr_) {
        DWORD global = compartmentValue(GUID_MaimusiGlobalHangul, true);
        if (global && (global == kGlobalHangul) != hangul_) setMode(global == kGlobalHangul, false);
        EngineHub::shared().warmUp();
    }
    return S_OK;
}

STDMETHODIMP TextService::OnSetThreadFocus() {
    if (!threadMgr_) return S_OK;
    DWORD global = compartmentValue(GUID_MaimusiGlobalHangul, true);
    if (global && (global == kGlobalHangul) != hangul_) setMode(global == kGlobalHangul, false);
    return S_OK;
}

STDMETHODIMP TextService::OnKillThreadFocus() {
    if (candidates_) candidates_->hide();
    return S_OK;
}

// MARK: Keys

TextService::Mapped TextService::mapKey(WPARAM vk, LPARAM lParam) const {
    Mapped m;
    if (vk == VK_HANGUL) {
        m.kind = Key::Toggle;
        return m;
    }
    if (vk == VK_HANJA) {
        m.kind = Key::Hanja;
        return m;
    }
    if (isModifierOnly(vk)) return m;
    bool shift = down(VK_SHIFT), ctrl = down(VK_CONTROL), alt = down(VK_MENU);
    bool win = down(VK_LWIN) || down(VK_RWIN);
    m.kind = Key::Char;
    if (ctrl && shift && !alt && !win && vk == 'R') {
        m.kind = Key::EditSelection;
        return m;
    }
    if (ctrl || alt || win) return m;  // HC_KEY_OTHER
    switch (vk) {
    case VK_SPACE: m.coreKey = shift ? HC_KEY_SHIFT_SPACE : HC_KEY_SPACE; return m;
    case VK_BACK: m.coreKey = HC_KEY_BACKSPACE; return m;
    case VK_RETURN: m.coreKey = HC_KEY_ENTER; return m;
    case VK_TAB: m.coreKey = HC_KEY_TAB; return m;
    case VK_ESCAPE: m.coreKey = HC_KEY_ESCAPE; return m;
    case VK_LEFT: m.coreKey = shift ? HC_KEY_SHRINK_SEGMENT : HC_KEY_LEFT; return m;
    case VK_RIGHT: m.coreKey = shift ? HC_KEY_EXPAND_SEGMENT : HC_KEY_RIGHT; return m;
    case VK_UP: m.coreKey = shift ? HC_KEY_OTHER : HC_KEY_UP; return m;
    case VK_DOWN: m.coreKey = shift ? HC_KEY_OTHER : HC_KEY_DOWN; return m;
    }
    // Letters by physical position (virtual keys of the Korean layout are
    // QWERTY) so the jamo do not depend on Caps Lock or a Latin layout.
    if (vk >= 'A' && vk <= 'Z') {
        m.coreKey = HC_KEY_CHAR;
        m.ch = shift ? static_cast<uint32_t>(vk) : static_cast<uint32_t>(vk - 'A' + 'a');
        return m;
    }
    // Digits and symbols: the character the keyboard layout produces.
    BYTE state[256];
    if (!GetKeyboardState(state)) return m;
    state[VK_CONTROL] = state[VK_LCONTROL] = state[VK_RCONTROL] = 0;
    state[VK_MENU] = state[VK_LMENU] = state[VK_RMENU] = 0;
    wchar_t buf[8];
    // Flag 4: do not change the keyboard state (dead keys), Windows 10 1607+.
    int n = ToUnicodeEx(static_cast<UINT>(vk), (lParam >> 16) & 0xFF, state, buf, 8, 4, GetKeyboardLayout(0));
    if (n == 1 && buf[0] >= 0x20 && buf[0] != 0x7F) {
        m.coreKey = HC_KEY_CHAR;
        m.ch = buf[0];
    }
    return m;
}

bool TextService::keyboardDisabled(ITfContext *context) {
    // Nothing editable has focus (a web page body, a video player, a list):
    // the keys are the application's shortcuts, not text.
    if (!context) return true;
    ITfCompartmentMgr *mgr = nullptr;
    if (SUCCEEDED(context->QueryInterface(IID_ITfCompartmentMgr, reinterpret_cast<void **>(&mgr)))) {
        bool disabled = false;
        for (const GUID *guid : {&GUID_COMPARTMENT_KEYBOARD_DISABLED, &GUID_COMPARTMENT_EMPTYCONTEXT}) {
            ITfCompartment *c = nullptr;
            if (SUCCEEDED(mgr->GetCompartment(*guid, &c))) {
                VARIANT v;
                VariantInit(&v);
                if (c->GetValue(&v) == S_OK && v.vt == VT_I4 && v.lVal) disabled = true;
                c->Release();
            }
        }
        mgr->Release();
        if (disabled) return true;
    }
    TF_STATUS status{};
    return SUCCEEDED(context->GetStatus(&status)) && (status.dwDynamicFlags & TF_SD_READONLY);
}

bool TextService::wouldEat(ITfContext *context, WPARAM vk, LPARAM lParam) {
    Mapped m = mapKey(vk, lParam);
    // The 한/영 key always switches modes; everything else is left to the
    // application unless the focused context takes text (or a composition is open).
    if (m.kind == Key::Toggle) return true;
    if (!active() && keyboardDisabled(context)) return false;
    switch (m.kind) {
    case Key::Toggle: return true;
    case Key::None: return false;
    case Key::Hanja: return hangul_ && active();
    case Key::EditSelection: return hangul_ && !active();
    case Key::Char: break;
    }
    if (!hangul_) return false;
    if (active()) return true;
    return m.coreKey == HC_KEY_CHAR;
}

STDMETHODIMP TextService::OnSetFocus(BOOL) { return S_OK; }

STDMETHODIMP TextService::OnTestKeyDown(ITfContext *context, WPARAM wParam, LPARAM lParam, BOOL *eaten) {
    applySettingsIfChanged();
    if (rightAltToggles_ && wParam == VK_MENU && (lParam & (1 << 24))) {
        rightAltDown_ = rightAltClean_ = true;
    } else if (!isModifierOnly(wParam)) {
        rightAltClean_ = false;
    }
    *eaten = wouldEat(context, wParam, lParam);
    Log::write("test key down vk %#x eaten %d", mapKey(wParam, lParam).coreKey == HC_KEY_CHAR ? 0u : (unsigned)wParam, *eaten);
    return S_OK;
}

STDMETHODIMP TextService::OnKeyDown(ITfContext *context, WPARAM wParam, LPARAM lParam, BOOL *eaten) {
    applySettingsIfChanged();
    *eaten = FALSE;
    if (!session_ || !wouldEat(context, wParam, lParam)) return S_OK;
    Mapped m = mapKey(wParam, lParam);
    Log::write("key down vk %#x", m.coreKey == HC_KEY_CHAR ? 0u : (unsigned)wParam);
    EngineHub &hub = EngineHub::shared();
    hc_output out{};
    switch (m.kind) {
    case Key::Toggle:
        Log::write("key down VK_HANGUL");
        if (active()) commitAll(context, true);
        toggleMode();
        *eaten = TRUE;
        break;
    case Key::Hanja:
        hc_session_key(session_, converting_ ? HC_KEY_DOWN : HC_KEY_SPACE, 0, hub.backend(), &out);
        apply(context, out);
        *eaten = TRUE;
        break;
    case Key::EditSelection:
        *eaten = editSelection(context);
        break;
    default:
        hc_session_key(session_, m.coreKey, m.ch, hub.backend(), &out);
        apply(context, out);
        takeLearning();
        *eaten = out.consumed;
        break;
    }
    if (wParam < 256) eatenDown_[wParam] = *eaten != FALSE;
    return S_OK;
}

STDMETHODIMP TextService::OnTestKeyUp(ITfContext *, WPARAM wParam, LPARAM lParam, BOOL *eaten) {
    *eaten = wParam < 256 && eatenDown_[wParam];
    if (rightAltToggles_ && wParam == VK_MENU && (lParam & (1 << 24)) && rightAltDown_ && rightAltClean_) *eaten = TRUE;
    return S_OK;
}

STDMETHODIMP TextService::OnKeyUp(ITfContext *context, WPARAM wParam, LPARAM lParam, BOOL *eaten) {
    *eaten = wParam < 256 && eatenDown_[wParam];
    if (wParam < 256) eatenDown_[wParam] = false;
    if (rightAltToggles_ && wParam == VK_MENU && (lParam & (1 << 24))) {
        if (rightAltDown_ && rightAltClean_) {
            if (active()) commitAll(context, true);
            toggleMode();
            *eaten = TRUE;
        }
        rightAltDown_ = rightAltClean_ = false;
    }
    return S_OK;
}

// MARK: Document edits

HRESULT TextService::editSession(ITfContext *context, std::function<HRESULT(TfEditCookie)> body, bool sync) {
    if (!context) return E_INVALIDARG;
    auto *session = new (std::nothrow) EditSession(std::move(body));
    if (!session) return E_OUTOFMEMORY;
    HRESULT result = E_FAIL;
    HRESULT hr = context->RequestEditSession(clientId_, session,
                                             (sync ? TF_ES_SYNC : TF_ES_ASYNCDONTCARE) | TF_ES_READWRITE, &result);
    if (sync && hr == TF_E_SYNCHRONOUS) {
        hr = context->RequestEditSession(clientId_, session, TF_ES_ASYNCDONTCARE | TF_ES_READWRITE, &result);
    }
    session->Release();
    return FAILED(hr) ? hr : result;
}

void TextService::apply(ITfContext *context, const hc_output &out, bool sync) {
    std::wstring commit = widen(out.commit);
    std::wstring preedit = widen(out.preedit);
    bool converting = out.highlight_start >= 0;
    int hs = out.highlight_start, hl = out.highlight_len;
    if (!context) context = compositionContext_;
    if (context && (!commit.empty() || !preedit.empty() || composition_)) {
        ITfContext *ctx = context;
        ctx->AddRef();
        editSession(ctx, [this, ctx, commit, preedit, hs, hl, converting](TfEditCookie ec) {
            HRESULT hr = applyIn(ec, ctx, commit, preedit, hs, hl, converting);
            ctx->Release();
            return hr;
        }, sync);
    }
    converting_ = converting;
    updateCandidates(out);
}

void TextService::setAttribute(TfEditCookie ec, ITfContext *context, ITfRange *range, TfGuidAtom atom) {
    ITfProperty *prop = nullptr;
    if (FAILED(context->GetProperty(GUID_PROP_ATTRIBUTE, &prop))) return;
    if (atom == TF_INVALID_GUIDATOM) {
        prop->Clear(ec, range);
    } else {
        VARIANT v;
        v.vt = VT_I4;
        v.lVal = static_cast<LONG>(atom);
        prop->SetValue(ec, range, &v);
    }
    prop->Release();
}

HRESULT TextService::applyIn(TfEditCookie ec, ITfContext *context, const std::wstring &commit,
                             const std::wstring &preedit, int hs, int hl, bool converting) {
    Log::write("apply: commit %zu preedit %zu composition %d", commit.size(), preedit.size(), composition_ != nullptr);
    auto caretAfter = [&](ITfRange *r) {
        ITfRange *caret = nullptr;
        if (SUCCEEDED(r->Clone(&caret))) {
            caret->Collapse(ec, TF_ANCHOR_END);
            TF_SELECTION sel{};
            sel.range = caret;
            sel.style.ase = TF_AE_NONE;
            sel.style.fInterimChar = FALSE;
            context->SetSelection(ec, 1, &sel);
            caret->Release();
        }
    };
    auto endComposition = [&] {
        if (!composition_) return;
        composition_->EndComposition(ec);
        release(composition_);
        release(compositionContext_);
    };

    if (!commit.empty()) {
        ITfRange *range = nullptr;
        if (composition_ && SUCCEEDED(composition_->GetRange(&range))) {
            range->SetText(ec, 0, commit.c_str(), static_cast<LONG>(commit.size()));
            setAttribute(ec, context, range, TF_INVALID_GUIDATOM);
            caretAfter(range);
            range->Release();
            endComposition();
        } else {
            ITfInsertAtSelection *insert = nullptr;
            if (SUCCEEDED(context->QueryInterface(IID_ITfInsertAtSelection, reinterpret_cast<void **>(&insert)))) {
                if (SUCCEEDED(insert->InsertTextAtSelection(ec, 0, commit.c_str(), static_cast<LONG>(commit.size()),
                                                            &range))) {
                    caretAfter(range);
                    range->Release();
                }
                insert->Release();
            }
        }
    }

    // Applications reached through the IMM32 bridge (transitory contexts:
    // classic EDIT controls, messengers and word processors that handle
    // WM_IME_* themselves) take a Korean composition only as one interim
    // syllable and commit everything before it. The phrase stays editable
    // until Space, so there it is shown in the floating window at the caret
    // and only the committed text enters the document.
    if (needsFloating(context)) {
        if (composition_) endComposition();
        bool floating = !preedit.empty();
        bool starting = floating && !floating_;
        if (floating != floating_) {
            floating_ = floating;
            if (floating) {
                release(compositionContext_);
                compositionContext_ = context;
                compositionContext_->AddRef();
            } else {
                release(compositionContext_);
            }
        }
        if (floating) {
            ITfInsertAtSelection *insert = nullptr;
            ITfRange *at = nullptr;
            if (SUCCEEDED(context->QueryInterface(IID_ITfInsertAtSelection, reinterpret_cast<void **>(&insert))) &&
                SUCCEEDED(insert->InsertTextAtSelection(ec, TF_IAS_QUERYONLY, nullptr, 0, &at))) {
                if (starting) readInputScope(ec, context, at);
                positionCandidates(ec, context, at);
            }
            if (at) at->Release();
            if (insert) insert->Release();
        }
        return S_OK;
    }

    if (preedit.empty()) {
        if (composition_) {
            ITfRange *range = nullptr;
            if (SUCCEEDED(composition_->GetRange(&range))) {
                range->SetText(ec, 0, L"", 0);
                range->Release();
            }
            endComposition();
        }
        return S_OK;
    }

    if (!composition_) {
        ITfInsertAtSelection *insert = nullptr;
        ITfContextComposition *cc = nullptr;
        ITfRange *at = nullptr;
        if (SUCCEEDED(context->QueryInterface(IID_ITfInsertAtSelection, reinterpret_cast<void **>(&insert))) &&
            SUCCEEDED(insert->InsertTextAtSelection(ec, TF_IAS_QUERYONLY, nullptr, 0, &at)) &&
            SUCCEEDED(context->QueryInterface(IID_ITfContextComposition, reinterpret_cast<void **>(&cc)))) {
            readInputScope(ec, context, at);
            ITfCompositionSink *sink = this;
            if (SUCCEEDED(cc->StartComposition(ec, at, sink, &composition_)) && composition_) {
                compositionContext_ = context;
                compositionContext_->AddRef();
            }
        }
        if (at) at->Release();
        if (cc) cc->Release();
        if (insert) insert->Release();
        if (!composition_) {
            Log::write("StartComposition failed");
            return E_FAIL;
        }
    }
    ITfRange *range = nullptr;
    if (FAILED(composition_->GetRange(&range))) return E_FAIL;
    range->SetText(ec, 0, preedit.c_str(), static_cast<LONG>(preedit.size()));
    setAttribute(ec, context, range, converting ? atomConverted_ : atomInput_);
    ITfRange *target = nullptr;
    if (converting && hs >= 0 && hl > 0 && hs + hl <= static_cast<int>(preedit.size()) &&
        SUCCEEDED(range->Clone(&target))) {
        LONG moved = 0;
        target->Collapse(ec, TF_ANCHOR_START);
        target->ShiftEnd(ec, hs + hl, &moved, nullptr);
        target->ShiftStart(ec, hs, &moved, nullptr);
        setAttribute(ec, context, target, atomTarget_);
    }
    // Korean compositions select the syllable being composed as an interim
    // character, as Korean applications expect.
    LONG lastLen = preedit.size() >= 2 && IS_LOW_SURROGATE(preedit.back()) ? 2 : 1;
    ITfRange *interim = nullptr;
    if (!converting && SUCCEEDED(range->Clone(&interim))) {
        LONG moved = 0;
        interim->Collapse(ec, TF_ANCHOR_END);
        interim->ShiftStart(ec, -lastLen, &moved, nullptr);
        TF_SELECTION sel{};
        sel.range = interim;
        sel.style.ase = TF_AE_NONE;
        sel.style.fInterimChar = TRUE;
        if (FAILED(context->SetSelection(ec, 1, &sel))) caretAfter(range);
        interim->Release();
    } else {
        caretAfter(range);
    }
    if (converting) positionCandidates(ec, context, target ? target : range);
    if (target) target->Release();
    range->Release();
    return S_OK;
}

bool TextService::needsFloating(ITfContext *context) {
    // Transitory text stores hold only the composition. TSF applications
    // such as Chromium-based ones report that too but compose inline fine;
    // the IMM32 bridge is the one that cuts Korean compositions to a single
    // syllable, and its windows have an input context.
    TF_STATUS status{};
    if (FAILED(context->GetStatus(&status))) return false;
    bool transitory = (status.dwStaticFlags & TF_SS_TRANSITORY) != 0;
    HWND hwnd = nullptr;
    ITfContextView *view = nullptr;
    if (SUCCEEDED(context->GetActiveView(&view))) {
        view->GetWnd(&hwnd);
        view->Release();
    }
    bool imm = false;
    if (hwnd) {
        HIMC imc = ImmGetContext(hwnd);
        imm = imc != nullptr;
        if (imc) ImmReleaseContext(hwnd, imc);
    }
    if (Log::enabled()) {
        wchar_t cls[64] = L"", exe[MAX_PATH] = L"";
        if (hwnd) GetClassNameW(hwnd, cls, 64);
        GetModuleFileNameW(nullptr, exe, MAX_PATH);
        const wchar_t *name = wcsrchr(exe, L'\\');
        Log::write("context static %#lx dynamic %#lx window %ls imc %d in %ls", status.dwStaticFlags,
                   status.dwDynamicFlags, cls, imm, name ? name + 1 : exe);
    }
    // Observed on Windows 11: the IMM32 bridge reports only TS_SS_TRANSITORY and
    // sets high (undocumented) dynamic flags; Chromium/Electron add
    // TS_SS_NOHIDDENTEXT and compose inline correctly.
    bool bridge = (status.dwDynamicFlags & 0xC0000000) != 0 || !(status.dwStaticFlags & TS_SS_NOHIDDENTEXT);
    return transitory && imm && bridge;
}

void TextService::positionCandidates(TfEditCookie ec, ITfContext *context, ITfRange *range) {
    if (!candidates_) return;
    ITfContextView *view = nullptr;
    if (FAILED(context->GetActiveView(&view))) return;
    RECT rc{};
    BOOL clipped = FALSE;
    HRESULT hr = view->GetTextExt(ec, range, &rc, &clipped);
    // A caret rectangle is often zero wide: only an empty height is invalid.
    bool ok = hr == S_OK && rc.bottom > rc.top;
    // Applications that never tell the IMM bridge where their caret is report
    // a default position; ignore one whose corner lies outside the focused window.
    RECT window;
    POINT corner{rc.left, rc.top};
    if (ok && GetFocus() && GetWindowRect(GetFocus(), &window)) {
        InflateRect(&window, 2, 2);
        if (!PtInRect(&window, corner)) ok = false;
    }
    Log::write("text ext hr %#lx rect %ld,%ld,%ld,%ld used %d", hr, rc.left, rc.top, rc.right, rc.bottom, ok);
    if (ok) {
        candidates_->setAnchor(rc);
    } else {
        // No layout yet (TF_E_NOLAYOUT): fall back to the system caret.
        GUITHREADINFO gui{sizeof gui};
        if (GetGUIThreadInfo(GetCurrentThreadId(), &gui) && gui.hwndCaret) {
            RECT caret = gui.rcCaret;
            MapWindowPoints(gui.hwndCaret, nullptr, reinterpret_cast<POINT *>(&caret), 2);
            candidates_->setAnchor(caret);
        } else if (HWND focus = GetFocus()) {
            // No caret either: the top-left corner of the focused window.
            RECT rc;
            GetWindowRect(focus, &rc);
            rc.bottom = rc.top + 24;
            candidates_->setAnchor(rc);
        }
    }
    view->Release();
}

void TextService::updateCandidates(const hc_output &out) {
    if (!candidates_) return;
    bool converting = out.highlight_start >= 0;
    if (!converting && !floating_) {
        candidates_->hide();
        return;
    }
    cand::Content content;
    for (uint32_t i = 0; i < out.candidate_count; ++i) {
        content.items.push_back(widen(hc_session_candidate(session_, i)));
        content.notes.push_back(widen(hc_session_candidate_note(session_, i)));
    }
    if (floating_) content.preedit = widen(out.preedit);
    content.hs = out.highlight_start;
    content.hl = out.highlight_len;
    content.converting = converting;
    content.selected = out.candidate_index;
    content.actions = hc_session_segment_actions(session_);
    // A remembered spacing shaped this phrase: say so (it can be forgotten from the menu).
    content.remembered = converting && EngineHub::shared().usesLearned(out.preedit ? out.preedit : "");
    candidates_->show(EngineHub::shared().candidateTheme(), content);
}

void TextService::commitAll(ITfContext *context, bool sync) {
    if (!session_) return;
    hc_output out{};
    hc_session_commit(session_, EngineHub::shared().backend(), &out);
    apply(context, out, sync);
    takeLearning();
}

void TextService::readInputScope(TfEditCookie ec, ITfContext *context, ITfRange *range) {
    noLearning_ = false;
    ITfProperty *prop = nullptr;
    if (!context || !range || FAILED(context->GetProperty(kPropInputScope, &prop)) || !prop) return;
    VARIANT v;
    VariantInit(&v);
    if (SUCCEEDED(prop->GetValue(ec, range, &v)) && v.vt == VT_UNKNOWN && v.punkVal) {
        ITfInputScope *scope = nullptr;
        if (SUCCEEDED(v.punkVal->QueryInterface(__uuidof(ITfInputScope), reinterpret_cast<void **>(&scope)))) {
            InputScope *scopes = nullptr;
            UINT count = 0;
            if (SUCCEEDED(scope->GetInputScopes(&scopes, &count)) && scopes) {
                for (UINT i = 0; i < count && !noLearning_; ++i) noLearning_ = privateScope(scopes[i]);
                CoTaskMemFree(scopes);
            }
            scope->Release();
        }
    }
    VariantClear(&v);
    prop->Release();
    if (noLearning_) Log::write("input scope: nothing is learned in this field");
}

void TextService::takeLearning() {
    const char *raw = hc_session_take_learning(session_);
    if (!raw) return;
    // A password, address, number or similar field (the engine itself also
    // skips text with addresses or paths, and text without Hangul).
    if (noLearning_) return;
    std::string s(raw);
    size_t sep = s.find('\x1f');
    if (sep == std::string::npos) return;
    EngineHub::shared().learn(s.substr(0, sep), s.substr(sep + 1));
}

bool TextService::editSelection(ITfContext *context) {
    if (!context || active()) return false;
    bool started = false;
    hc_output out{};
    ITfContext *ctx = context;
    editSession(ctx, [&](TfEditCookie ec) -> HRESULT {
        TF_SELECTION sel{};
        ULONG fetched = 0;
        if (FAILED(ctx->GetSelection(ec, TF_DEFAULT_SELECTION, 1, &sel, &fetched)) || fetched != 1) return E_FAIL;
        std::vector<wchar_t> buf(1002);
        ULONG got = 0;
        HRESULT hr = sel.range->GetText(ec, 0, buf.data(), static_cast<ULONG>(buf.size() - 1), &got);
        std::wstring text(buf.data(), got);
        // Empty, multi-line and oversized selections are not edited.
        if (FAILED(hr) || text.empty() || got > 1000 || text.find_first_of(L"\r\n") != std::wstring::npos) {
            sel.range->Release();
            return E_FAIL;
        }
        hc_session_edit_selection(session_, narrow(text).c_str(), &out);
        if (!out.consumed) {
            sel.range->Release();
            return E_FAIL;
        }
        ITfContextComposition *cc = nullptr;
        if (SUCCEEDED(ctx->QueryInterface(IID_ITfContextComposition, reinterpret_cast<void **>(&cc)))) {
            readInputScope(ec, ctx, sel.range);
            if (SUCCEEDED(cc->StartComposition(ec, sel.range, this, &composition_)) && composition_) {
                compositionContext_ = ctx;
                compositionContext_->AddRef();
                started = true;
            }
            cc->Release();
        }
        sel.range->Release();
        if (!started) {
            hc_output reset{};
            hc_session_reset(session_, &reset);
            return E_FAIL;
        }
        return applyIn(ec, ctx, L"", widen(out.preedit), out.highlight_start, out.highlight_len,
                       out.highlight_start >= 0);
    }, true);
    if (!started) return false;
    converting_ = out.highlight_start >= 0;
    updateCandidates(out);
    return true;
}

STDMETHODIMP TextService::OnCompositionTerminated(TfEditCookie ec, ITfComposition *composition) {
    Log::write("composition terminated by the application");
    if (Log::enabled()) {
        void *frames[24];
        USHORT n = CaptureStackBackTrace(0, 24, frames, nullptr);
        for (USHORT i = 0; i < n; ++i) {
            HMODULE mod = nullptr;
            wchar_t name[MAX_PATH] = L"?";
            if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                   static_cast<LPCWSTR>(frames[i]), &mod))
                GetModuleFileNameW(mod, name, MAX_PATH);
            const wchar_t *base = wcsrchr(name, L'\\');
            Log::write("  #%u %ls+%#llx", i, base ? base + 1 : name,
                       static_cast<unsigned long long>(static_cast<char *>(frames[i]) - reinterpret_cast<char *>(mod)));
        }
    }
    if (composition != composition_ || !session_) return S_OK;
    hc_output out{};
    hc_session_commit(session_, EngineHub::shared().backend(), &out);
    std::wstring commit = widen(out.commit);
    ITfRange *range = nullptr;
    if (SUCCEEDED(composition_->GetRange(&range))) {
        if (compositionContext_) {
            range->SetText(ec, 0, commit.c_str(), static_cast<LONG>(commit.size()));
            setAttribute(ec, compositionContext_, range, TF_INVALID_GUIDATOM);
        }
        range->Release();
    }
    release(composition_);
    release(compositionContext_);
    converting_ = false;
    if (candidates_) candidates_->hide();
    takeLearning();
    return S_OK;
}

// MARK: Candidate window and menu actions

void TextService::chooseCandidate(int index) {
    if (!session_ || !compositionContext_) return;
    hc_output out{};
    hc_session_select_candidate(session_, static_cast<uint32_t>(index), &out);
    apply(compositionContext_, out, false);
}

void TextService::segmentAction(uint32_t key) {
    if (!session_ || !compositionContext_ || !converting_) return;
    hc_output out{};
    // Boundary operations never ask the automatic spacing backend to run.
    hc_session_key(session_, key, 0, nullptr, &out);
    apply(compositionContext_, out, false);
}

void TextService::openSettings() {
    std::wstring exe = EngineHub::shared().locate(L"MaimusiSettings.exe");
    ShellExecuteW(nullptr, L"open", exe.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
}

void TextService::toggleAutoSpacing() {
    Settings s;
    s.update([](Settings &edit) { edit.set("convertOnSpace", !edit.getBool("convertOnSpace")); });
}

void TextService::selectEngine(const char *engine) {
    std::string value = engine;
    Settings s;
    s.update([&](Settings &edit) { edit.set("engine", value); });
    EngineHub::shared().warmUp();
}

void TextService::forgetLastLearned() {
    Settings s;
    s.update([](Settings &edit) { edit.forgetLastLearned(); });
    EngineHub::shared().wordbookChanged();
}

// MARK: ITfDisplayAttributeProvider

STDMETHODIMP TextService::EnumDisplayAttributeInfo(IEnumTfDisplayAttributeInfo **ppEnum) {
    if (!ppEnum) return E_INVALIDARG;
    *ppEnum = new (std::nothrow) DisplayAttributeEnum();
    return *ppEnum ? S_OK : E_OUTOFMEMORY;
}

STDMETHODIMP TextService::GetDisplayAttributeInfo(REFGUID guid, ITfDisplayAttributeInfo **ppInfo) {
    if (!ppInfo) return E_INVALIDARG;
    *ppInfo = DisplayAttributeInfo::create(guid);
    return *ppInfo ? S_OK : E_INVALIDARG;
}

}  // namespace maimusi
