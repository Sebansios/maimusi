#include "displayattr.h"

#include <algorithm>
#include <new>

#include "globals.h"

namespace maimusi {

namespace {

TF_DISPLAYATTRIBUTE attribute(TF_DA_LINESTYLE line, BOOL bold, TF_DA_ATTR_INFO info, bool highlighted) {
    TF_DISPLAYATTRIBUTE a{};
    a.crText.type = highlighted ? TF_CT_SYSCOLOR : TF_CT_NONE;
    a.crText.nIndex = COLOR_HIGHLIGHTTEXT;
    a.crBk.type = highlighted ? TF_CT_SYSCOLOR : TF_CT_NONE;
    a.crBk.nIndex = COLOR_HIGHLIGHT;
    a.lsStyle = line;
    a.fBoldLine = bold;
    a.crLine.type = TF_CT_NONE;
    a.bAttr = info;
    return a;
}

const GUID *const kGuids[] = {&GUID_MaimusiAttrInput, &GUID_MaimusiAttrConverted, &GUID_MaimusiAttrTarget};

}  // namespace

DisplayAttributeInfo *DisplayAttributeInfo::create(REFGUID guid) {
    if (guid == GUID_MaimusiAttrInput)
        return new (std::nothrow)
            DisplayAttributeInfo(guid, L"입력 중", attribute(TF_LS_DOT, FALSE, TF_ATTR_INPUT, false));
    if (guid == GUID_MaimusiAttrConverted)
        return new (std::nothrow)
            DisplayAttributeInfo(guid, L"띄어쓰기 변환", attribute(TF_LS_SOLID, FALSE, TF_ATTR_CONVERTED, false));
    if (guid == GUID_MaimusiAttrTarget)
        return new (std::nothrow)
            DisplayAttributeInfo(guid, L"선택한 어절", attribute(TF_LS_SOLID, TRUE, TF_ATTR_TARGET_CONVERTED, true));
    return nullptr;
}

DisplayAttributeInfo::DisplayAttributeInfo(const GUID &guid, const wchar_t *desc, const TF_DISPLAYATTRIBUTE &attr)
    : guid_(guid), desc_(desc), attr_(attr) {
    DllAddRef();
}

DisplayAttributeInfo::~DisplayAttributeInfo() { DllRelease(); }

STDMETHODIMP DisplayAttributeInfo::QueryInterface(REFIID riid, void **ppv) {
    if (!ppv) return E_INVALIDARG;
    if (riid == IID_IUnknown || riid == IID_ITfDisplayAttributeInfo) {
        *ppv = static_cast<ITfDisplayAttributeInfo *>(this);
        AddRef();
        return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
}

STDMETHODIMP_(ULONG) DisplayAttributeInfo::AddRef() { return InterlockedIncrement(&refs_); }

STDMETHODIMP_(ULONG) DisplayAttributeInfo::Release() {
    LONG n = InterlockedDecrement(&refs_);
    if (!n) delete this;
    return n;
}

STDMETHODIMP DisplayAttributeInfo::GetGUID(GUID *guid) {
    if (!guid) return E_INVALIDARG;
    *guid = guid_;
    return S_OK;
}

STDMETHODIMP DisplayAttributeInfo::GetDescription(BSTR *desc) {
    if (!desc) return E_INVALIDARG;
    *desc = SysAllocString(desc_);
    return *desc ? S_OK : E_OUTOFMEMORY;
}

STDMETHODIMP DisplayAttributeInfo::GetAttributeInfo(TF_DISPLAYATTRIBUTE *attr) {
    if (!attr) return E_INVALIDARG;
    *attr = attr_;
    return S_OK;
}

DisplayAttributeEnum::DisplayAttributeEnum() { DllAddRef(); }

DisplayAttributeEnum::~DisplayAttributeEnum() { DllRelease(); }

STDMETHODIMP DisplayAttributeEnum::QueryInterface(REFIID riid, void **ppv) {
    if (!ppv) return E_INVALIDARG;
    if (riid == IID_IUnknown || riid == IID_IEnumTfDisplayAttributeInfo) {
        *ppv = static_cast<IEnumTfDisplayAttributeInfo *>(this);
        AddRef();
        return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
}

STDMETHODIMP_(ULONG) DisplayAttributeEnum::AddRef() { return InterlockedIncrement(&refs_); }

STDMETHODIMP_(ULONG) DisplayAttributeEnum::Release() {
    LONG n = InterlockedDecrement(&refs_);
    if (!n) delete this;
    return n;
}

STDMETHODIMP DisplayAttributeEnum::Clone(IEnumTfDisplayAttributeInfo **ppEnum) {
    if (!ppEnum) return E_INVALIDARG;
    auto *e = new (std::nothrow) DisplayAttributeEnum();
    if (!e) return E_OUTOFMEMORY;
    e->index_ = index_;
    *ppEnum = e;
    return S_OK;
}

STDMETHODIMP DisplayAttributeEnum::Next(ULONG count, ITfDisplayAttributeInfo **info, ULONG *fetched) {
    if (!info) return E_INVALIDARG;
    ULONG n = 0;
    while (n < count && index_ < ARRAYSIZE(kGuids)) {
        info[n] = DisplayAttributeInfo::create(*kGuids[index_]);
        if (!info[n]) break;
        ++n;
        ++index_;
    }
    if (fetched) *fetched = n;
    return n == count ? S_OK : S_FALSE;
}

STDMETHODIMP DisplayAttributeEnum::Reset() {
    index_ = 0;
    return S_OK;
}

STDMETHODIMP DisplayAttributeEnum::Skip(ULONG count) {
    index_ = std::min<ULONG>(ARRAYSIZE(kGuids), index_ + count);
    return index_ < ARRAYSIZE(kGuids) ? S_OK : S_FALSE;
}

}  // namespace maimusi
