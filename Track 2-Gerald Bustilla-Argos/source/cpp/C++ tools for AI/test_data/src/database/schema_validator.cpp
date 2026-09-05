// Schema validation for database models
#include "schema_validator.h"

bool SchemaValidator::validate(const nlohmann::json& data, const Schema& schema) {
    for (const auto& field : schema.required_fields) {
        if (!data.contains(field.name)) {
            errors.push_back("Missing required field: " + field.name);
            return false;
        }
    }
    return true;
}
