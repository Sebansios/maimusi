#include "candidatetheme.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>

#include "settings.h"

namespace maimusi::cand {

namespace {

Theme make(Corner corner, float radius, Backdrop backdrop, float fontSize, float padding) {
    Theme t;
    t.corner = corner;
    t.radius = radius;
    t.backdrop = backdrop;
    t.fontSize = fontSize;
    t.padding = padding;
    return t;
}

Theme solid(Corner corner, float radius, const char *background, const char *border, Family family, float fontSize,
            const char *text, const char *secondary, Selection selection, const char *selectionColor,
            const char *selectionText, float padding) {
    Theme t = make(corner, radius, Backdrop::Solid, fontSize, padding);
    t.background = background;
    t.border = border;
    t.family = family;
    t.text = text;
    t.secondary = secondary;
    t.selection = selection;
    t.selectionColor = selectionColor;
    t.selectionText = selectionText;
    return t;
}

std::vector<Preset> makePresets() {
    // Same order, names and values as macOS (CandidateTheme.presets).
    std::vector<Preset> p;
    p.push_back({"glass", L"유리",
                 L"밝은 반투명 바탕과 빛 테두리, 연속 곡률 모서리. macOS의 Liquid Glass에 맞춘 모양(Windows에서는 뒤 화면을 "
                 L"흐리게 비추지 않는다)",
                 make(Corner::Squircle, 18, Backdrop::Glass, 16, 10)});
    p.push_back({"lacquer", L"옻칠", L"흑칠 바탕에 주칠 선택, 한지색 글자",
                 solid(Corner::Squircle, 12, "#120C0AF7", "#2E201A", Family::Sans, 15, "#E8DAC2", "#8E7A68",
                       Selection::Fill, "#B5462F", "#FFF4E6", 8)});
    p.push_back({"hanji", L"한지", L"한지색 바탕, 명조, 각진 모서리, 먹색 밑줄 선택",
                 solid(Corner::Square, 0, "#F4EFE3", "#D6CDB8", Family::Serif, 16, "#2B2A26", "#8C8475",
                       Selection::Underline, "#2F4F4A", "#2F4F4A", 10)});
    p.push_back({"ink", L"먹", L"흰 바탕에 먹색 선택, 흑백만",
                 solid(Corner::Squircle, 8, "#FFFFFF", "#00000024", Family::Sans, 15, "#1A1A1A", "#8A8A8A",
                       Selection::Fill, "#1A1A1A", "#FFFFFF", 6)});
    p.push_back({"celadon", L"청자", L"청자 유약색 바탕, 쪽빛 먹청 선택",
                 solid(Corner::Squircle, 16, "#DCE8E2F7", "#B9CEC4", Family::Sans, 15, "#1F3532", "#5E7A72",
                       Selection::Fill, "#2F4F4A", "#F4F1E8", 9)});
    Theme strip = make(Corner::Squircle, 10, Backdrop::Menu, 15, 6);
    strip.horizontal = true;
    strip.showNotes = false;
    strip.showTools = false;
    p.push_back({"strip", L"가로", L"후보를 한 줄로 늘어놓는 작은 띠", strip});
    Theme quiet = make(Corner::Squircle, 10, Backdrop::Menu, 15, 6);
    quiet.selection = Selection::Bar;
    quiet.showNumbers = false;
    quiet.showTools = false;
    p.push_back({"quiet", L"담백", L"배경을 거의 비우고 선택은 왼쪽 막대로만", quiet});
    Theme classic = make(Corner::Rounded, 6, Backdrop::Menu, 15, 4);
    classic.family = Family::System;
    classic.showHint = true;
    p.push_back({"classic", L"기본(0.5.2)", L"0.5.2까지 macOS 후보 창의 모양", classic});
    return p;
}

D2D1_COLOR_F rgba(float r, float g, float b, float a) { return D2D1::ColorF(r, g, b, a); }

D2D1_COLOR_F hexOr(const char *hex, D2D1_COLOR_F fallback) {
    D2D1_COLOR_F c;
    return parseColor(hex, c) ? c : fallback;
}

}  // namespace

const TextScale kTextScales[3] = {{"normal", L"보통", 1.f}, {"large", L"크게", 1.25f}, {"xlarge", L"아주 크게", 1.5f}};

float Theme::innerRadius() const {
    return corner == Corner::Square ? 0 : std::max(3.f, cornerRadius() - padding / 2 - 2);
}

Theme Theme::scaled(float factor) const {
    if (factor == 1.f) return *this;
    Theme t = *this;
    t.fontSize = std::round(fontSize * factor);
    t.padding = std::round(padding * factor);
    t.radius = std::round(radius * factor);
    return t;
}

const std::vector<Preset> &presets() {
    static const std::vector<Preset> p = makePresets();
    return p;
}

const Preset *preset(const std::string &id) {
    for (const Preset &p : presets())
        if (id == p.id) return &p;
    return nullptr;
}

std::string presetId(const Settings &s) {
    std::string id = s.getString("candidatePreset");
    if (id == "squircle") id = "glass";  // a macOS 0.5.3 test build's name for the same look
    return preset(id) ? id : kDefaultPreset;
}

Theme current(const Settings &s) {
    float factor = 1;
    std::string size = s.getString("candidateTextSize");
    for (const TextScale &t : kTextScales)
        if (size == t.id) factor = t.factor;
    return preset(presetId(s))->theme.scaled(factor);
}

bool parseColor(const char *hex, D2D1_COLOR_F &out) {
    if (!hex || hex[0] != '#') return false;
    size_t n = std::strlen(hex + 1);
    if (n != 6 && n != 8) return false;
    char *end = nullptr;
    unsigned long v = std::strtoul(hex + 1, &end, 16);
    if (!end || *end) return false;
    if (n == 6) v = (v << 8) | 0xFF;
    out = D2D1::ColorF(((v >> 24) & 0xFF) / 255.f, ((v >> 16) & 0xFF) / 255.f, ((v >> 8) & 0xFF) / 255.f, (v & 0xFF) / 255.f);
    return true;
}

const wchar_t *familyName(Family family) { return family == Family::Serif ? L"Batang" : L"Malgun Gothic"; }

Palette palette(const Theme &t, bool dark, D2D1_COLOR_F accent) {
    // The HUD material is always dark; system colors follow it (macOS: vibrantDark).
    if (t.backdrop == Backdrop::Hud) dark = true;
    Palette p{};
    // macOS labelColor and secondaryLabelColor.
    p.text = hexOr(t.text, dark ? rgba(1, 1, 1, 0.85f) : rgba(0, 0, 0, 0.85f));
    p.secondary = hexOr(t.secondary, dark ? rgba(1, 1, 1, 0.55f) : rgba(0, 0, 0, 0.5f));
    p.selectionFill = hexOr(t.selectionColor, accent);
    p.selectionText = hexOr(t.selectionText, t.selection == Selection::Fill ? rgba(1, 1, 1, 1) : p.selectionFill);
    // The fills macOS uses for its own offscreen pictures of the materials.
    const char *fill = nullptr, *edge = nullptr;
    switch (t.backdrop) {
    case Backdrop::Solid: fill = dark ? "#323232" : "#ECECEC"; break;  // windowBackgroundColor
    case Backdrop::Glass: fill = dark ? "#3A3A3CC7" : "#FFFFFFC2"; edge = dark ? "#FFFFFF33" : "#FFFFFFE6"; break;
    case Backdrop::ClearGlass: fill = dark ? "#3A3A3C99" : "#FFFFFF99"; edge = dark ? "#FFFFFF33" : "#FFFFFFE6"; break;
    case Backdrop::Hud: fill = "#1E1E1EE6"; break;
    case Backdrop::Menu:
    case Backdrop::Popover: fill = dark ? "#2B2B2BF2" : "#F4F4F4F2"; break;
    }
    // A theme color replaces the solid fill, or tints the glass.
    p.background = hexOr(t.background, hexOr(fill, rgba(1, 1, 1, 1)));
    p.hasBorder = parseColor(t.border, p.border) || parseColor(edge, p.border);
    return p;
}

}  // namespace maimusi::cand
