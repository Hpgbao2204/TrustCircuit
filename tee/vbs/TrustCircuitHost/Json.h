#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <string_view>

namespace trustcircuit::json
{
enum class ValueType
{
    String,
    Number,
    Boolean,
    Null,
};

struct Value
{
    ValueType type{ValueType::Null};
    std::string text;
    bool boolean{false};
};

using Object = std::map<std::string, Value, std::less<>>;

Object parseObject(std::string_view input);
const Value& require(const Object& object, std::string_view key);
std::string requireString(const Object& object, std::string_view key);
std::uint64_t requireUint64(const Object& object, std::string_view key);
std::int64_t requireInt64(const Object& object, std::string_view key);
bool requireBoolean(const Object& object, std::string_view key);
long double requireNumber(const Object& object, std::string_view key);
std::string escape(std::string_view value);
}
