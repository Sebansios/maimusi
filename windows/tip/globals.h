#pragma once

#include <windows.h>

extern HINSTANCE g_hInst;

void DllAddRef();
void DllRelease();

// Permanent identifiers: Windows keys the input profile, the user's language
// list entry and the COM registration to these. Never change them.
extern const CLSID CLSID_MaimusiTextService;
extern const GUID GUID_MaimusiProfile;
extern const GUID GUID_MaimusiAttrInput;
extern const GUID GUID_MaimusiAttrConverted;
extern const GUID GUID_MaimusiAttrTarget;
// Global compartment holding the Hangul/English mode shared by all applications.
extern const GUID GUID_MaimusiGlobalHangul;

#define MAIMUSI_LANGID MAKELANGID(LANG_KOREAN, SUBLANG_KOREAN)
