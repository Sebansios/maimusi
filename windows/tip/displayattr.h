// Display attributes of the composition: raw input (dotted underline), the
// spaced conversion (solid underline) and its selected word (highlighted).
#pragma once

#include <windows.h>
#include <msctf.h>

namespace maimusi {

class DisplayAttributeInfo final : public ITfDisplayAttributeInfo {
public:
    // Null for an unknown GUID.
    static DisplayAttributeInfo *create(REFGUID guid);

    STDMETHODIMP QueryInterface(REFIID riid, void **ppv) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    STDMETHODIMP GetGUID(GUID *guid) override;
    STDMETHODIMP GetDescription(BSTR *desc) override;
    STDMETHODIMP GetAttributeInfo(TF_DISPLAYATTRIBUTE *attr) override;
    STDMETHODIMP SetAttributeInfo(const TF_DISPLAYATTRIBUTE *) override { return E_NOTIMPL; }
    STDMETHODIMP Reset() override { return S_OK; }

private:
    DisplayAttributeInfo(const GUID &guid, const wchar_t *desc, const TF_DISPLAYATTRIBUTE &attr);
    ~DisplayAttributeInfo();
    LONG refs_ = 1;
    GUID guid_;
    const wchar_t *desc_;
    TF_DISPLAYATTRIBUTE attr_;
};

class DisplayAttributeEnum final : public IEnumTfDisplayAttributeInfo {
public:
    DisplayAttributeEnum();

    STDMETHODIMP QueryInterface(REFIID riid, void **ppv) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    STDMETHODIMP Clone(IEnumTfDisplayAttributeInfo **ppEnum) override;
    STDMETHODIMP Next(ULONG count, ITfDisplayAttributeInfo **info, ULONG *fetched) override;
    STDMETHODIMP Reset() override;
    STDMETHODIMP Skip(ULONG count) override;

private:
    ~DisplayAttributeEnum();
    LONG refs_ = 1;
    ULONG index_ = 0;
};

}  // namespace maimusi
