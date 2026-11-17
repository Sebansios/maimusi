// The candidate window's content, laid out and drawn with Direct2D the way
// macOS draws it (macos/Sources/CandidateView.swift): rows of number,
// candidate and note, the selection as fill, underline or bar, and a footer
// with the two boundary keys, the hint, 「기억한 띄어쓰기」 and the page. The
// panel has the theme's shape (squircle, rounded or square) and a soft
// shadow around it, on a transparent surface. The text service's window, the
// settings preview and the pictures of `MaimusiSettings --render-candidates`
// all draw with this class.
#pragma once

#include <windows.h>
#include <d2d1.h>
#include <dwrite.h>

#include <cstdint>
#include <string>
#include <vector>

#include "candidatetheme.h"

namespace maimusi::cand {

constexpr int kPageSize = 9;

struct Content {
    // Applications without inline composition (Windows only): the phrase
    // being typed, above the candidates; hs/hl select its word.
    std::wstring preedit;
    int hs = -1, hl = 0;
    bool converting = true;  // false: only the phrase is shown
    std::vector<std::wstring> items, notes;
    int selected = -1;
    uint32_t actions = 0;  // HC_SEGMENT_* bits
    bool remembered = false;

    // The macOS settings preview's example.
    static Content sample();
};

struct Hit {
    D2D1_RECT_F rc;  // DIPs, view coordinates
    int candidate;   // absolute index, or -1
    uint32_t key;    // HC_KEY_* boundary action, or 0
    bool enabled;
};

class View {
public:
    static constexpr float kShadow = 14;  // margin around the panel, in DIPs

    View() = default;
    ~View();
    View(const View &) = delete;
    View &operator=(const View &) = delete;

    // `dark`: the system's app theme; `accent`: its accent color.
    void layout(const Theme &theme, const Content &content, bool dark, D2D1_COLOR_F accent);
    // The whole surface in DIPs: the panel and its shadow margin.
    D2D1_SIZE_F size() const { return size_; }
    // Draws at the target's origin onto what is there (transparent for a window).
    void draw(ID2D1RenderTarget *rt, int hover) const;
    const std::vector<Hit> &hits() const { return hits_; }
    int hitAt(float x, float y) const;
    // Nothing to show (no phrase, no candidates, no footer).
    bool empty() const { return rows_.empty() && tools_.empty() && footerTexts_.empty() && content_.preedit.empty(); }

private:
    struct Row {
        D2D1_RECT_F rc;
        int index;
    };
    struct Tool {
        D2D1_RECT_F rc;
        const wchar_t *cap;
        const wchar_t *title;
        bool enabled;
    };
    void releaseFormats();

    Theme theme_;
    Palette palette_{};
    Content content_;
    IDWriteTextFormat *main_ = nullptr, *small_ = nullptr, *cap_ = nullptr;
    float formatSize_ = 0;
    Family formatFamily_ = Family::Sans;
    D2D1_SIZE_F size_{};
    D2D1_RECT_F panel_{};
    D2D1_RECT_F preedit_{};
    std::vector<Row> rows_;
    std::vector<Tool> tools_;
    std::vector<std::pair<D2D1_RECT_F, std::wstring>> footerTexts_;  // hint, remembered, page
    float numberWidth_ = 0, gap_ = 0, side_ = 9, rowPad_ = 3;
    std::vector<Hit> hits_;
};

}  // namespace maimusi::cand
