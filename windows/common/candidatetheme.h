// The candidate window's look: the same presets and fields as macOS
// (macos/Sources/CandidateTheme.swift), so both systems show the same window.
// Settings: candidatePreset (preset id, default "glass") and candidateTextSize
// ("normal", "large", "xlarge"), as on macOS. macOS can also save a custom theme
// ("custom", edited field by field); Windows offers the presets only and shows
// the default for "custom".
//
// Windows draws every backdrop itself: macOS materials and Liquid Glass become
// the translucent fills macOS uses for its own offscreen pictures (no blur),
// and fonts are Malgun Gothic (sans and system) and Batang (serif).
#pragma once

#include <windows.h>
#include <d2d1.h>

#include <string>
#include <vector>

namespace maimusi {

class Settings;

namespace cand {

enum class Corner { Squircle, Rounded, Square };
enum class Backdrop { Menu, Popover, Hud, Glass, ClearGlass, Solid };
enum class Selection { Fill, Underline, Bar };
enum class Family { Sans, Serif, System };

struct Theme {
    Corner corner = Corner::Squircle;
    float radius = 14;
    Backdrop backdrop = Backdrop::Popover;
    // "#RRGGBB" or "#RRGGBBAA"; null: the system color (light or dark).
    const char *background = nullptr;
    const char *border = nullptr;
    Family family = Family::Sans;
    float fontSize = 15;
    const char *text = nullptr;
    const char *secondary = nullptr;
    Selection selection = Selection::Fill;
    const char *selectionColor = nullptr;
    const char *selectionText = nullptr;
    bool horizontal = false;
    bool showNumbers = true;
    bool showNotes = true;
    bool showTools = true;
    bool showHint = false;
    float padding = 8;

    float cornerRadius() const { return corner == Corner::Square ? 0 : radius; }
    // Selected rows: smaller than the window's corner, same curve.
    float innerRadius() const;
    bool glass() const { return backdrop == Backdrop::Glass || backdrop == Backdrop::ClearGlass; }
    // Text size option: font, padding and corner grow together.
    Theme scaled(float factor) const;
};

struct Preset {
    const char *id;
    const wchar_t *name;
    const wchar_t *summary;
    Theme theme;
};

const std::vector<Preset> &presets();
const Preset *preset(const std::string &id);
constexpr const char *kDefaultPreset = "glass";

struct TextScale {
    const char *id;
    const wchar_t *name;
    float factor;
};
extern const TextScale kTextScales[3];

// The preset id in effect (unknown ids and "custom" fall back to the default).
std::string presetId(const Settings &s);
// The theme of the settings, with the text size applied.
Theme current(const Settings &s);

// Colors with the system theme filled in.
struct Palette {
    D2D1_COLOR_F background, border, text, secondary, selectionFill, selectionText;
    bool hasBorder;
};
Palette palette(const Theme &theme, bool dark, D2D1_COLOR_F accent);

// "#RRGGBB" / "#RRGGBBAA" (sRGB); false when null or malformed.
bool parseColor(const char *hex, D2D1_COLOR_F &out);
const wchar_t *familyName(Family family);

}  // namespace cand
}  // namespace maimusi
