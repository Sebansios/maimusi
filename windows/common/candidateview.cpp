#include "candidateview.h"

#include <algorithm>
#include <cmath>

#include "../../core/include/hangul_core.h"
#include "graphics.h"

namespace maimusi::cand {

namespace {

template <class T> void release(T *&p) {
    if (p) {
        p->Release();
        p = nullptr;
    }
}

struct Metrics {
    float width = 0, height = 0, baseline = 0;
};

IDWriteTextLayout *makeLayout(IDWriteTextFormat *format, const std::wstring &text, float maxWidth = 10000) {
    IDWriteTextLayout *layout = nullptr;
    if (format && gfx::dwrite())
        gfx::dwrite()->CreateTextLayout(text.c_str(), static_cast<UINT32>(text.size()), format, maxWidth, 1000, &layout);
    return layout;
}

Metrics measure(IDWriteTextFormat *format, const std::wstring &text) {
    Metrics m;
    IDWriteTextLayout *layout = makeLayout(format, text);
    if (!layout) return m;
    DWRITE_TEXT_METRICS tm{};
    layout->GetMetrics(&tm);
    DWRITE_LINE_METRICS line{};
    UINT32 count = 0;
    layout->GetLineMetrics(&line, 1, &count);
    layout->Release();
    m.width = tm.widthIncludingTrailingWhitespace;
    m.height = tm.height;
    m.baseline = count ? line.baseline : tm.height * 0.8f;
    return m;
}

// Grayscale text (the surface is transparent), with the system's gamma and
// at least the default contrast: Malgun Gothic's hinting keeps it crisp.
IDWriteRenderingParams *textParams() {
    static IDWriteRenderingParams *params = [] {
        IDWriteRenderingParams *system = nullptr, *custom = nullptr;
        if (gfx::dwrite() && SUCCEEDED(gfx::dwrite()->CreateRenderingParams(&system))) {
            gfx::dwrite()->CreateCustomRenderingParams(system->GetGamma(), std::max(1.0f, system->GetEnhancedContrast()), 0.f,
                                                       DWRITE_PIXEL_GEOMETRY_FLAT, DWRITE_RENDERING_MODE_DEFAULT, &custom);
            system->Release();
        }
        return custom;
    }();
    return params;
}

D2D1_COLOR_F withAlpha(D2D1_COLOR_F c, float a) {
    c.a *= a;
    return c;
}

D2D1_RECT_F inflate(D2D1_RECT_F r, float dx, float dy) { return D2D1::RectF(r.left - dx, r.top - dy, r.right + dx, r.bottom + dy); }

// Continuous-curvature corners (macOS CandidateShape.continuous): per corner,
// three cubic Béziers in units of the radius along the incoming (u) and
// outgoing (v) edges.
const float kCurve[9][2] = {{1.08849323f, 0},          {0.86840689f, 0},          {0.63149399f, 0.07491100f},
                            {0.37282392f, 0.16905899f}, {0.16905899f, 0.37282392f}, {0.07491100f, 0.63149399f},
                            {0, 0.86840689f},          {0, 1.08849323f},          {0, 1.52866483f}};

ID2D1Geometry *shape(D2D1_RECT_F r, float radius, Corner corner) {
    ID2D1Factory *f = gfx::d2d();
    if (!f) return nullptr;
    float w = r.right - r.left, h = r.bottom - r.top;
    if (corner == Corner::Rounded && radius > 0) {
        float rr = std::min({radius, w / 2, h / 2});
        ID2D1RoundedRectangleGeometry *g = nullptr;
        f->CreateRoundedRectangleGeometry(D2D1::RoundedRect(r, rr, rr), &g);
        return g;
    }
    float rr = std::max(0.f, std::min(radius, std::min(w, h) / (2 * 1.52866483f)));
    if (corner == Corner::Square || rr <= 0) {
        ID2D1RectangleGeometry *g = nullptr;
        f->CreateRectangleGeometry(r, &g);
        return g;
    }
    struct V {
        float x, y;
    };
    const struct {
        V c, u, v;
    } corners[4] = {{{r.right, r.top}, {1, 0}, {0, 1}},
                    {{r.right, r.bottom}, {0, 1}, {-1, 0}},
                    {{r.left, r.bottom}, {-1, 0}, {0, -1}},
                    {{r.left, r.top}, {0, -1}, {1, 0}}};
    auto pt = [&](const V &c, const V &u, const V &v, float a, float b) {
        return D2D1::Point2F(c.x - a * rr * u.x + b * rr * v.x, c.y - a * rr * u.y + b * rr * v.y);
    };
    ID2D1PathGeometry *path = nullptr;
    ID2D1GeometrySink *sink = nullptr;
    if (FAILED(f->CreatePathGeometry(&path)) || FAILED(path->Open(&sink))) {
        release(path);
        return nullptr;
    }
    for (int i = 0; i < 4; ++i) {
        const auto &k = corners[i];
        D2D1_POINT_2F start = pt(k.c, k.u, k.v, 1.52866483f, 0);
        if (i == 0) sink->BeginFigure(start, D2D1_FIGURE_BEGIN_FILLED);
        else sink->AddLine(start);
        for (int j = 0; j < 9; j += 3)
            sink->AddBezier(D2D1::BezierSegment(pt(k.c, k.u, k.v, kCurve[j][0], kCurve[j][1]),
                                                pt(k.c, k.u, k.v, kCurve[j + 1][0], kCurve[j + 1][1]),
                                                pt(k.c, k.u, k.v, kCurve[j + 2][0], kCurve[j + 2][1])));
    }
    sink->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink->Close();
    sink->Release();
    return path;
}

bool hasFamily(const wchar_t *name) {
    IDWriteFontCollection *fonts = nullptr;
    if (!gfx::dwrite() || FAILED(gfx::dwrite()->GetSystemFontCollection(&fonts, FALSE))) return false;
    UINT32 index = 0;
    BOOL exists = FALSE;
    fonts->FindFamilyName(name, &index, &exists);
    fonts->Release();
    return exists != FALSE;
}

const wchar_t kHint[] = L"← → 어절 · Enter 확정 · Esc 취소";
const wchar_t kRemembered[] = L"기억한 띄어쓰기";

}  // namespace

Content Content::sample() {
    Content c;
    c.items = {L"學校", L"학교", L"🏫", L"學敎", L"hakgyo", L"hakkyo"};
    c.notes = {L"배울 학, 학교 교", L"", L"이모지", L"배울 학, 가르침 교", L"로마자 2000", L"매큔-라이샤워"};
    c.selected = 0;
    c.actions = HC_SEGMENT_SHRINK | HC_SEGMENT_EXPAND;
    return c;
}

View::~View() { releaseFormats(); }

void View::releaseFormats() {
    release(main_);
    release(small_);
    release(cap_);
    formatSize_ = 0;
}

void View::layout(const Theme &theme, const Content &content, bool dark, D2D1_COLOR_F accent) {
    theme_ = theme;
    content_ = content;
    palette_ = palette(theme, dark, accent);
    const float F = theme.fontSize, S = std::max(10.f, F * 0.72f), C = std::max(9.f, S - 1);
    if (!main_ || formatSize_ != F || formatFamily_ != theme.family) {
        releaseFormats();
        const wchar_t *family = familyName(theme.family);
        if (theme.family == Family::Serif && !hasFamily(family)) family = familyName(Family::Sans);
        main_ = gfx::textFormat(F, DWRITE_FONT_WEIGHT_NORMAL, family);
        small_ = gfx::textFormat(S, DWRITE_FONT_WEIGHT_NORMAL, family);
        cap_ = gfx::textFormat(C, DWRITE_FONT_WEIGHT_NORMAL, L"Segoe UI");
        formatSize_ = F;
        formatFamily_ = theme.family;
    }
    rowPad_ = std::max(3.f, F * 0.3f);
    gap_ = F * 0.5f;
    side_ = theme.selection == Selection::Bar ? 12.f : 9.f;
    Metrics mainM = measure(main_, L"가Ag"), smallM = measure(small_, L"가Ag");
    float baseline = std::max(mainM.baseline, smallM.baseline);
    float lineH = baseline + std::max(mainM.height - mainM.baseline, smallM.height - smallM.baseline);
    float rowH = lineH + 2 * rowPad_;
    numberWidth_ = theme.showNumbers ? measure(small_, L"8").width : 0;

    const auto &items = content.items;
    int page = std::max(0, content.selected) / kPageSize;
    int start = page * kPageSize, end = std::min<int>(static_cast<int>(items.size()), start + kPageSize);
    int pages = (static_cast<int>(items.size()) + kPageSize - 1) / kPageSize;
    bool converting = content.converting;

    // Widths: rows, the phrase being typed, the footer.
    std::vector<float> rowW;
    float listW = 0;
    if (converting) {
        for (int i = start; i < end; ++i) {
            float w = side_ + (numberWidth_ ? numberWidth_ + gap_ : 0) + measure(main_, items[i]).width + 9;
            const std::wstring &note = i < static_cast<int>(content.notes.size()) ? content.notes[i] : std::wstring();
            if (theme.showNotes && !theme.horizontal && !note.empty()) w += 2 * gap_ + measure(small_, note).width;
            rowW.push_back(std::ceil(w));
        }
        if (theme.horizontal) {
            for (float w : rowW) listW += w;
            if (!rowW.empty()) listW += 2.f * (rowW.size() - 1);
        } else {
            listW = F * 11;
            for (float w : rowW) listW = std::max(listW, w);
        }
    }
    float preeditW = content.preedit.empty() ? 0 : side_ + measure(main_, content.preedit).width + 9;

    tools_.clear();
    footerTexts_.clear();
    float capH = measure(cap_, L"⇧←").height + 2;
    float footerH = 0, footerW = 0;
    std::vector<float> leftW, rightW;
    if (converting) {
        if (theme.showTools) {
            const struct {
                const wchar_t *cap, *title;
                uint32_t bit;
            } actions[] = {{L"⇧←", L"줄이기", HC_SEGMENT_SHRINK}, {L"⇧→", L"늘리기", HC_SEGMENT_EXPAND}};
            for (const auto &a : actions) {
                tools_.push_back({{}, a.cap, a.title, (content.actions & a.bit) != 0});
                leftW.push_back(measure(cap_, a.cap).width + 8 + 4 + measure(small_, a.title).width);
            }
        }
        if (theme.showHint) {
            footerTexts_.push_back({{}, kHint});
            leftW.push_back(measure(small_, kHint).width);
        }
        if (content.remembered) {
            footerTexts_.push_back({{}, kRemembered});
            rightW.push_back(measure(small_, kRemembered).width);
        }
        if (pages > 1) {
            footerTexts_.push_back({{}, std::to_wstring(page + 1) + L"/" + std::to_wstring(pages)});
            rightW.push_back(measure(small_, footerTexts_.back().second).width);
        }
        size_t count = leftW.size() + rightW.size();
        if (count) {
            footerW = 18;
            for (float w : leftW) footerW += w;
            for (float w : rightW) footerW += w;
            footerW += 10.f * (count - 1) + (!leftW.empty() && !rightW.empty() ? 10.f : 0);
            footerH = 2 + std::max(tools_.empty() ? 0.f : capH, smallM.height);
        }
    }
    float contentW = std::ceil(std::max({listW, footerW, preeditW}));

    // Positions (DIPs), the shadow margin first.
    const float P = theme.padding, M = kShadow;
    float x = M + P, y = M + P;
    rows_.clear();
    hits_.clear();
    preedit_ = {};
    if (!content.preedit.empty()) {
        preedit_ = D2D1::RectF(x, y, x + contentW, y + rowH);
        y += rowH;
        if (converting && (end > start || footerH > 0)) y += 4;
    }
    if (converting) {
        float rx = x;
        for (int i = start; i < end; ++i) {
            D2D1_RECT_F rc = theme.horizontal ? D2D1::RectF(rx, y, rx + rowW[i - start], y + rowH)
                                              : D2D1::RectF(x, y, x + contentW, y + rowH);
            rows_.push_back({rc, i});
            hits_.push_back({rc, i, 0, true});
            if (theme.horizontal) {
                rx += rowW[i - start] + 2;
            } else {
                y += rowH + 1;
            }
        }
        if (end > start) y = theme.horizontal ? y + rowH : y - 1;
        if (footerH > 0) {
            if (end > start) y += 4;
            float top = y + 2, mid = top + (footerH - 2) / 2;
            float fx = x + 9;
            size_t k = 0;
            for (Tool &t : tools_) {
                float w = leftW[k++];
                t.rc = D2D1::RectF(fx - 4, mid - capH / 2 - 2, fx + w + 4, mid + capH / 2 + 2);
                static const uint32_t keys[] = {HC_KEY_SHRINK_SEGMENT, HC_KEY_EXPAND_SEGMENT};
                hits_.push_back({t.rc, -1, keys[&t - tools_.data()], t.enabled});
                fx += w + 10;
            }
            size_t text = 0;
            if (theme.showHint) {
                footerTexts_[text].first = D2D1::RectF(fx, top, fx + leftW[k] + 1, y + footerH);
                ++text;
            }
            // Right side: 「기억한 띄어쓰기」, then the page.
            float rxEnd = x + contentW - 9;
            for (size_t r = rightW.size(); r-- > 0;) {
                float w = rightW[r];
                footerTexts_[text + r].first = D2D1::RectF(rxEnd - w - 1, top, rxEnd, y + footerH);
                rxEnd -= w + 10;
            }
            y += footerH;
        }
    }
    panel_ = D2D1::RectF(M, M, M + contentW + 2 * P, y + P);
    size_ = D2D1::SizeF(panel_.right + M, panel_.bottom + M);
}

int View::hitAt(float x, float y) const {
    for (size_t k = 0; k < hits_.size(); ++k) {
        const D2D1_RECT_F &r = hits_[k].rc;
        if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) return static_cast<int>(k);
    }
    return -1;
}

