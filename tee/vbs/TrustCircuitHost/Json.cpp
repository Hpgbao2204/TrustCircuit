#include "Json.h"

#include <charconv>
#include <cctype>
#include <stdexcept>

namespace trustcircuit::json
{
namespace
{
class Parser
{
public:
    explicit Parser(std::string_view input) : input_(input) {}

    Object parse()
    {
        Object result;
        skipWhitespace();
        expect('{');
        skipWhitespace();
        if (consume('}'))
        {
            ensureFinished();
            return result;
        }

        for (;;)
        {
            skipWhitespace();
            const auto key = parseString();
            skipWhitespace();
            expect(':');
            skipWhitespace();
            const auto [_, inserted] = result.emplace(key, parseValue());
            if (!inserted)
            {
                throw std::runtime_error("duplicate JSON key: " + key);
            }
            skipWhitespace();
            if (consume('}'))
            {
                ensureFinished();
                return result;
            }
            expect(',');
        }
    }

private:
    Value parseValue()
    {
        if (position_ >= input_.size())
        {
            throw std::runtime_error("missing JSON value");
        }
        if (input_[position_] == '"')
        {
            return {ValueType::String, parseString(), false};
        }
        if (startsWith("true"))
        {
            position_ += 4;
            return {ValueType::Boolean, {}, true};
        }
        if (startsWith("false"))
        {
            position_ += 5;
            return {ValueType::Boolean, {}, false};
        }
        if (startsWith("null"))
        {
            position_ += 4;
            return {ValueType::Null, {}, false};
        }
        if (input_[position_] == '{' || input_[position_] == '[')
        {
            throw std::runtime_error("nested JSON values are not supported");
        }
        return {ValueType::Number, parseNumber(), false};
    }

    std::string parseString()
    {
        expect('"');
        std::string result;
        while (position_ < input_.size())
        {
            const auto value = input_[position_++];
            if (value == '"')
            {
                return result;
            }
            if (static_cast<unsigned char>(value) < 0x20)
            {
                throw std::runtime_error("control character in JSON string");
            }
            if (value != '\\')
            {
                result.push_back(value);
                continue;
            }
            if (position_ >= input_.size())
            {
                throw std::runtime_error("unterminated JSON escape");
            }
            switch (input_[position_++])
            {
            case '"': result.push_back('"'); break;
            case '\\': result.push_back('\\'); break;
            case '/': result.push_back('/'); break;
            case 'b': result.push_back('\b'); break;
            case 'f': result.push_back('\f'); break;
            case 'n': result.push_back('\n'); break;
            case 'r': result.push_back('\r'); break;
            case 't': result.push_back('\t'); break;
            default:
                throw std::runtime_error(
                    "unsupported JSON escape; canonical requests use UTF-8");
            }
        }
        throw std::runtime_error("unterminated JSON string");
    }

    std::string parseNumber()
    {
        const auto start = position_;
        consume('-');
        if (position_ >= input_.size())
        {
            throw std::runtime_error("invalid JSON number");
        }
        if (input_[position_] == '0')
        {
            ++position_;
        }
        else
        {
            requireDigitOneToNine();
            while (position_ < input_.size() && isDigit(input_[position_]))
            {
                ++position_;
            }
        }
        if (consume('.'))
        {
            requireDigit();
            while (position_ < input_.size() && isDigit(input_[position_]))
            {
                ++position_;
            }
        }
        if (position_ < input_.size() &&
            (input_[position_] == 'e' || input_[position_] == 'E'))
        {
            ++position_;
            if (position_ < input_.size() &&
                (input_[position_] == '+' || input_[position_] == '-'))
            {
                ++position_;
            }
            requireDigit();
            while (position_ < input_.size() && isDigit(input_[position_]))
            {
                ++position_;
            }
        }
        return std::string(input_.substr(start, position_ - start));
    }

    void requireDigit()
    {
        if (position_ >= input_.size() || !isDigit(input_[position_]))
        {
            throw std::runtime_error("invalid JSON number");
        }
    }

