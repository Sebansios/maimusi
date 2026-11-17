// Minimal JSON value, parser and writer for settings and the engine protocol.
// Strings are UTF-8. Numbers are doubles. Object member order is kept.
#pragma once

#include <string>
#include <utility>
#include <vector>

namespace maimusi {

class Json {
public:
    enum class Type { Null, Bool, Number, String, Array, Object };

    Json() = default;
    Json(bool b) : type_(Type::Bool), bool_(b) {}
    Json(int n) : type_(Type::Number), number_(n) {}
    Json(double n) : type_(Type::Number), number_(n) {}
    Json(const char *s) : type_(Type::String), string_(s) {}
    Json(std::string s) : type_(Type::String), string_(std::move(s)) {}

    static Json array() { Json j; j.type_ = Type::Array; return j; }
    static Json object() { Json j; j.type_ = Type::Object; return j; }

    Type type() const { return type_; }
    bool isNull() const { return type_ == Type::Null; }
    bool isBool() const { return type_ == Type::Bool; }
    bool isNumber() const { return type_ == Type::Number; }
    bool isString() const { return type_ == Type::String; }
    bool isArray() const { return type_ == Type::Array; }
    bool isObject() const { return type_ == Type::Object; }

    bool asBool(bool fallback = false) const { return isBool() ? bool_ : fallback; }
    double asNumber(double fallback = 0) const { return isNumber() ? number_ : fallback; }
    int asInt(int fallback = 0) const { return isNumber() ? static_cast<int>(number_) : fallback; }
    const std::string &asString() const;

    // Arrays
    const std::vector<Json> &items() const { return items_; }
    void push(Json v);

    // Objects
    const std::vector<std::pair<std::string, Json>> &members() const { return members_; }
    const Json *find(const std::string &key) const;
    const Json &operator[](const std::string &key) const;
    void set(const std::string &key, Json v);
    // Appends a member without looking for an existing one (the caller knows the key is new).
    void add(std::string key, Json v) { members_.emplace_back(std::move(key), std::move(v)); }

    std::string dump() const;
    // Returns false (and leaves out unchanged) on malformed input.
    static bool parse(const std::string &text, Json &out);

private:
    void dumpTo(std::string &out) const;

    Type type_ = Type::Null;
    bool bool_ = false;
    double number_ = 0;
    std::string string_;
    std::vector<Json> items_;
    std::vector<std::pair<std::string, Json>> members_;
};

}  // namespace maimusi