void View::draw(ID2D1RenderTarget *rt, int hover) const {
    ID2D1Factory *factory = gfx::d2d();
    if (!rt || !factory || !main_ || !small_) return;
    rt->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
    if (textParams()) rt->SetTextRenderingParams(textParams());
    ID2D1SolidColorBrush *brush = nullptr;
    if (FAILED(rt->CreateSolidColorBrush(palette_.text, &brush))) return;
    auto fillGeometry = [&](ID2D1Geometry *g, D2D1_COLOR_F c) {
        if (!g) return;
        brush->SetColor(c);
        rt->FillGeometry(g, brush);
        g->Release();
    };
    const Theme &t = theme_;
    const Palette &p = palette_;

    // Shadow: soft rings outside the panel only (a translucent panel must not darken).
    ID2D1Geometry *panel = shape(panel_, t.cornerRadius(), t.corner);
    ID2D1RectangleGeometry *all = nullptr;
    ID2D1PathGeometry *outside = nullptr;
    ID2D1GeometrySink *sink = nullptr;
    ID2D1Layer *layer = nullptr;
    if (panel && SUCCEEDED(factory->CreateRectangleGeometry(D2D1::RectF(0, 0, size_.width, size_.height), &all)) &&
        SUCCEEDED(factory->CreatePathGeometry(&outside)) && SUCCEEDED(outside->Open(&sink))) {
        all->CombineWithGeometry(panel, D2D1_COMBINE_MODE_EXCLUDE, nullptr, sink);
        sink->Close();
        if (SUCCEEDED(rt->CreateLayer(nullptr, &layer))) {
            rt->PushLayer(D2D1::LayerParameters(D2D1::InfiniteRect(), outside), layer);
            // Like a popover's shadow: faint, wide, a little below the panel.
            float alpha = p.background.r + p.background.g + p.background.b < 1.5f ? 0.026f : 0.012f;
            for (int i = 12; i >= 1; --i) {
                D2D1_RECT_F r = inflate(panel_, i * 1.0f, i * 1.0f);
                r.top += 4;
                r.bottom += 4;
                fillGeometry(shape(r, t.cornerRadius() + i * 1.0f, t.corner), D2D1::ColorF(0, 0, 0, alpha));
            }
            rt->PopLayer();
        }
    }
    release(sink);
    release(layer);
    release(outside);
    release(all);

    // Panel and border.
    if (panel) {
        brush->SetColor(p.background);
        rt->FillGeometry(panel, brush);
    }
    if (p.hasBorder) {
        if (ID2D1Geometry *edge = shape(inflate(panel_, -0.5f, -0.5f), std::max(0.f, t.cornerRadius() - 0.5f), t.corner)) {
            brush->SetColor(p.border);
            rt->DrawGeometry(edge, brush, 1.f);
            edge->Release();
        }
    }
    release(panel);

    Metrics mainM = measure(main_, L"가Ag"), smallM = measure(small_, L"가Ag");
    float baseline = std::max(mainM.baseline, smallM.baseline);
    auto text = [&](IDWriteTextFormat *f, const std::wstring &s, float x, float top, float maxW, D2D1_COLOR_F c,
                    DWRITE_TEXT_ALIGNMENT align = DWRITE_TEXT_ALIGNMENT_LEADING) {
        IDWriteTextLayout *layout = makeLayout(f, s, std::max(1.f, maxW));
        if (!layout) return;
        layout->SetTextAlignment(align);
        DWRITE_TRIMMING trim{DWRITE_TRIMMING_GRANULARITY_CHARACTER, 0, 0};
        IDWriteInlineObject *ellipsis = nullptr;
        gfx::dwrite()->CreateEllipsisTrimmingSign(f, &ellipsis);
        layout->SetTrimming(&trim, ellipsis);
        brush->SetColor(c);
        rt->DrawTextLayout(D2D1::Point2F(x, top), layout, brush, D2D1_DRAW_TEXT_OPTIONS_ENABLE_COLOR_FONT);
        if (ellipsis) ellipsis->Release();
        layout->Release();
    };
    // Selection mark of a row (or of the selected word in the phrase being typed).
    auto mark = [&](D2D1_RECT_F rc, bool selected, bool hovered) {
        if (selected) {
            switch (t.selection) {
            case Selection::Fill: fillGeometry(shape(rc, t.innerRadius(), t.corner), p.selectionFill); break;
            case Selection::Underline:
                brush->SetColor(p.selectionFill);
                rt->FillRectangle(D2D1::RectF(rc.left + 8, rc.bottom - 3, rc.right - 8, rc.bottom - 1.5f), brush);
                break;
            case Selection::Bar:
                brush->SetColor(p.selectionFill);
                rt->FillRoundedRectangle(
                    D2D1::RoundedRect(D2D1::RectF(rc.left + 1, rc.top + 6, rc.left + 4, std::max(rc.top + 10, rc.bottom - 6)), 1.5f, 1.5f),
                    brush);
                break;
            }
        } else if (hovered) {
            fillGeometry(shape(rc, t.innerRadius(), t.corner), withAlpha(p.selectionFill, 0.12f));
        }
    };

    // The phrase being typed (applications without inline composition).
    if (!content_.preedit.empty()) {
        D2D1_RECT_F r = preedit_;
        float x = r.left + side_, top = r.top + rowPad_ + baseline - mainM.baseline;
        IDWriteTextLayout *layout = makeLayout(main_, content_.preedit, r.right - 9 - x);
        if (layout) {
            int len = static_cast<int>(content_.preedit.size());
            if (content_.converting && content_.hs >= 0 && content_.hl > 0 && content_.hs + content_.hl <= len) {
                DWRITE_HIT_TEST_METRICS hit{};
                UINT32 count = 0;
                layout->HitTestTextRange(content_.hs, content_.hl, x, top, &hit, 1, &count);
                if (count) {
                    D2D1_RECT_F word = D2D1::RectF(hit.left - 4, r.top + 1, hit.left + hit.width + 4, r.bottom - 1);
                    if (t.selection == Selection::Fill) {
                        mark(word, true, false);
                        ID2D1SolidColorBrush *on = nullptr;
                        rt->CreateSolidColorBrush(p.selectionText, &on);
                        if (on) {
                            layout->SetDrawingEffect(on, DWRITE_TEXT_RANGE{static_cast<UINT32>(content_.hs),
                                                                           static_cast<UINT32>(content_.hl)});
                            on->Release();
                        }
                    } else {
                        brush->SetColor(p.selectionFill);
                        rt->FillRectangle(D2D1::RectF(word.left + 4, r.bottom - 3, word.right - 4, r.bottom - 1.5f), brush);
                    }
                }
            }
            brush->SetColor(p.text);
            rt->DrawTextLayout(D2D1::Point2F(x, top), layout, brush, D2D1_DRAW_TEXT_OPTIONS_ENABLE_COLOR_FONT);
            if (!content_.converting) {
                // Dotted underline while typing, as for inline composition.
                DWRITE_TEXT_METRICS m{};
                layout->GetMetrics(&m);
                ID2D1StrokeStyle *dots = nullptr;
                float dash[] = {1.f, 2.f};
                factory->CreateStrokeStyle(D2D1::StrokeStyleProperties(D2D1_CAP_STYLE_FLAT, D2D1_CAP_STYLE_FLAT, D2D1_CAP_STYLE_FLAT,
                                                                       D2D1_LINE_JOIN_MITER, 10, D2D1_DASH_STYLE_CUSTOM),
                                           dash, 2, &dots);
                brush->SetColor(withAlpha(p.text, 0.7f));
                float uy = top + mainM.baseline + 3;
                rt->DrawLine(D2D1::Point2F(x, uy), D2D1::Point2F(x + m.width, uy), brush, 1.f, dots);
                if (dots) dots->Release();
            }
            layout->Release();
        }
    }

    // Candidates.
    for (const Row &row : rows_) {
        const D2D1_RECT_F &rc = row.rc;
        bool selected = row.index == content_.selected;
        int hitIndex = static_cast<int>(&row - rows_.data());
        mark(rc, selected, hitIndex == hover);
        D2D1_COLOR_F fg = selected ? p.selectionText : p.text;
        D2D1_COLOR_F dim = selected ? withAlpha(p.selectionText, 0.72f) : p.secondary;
        float x = rc.left + side_;
        float mainTop = rc.top + rowPad_ + baseline - mainM.baseline;
        float smallTop = rc.top + rowPad_ + baseline - smallM.baseline;
        if (t.showNumbers) {
            text(small_, std::to_wstring(row.index % kPageSize + 1), x, smallTop, numberWidth_ + 1, dim);
            x += numberWidth_ + gap_;
        }
        const std::wstring &note =
            row.index < static_cast<int>(content_.notes.size()) ? content_.notes[row.index] : std::wstring();
        float noteW = t.showNotes && !t.horizontal && !note.empty() ? measure(small_, note).width : 0;
        float right = rc.right - 9;
        text(main_, content_.items[row.index], x, mainTop, right - x - (noteW ? noteW + 2 * gap_ : 0), fg);
        if (noteW) text(small_, note, right - noteW - 1, smallTop, noteW + 1, dim);
    }

    // Footer: the boundary keys, the hint, 「기억한 띄어쓰기」, the page.
    for (const Tool &tool : tools_) {
        int hitIndex = -1;
        for (size_t k = 0; k < hits_.size(); ++k)
            if (hits_[k].key && hits_[k].rc.left == tool.rc.left) hitIndex = static_cast<int>(k);
        D2D1_COLOR_F c = tool.enabled ? p.secondary : withAlpha(p.secondary, 0.35f);
        if (tool.enabled && hitIndex == hover) {
            brush->SetColor(withAlpha(p.secondary, 0.14f));
            rt->FillRoundedRectangle(D2D1::RoundedRect(tool.rc, 4, 4), brush);
        }
        Metrics capM = measure(cap_, tool.cap);
        float capH = capM.height + 2, mid = (tool.rc.top + tool.rc.bottom) / 2;
        D2D1_RECT_F cap = D2D1::RectF(tool.rc.left + 4, mid - capH / 2, tool.rc.left + 4 + capM.width + 8, mid + capH / 2);
        brush->SetColor(withAlpha(c, 0.45f));
        rt->DrawRoundedRectangle(D2D1::RoundedRect(inflate(cap, -0.5f, -0.5f), 4, 4), brush, 0.75f);
        text(cap_, tool.cap, cap.left, cap.top + 1, cap.right - cap.left, c, DWRITE_TEXT_ALIGNMENT_CENTER);
        float tx = cap.right + 4;
        text(small_, tool.title, tx, mid - smallM.height / 2, tool.rc.right - tx, c);
    }
    for (const auto &[rc, s] : footerTexts_) {
        float mid = (rc.top + rc.bottom) / 2;
        text(small_, s, rc.left, mid - smallM.height / 2, rc.right - rc.left, p.secondary);
    }
    brush->Release();
}

}  // namespace maimusi::cand
