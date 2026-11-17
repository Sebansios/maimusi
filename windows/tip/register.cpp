// COM registration (InprocServer32) and the TSF input profile and categories.
#include "register.h"

#include <windows.h>
#include <msctf.h>
#include <shlwapi.h>

#include <string>

#include "globals.h"
#include "product.h"

namespace maimusi {

namespace {

std::wstring clsidKey() {
    wchar_t guid[64];
    StringFromGUID2(CLSID_MaimusiTextService, guid, 64);
    return std::wstring(L"CLSID\\") + guid;
}

std::wstring modulePath() {
    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(g_hInst, path, MAX_PATH);
    return std::wstring(path, n);
}

bool setString(HKEY key, const wchar_t *name, const std::wstring &value) {
    return RegSetValueExW(key, name, 0, REG_SZ, reinterpret_cast<const BYTE *>(value.c_str()),
                          static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t))) == ERROR_SUCCESS;
}

const GUID kCategories[] = {
    GUID_TFCAT_TIP_KEYBOARD,
    GUID_TFCAT_DISPLAYATTRIBUTEPROVIDER,
    GUID_TFCAT_TIPCAP_IMMERSIVESUPPORT,
    GUID_TFCAT_TIPCAP_SYSTRAYSUPPORT,
    GUID_TFCAT_TIPCAP_INPUTMODECOMPARTMENT,
    GUID_TFCAT_TIPCAP_COMLESS,
};

}  // namespace

bool RegisterServer() {
    HKEY key = nullptr, inproc = nullptr;
    bool ok = RegCreateKeyExW(HKEY_CLASSES_ROOT, clsidKey().c_str(), 0, nullptr, 0, KEY_WRITE, nullptr, &key, nullptr) ==
              ERROR_SUCCESS;
    if (ok) {
        ok = setString(key, nullptr, MAIMUSI_NAME_KO);
        ok = ok && RegCreateKeyExW(key, L"InprocServer32", 0, nullptr, 0, KEY_WRITE, nullptr, &inproc, nullptr) ==
                       ERROR_SUCCESS;
        ok = ok && setString(inproc, nullptr, modulePath()) && setString(inproc, L"ThreadingModel", L"Apartment");
    }
    if (inproc) RegCloseKey(inproc);
    if (key) RegCloseKey(key);
    return ok;
}

void UnregisterServer() { SHDeleteKeyW(HKEY_CLASSES_ROOT, clsidKey().c_str()); }

// TSF's own keys for this text service (one 64-bit view shared by both DLLs).
std::wstring tipKey() {
    wchar_t guid[64];
    StringFromGUID2(CLSID_MaimusiTextService, guid, 64);
    return std::wstring(L"SOFTWARE\\Microsoft\\CTF\\TIP\\") + guid;
}

bool keyExists(const std::wstring &path) {
    HKEY key = nullptr;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, path.c_str(), 0, KEY_READ | KEY_WOW64_64KEY, &key) != ERROR_SUCCESS)
        return false;
    RegCloseKey(key);
    return true;
}

std::wstring guidString(const GUID &g) {
    wchar_t text[64];
    StringFromGUID2(g, text, 64);
    return text;
}

bool RegisterProfile() {
    // Updating an existing installation: re-registering the profile makes
    // Windows switch every running application away from this input method,
    // so only point its icon at the new DLL.
    std::wstring profile = tipKey() + L"\\LanguageProfile\\0x00000412\\" + guidString(GUID_MaimusiProfile);
    HKEY key = nullptr;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, profile.c_str(), 0, KEY_SET_VALUE | KEY_WOW64_64KEY, &key) == ERROR_SUCCESS) {
        bool ok = setString(key, L"IconFile", modulePath());
        RegCloseKey(key);
        return ok;
    }
    ITfInputProcessorProfileMgr *mgr = nullptr;
    if (FAILED(CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr, CLSCTX_INPROC_SERVER,
                                IID_ITfInputProcessorProfileMgr, reinterpret_cast<void **>(&mgr))))
        return false;
    std::wstring name = MAIMUSI_NAME_KO;
    std::wstring icon = modulePath();
    HRESULT hr = mgr->RegisterProfile(CLSID_MaimusiTextService, MAIMUSI_LANGID, GUID_MaimusiProfile, name.c_str(),
                                      static_cast<ULONG>(name.size()), icon.c_str(), static_cast<ULONG>(icon.size()),
                                      static_cast<UINT>(-IDI_MAIMUSI), nullptr, 0, TRUE, 0);
    mgr->Release();
    return SUCCEEDED(hr);
}

void UnregisterProfile() {
    ITfInputProcessorProfileMgr *mgr = nullptr;
    if (FAILED(CoCreateInstance(CLSID_TF_InputProcessorProfiles, nullptr, CLSCTX_INPROC_SERVER,
                                IID_ITfInputProcessorProfileMgr, reinterpret_cast<void **>(&mgr))))
        return;
    mgr->UnregisterProfile(CLSID_MaimusiTextService, MAIMUSI_LANGID, GUID_MaimusiProfile, 0);
    mgr->Release();
}

bool RegisterCategories() {
    ITfCategoryMgr *mgr = nullptr;
    if (FAILED(CoCreateInstance(CLSID_TF_CategoryMgr, nullptr, CLSCTX_INPROC_SERVER, IID_ITfCategoryMgr,
                                reinterpret_cast<void **>(&mgr))))
        return false;
    bool ok = true;
    std::wstring self = guidString(CLSID_MaimusiTextService);
    for (const GUID &cat : kCategories) {
        // Only what is missing: re-registering also disturbs running applications.
        if (keyExists(tipKey() + L"\\Category\\Category\\" + guidString(cat) + L"\\" + self)) continue;
        ok = SUCCEEDED(mgr->RegisterCategory(CLSID_MaimusiTextService, cat, CLSID_MaimusiTextService)) && ok;
    }
    mgr->Release();
    return ok;
}

void UnregisterCategories() {
    ITfCategoryMgr *mgr = nullptr;
    if (FAILED(CoCreateInstance(CLSID_TF_CategoryMgr, nullptr, CLSCTX_INPROC_SERVER, IID_ITfCategoryMgr,
                                reinterpret_cast<void **>(&mgr))))
        return;
    for (const GUID &cat : kCategories) mgr->UnregisterCategory(CLSID_MaimusiTextService, cat, CLSID_MaimusiTextService);
    mgr->Release();
    // The calls above leave the (now empty) category tree of this TIP behind.
    wchar_t guid[64];
    StringFromGUID2(CLSID_MaimusiTextService, guid, 64);
    std::wstring key = std::wstring(L"SOFTWARE\\Microsoft\\CTF\\TIP\\") + guid;
    SHDeleteKeyW(HKEY_LOCAL_MACHINE, key.c_str());
}

}  // namespace maimusi