    void requireDigitOneToNine()
    {
        if (position_ >= input_.size() || input_[position_] < '1' ||
            input_[position_] > '9')
        {
            throw std::runtime_error("invalid JSON number");
        }
        ++position_;
    }

    static bool isDigit(char value)
    {
        return value >= '0' && value <= '9';
    }

    bool startsWith(std::string_view value) const
    {
        return input_.substr(position_, value.size()) == value;
    }

    bool consume(char expected)
    {
        if (position_ < input_.size() && input_[position_] == expected)
        {
            ++position_;
            return true;
        }
        return false;
    }

    void expect(char expected)
    {
        if (!consume(expected))
        {
            throw std::runtime_error("malformed JSON object");
        }
    }

    void skipWhitespace()
    {
        while (position_ < input_.size() &&
               std::isspace(static_cast<unsigned char>(input_[position_])))
        {
            ++position_;
        }
    }

    void ensureFinished()
    {
        skipWhitespace();
        if (position_ != input_.size())
        {
            throw std::runtime_error("trailing data after JSON object");
        }
    }

    std::string_view input_;
    std::size_t position_{0};
};

template <typename Integer>
Integer parseInteger(const Value& value)
{
    if (value.type != ValueType::Number ||
        value.text.find_first_of(".eE") != std::string::npos)
    {
        throw std::runtime_error("expected integer JSON value");
    }
    Integer parsed{};
    const auto* begin = value.text.data();
    const auto* end = begin + value.text.size();
    const auto result = std::from_chars(begin, end, parsed);
    if (result.ec != std::errc{} || result.ptr != end)
    {
        throw std::runtime_error("integer JSON value is out of range");
    }
    return parsed;
}
}

Object parseObject(std::string_view input)
{
    return Parser(input).parse();
}

const Value& require(const Object& object, std::string_view key)
{
    const auto iterator = object.find(key);
    if (iterator == object.end())
    {
        throw std::runtime_error("missing JSON key: " + std::string(key));
    }
    return iterator->second;
}

std::string requireString(const Object& object, std::string_view key)
{
    const auto& value = require(object, key);
    if (value.type != ValueType::String)
    {
        throw std::runtime_error("expected JSON string: " + std::string(key));
    }
    return value.text;
}

std::uint64_t requireUint64(const Object& object, std::string_view key)
{
    return parseInteger<std::uint64_t>(require(object, key));
}

std::int64_t requireInt64(const Object& object, std::string_view key)
{
    return parseInteger<std::int64_t>(require(object, key));
}

bool requireBoolean(const Object& object, std::string_view key)
{
    const auto& value = require(object, key);
    if (value.type != ValueType::Boolean)
    {
        throw std::runtime_error("expected JSON boolean: " + std::string(key));
    }
    return value.boolean;
}

long double requireNumber(const Object& object, std::string_view key)
{
    const auto& value = require(object, key);
    if (value.type != ValueType::Number)
    {
        throw std::runtime_error("expected JSON number: " + std::string(key));
    }
    std::size_t consumed = 0;
    const auto parsed = std::stold(value.text, &consumed);
    if (consumed != value.text.size())
    {
        throw std::runtime_error("invalid JSON number: " + std::string(key));
    }
    return parsed;
}

std::string escape(std::string_view value)
{
    std::string result;
    result.reserve(value.size() + 2);
    for (const auto character : value)
    {
        switch (character)
        {
        case '"': result += "\\\""; break;
        case '\\': result += "\\\\"; break;
        case '\b': result += "\\b"; break;
        case '\f': result += "\\f"; break;
        case '\n': result += "\\n"; break;
        case '\r': result += "\\r"; break;
        case '\t': result += "\\t"; break;
        default:
            if (static_cast<unsigned char>(character) < 0x20)
            {
                throw std::runtime_error("control character in JSON output");
            }
            result.push_back(character);
        }
    }
    return result;
}
}
