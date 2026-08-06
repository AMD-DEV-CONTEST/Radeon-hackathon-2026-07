// Configuration parser for JSON and YAML files
#include "config_parser.h"

Config ConfigParser::parse(const std::string& filepath) {
    std::string content = read_file(filepath);
    std::string ext = get_extension(filepath);
    
    if (ext == ".json") return parse_json(content);
    if (ext == ".yaml" || ext == ".yml") return parse_yaml(content);
    if (ext == ".ini" || ext == ".conf") return parse_ini(content);
    
    throw std::runtime_error("Unsupported config format: " + ext);
}
