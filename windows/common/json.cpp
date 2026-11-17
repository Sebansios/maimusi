#include "json.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace maimusi {

namespace {

const std::string kEmpty;
const Json kNull;

class Parser {
public:
    explicit Parser(const std::string &s) : s_(s) {}

    bool parseDocument(Json &out) {
        if (!value(out, 0)) return false;
        ws();
        return i_ == s_.size();
    }

private:
    void ws() {
        while (i_ < s_.size() && (s_[i_] == ' ' || s_[i_] == '\t' || s_[i_] == '\n' || s_[i_] == '\r')) ++i_;
    }

    bool literal(const char *word) {
        size_t n = std::char_traits<char>::length(word);
        if (s_.compare(i_, n, word) != 0) return false;
        i_ += n;
        return true;
    }

    static void appendUtf8(std::string &out, unsigned cp) {
        if (cp < 0x80) {
            out += static_cast<char>(cp);
        } else if (cp < 0x800) {
            out += static_cast<char>(0xC0 | (cp >> 6));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        } else if (cp < 0x10000) {
            out += static_cast<char>(0xE0 | (cp >> 12));
            out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        } else {
            out += static_cast<char>(0xF0 | (cp >> 18));
            out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
            out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        }
    }

    bool hex4(unsigned &cp) {
        if (i_ + 4 > s_.size()) return false;
        cp = 0;
        for (int k = 0; k < 4; ++k) {
            char c = s_[i_++];
            cp <<= 4;
            if (c >= '0' && c <= '9') cp |= c - '0';
            else if (c >= 'a' && c <= 'f') cp |= c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') cp |= c - 'A' + 10;
            else return false;
        }
        return true;
    }

    bool string(std::string &out) {
        if (s_[i_] != '"') return false;
        ++i_;
        while (i_ < s_.size()) {
            char c = s_[i_++];
            if (c == '"') return true;
            if (static_cast<unsigned char>(c) < 0x20) return false;
            if (c != '\\') {
                out += c;
                continue;
            }
            if (i_ >= s_.size()) return false;
            char e = s_[i_++];
            switch (e) {
            case '"': out += '"'; break;
            case '\\': out += '\\'; break;
            case '/': out += '/'; break;
            case 'b': out += '\b'; break;
            case 'f': out += '\f'; break;
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            case 'u': {
                unsigned cp;
                if (!hex4(cp)) return false;
                if (cp >= 0xD800 && cp < 0xDC00) {
                    unsigned lo;
                    if (i_ + 2 > s_.size() || s_[i_] != '\\' || s_[i_ + 1] != 'u') return false;
                    i_ += 2;
                    if (!hex4(lo) || lo < 0xDC00 || lo >= 0xE000) return false;
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                } else if (cp >= 0xDC00 && cp < 0xE000) {
                    return false;
                }
                appendUtf8(out, cp);
                break;
            }
            default: return false;
            }
        }
        return false;
    }

    bool value(Json &out, int depth) {
        if (depth > 64) return false;
        ws();
        if (i_ >= s_.size()) return false;
        char c = s_[i_];
        if (c == '{') {
            ++i_;
            out = Json::object();
            ws();
            if (i_ < s_.size() && s_[i_] == '}') { ++i_; return true; }
            for (;;) {
                ws();
                std::string key;
                if (i_ >= s_.size() || !string(key)) return false;
                ws();
                if (i_ >= s_.size() || s_[i_++] != ':') return false;
                Json v;
                if (!value(v, depth + 1)) return false;
                out.set(key, std::move(v));
                ws();
                if (i_ >= s_.size()) return false;
                if (s_[i_] == ',') { ++i_; continue; }
                if (s_[i_] == '}') { ++i_; return true; }
                return false;
            }
        }
        if (c == '[') {
            ++i_;
            out = Json::array();
            ws();
            if (i_ < s_.size() && s_[i_] == ']') { ++i_; return true; }
            for (;;) {
                Json v;
                if (!value(v, depth + 1)) return false;
                out.push(std::move(v));
                ws();
                if (i_ >= s_.size()) return false;
                if (s_[i_] == ',') { ++i_; continue; }
                if (s_[i_] == ']') { ++i_; return true; }
                return false;
            }
        }
        if (c == '"') {
            std::string s;
            if (!string(s)) return false;
            out = Json(std::move(s));
            return true;
        }
        if (literal("true")) { out = Json(true); return true; }
        if (literal("false")) { out = Json(false); return true; }
        if (literal("null")) { out = Json(); return true; }
        const char *begin = s_.c_str() + i_;
        char *end = nullptr;
        double n = std::strtod(begin, &end);
        if (end == begin || !std::isfinite(n)) return false;
        i_ += end - begin;
        out = Json(n);
        return true;
    }

    const std::string &s_;
    size_t i_ = 0;
};

void dumpString(const std::string &s, std::string &out) {
    out += '"';
    for (unsigned char c : s) {
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (c < 0x20) {
                char buf[8];
                std::snprintf(buf, sizeof buf, "\\u%04x", c);
                out += buf;
            } else {
                out += static_cast<char>(c);
            }
        }
    }
    out += '"';
}

}  // namespace

const std::string &Json::asString() const { return isString() ? string_ : kEmpty; }

void Json::push(Json v) {
    type_ = Type::Array;
    items_.push_back(std::move(v));
}

const Json *Json::find(const std::string &key) const {
    for (auto &m : members_)
        if (m.first == key) return &m.second;
    return nullptr;
}

const Json &Json::operator[](const std::string &key) const {
    const Json *v = find(key);
    return v ? *v : kNull;
}

void Json::set(const std::string &key, Json v) {
    type_ = Type::Object;
    for (auto &m : members_) {
        if (m.first == key) {
            m.second = std::move(v);
            return;
        }
    }
    members_.emplace_back(key, std::move(v));
}

void Json::dumpTo(std::string &out) const {
    switch (type_) {
    case Type::Null: out += "null"; break;
    case Type::Bool: out += bool_ ? "true" : "false"; break;
    case Type::Number: {
        char buf[32];
        if (number_ == std::floor(number_) && std::fabs(number_) < 1e15)
            std::snprintf(buf, sizeof buf, "%.0f", number_);
        else
            std::snprintf(buf, sizeof buf, "%.17g", number_);
        out += buf;
        break;
    }
    case Type::String: dumpString(string_, out); break;
    case Type::Array:
        out += '[';
        for (size_t k = 0; k < items_.size(); ++k) {
            if (k) out += ',';
            items_[k].dumpTo(out);
        }
        out += ']';
        break;
    case Type::Object:
        out += '{';
        for (size_t k = 0; k < members_.size(); ++k) {
            if (k) out += ',';
            dumpString(members_[k].first, out);
            out += ':';
            members_[k].second.dumpTo(out);
        }
        out += '}';
        break;
    }
}

std::string Json::dump() const {
    std::string out;
    dumpTo(out);
    return out;
}

bool Json::parse(const std::string &text, Json &out) {
    Json v;
    if (!Parser(text).parseDocument(v)) return false;
    out = std::move(v);
    return true;
}

}  // namespace maimusi
