// DLL entry points: COM class factory and self-registration (regsvr32).
#include <windows.h>
#include <msctf.h>

#include <new>

#include "candidatewindow.h"
#include "globals.h"
#include "register.h"
#include "textservice.h"

HINSTANCE g_hInst = nullptr;
static LONG g_dllRefs = 0;

// {1A36DDCD-E1AE-4B54-AAF1-EF5418F4B25B}
const CLSID CLSID_MaimusiTextService = {0x1a36ddcd, 0xe1ae, 0x4b54, {0xaa, 0xf1, 0xef, 0x54, 0x18, 0xf4, 0xb2, 0x5b}};
// {3BE0990F-7425-4407-81CB-4C4C3CEC4A50}
const GUID GUID_MaimusiProfile = {0x3be0990f, 0x7425, 0x4407, {0x81, 0xcb, 0x4c, 0x4c, 0x3c, 0xec, 0x4a, 0x50}};
// {B67BA668-986C-4CF0-9736-8331D61AF61C}
const GUID GUID_MaimusiAttrInput = {0xb67ba668, 0x986c, 0x4cf0, {0x97, 0x36, 0x83, 0x31, 0xd6, 0x1a, 0xf6, 0x1c}};
// {C624352F-0ED5-4F3F-925F-59D0F19DD950}
const GUID GUID_MaimusiAttrConverted = {0xc624352f, 0x0ed5, 0x4f3f, {0x92, 0x5f, 0x59, 0xd0, 0xf1, 0x9d, 0xd9, 0x50}};
// {7F268F04-BF7A-46E6-A115-23EE3CE5CFF8}
const GUID GUID_MaimusiAttrTarget = {0x7f268f04, 0xbf7a, 0x46e6, {0xa1, 0x15, 0x23, 0xee, 0x3c, 0xe5, 0xcf, 0xf8}};
// {19D424C3-C4AA-4C20-B66D-8274AD3B0C5E}
const GUID GUID_MaimusiGlobalHangul = {0x19d424c3, 0xc4aa, 0x4c20, {0xb6, 0x6d, 0x82, 0x74, 0xad, 0x3b, 0x0c, 0x5e}};

STDAPI DllUnregisterServer();

void DllAddRef() { InterlockedIncrement(&g_dllRefs); }
void DllRelease() { InterlockedDecrement(&g_dllRefs); }

namespace {

class ClassFactory final : public IClassFactory {
public:
    STDMETHODIMP QueryInterface(REFIID riid, void **ppv) override {
        if (!ppv) return E_INVALIDARG;
        if (riid == IID_IUnknown || riid == IID_IClassFactory) {
            *ppv = static_cast<IClassFactory *>(this);
            DllAddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override {
        DllAddRef();
        return 2;
    }
    STDMETHODIMP_(ULONG) Release() override {
        DllRelease();
        return 1;
    }
    STDMETHODIMP CreateInstance(IUnknown *outer, REFIID riid, void **ppv) override {
        if (!ppv) return E_INVALIDARG;
        *ppv = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        auto *service = new (std::nothrow) maimusi::TextService();
        if (!service) return E_OUTOFMEMORY;
        HRESULT hr = service->QueryInterface(riid, ppv);
        service->Release();
        return hr;
    }
    STDMETHODIMP LockServer(BOOL lock) override {
        lock ? DllAddRef() : DllRelease();
        return S_OK;
    }
};

ClassFactory g_factory;

}  // namespace

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_hInst = instance;
        DisableThreadLibraryCalls(instance);
    } else if (reason == DLL_PROCESS_DETACH) {
        maimusi::CandidateWindow::unregisterClass();
    }
    return TRUE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void **ppv) {
    if (!ppv) return E_INVALIDARG;
    *ppv = nullptr;
    if (clsid != CLSID_MaimusiTextService) return CLASS_E_CLASSNOTAVAILABLE;
    return g_factory.QueryInterface(riid, ppv);
}

STDAPI DllCanUnloadNow() { return g_dllRefs <= 0 ? S_OK : S_FALSE; }

STDAPI DllRegisterServer() {
    if (!maimusi::RegisterServer() || !maimusi::RegisterProfile() || !maimusi::RegisterCategories()) {
        DllUnregisterServer();
        return E_FAIL;
    }
    return S_OK;
}

STDAPI DllUnregisterServer() {
    maimusi::UnregisterProfile();
    maimusi::UnregisterCategories();
    maimusi::UnregisterServer();
    return S_OK;
}
