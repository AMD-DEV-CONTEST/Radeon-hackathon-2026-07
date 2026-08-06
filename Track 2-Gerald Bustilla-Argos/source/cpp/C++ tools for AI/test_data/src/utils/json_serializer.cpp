// JSON serialization utility
#include "json_serializer.h"

std::string JsonSerializer::serialize(const JsonValue& value) {
    std::ostringstream ss;
    serialize_value(ss, value);
    return ss.str();
}

void JsonSerializer::serialize_value(std::ostringstream& ss, const JsonValue& value) {
    if (value.is_string()) ss << "\"" << escape(value.as_string()) << "\"";
    else if (value.is_number()) ss << value.as_number();
    else if (value.is_bool()) ss << (value.as_bool() ? "true" : "false");
    else if (value.is_null()) ss << "null";
}
