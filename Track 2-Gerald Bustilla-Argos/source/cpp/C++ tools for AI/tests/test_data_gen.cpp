// test_data_gen.cpp - Generates complex test data for the AI search tool
// Creates: nested folders, text files with known content, fake images (PNG/BMP/JPEG),
// hidden files, various file extensions, duplicate content, large/small files
#include <iostream>
#include <fstream>
#include <filesystem>
#include <string>
#include <vector>
#include <random>
#include <sstream>
#include <iomanip>
#include <cstdint>

namespace fs = std::filesystem;

static std::mt19937 rng(42);

static std::string random_text(size_t words) {
    static const std::vector<std::string> vocab = {
        "authentication", "database", "config", "parser", "handler", "router",
        "middleware", "logger", "cache", "session", "token", "encrypt", "decrypt",
        "validation", "schema", "migration", "controller", "service", "model",
        "view", "template", "render", "request", "response", "header", "cookie",
        "payload", "query", "index", "search", "vector", "embedding", "similarity",
        "cosine", "tfidf", "inverted", "posting", "tokenize", "chunk", "overlap",
        "fingerprint", "perceptual", "hash", "base64", "encode", "decode",
        "image", "png", "jpeg", "bitmap", "pixel", "sample", "dimension",
        "width", "height", "format", "detect", "magic", "bytes", "header",
        "error", "exception", "warning", "debug", "trace", "verbose", "silent",
        "network", "socket", "connection", "timeout", "retry", "fallback",
        "async", "thread", "mutex", "lock", "atomic", "queue", "buffer",
        "file", "directory", "path", "recursive", "scan", "filter", "hidden",
        "json", "yaml", "xml", "csv", "markdown", "html", "css", "javascript",
        "python", "java", "golang", "rust", "swift", "kotlin", "typescript",
        "docker", "kubernetes", "deployment", "container", "volume", "mount",
        "redis", "postgres", "mongodb", "elasticsearch", "kafka", "rabbitmq",
        "algorithm", "complexity", "optimize", "performance", "benchmark",
        "memory", "leak", "garbage", "collect", "allocate", "deallocate",
        "test", "unit", "integration", "mock", "stub", "fixture", "assert",
        "security", "vulnerability", "injection", "xss", "csrf", "cors",
        "oauth", "jwt", "bearer", "refresh", "access", "credential", "secret"
    };

    std::uniform_int_distribution<size_t> vocab_dist(0, vocab.size() - 1);
    std::uniform_int_distribution<int> sentence_len(5, 15);
    std::uniform_int_distribution<int> paragraph_sentences(2, 5);

    std::ostringstream ss;
    for (int p = 0; p < static_cast<int>(words) / 10; p++) {
        for (int s = 0; s < paragraph_sentences(rng); s++) {
            int slen = sentence_len(rng);
            for (int w = 0; w < slen; w++) {
                if (w > 0) ss << " ";
                ss << vocab[vocab_dist(rng)];
            }
            ss << ". ";
        }
        ss << "\n";
    }
    return ss.str();
}

static void write_png(const std::string& path, int width, int height, uint8_t seed) {
    // Minimal valid PNG: signature + IHDR + IDAT (stored) + IEND
    fs::create_directories(fs::path(path).parent_path());
    std::ofstream f(path, std::ios::binary);
    if (!f) return;

    // PNG signature
    uint8_t sig[] = {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
    f.write(reinterpret_cast<char*>(sig), 8);

    // IHDR chunk
    uint32_t ihdr_len = 13;
    uint8_t ihdr_type[] = {'I', 'H', 'D', 'R'};
    f.write(reinterpret_cast<char*>(&ihdr_len), 4);
    f.write(reinterpret_cast<char*>(ihdr_type), 4);
    // Width (big-endian)
    f.put((width >> 24) & 0xFF);
    f.put((width >> 16) & 0xFF);
    f.put((width >> 8) & 0xFF);
    f.put(width & 0xFF);
    // Height (big-endian)
    f.put((height >> 24) & 0xFF);
    f.put((height >> 16) & 0xFF);
    f.put((height >> 8) & 0xFF);
    f.put(height & 0xFF);
    // Bit depth=8, color type=2 (RGB), compression=0, filter=0, interlace=0
    f.put(8); f.put(2); f.put(0); f.put(0); f.put(0);
    // CRC (simplified - just write zeros, the tool doesn't validate CRC)
    f.put(0); f.put(0); f.put(0); f.put(0);

    // IDAT chunk - raw pixel data with stored compression
    // Each scanline: 1 filter byte + width*3 bytes (RGB)
    size_t raw_size = static_cast<size_t>(height) * (1 + static_cast<size_t>(width) * 3);
    // zlib stored block header (2 bytes) + data + adler32 (4 bytes)
    size_t idat_data_size = 2 + raw_size + 4;

    uint32_t idat_len = static_cast<uint32_t>(idat_data_size);
    uint8_t idat_type[] = {'I', 'D', 'A', 'T'};
    f.write(reinterpret_cast<char*>(&idat_len), 4);
    f.write(reinterpret_cast<char*>(idat_type), 4);

    // zlib stored block
    f.put(0x01); // BFINAL=1, BTYPE=00 (stored)
    f.put(static_cast<char>(raw_size & 0xFF));
    f.put(static_cast<char>((raw_size >> 8) & 0xFF));
    f.put(static_cast<char>(~raw_size & 0xFF));
    f.put(static_cast<char>((~raw_size >> 8) & 0xFF));

    // Pixel data
    for (int y = 0; y < height; y++) {
        f.put(0); // filter: none
        for (int x = 0; x < width; x++) {
            uint8_t r = static_cast<uint8_t>((seed + x * 7 + y * 13) & 0xFF);
            uint8_t g = static_cast<uint8_t>((seed + x * 11 + y * 3) & 0xFF);
            uint8_t b = static_cast<uint8_t>((seed + x * 5 + y * 17) & 0xFF);
            f.put(static_cast<char>(r));
            f.put(static_cast<char>(g));
            f.put(static_cast<char>(b));
        }
    }

    // Adler32 (simplified)
    f.put(0); f.put(1); f.put(0); f.put(1);

    // IEND chunk
    uint32_t iend_len = 0;
    uint8_t iend_type[] = {'I', 'E', 'N', 'D'};
    f.write(reinterpret_cast<char*>(&iend_len), 4);
    f.write(reinterpret_cast<char*>(iend_type), 4);
    f.put(0); f.put(0); f.put(0); f.put(0);
}

static void write_bmp(const std::string& path, int width, int height, uint8_t seed) {
    fs::create_directories(fs::path(path).parent_path());
    std::ofstream f(path, std::ios::binary);
    if (!f) return;

    // BMP file header (14 bytes)
    size_t row_size = ((static_cast<size_t>(width) * 3 + 3) / 4) * 4;
    size_t pixel_size = row_size * static_cast<size_t>(height);
    size_t file_size = 14 + 40 + pixel_size;

    f.put('B'); f.put('M');
    uint32_t fs32 = static_cast<uint32_t>(file_size);
    f.write(reinterpret_cast<char*>(&fs32), 4);
    f.put(0); f.put(0); f.put(0); f.put(0); // reserved
    uint32_t offset = 14 + 40;
    f.write(reinterpret_cast<char*>(&offset), 4);

    // DIB header (40 bytes)
    uint32_t hdr_size = 40;
    f.write(reinterpret_cast<char*>(&hdr_size), 4);
    int32_t w32 = width;
    f.write(reinterpret_cast<char*>(&w32), 4);
    int32_t h32 = height;
    f.write(reinterpret_cast<char*>(&h32), 4);
    uint16_t planes = 1;
    f.write(reinterpret_cast<char*>(&planes), 2);
    uint16_t bpp = 24;
    f.write(reinterpret_cast<char*>(&bpp), 2);
    uint32_t compression = 0;
    f.write(reinterpret_cast<char*>(&compression), 4);
    uint32_t img_size = static_cast<uint32_t>(pixel_size);
    f.write(reinterpret_cast<char*>(&img_size), 4);
    uint32_t ppm = 2835;
    f.write(reinterpret_cast<char*>(&ppm), 4);
    f.write(reinterpret_cast<char*>(&ppm), 4);
    uint32_t colors = 0;
    f.write(reinterpret_cast<char*>(&colors), 4);
    f.write(reinterpret_cast<char*>(&colors), 4);

    // Pixel data (BGR, bottom-up)
    for (int y = height - 1; y >= 0; y--) {
        for (int x = 0; x < width; x++) {
            uint8_t b = static_cast<uint8_t>((seed + x * 7 + y * 13) & 0xFF);
            uint8_t g = static_cast<uint8_t>((seed + x * 11 + y * 3) & 0xFF);
            uint8_t r = static_cast<uint8_t>((seed + x * 5 + y * 17) & 0xFF);
            f.put(static_cast<char>(b));
            f.put(static_cast<char>(g));
            f.put(static_cast<char>(r));
        }
        // Padding
        for (size_t p = static_cast<size_t>(width) * 3; p < row_size; p++) {
            f.put(0);
        }
    }
}

static void write_jpeg(const std::string& path, int width, int height, uint8_t seed) {
    // Minimal JPEG with SOI, SOF0, SOS, EOI markers
    fs::create_directories(fs::path(path).parent_path());
    std::ofstream f(path, std::ios::binary);
    if (!f) return;

    // SOI
    f.put(0xFF); f.put(0xD8);

    // APP0 (JFIF header)
    f.put(0xFF); f.put(0xE0);
    uint16_t len0 = 16;
    f.put(static_cast<char>(len0 >> 8)); f.put(static_cast<char>(len0 & 0xFF));
    f.put('J'); f.put('F'); f.put('I'); f.put('F'); f.put(0);
    f.put(1); f.put(1);
    f.put(0);
    f.put(0); f.put(8);
    f.put(0); f.put(8);
    f.put(0); f.put(0); f.put(0); f.put(0);

    // SOF0 marker
    f.put(0xFF); f.put(0xC0);
    uint16_t sof_len = 17;
    f.put(static_cast<char>(sof_len >> 8)); f.put(static_cast<char>(sof_len & 0xFF));
    f.put(8); // precision
    uint16_t h16 = static_cast<uint16_t>(height);
    f.put(static_cast<char>(h16 >> 8)); f.put(static_cast<char>(h16 & 0xFF));
    uint16_t w16 = static_cast<uint16_t>(width);
    f.put(static_cast<char>(w16 >> 8)); f.put(static_cast<char>(w16 & 0xFF));
    f.put(3); // 3 components (Y, Cb, Cr)
    f.put(1); f.put(0x11); f.put(0);
    f.put(2); f.put(0x11); f.put(1);
    f.put(3); f.put(0x11); f.put(1);

    // DQT marker (simplified)
    f.put(0xFF); f.put(0xDB);
    uint16_t dqt_len = 67;
    f.put(static_cast<char>(dqt_len >> 8)); f.put(static_cast<char>(dqt_len & 0xFF));
    f.put(0);
    for (int i = 0; i < 64; i++) f.put(static_cast<char>(16 + i));

    // DHT marker (simplified)
    f.put(0xFF); f.put(0xC4);
    uint16_t dht_len = 31;
    f.put(static_cast<char>(dht_len >> 8)); f.put(static_cast<char>(dht_len & 0xFF));
    f.put(0);
    for (int i = 0; i < 16; i++) f.put(static_cast<char>(i));
    for (int i = 0; i < 12; i++) f.put(static_cast<char>(i));

    // SOS marker
    f.put(0xFF); f.put(0xDA);
    uint16_t sos_len = 12;
    f.put(static_cast<char>(sos_len >> 8)); f.put(static_cast<char>(sos_len & 0xFF));
    f.put(3);
    f.put(1); f.put(0);
    f.put(2); f.put(0x11);
    f.put(3); f.put(0x11);
    f.put(0); f.put(63); f.put(0);

    // Fake scan data (random-ish based on seed)
    for (int i = 0; i < width * height / 4; i++) {
        f.put(static_cast<char>((seed + i * 37) & 0xFF));
    }

    // EOI
    f.put(0xFF); f.put(0xD9);
}

static void write_gif(const std::string& path, int width, int height, uint8_t seed) {
    fs::create_directories(fs::path(path).parent_path());
    std::ofstream f(path, std::ios::binary);
    if (!f) return;

    // GIF header
    f.put('G'); f.put('I'); f.put('F'); f.put('8'); f.put('9'); f.put('a');

    // Logical screen descriptor
    uint16_t w16 = static_cast<uint16_t>(width);
    uint16_t h16 = static_cast<uint16_t>(height);
    f.write(reinterpret_cast<char*>(&w16), 2);
    f.write(reinterpret_cast<char*>(&h16), 2);
    f.put(0x80); // GCT flag
    f.put(0);    // background color
    f.put(0);    // aspect ratio

    // Global color table (256 entries)
    for (int i = 0; i < 256; i++) {
        f.put(static_cast<char>((seed + i * 7) & 0xFF));
        f.put(static_cast<char>((seed + i * 11) & 0xFF));
        f.put(static_cast<char>((seed + i * 13) & 0xFF));
    }

    // Image descriptor
    f.put(0x2C);
    f.put(0); f.put(0); // left
    f.put(0); f.put(0); // top
    f.write(reinterpret_cast<char*>(&w16), 2);
    f.write(reinterpret_cast<char*>(&h16), 2);
    f.put(0); // no LCT

    // Image data (simplified - just LZW minimum code size + a block)
    f.put(8); // LZW min code size
    // Write some data blocks
    for (int i = 0; i < 10; i++) {
        f.put(255); // block size
        for (int j = 0; j < 255; j++) {
            f.put(static_cast<char>((seed + i * 31 + j * 17) & 0xFF));
        }
    }
    f.put(0); // block terminator

    // Trailer
    f.put(0x3B);
}

static void write_file(const std::string& path, const std::string& content) {
    fs::create_directories(fs::path(path).parent_path());
    std::ofstream f(path, std::ios::binary);
    if (f) f.write(content.data(), static_cast<std::streamsize>(content.size()));
}

int main(int argc, char* argv[]) {
    std::string base = "test_data";
    if (argc > 1) base = argv[1];

    // Clean up old test data
    std::error_code ec;
    fs::remove_all(base, ec);

    fs::create_directories(base);

    std::cout << "Generating test data in: " << base << std::endl;

    // ===== Create nested directory structure =====
    // test_data/
    //   src/
    //     auth/
    //       login.cpp, auth_service.cpp, token_handler.cpp, session_manager.cpp
    //     database/
    //       connection_pool.cpp, query_builder.cpp, migration_handler.cpp, schema_validator.cpp
    //     utils/
    //       logger.cpp, config_parser.cpp, json_serializer.cpp, string_utils.cpp
    //     search/
    //       vector_store.cpp, tfidf.cpp, inverted_index.cpp, cosine_similarity.cpp
    //     image/
    //       hasher.cpp, fingerprint.cpp, perceptual.cpp, base64_encoder.cpp
    //   docs/
    //     api/
    //       authentication.md, database_schema.md, search_engine.md
    //     guides/
    //       getting_started.md, deployment.md, configuration.md
    //   config/
    //     app.json, database.yml, logging.conf, secrets.env
    //   tests/
    //     unit/
    //       test_auth.cpp, test_database.cpp, test_search.cpp
    //     integration/
    //       test_api.py, test_e2e.py
    //   images/
    //     logos/
    //       logo_primary.png, logo_secondary.png, logo_dark.png
    //     photos/
    //       photo1.jpg, photo2.jpg, photo3.jpg, photo4.jpg
    //     icons/
    //       icon_home.png, icon_settings.png, icon_user.png
    //     banners/
    //       banner1.bmp, banner2.bmp
    //     gifs/
    //       animation1.gif, animation2.gif
    //   data/
    //     users.csv, products.csv, orders.json, logs.txt
    //   .hidden/
    //     .env, .gitignore, .secret_config
    //   scripts/
    //     deploy.sh, build.sh, test.sh
    //   styles/
    //     main.css, theme.scss
    //   web/
    //     index.html, app.js, styles.css
    //   README.md, CHANGELOG.md, LICENSE.txt

    // ===== Text files with known content =====

    // Auth files
    write_file(base + "/src/auth/login.cpp",
        "// Authentication login handler\n"
        "#include \"auth_service.h\"\n\n"
        "void LoginHandler::handle(const Request& req, Response& res) {\n"
        "    std::string username = req.get_param(\"username\");\n"
        "    std::string password = req.get_param(\"password\");\n"
        "    \n"
        "    if (auth_service.authenticate(username, password)) {\n"
        "        std::string token = token_handler.generate_token(username);\n"
        "        session_manager.create_session(token, username);\n"
        "        res.set_cookie(\"auth_token\", token);\n"
        "        res.json({{\"status\", \"success\"}, {\"token\", token}});\n"
        "    } else {\n"
        "        res.status(401).json({{\"error\", \"authentication failed\"}});\n"
        "    }\n"
        "}\n");

    write_file(base + "/src/auth/auth_service.cpp",
        "// Authentication service implementation\n"
        "#include \"auth_service.h\"\n"
        "#include <bcrypt/bcrypt.h>\n\n"
        "bool AuthService::authenticate(const std::string& username, const std::string& password) {\n"
        "    auto user = database.find_user(username);\n"
        "    if (!user) return false;\n"
        "    \n"
        "    return bcrypt::validate(password, user->password_hash);\n"
        "}\n\n"
        "bool AuthService::register_user(const std::string& username, const std::string& password) {\n"
        "    std::string hash = bcrypt::generate(password);\n"
        "    return database.insert_user(username, hash);\n"
        "}\n");

    write_file(base + "/src/auth/token_handler.cpp",
        "// JWT token handler for authentication\n"
        "#include \"token_handler.h\"\n"
        "#include <jwt/jwt.h>\n\n"
        "std::string TokenHandler::generate_token(const std::string& username) {\n"
        "    jwt::jwt_object obj{jwt::params::algorithm(\"HS256\")};\n"
        "    obj.add_claim(\"username\", username);\n"
        "    obj.add_claim(\"exp\", std::time(nullptr) + 3600);\n"
        "    obj.set_secret(config.get(\"jwt_secret\"));\n"
        "    return obj.signature();\n"
        "}\n\n"
        "bool TokenHandler::validate_token(const std::string& token) {\n"
        "    try {\n"
        "        auto decoded = jwt::decode(token, jwt::params::algorithm(\"HS256\"));\n"
        "        return true;\n"
        "    } catch (...) {\n"
        "        return false;\n"
        "    }\n"
        "}\n");

    write_file(base + "/src/auth/session_manager.cpp",
        "// Session management with Redis cache\n"
        "#include \"session_manager.h\"\n\n"
        "void SessionManager::create_session(const std::string& token, const std::string& username) {\n"
        "    Session session;\n"
        "    session.token = token;\n"
        "    session.username = username;\n"
        "    session.created_at = std::time(nullptr);\n"
        "    session.expires_at = session.created_at + 3600;\n"
        "    \n"
        "    cache.set(\"session:\" + token, session.serialize(), 3600);\n"
        "}\n\n"
        "bool SessionManager::validate_session(const std::string& token) {\n"
        "    auto data = cache.get(\"session:\" + token);\n"
        "    if (!data) return false;\n"
        "    return true;\n"
        "}\n");

    // Database files
    write_file(base + "/src/database/connection_pool.cpp",
        "// Database connection pool implementation\n"
        "#include \"connection_pool.h\"\n\n"
        "ConnectionPool::ConnectionPool(size_t max_connections, const std::string& conn_str)\n"
        "    : max_connections_(max_connections), conn_str_(conn_str) {\n"
        "    for (size_t i = 0; i < max_connections; i++) {\n"
        "        connections_.push(create_connection());\n"
        "    }\n"
        "}\n\n"
        "Connection ConnectionPool::acquire() {\n"
        "    std::unique_lock<std::mutex> lock(mutex_);\n"
        "    cv_.wait(lock, [this] { return !connections_.empty(); });\n"
        "    auto conn = connections_.front();\n"
        "    connections_.pop();\n"
        "    return conn;\n"
        "}\n");

    write_file(base + "/src/database/query_builder.cpp",
        "// SQL query builder with fluent interface\n"
        "#include \"query_builder.h\"\n\n"
        "QueryBuilder& QueryBuilder::select(const std::string& columns) {\n"
        "    query_ = \"SELECT \" + columns + \" FROM \" + table_;\n"
        "    return *this;\n"
        "}\n\n"
        "QueryBuilder& QueryBuilder::where(const std::string& condition) {\n"
        "    query_ += \" WHERE \" + condition;\n"
        "    return *this;\n"
        "}\n\n"
        "QueryBuilder& QueryBuilder::order_by(const std::string& column, bool desc) {\n"
        "    query_ += \" ORDER BY \" + column + (desc ? \" DESC\" : \" ASC\");\n"
        "    return *this;\n"
        "}\n");

    write_file(base + "/src/database/migration_handler.cpp",
        "// Database migration handler\n"
        "#include \"migration_handler.h\"\n\n"
        "void MigrationHandler::run_migrations() {\n"
        "    auto files = scan_migration_directory(\"migrations/\");\n"
        "    for (const auto& file : files) {\n"
        "        std::string sql = read_file(file);\n"
        "        database.execute(sql);\n"
        "        record_migration(file);\n"
        "    }\n"
        "}\n");

    write_file(base + "/src/database/schema_validator.cpp",
        "// Schema validation for database models\n"
        "#include \"schema_validator.h\"\n\n"
        "bool SchemaValidator::validate(const nlohmann::json& data, const Schema& schema) {\n"
        "    for (const auto& field : schema.required_fields) {\n"
        "        if (!data.contains(field.name)) {\n"
        "            errors.push_back(\"Missing required field: \" + field.name);\n"
        "            return false;\n"
        "        }\n"
        "    }\n"
        "    return true;\n"
        "}\n");

    // Utils files
    write_file(base + "/src/utils/logger.cpp",
        "// Logging utility with multiple log levels\n"
        "#include \"logger.h\"\n\n"
        "void Logger::log(Level level, const std::string& message) {\n"
        "    if (level < min_level_) return;\n"
        "    \n"
        "    std::lock_guard<std::mutex> lock(mutex_);\n"
        "    std::string formatted = format_message(level, message);\n"
        "    \n"
        "    if (console_output_) std::cout << formatted << std::endl;\n"
        "    if (file_output_) file_ << formatted << std::endl;\n"
        "}\n");

    write_file(base + "/src/utils/config_parser.cpp",
        "// Configuration parser for JSON and YAML files\n"
        "#include \"config_parser.h\"\n\n"
        "Config ConfigParser::parse(const std::string& filepath) {\n"
        "    std::string content = read_file(filepath);\n"
        "    std::string ext = get_extension(filepath);\n"
        "    \n"
        "    if (ext == \".json\") return parse_json(content);\n"
        "    if (ext == \".yaml\" || ext == \".yml\") return parse_yaml(content);\n"
        "    if (ext == \".ini\" || ext == \".conf\") return parse_ini(content);\n"
        "    \n"
        "    throw std::runtime_error(\"Unsupported config format: \" + ext);\n"
        "}\n");

    write_file(base + "/src/utils/json_serializer.cpp",
        "// JSON serialization utility\n"
        "#include \"json_serializer.h\"\n\n"
        "std::string JsonSerializer::serialize(const JsonValue& value) {\n"
        "    std::ostringstream ss;\n"
        "    serialize_value(ss, value);\n"
        "    return ss.str();\n"
        "}\n\n"
        "void JsonSerializer::serialize_value(std::ostringstream& ss, const JsonValue& value) {\n"
        "    if (value.is_string()) ss << \"\\\"\" << escape(value.as_string()) << \"\\\"\";\n"
        "    else if (value.is_number()) ss << value.as_number();\n"
        "    else if (value.is_bool()) ss << (value.as_bool() ? \"true\" : \"false\");\n"
        "    else if (value.is_null()) ss << \"null\";\n"
        "}\n");

    write_file(base + "/src/utils/string_utils.cpp",
        "// String utility functions\n"
        "#include \"string_utils.h\"\n\n"
        "std::vector<std::string> StringUtils::split(const std::string& str, char delimiter) {\n"
        "    std::vector<std::string> tokens;\n"
        "    std::stringstream ss(str);\n"
        "    std::string token;\n"
        "    while (std::getline(ss, token, delimiter)) {\n"
        "        tokens.push_back(token);\n"
        "    }\n"
        "    return tokens;\n"
        "}\n\n"
        "std::string StringUtils::trim(const std::string& str) {\n"
        "    size_t start = str.find_first_not_of(\" \\t\\n\\r\");\n"
        "    if (start == std::string::npos) return \"\";\n"
        "    size_t end = str.find_last_not_of(\" \\t\\n\\r\");\n"
        "    return str.substr(start, end - start + 1);\n"
        "}\n");

    // Search files
    write_file(base + "/src/search/vector_store.cpp",
        "// TF-IDF vector store for RAG-style retrieval\n"
        "#include \"vector_store.h\"\n\n"
        "void VectorStore::add_chunk(const std::string& text) {\n"
        "    auto tokens = tokenize(text);\n"
        "    auto tf = compute_term_frequency(tokens);\n"
        "    for (const auto& [term, freq] : tf) {\n"
        "        vocabulary_[term]++;\n"
        "        inverted_index_[term].push_back(current_chunk_id_);\n"
        "    }\n"
        "    chunks_.push_back({current_chunk_id_++, text, tf});\n"
        "}\n\n"
        "std::vector<SearchResult> VectorStore::search(const std::string& query, size_t top_k) {\n"
        "    auto query_vec = compute_tfidf_vector(query);\n"
        "    std::vector<SearchResult> results;\n"
        "    for (const auto& chunk : chunks_) {\n"
        "        double sim = cosine_similarity(query_vec, chunk.tfidf_vector);\n"
        "        if (sim > 0) results.push_back({chunk.id, sim});\n"
        "    }\n"
        "    std::sort(results.begin(), results.end(), [](auto& a, auto& b) { return a.score > b.score; });\n"
        "    if (results.size() > top_k) results.resize(top_k);\n"
        "    return results;\n"
        "}\n");

    write_file(base + "/src/search/tfidf.cpp",
        "// TF-IDF computation for text indexing\n"
        "#include \"tfidf.h\"\n\n"
        "double TfIdf::compute_tf(const std::string& term, const std::vector<std::string>& tokens) {\n"
        "    int count = 0;\n"
        "    for (const auto& t : tokens) {\n"
        "        if (t == term) count++;\n"
        "    }\n"
        "    return static_cast<double>(count) / tokens.size();\n"
        "}\n\n"
        "double TfIdf::compute_idf(const std::string& term, size_t total_docs, int doc_freq) {\n"
        "    return std::log(static_cast<double>(total_docs) / doc_freq);\n"
        "}\n");

    write_file(base + "/src/search/inverted_index.cpp",
        "// Inverted index for fast text search\n"
        "#include \"inverted_index.h\"\n\n"
        "void InvertedIndex::add(const std::string& term, int doc_id, double frequency) {\n"
        "    postings_[term].push_back({doc_id, frequency});\n"
        "}\n\n"
        "std::vector<Posting> InvertedIndex::search(const std::string& term) {\n"
        "    auto it = postings_.find(term);\n"
        "    if (it == postings_.end()) return {};\n"
        "    return it->second;\n"
        "}\n");

    write_file(base + "/src/search/cosine_similarity.cpp",
        "// Cosine similarity for vector comparison\n"
        "#include \"cosine_similarity.h\"\n\n"
        "double cosine_similarity(const std::unordered_map<std::string, double>& a,\n"
        "                         const std::unordered_map<std::string, double>& b) {\n"
        "    double dot = 0, mag_a = 0, mag_b = 0;\n"
        "    for (const auto& [term, val] : a) {\n"
        "        auto it = b.find(term);\n"
        "        if (it != b.end()) dot += val * it->second;\n"
        "        mag_a += val * val;\n"
        "    }\n"
        "    for (const auto& [term, val] : b) mag_b += val * val;\n"
        "    if (mag_a == 0 || mag_b == 0) return 0;\n"
        "    return dot / (std::sqrt(mag_a) * std::sqrt(mag_b));\n"
        "}\n");

    // Image processing files
    write_file(base + "/src/image/hasher.cpp",
        "// Image hashing for content identification\n"
        "#include \"hasher.h\"\n\n"
        "uint64_t ImageHasher::compute_hash(const std::vector<uint8_t>& data) {\n"
        "    uint64_t hash = 0xcbf29ce484222325ULL;\n"
        "    for (auto byte : data) {\n"
        "        hash ^= byte;\n"
        "        hash *= 0x100000001b3ULL;\n"
        "    }\n"
        "    return hash;\n"
        "}\n");

    write_file(base + "/src/image/fingerprint.cpp",
        "// Image fingerprinting with base64 encoding\n"
        "#include \"fingerprint.h\"\n\n"
        "ImageFingerprint Fingerprinter::fingerprint(const std::vector<uint8_t>& data) {\n"
        "    ImageFingerprint fp;\n"
        "    fp.content_hash = hasher_.compute_hash(data);\n"
        "    fp.base64_hash = base64_encode(data.data(), std::min(data.size(), size_t(48)));\n"
        "    fp.perceptual_hash = compute_perceptual_hash(data);\n"
        "    fp.format = detect_format(data);\n"
        "    fp.dimensions = detect_dimensions(data, fp.format);\n"
        "    return fp;\n"
        "}\n");

    write_file(base + "/src/image/perceptual.cpp",
        "// Perceptual hashing for similar image detection\n"
        "#include \"perceptual.h\"\n\n"
        "uint64_t PerceptualHasher::compute(const std::vector<uint8_t>& data) {\n"
        "    if (data.size() < 64) return fnv1a(data);\n"
        "    \n"
        "    size_t step = (data.size() - 64) / 64;\n"
        "    uint8_t samples[64];\n"
        "    for (int i = 0; i < 64; i++) {\n"
        "        samples[i] = data[64 + i * step];\n"
        "    }\n"
        "    \n"
        "    uint32_t sum = 0;\n"
        "    for (int i = 0; i < 64; i++) sum += samples[i];\n"
        "    uint8_t avg = sum / 64;\n"
        "    \n"
        "    uint64_t hash = 0;\n"
        "    for (int i = 0; i < 64; i++) {\n"
        "        if (samples[i] > avg) hash |= (1ULL << i);\n"
        "    }\n"
        "    return hash;\n"
        "}\n");

    write_file(base + "/src/image/base64_encoder.cpp",
        "// Base64 encoding utility for image data\n"
        "#include \"base64_encoder.h\"\n\n"
        "static const char chars[] = \"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/\";\n\n"
        "std::string Base64Encoder::encode(const uint8_t* data, size_t len) {\n"
        "    std::string result;\n"
        "    for (size_t i = 0; i < len; i += 3) {\n"
        "        uint32_t triple = 0;\n"
        "        int pad = 0;\n"
        "        triple |= (uint32_t)data[i] << 16;\n"
        "        if (i + 1 < len) triple |= (uint32_t)data[i+1] << 8; else pad++;\n"
        "        if (i + 2 < len) triple |= (uint32_t)data[i+2]; else pad++;\n"
        "        result += chars[(triple >> 18) & 0x3F];\n"
        "        result += chars[(triple >> 12) & 0x3F];\n"
        "        result += (pad < 2) ? chars[(triple >> 6) & 0x3F] : '=';\n"
        "        result += (pad < 1) ? chars[triple & 0x3F] : '=';\n"
        "    }\n"
        "    return result;\n"
        "}\n");

    // Docs
    write_file(base + "/docs/api/authentication.md",
        "# Authentication API\n\n"
        "## Overview\n"
        "The authentication system provides secure login, token generation, and session management.\n\n"
        "## Endpoints\n"
        "- `POST /api/auth/login` - Login with username and password\n"
        "- `POST /api/auth/register` - Register a new user\n"
        "- `POST /api/auth/refresh` - Refresh authentication token\n"
        "- `POST /api/auth/logout` - Logout and invalidate session\n\n"
        "## Token Format\n"
        "Tokens are JWT formatted with HS256 signing. Claims include username and expiration.\n");

    write_file(base + "/docs/api/database_schema.md",
        "# Database Schema\n\n"
        "## Tables\n\n"
        "### users\n"
        "- id (PK, UUID)\n"
        "- username (VARCHAR, UNIQUE)\n"
        "- password_hash (VARCHAR)\n"
        "- created_at (TIMESTAMP)\n\n"
        "### sessions\n"
        "- token (PK, VARCHAR)\n"
        "- user_id (FK, UUID)\n"
        "- expires_at (TIMESTAMP)\n\n"
        "### migrations\n"
        "- id (PK, SERIAL)\n"
        "- filename (VARCHAR)\n"
        "- executed_at (TIMESTAMP)\n");

    write_file(base + "/docs/api/search_engine.md",
        "# Search Engine API\n\n"
        "## Overview\n"
        "The search engine provides TF-IDF vectorized text search with cosine similarity ranking.\n\n"
        "## Features\n"
        "- Text chunking with overlapping windows\n"
        "- TF-IDF vectorization\n"
        "- Inverted index for fast retrieval\n"
        "- Cosine similarity scoring\n"
        "- Image fingerprinting with base64 and perceptual hashes\n\n"
        "## Usage\n"
        "```cpp\n"
        "VectorStore store;\n"
        "store.add_chunk(\"some text content\");\n"
        "store.finalize();\n"
        "auto results = store.search(\"query text\", 10);\n"
        "```\n");

    write_file(base + "/docs/guides/getting_started.md",
        "# Getting Started\n\n"
        "## Installation\n"
        "1. Clone the repository\n"
        "2. Run `cmake -B build && cmake --build build`\n"
        "3. The executable will be in `build/aisearch`\n\n"
        "## Quick Start\n"
        "```bash\n"
        "aisearch index ./my-project\n"
        "aisearch search ./my-project --query \"authentication\"\n"
        "```\n");

    write_file(base + "/docs/guides/deployment.md",
        "# Deployment Guide\n\n"
        "## Docker\n"
        "```dockerfile\n"
        "FROM ubuntu:22.04\n"
        "COPY aisearch /usr/local/bin/\n"
        "CMD [\"aisearch\", \"index\", \"/data\"]\n"
        "```\n\n"
        "## Kubernetes\n"
        "Deploy as a sidecar container for AI agents to query file contents.\n");

    write_file(base + "/docs/guides/configuration.md",
        "# Configuration Guide\n\n"
        "## Config File\n"
        "The tool reads configuration from `config/app.json`:\n\n"
        "```json\n"
        "{\n"
        "  \"chunk_size\": 512,\n"
        "  \"overlap\": 64,\n"
        "  \"top_k\": 10,\n"
        "  \"include_hidden\": false\n"
        "}\n"
        "```\n");

    // Config files
    write_file(base + "/config/app.json",
        "{\n"
        "  \"app_name\": \"AI Search Tool\",\n"
        "  \"version\": \"1.0.0\",\n"
        "  \"chunk_size\": 512,\n"
        "  \"overlap\": 64,\n"
        "  \"top_k\": 10,\n"
        "  \"log_level\": \"info\",\n"
        "  \"max_file_size\": 10485760,\n"
        "  \"include_hidden\": false,\n"
        "  \"image_formats\": [\"png\", \"jpg\", \"jpeg\", \"bmp\", \"gif\", \"webp\"]\n"
        "}\n");

    write_file(base + "/config/database.yml",
        "database:\n"
        "  host: localhost\n"
        "  port: 5432\n"
        "  name: aisearch_db\n"
        "  user: postgres\n"
        "  pool_size: 10\n"
        "  timeout: 30\n"
        "  ssl: true\n");

    write_file(base + "/config/logging.conf",
        "[log]\n"
        "level=info\n"
        "format=%(asctime)s [%(levelname)s] %(message)s\n"
        "file=/var/log/aisearch.log\n"
        "max_size=100MB\n"
        "backup_count=5\n");

    write_file(base + "/config/secrets.env",
        "JWT_SECRET=super_secret_key_change_in_production\n"
        "REDIS_URL=redis://localhost:6379\n"
        "DATABASE_URL=postgresql://user:pass@localhost:5432/db\n");

    // Test files
    write_file(base + "/tests/unit/test_auth.cpp",
        "#include <cassert>\n"
        "#include \"auth_service.h\"\n\n"
        "void test_authentication_success() {\n"
        "    AuthService auth;\n"
        "    auth.register_user(\"testuser\", \"password123\");\n"
        "    assert(auth.authenticate(\"testuser\", \"password123\"));\n"
        "}\n\n"
        "void test_authentication_failure() {\n"
        "    AuthService auth;\n"
        "    assert(!auth.authenticate(\"nonexistent\", \"wrong\"));\n"
        "}\n\n"
        "void test_token_generation() {\n"
        "    TokenHandler handler;\n"
        "    auto token = handler.generate_token(\"user\");\n"
        "    assert(!token.empty());\n"
        "    assert(handler.validate_token(token));\n"
        "}\n");

    write_file(base + "/tests/unit/test_database.cpp",
        "#include <cassert>\n"
        "#include \"connection_pool.h\"\n\n"
        "void test_connection_pool() {\n"
        "    ConnectionPool pool(5, \"postgresql://localhost/db\");\n"
        "    auto conn = pool.acquire();\n"
        "    assert(conn.is_valid());\n"
        "    pool.release(conn);\n"
        "}\n\n"
        "void test_query_builder() {\n"
        "    QueryBuilder qb(\"users\");\n"
        "    auto query = qb.select(\"*\").where(\"age > 18\").order_by(\"name\").build();\n"
        "    assert(query.find(\"SELECT\") != std::string::npos);\n"
        "    assert(query.find(\"WHERE\") != std::string::npos);\n"
        "}\n");

    write_file(base + "/tests/unit/test_search.cpp",
        "#include <cassert>\n"
        "#include \"vector_store.h\"\n\n"
        "void test_tfidf_search() {\n"
        "    VectorStore store;\n"
        "    store.add_chunk(\"authentication token validation\");\n"
        "    store.add_chunk(\"database connection pool\");\n"
        "    store.finalize();\n"
        "    auto results = store.search(\"authentication\", 5);\n"
        "    assert(!results.empty());\n"
        "    assert(results[0].score > 0);\n"
        "}\n\n"
        "void test_cosine_similarity() {\n"
        "    std::unordered_map<std::string, double> a = {{\"hello\", 1.0}, {\"world\", 0.5}};\n"
        "    std::unordered_map<std::string, double> b = {{\"hello\", 1.0}, {\"world\", 0.5}};\n"
        "    assert(cosine_similarity(a, b) > 0.99);\n"
        "}\n");

    write_file(base + "/tests/integration/test_api.py",
        "import requests\n\n"
        "def test_login_endpoint():\n"
        "    response = requests.post('http://localhost:8080/api/auth/login',\n"
        "        json={'username': 'admin', 'password': 'admin'})\n"
        "    assert response.status_code == 200\n"
        "    assert 'token' in response.json()\n\n"
        "def test_search_endpoint():\n"
        "    response = requests.get('http://localhost:8080/api/search',\n"
        "        params={'query': 'authentication'})\n"
        "    assert response.status_code == 200\n"
        "    assert len(response.json()['results']) > 0\n");

    write_file(base + "/tests/integration/test_e2e.py",
        "import subprocess\n"
        "import json\n\n"
        "def test_full_search_workflow():\n"
        "    result = subprocess.run(['./aisearch', 'index', './test_data'], capture_output=True)\n"
        "    assert result.returncode == 0\n"
        "    \n"
        "    result = subprocess.run(['./aisearch', 'search', './test_data', '--query', 'auth'], capture_output=True)\n"
        "    assert result.returncode == 0\n"
        "    data = json.loads(result.stdout)\n"
        "    assert data['total_hits'] > 0\n");

    // Data files
    write_file(base + "/data/users.csv",
        "id,username,email,created_at\n"
        "1,admin,admin@example.com,2024-01-01T00:00:00Z\n"
        "2,john_doe,john@example.com,2024-01-15T10:30:00Z\n"
        "3,jane_smith,jane@example.com,2024-02-01T14:45:00Z\n"
        "4,bob_wilson,bob@example.com,2024-02-15T09:15:00Z\n"
        "5,alice_brown,alice@example.com,2024-03-01T16:20:00Z\n");

    write_file(base + "/data/products.csv",
        "id,name,category,price,stock\n"
        "1,Laptop,Electronics,999.99,50\n"
        "2,Mouse,Electronics,29.99,200\n"
        "3,Keyboard,Electronics,79.99,150\n"
        "4,Monitor,Electronics,399.99,30\n"
        "5,Headphones,Electronics,149.99,100\n");

    write_file(base + "/data/orders.json",
        "[\n"
        "  {\"order_id\": 1001, \"user_id\": 1, \"product_id\": 1, \"quantity\": 1, \"total\": 999.99},\n"
        "  {\"order_id\": 1002, \"user_id\": 2, \"product_id\": 2, \"quantity\": 2, \"total\": 59.98},\n"
        "  {\"order_id\": 1003, \"user_id\": 3, \"product_id\": 3, \"quantity\": 1, \"total\": 79.99}\n"
        "]\n");

    write_file(base + "/data/logs.txt",
        "[2024-01-01 10:00:00] INFO: Server started on port 8080\n"
        "[2024-01-01 10:00:01] INFO: Database connection established\n"
        "[2024-01-01 10:00:02] INFO: Redis cache connected\n"
        "[2024-01-01 10:05:00] WARNING: High memory usage detected\n"
        "[2024-01-01 10:10:00] ERROR: Authentication failed for user 'test'\n"
        "[2024-01-01 10:10:01] ERROR: Invalid token provided\n"
        "[2024-01-01 10:15:00] INFO: Search index built successfully\n"
        "[2024-01-01 10:20:00] DEBUG: TF-IDF vector computation completed\n"
        "[2024-01-01 10:25:00] ERROR: Database connection timeout\n"
        "[2024-01-01 10:30:00] INFO: Connection pool recovered\n");

    // Scripts
    write_file(base + "/scripts/deploy.sh",
        "#!/bin/bash\n"
        "# Deployment script for AI search tool\n"
        "set -e\n\n"
        "echo \"Building AI search tool...\"\n"
        "cmake -B build -DCMAKE_BUILD_TYPE=Release\n"
        "cmake --build build --config Release\n\n"
        "echo \"Deploying...\"\n"
        "cp build/aisearch /usr/local/bin/\n"
        "echo \"Deployment complete!\"\n");

    write_file(base + "/scripts/build.sh",
        "#!/bin/bash\n"
        "set -e\n"
        "mkdir -p build\n"
        "cd build\n"
        "cmake .. -DCMAKE_BUILD_TYPE=Debug\n"
        "make -j$(nproc)\n"
        "echo \"Build complete\"\n");

    write_file(base + "/scripts/test.sh",
        "#!/bin/bash\n"
        "set -e\n"
        "echo \"Running tests...\"\n"
        "./build/aisearch test_data\n"
        "echo \"All tests passed!\"\n");

    // Web files
    write_file(base + "/web/index.html",
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "    <title>AI Search Tool</title>\n"
        "    <link rel=\"stylesheet\" href=\"styles.css\">\n"
        "</head>\n"
        "<body>\n"
        "    <div id=\"app\">\n"
        "        <h1>AI Search Tool</h1>\n"
        "        <input type=\"text\" id=\"search-input\" placeholder=\"Search...\">\n"
        "        <div id=\"results\"></div>\n"
        "    </div>\n"
        "    <script src=\"app.js\"></script>\n"
        "</body>\n"
        "</html>\n");

    write_file(base + "/web/app.js",
        "class SearchClient {\n"
        "    constructor(baseUrl) {\n"
        "        this.baseUrl = baseUrl;\n"
        "    }\n\n"
        "    async search(query) {\n"
        "        const response = await fetch(`${this.baseUrl}/api/search?query=${encodeURIComponent(query)}`);\n"
        "        return response.json();\n"
        "    }\n"
        "}\n\n"
        "const client = new SearchClient('http://localhost:8080');\n"
        "document.getElementById('search-input').addEventListener('input', async (e) => {\n"
        "    const results = await client.search(e.target.value);\n"
        "    displayResults(results);\n"
        "});\n");

    write_file(base + "/web/styles.css",
        "body { font-family: Arial, sans-serif; margin: 20px; }\n"
        "#search-input { width: 100%; padding: 10px; font-size: 16px; }\n"
        ".result-item { padding: 10px; border-bottom: 1px solid #eee; }\n"
        ".result-item .snippet { color: #666; font-size: 14px; }\n");

    // Styles
    write_file(base + "/styles/main.css",
        ":root {\n"
        "  --primary: #007bff;\n"
        "  --secondary: #6c757d;\n"
        "  --success: #28a745;\n"
        "  --error: #dc3545;\n"
        "}\n"
        "body { font-family: 'Segoe UI', sans-serif; }\n");

    write_file(base + "/styles/theme.scss",
        "$primary-color: #007bff;\n"
        "$border-radius: 4px;\n"
        "\n"
        ".button {\n"
        "  background: $primary-color;\n"
        "  border-radius: $border-radius;\n"
        "  padding: 8px 16px;\n"
        "}\n");

    // Root files
    write_file(base + "/README.md",
        "# AI Search Tool\n\n"
        "A C++ tool for vectorized file content search designed for AI agents.\n\n"
        "## Features\n"
        "- TF-IDF vectorized text search\n"
        "- Image fingerprinting with base64 and perceptual hashes\n"
        "- Recursive directory scanning\n"
        "- JSON output for AI consumption\n\n"
        "## Build\n"
        "```bash\n"
        "cmake -B build && cmake --build build\n"
        "```\n");

    write_file(base + "/CHANGELOG.md",
        "# Changelog\n\n"
        "## v1.0.0\n"
        "- Initial release\n"
        "- TF-IDF vector search\n"
        "- Image fingerprinting\n"
        "- JSON output\n");

    write_file(base + "/LICENSE.txt",
        "MIT License\n\n"
        "Copyright (c) 2024 AI Search Tool\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        "of this software and associated documentation files...\n");

    // Hidden files
    write_file(base + "/.hidden/.env",
        "SECRET_KEY=abc123def456\n"
        "API_KEY=xyz789\n"
        "DATABASE_PASSWORD=supersecret\n");

    write_file(base + "/.hidden/.gitignore",
        "build/\n"
        "*.o\n"
        "*.obj\n"
        "*.exe\n"
        ".env\n"
        "node_modules/\n");

    write_file(base + "/.hidden/.secret_config",
        "encryption_key=256bit_key_here\n"
        "salt=random_salt_value\n");

    // ===== Root-level .gitignore for gitignore support testing =====
    write_file(base + "/.gitignore",
        "*.tmp\n"
        "*.log\n"
        "build/\n"
        "node_modules/\n"
        "*.exe\n"
        "*.obj\n"
        "temp/\n"
        "ignored_file.txt\n"
        "data/ignored_data.json\n");
    write_file(base + "/ignored_file.txt",
        "This file should be ignored by gitignore.\n"
        "It contains authentication secrets and should not be indexed.\n");
    write_file(base + "/data/ignored_data.json",
        "{\"ignored\": true, \"secret\": \"should_not_appear\"}\n");
    write_file(base + "/temp/temp_file.tmp",
        "Temporary file that should be ignored.\n");
    write_file(base + "/build/build_artifact.txt",
        "Build artifact that should be ignored.\n");

    // ===== Generate images =====
    std::cout << "Generating images..." << std::endl;

    // Logos (PNG, similar to each other for similar image testing)
    write_png(base + "/images/logos/logo_primary.png", 128, 128, 42);
    write_png(base + "/images/logos/logo_secondary.png", 128, 128, 42);  // Same seed = same image (duplicate)
    write_png(base + "/images/logos/logo_dark.png", 128, 128, 99);       // Different seed

    // Photos (JPEG)
    write_jpeg(base + "/images/photos/photo1.jpg", 640, 480, 10);
    write_jpeg(base + "/images/photos/photo2.jpg", 640, 480, 20);
    write_jpeg(base + "/images/photos/photo3.jpg", 800, 600, 30);
    write_jpeg(base + "/images/photos/photo4.jpg", 320, 240, 40);

    // Icons (PNG, small)
    write_png(base + "/images/icons/icon_home.png", 32, 32, 200);
    write_png(base + "/images/icons/icon_settings.png", 32, 32, 201);
    write_png(base + "/images/icons/icon_user.png", 32, 32, 202);

    // Banners (BMP)
    write_bmp(base + "/images/banners/banner1.bmp", 400, 100, 50);
    write_bmp(base + "/images/banners/banner2.bmp", 400, 100, 60);

    // GIFs
    write_gif(base + "/images/gifs/animation1.gif", 100, 100, 150);
    write_gif(base + "/images/gifs/animation2.gif", 100, 100, 151);

    // Duplicate image (exact copy of logo_primary for dedup testing)
    write_png(base + "/images/logos/logo_copy.png", 128, 128, 42);

    // ===== Generate large random text files =====
    std::cout << "Generating large text files..." << std::endl;
    write_file(base + "/data/large_document.txt", random_text(500));
    write_file(base + "/data/medium_doc.md", random_text(200));
    write_file(base + "/src/utils/large_util.cpp", random_text(300));

    // Small files for size filter testing
    write_file(base + "/data/tiny.txt", "hello world\n");
    write_file(base + "/data/small.json", "{\"key\":\"value\"}\n");

    // File with specific known phrases for exact phrase search
    write_file(base + "/docs/guides/special.md",
        "# Special Guide\n\n"
        "This document contains a TODO fix this section that needs attention.\n"
        "The FIXME handle error case is also important.\n"
        "Please review the HACK temporary workaround before merging.\n"
        "The NOTE important security consideration must be followed.\n");

    // ===== EXPANDED TEST DATA for scenario 2 =====
    std::cout << "Generating expanded test data..." << std::endl;

    // --- Empty files ---
    write_file(base + "/data/empty.txt", "");
    write_file(base + "/data/empty.json", "");
    write_file(base + "/data/empty.md", "");
    write_file(base + "/src/utils/empty_util.cpp", "");

    // --- Deeply nested directories ---
    write_file(base + "/deep/a/b/c/d/e/f/deep_file.txt",
        "This file is deeply nested in many directories.\n"
        "It tests the recursive directory scanning capability.\n"
        "Keywords: deep nesting recursive scan directory traversal\n");
    write_file(base + "/deep/a/b/c/d/e/f/g/h/very_deep.cpp",
        "// Very deeply nested C++ file\n"
        "int main() { return 0; }\n");
    write_file(base + "/deep/level1/level2/level3/level4/config.xml",
        "<?xml version=\"1.0\"?>\n"
        "<config>\n"
        "  <server port=\"8080\"/>\n"
        "  <database host=\"localhost\"/>\n"
        "</config>\n");

    // --- Duplicate content files (same text, different names) ---
    std::string dup_content =
        "This is duplicate content for testing file deduplication.\n"
        "The search tool should find all copies of this text.\n"
        "Keywords: duplicate copy dedup identical content\n";
    write_file(base + "/data/copy1.txt", dup_content);
    write_file(base + "/data/copy2.txt", dup_content);
    write_file(base + "/data/copy3.txt", dup_content);

    // --- Various programming language files ---
    write_file(base + "/src/lang/typescript.ts",
        "// TypeScript interface definition\n"
        "interface SearchRequest {\n"
        "    query: string;\n"
        "    topK: number;\n"
        "    filters?: SearchFilter;\n"
        "}\n\n"
        "export class SearchService {\n"
        "    async search(request: SearchRequest): Promise<SearchResult[]> {\n"
        "        const response = await fetch('/api/search', {\n"
        "            method: 'POST',\n"
        "            body: JSON.stringify(request)\n"
        "        });\n"
        "        return response.json();\n"
        "    }\n"
        "}\n");

    write_file(base + "/src/lang/golang.go",
        "package main\n\n"
        "import (\n"
        "    \"fmt\"\n"
        "    \"net/http\"\n"
        ")\n\n"
        "func searchHandler(w http.ResponseWriter, r *http.Request) {\n"
        "    query := r.URL.Query().Get(\"query\")\n"
        "    fmt.Fprintf(w, \"Search results for: %s\", query)\n"
        "}\n\n"
        "func main() {\n"
        "    http.HandleFunc(\"/search\", searchHandler)\n"
        "    http.ListenAndServe(\":8080\", nil)\n"
        "}\n");

    write_file(base + "/src/lang/rust.rs",
        "use std::collections::HashMap;\n\n"
        "pub struct InvertedIndex {\n"
        "    postings: HashMap<String, Vec<u32>>,\n"
        "}\n\n"
        "impl InvertedIndex {\n"
        "    pub fn new() -> Self {\n"
        "        InvertedIndex { postings: HashMap::new() }\n"
        "    }\n\n"
        "    pub fn add(&mut self, term: &str, doc_id: u32) {\n"
        "        self.postings.entry(term.to_string()).or_insert_with(Vec::new).push(doc_id);\n"
        "    }\n"
        "}\n");

    write_file(base + "/src/lang/swift.swift",
        "import Foundation\n\n"
        "class ImageFingerprint {\n"
        "    var perceptualHash: UInt64\n"
        "    var base64Hash: String\n"
        "    \n"
        "    init(data: [UInt8]) {\n"
        "        self.perceptualHash = Self.computePerceptualHash(data)\n"
        "        self.base64Hash = Self.base64Encode(data)\n"
        "    }\n"
        "}\n");

    write_file(base + "/src/lang/kotlin.kt",
        "data class SearchResult(\n"
        "    val filePath: String,\n"
        "    val score: Double,\n"
        "    val snippet: String\n"
        ")\n\n"
        "class SearchEngine {\n"
        "    fun search(query: String, topK: Int): List<SearchResult> {\n"
        "        return emptyList()\n"
        "    }\n"
        "}\n");

    write_file(base + "/src/lang/python_model.py",
        "import numpy as np\n"
        "from sklearn.feature_extraction.text import TfidfVectorizer\n\n"
        "class SearchModel:\n"
        "    def __init__(self):\n"
        "        self.vectorizer = TfidfVectorizer(\n"
        "            max_features=10000,\n"
        "            stop_words='english'\n"
        "        )\n"
        "    \n"
        "    def fit(self, documents):\n"
        "        self.tfidf_matrix = self.vectorizer.fit_transform(documents)\n"
        "    \n"
        "    def search(self, query, top_k=10):\n"
        "        query_vec = self.vectorizer.transform([query])\n"
        "        scores = (self.tfidf_matrix @ query_vec.T).toarray().flatten()\n"
        "        top_indices = np.argsort(scores)[-top_k:][::-1]\n"
        "        return top_indices, scores[top_indices]\n");

    // --- Config and system files ---
    write_file(base + "/sys/Dockerfile",
        "FROM node:18-alpine\n"
        "WORKDIR /app\n"
        "COPY package*.json ./\n"
        "RUN npm install\n"
        "COPY . .\n"
        "EXPOSE 3000\n"
        "CMD [\"node\", \"server.js\"]\n");

    write_file(base + "/sys/docker-compose.yml",
        "version: '3.8'\n"
        "services:\n"
        "  app:\n"
        "    build: .\n"
        "    ports:\n"
        "      - \"3000:3000\"\n"
        "  redis:\n"
        "    image: redis:7-alpine\n"
        "  postgres:\n"
        "    image: postgres:15\n"
        "    environment:\n"
        "      POSTGRES_DB: aisearch\n");

    write_file(base + "/sys/Makefile",
        "CXX = g++\n"
        "CXXFLAGS = -std=c++17 -O2 -Wall\n"
        "\n"
        "all: aisearch\n"
        "\n"
        "aisearch: main.cpp search_engine.cpp\n"
        "\t$(CXX) $(CXXFLAGS) -o aisearch main.cpp search_engine.cpp\n"
        "\n"
        "clean:\n"
        "\trm -f aisearch\n");

    write_file(base + "/sys/CMakeLists.txt",
        "cmake_minimum_required(VERSION 3.16)\n"
        "project(AISearch CXX)\n"
        "set(CMAKE_CXX_STANDARD 17)\n"
        "add_executable(aisearch main.cpp search_engine.cpp)\n");

    write_file(base + "/sys/.gitignore",
        "build/\n"
        "*.o\n"
        "*.exe\n"
        "node_modules/\n"
        ".env\n");

    // --- SQL files ---
    write_file(base + "/sql/schema.sql",
        "-- Database schema for AI search tool\n"
        "CREATE TABLE documents (\n"
        "    id SERIAL PRIMARY KEY,\n"
        "    path VARCHAR(512) NOT NULL,\n"
        "    content TEXT,\n"
        "    created_at TIMESTAMP DEFAULT NOW()\n"
        ");\n\n"
        "CREATE INDEX idx_documents_content ON documents USING gin(to_tsvector(content));\n");

    write_file(base + "/sql/migration_001.sql",
        "-- Initial migration\n"
        "CREATE TABLE users (\n"
        "    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
        "    username VARCHAR(255) UNIQUE NOT NULL,\n"
        "    password_hash VARCHAR(255) NOT NULL\n"
        ");\n");

    // --- XML and data formats ---
    write_file(base + "/data/config.xml",
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<settings>\n"
        "  <search>\n"
        "    <chunk_size>512</chunk_size>\n"
        "    <overlap>64</overlap>\n"
        "  </search>\n"
        "  <image>\n"
        "    <formats>png,jpg,bmp,gif</formats>\n"
        "  </image>\n"
        "</settings>\n");

    write_file(base + "/data/toml_config.toml",
        "[server]\n"
        "host = \"0.0.0.0\"\n"
        "port = 8080\n\n"
        "[search]\n"
        "top_k = 10\n"
        "max_distance = 15\n");

    // --- Log files with different levels ---
    write_file(base + "/logs/error.log",
        "[ERROR] 2024-03-01: Failed to connect to database\n"
        "[ERROR] 2024-03-01: Authentication token expired\n"
        "[ERROR] 2024-03-02: Image fingerprinting failed for photo.jpg\n"
        "[ERROR] 2024-03-02: Vector store index corruption detected\n");

    write_file(base + "/logs/access.log",
        "192.168.1.1 GET /api/search?query=authentication 200 1234ms\n"
        "192.168.1.2 POST /api/auth/login 200 56ms\n"
        "192.168.1.3 GET /api/search?query=database 200 892ms\n"
        "192.168.1.4 GET /images/logo.png 200 12ms\n");

    // --- Markdown with code blocks ---
    write_file(base + "/docs/guides/code_examples.md",
        "# Code Examples\n\n"
        "## C++ Search Example\n"
        "```cpp\n"
        "VectorStore store;\n"
        "store.add_chunk(\"authentication token\");\n"
        "store.finalize();\n"
        "auto results = store.search(\"auth\", 10);\n"
        "```\n\n"
        "## Python Search Example\n"
        "```python\n"
        "from sklearn.feature_extraction.text import TfidfVectorizer\n"
        "vectorizer = TfidfVectorizer()\n"
        "matrix = vectorizer.fit_transform(documents)\n"
        "```\n");

    // --- Files with numbers and special patterns ---
    write_file(base + "/data/numbers.txt",
        "File ID: 12345\n"
        "Version: 2.0.1\n"
        "Port: 8080\n"
        "Timeout: 30000\n"
        "MaxConnections: 100\n"
        "BufferSize: 4096\n");

    // --- Very small image for edge case ---
    write_png(base + "/images/tiny_1x1.png", 1, 1, 255);
    write_png(base + "/images/tiny_2x2.png", 2, 2, 128);

    // --- Large image for dimension detection ---
    write_png(base + "/images/large_1024.png", 1024, 768, 77);

    // --- More duplicate images for dedup testing ---
    write_jpeg(base + "/images/dup_photo1.jpg", 640, 480, 10);  // Same as photo1.jpg
    write_bmp(base + "/images/dup_banner1.bmp", 400, 100, 50);  // Same as banner1.bmp

    // --- File with only whitespace ---
    write_file(base + "/data/whitespace.txt", "   \n\n   \t\t  \n");

    // --- File with UTF-8 content (non-ASCII characters) ---
    {
        std::ofstream f(base + "/data/utf8_test.txt", std::ios::binary);
        if (f) {
            f << "UTF-8 test file with international characters\n";
            f << "Caf\xC3\xA9" << " r\xC3\xA9" << "sum\xC3\xA9" << " na\xC3\xAF" << "ve\n";
            f << "\xE4\xB8\xAD\xE6\x96\x87" << " test Chinese characters\n";
            f << "\xC3\x9C" << "ber \xC3\xA4" << "nderung\n";
            f << "Emoji test: \xF0\x9F\x9A\x80" << " rocket\n";
        }
    }

    // --- File with single character ---
    write_file(base + "/data/single_char.txt", "X");

    // --- File with very long line ---
    std::string long_line(5000, 'A');
    write_file(base + "/data/long_line.txt", long_line + "\n");

    // --- Multiple files with same name in different dirs ---
    write_file(base + "/dup_name/config.txt", "config in dup_name dir\n");
    write_file(base + "/deep/a/b/config.txt", "config in deep dir\n");
    write_file(base + "/src/config.txt", "config in src dir\n");

    // --- File with JSON array ---
    write_file(base + "/data/array.json",
        "[\"authentication\", \"database\", \"config\", \"search\", \"image\", \"hash\"]\n");

    // --- File with nested JSON ---
    write_file(base + "/data/nested.json",
        "{\n"
        "  \"search\": {\n"
        "    \"engine\": {\n"
        "      \"type\": \"tfidf\",\n"
        "      \"params\": {\n"
        "        \"top_k\": 10,\n"
        "        \"threshold\": 0.01\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n");

    // --- TypeScript JSX file ---
    write_file(base + "/src/lang/component.tsx",
        "import React from 'react';\n\n"
        "export const SearchBar: React.FC = () => {\n"
        "    return (\n"
        "        <input type=\"text\" placeholder=\"Search...\" />\n"
        "    );\n"
        "};\n");

    // --- Ruby file ---
    write_file(base + "/src/lang/ruby.rb",
        "class SearchController < ApplicationController\n"
        "  def search\n"
        "    query = params[:query]\n"
        "    results = SearchEngine.search(query)\n"
        "    render json: results\n"
        "  end\n"
        "end\n");

    // --- Java file ---
    write_file(base + "/src/lang/java.java",
        "package com.aisearch;\n\n"
        "public class SearchEngine {\n"
        "    private final VectorStore vectorStore;\n"
        "    \n"
        "    public SearchEngine() {\n"
        "        this.vectorStore = new VectorStore();\n"
        "    }\n"
        "    \n"
        "    public List<SearchResult> search(String query, int topK) {\n"
        "        return vectorStore.search(query, topK);\n"
        "    }\n"
        "}\n");

    // --- File with email-like patterns ---
    write_file(base + "/data/contacts.csv",
        "name,email,department\n"
        "John Doe,john@company.com,Engineering\n"
        "Jane Smith,jane@company.com,Security\n"
        "Bob Wilson,bob@company.com,Database\n");

    // --- File with URLs ---
    write_file(base + "/data/urls.txt",
        "https://api.example.com/v1/search\n"
        "https://api.example.com/v1/auth/login\n"
        "https://cdn.example.com/images/logo.png\n"
        "https://docs.example.com/guides/authentication\n");

    // --- File with IP addresses ---
    write_file(base + "/data/network.txt",
        "Server IP: 192.168.1.100\n"
        "Database IP: 10.0.0.5\n"
        "Redis IP: 172.16.0.3\n"
        "Load Balancer: 203.0.113.50\n");

    // --- File with code comments ---
    write_file(base + "/src/utils/commented.cpp",
        "// This file has many comments\n"
        "// It tests comment-based search\n"
        "/*\n"
        " * Multi-line comment with keywords:\n"
        " * authentication, database, search, image\n"
        " */\n"
        "int main() {\n"
        "    // TODO: implement search functionality\n"
        "    // FIXME: handle edge cases\n"
        "    return 0;\n"
        "}\n");

    // --- File with hex values ---
    write_file(base + "/data/hex_values.txt",
        "PNG_MAGIC: 89 50 4E 47 0D 0A 1A 0A\n"
        "JPEG_MAGIC: FF D8 FF\n"
        "BMP_MAGIC: 42 4D\n"
        "GIF_MAGIC: 47 49 46 38\n");

    // --- File with timestamps ---
    write_file(base + "/data/timestamps.txt",
        "2024-01-01T00:00:00Z - System started\n"
        "2024-01-01T00:05:00Z - Index built\n"
        "2024-01-01T00:10:00Z - Search ready\n"
        "2024-06-15T12:30:45Z - Last update\n");

    // --- File with JSON with special chars ---
    write_file(base + "/data/special_chars.json",
        "{\n"
        "  \"path\": \"C:\\\\Users\\\\documents\\\\file.txt\",\n"
        "  \"regex\": \"^[a-zA-Z]+\\\\d+$\",\n"
        "  \"html\": \"<div class=\\\"content\\\">Hello</div>\",\n"
        "  \"newline\": \"line1\\nline2\"\n"
        "}\n");

    // --- File with repeated words ---
    write_file(base + "/data/repeated.txt",
        "search search search search search\n"
        "database database database\n"
        "authentication authentication\n"
        "image image image image image image\n");

    // --- File with mixed languages text ---
    write_file(base + "/data/mixed_content.txt",
        "English: authentication database search\n"
        "Code: VectorStore tfidf cosine_similarity\n"
        "Config: chunk_size=512 overlap=64\n"
        "Error: ConnectionRefusedError TimeoutError\n");

    // --- File with version numbers ---
    write_file(base + "/data/versions.txt",
        "v1.0.0 - initial release\n"
        "v1.1.0 - added fuzzy search\n"
        "v1.2.0 - added boolean search\n"
        "v2.0.0 - added image fingerprinting\n");

    // --- File with paths ---
    write_file(base + "/data/file_paths.txt",
        "/usr/local/bin/aisearch\n"
        "/etc/aisearch/config.json\n"
        "/var/log/aisearch/search.log\n"
        "/opt/aisearch/data/index/\n");

    // --- File with API endpoints ---
    write_file(base + "/data/endpoints.txt",
        "GET  /api/search - Search documents\n"
        "POST /api/auth/login - User login\n"
        "GET  /api/images/:hash - Get image by hash\n"
        "POST /api/index - Build search index\n");

    // --- File with environment variables ---
    write_file(base + "/config/production.env",
        "NODE_ENV=production\n"
        "DATABASE_URL=postgresql://prod:5432/aisearch\n"
        "REDIS_URL=redis://prod-redis:6379\n"
        "SECRET_KEY=prod_secret_abc123\n"
        "LOG_LEVEL=warn\n");

    // --- File with CSV containing special data ---
    write_file(base + "/data/transactions.csv",
        "tx_id,from_account,to_account,amount,currency,status\n"
        "TX001,ACC001,ACC002,100.00,USD,completed\n"
        "TX002,ACC003,ACC001,50.50,EUR,pending\n"
        "TX003,ACC002,ACC004,1000.00,GBP,failed\n");

    // --- File with YAML frontmatter ---
    write_file(base + "/docs/guides/frontmatter.md",
        "---\n"
        "title: Search Engine Guide\n"
        "author: AI Team\n"
        "date: 2024-06-01\n"
        "tags: [search, tfidf, vector, cosine]\n"
        "---\n\n"
        "# Search Engine Guide\n\n"
        "This guide covers the TF-IDF search engine implementation.\n");

    // --- File with base64-like content ---
    write_file(base + "/data/base64_sample.txt",
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC\n");

    // --- File with hash-like content ---
    write_file(base + "/data/hash_sample.txt",
        "SHA256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n"
        "MD5: d41d8cd98f00b204e9800998ecf8427e\n"
        "FNV1A: cbf29ce484222325\n");

    // --- File with regex patterns ---
    write_file(base + "/data/regex.txt",
        "Email: [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}\n"
        "URL: https?://[\\w./-]+\n"
        "IP: \\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\n");

    // --- File with JSON Lines format ---
    write_file(base + "/data/jsonl_data.jsonl",
        "{\"id\":1,\"type\":\"authentication\",\"status\":\"active\"}\n"
        "{\"id\":2,\"type\":\"database\",\"status\":\"connected\"}\n"
        "{\"id\":3,\"type\":\"search\",\"status\":\"ready\"}\n");

    // --- File with INI format ---
    write_file(base + "/config/app.ini",
        "[general]\n"
        "name = AI Search\n"
        "version = 2.0\n\n"
        "[search]\n"
        "engine = tfidf\n"
        "top_k = 10\n\n"
        "[image]\n"
        "hash_algorithm = perceptual\n");

    // --- File with GraphQL schema ---
    write_file(base + "/data/schema.graphql",
        "type Query {\n"
        "    search(query: String!, topK: Int): [SearchResult!]\n"
        "    imageByHash(hash: String!): Image\n"
        "}\n\n"
        "type SearchResult {\n"
        "    filePath: String!\n"
        "    score: Float!\n"
        "    snippet: String\n"
        "}\n");

    // --- File with LaTeX ---
    write_file(base + "/data/formula.tex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "The cosine similarity between vectors $a$ and $b$ is:\n"
        "$$ \\cos(\\theta) = \\frac{a \\cdot b}{|a||b|} $$\n"
        "\\end{document}\n");

    // --- File with shell script with variables ---
    write_file(base + "/scripts/setup.sh",
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        "APP_NAME=\"aisearch\"\n"
        "INSTALL_DIR=\"/usr/local/bin\"\n"
        "CONFIG_DIR=\"/etc/aisearch\"\n\n"
        "echo \"Installing $APP_NAME...\"\n"
        "cp build/$APP_NAME $INSTALL_DIR/\n"
        "mkdir -p $CONFIG_DIR\n"
        "echo \"Installation complete.\"\n");

    // --- File with PowerShell script ---
    write_file(base + "/scripts/deploy.ps1",
        "$ErrorActionPreference = \"Stop\"\n"
        "$appName = \"aisearch\"\n"
        "$installPath = \"C:\\Program Files\\$appName\"\n\n"
        "Write-Host \"Installing $appName...\"\n"
        "New-Item -ItemType Directory -Force -Path $installPath\n"
        "Copy-Item \"build\\$appName.exe\" $installPath\n"
        "Write-Host \"Installation complete.\"\n");

    // --- File with Lua script ---
    write_file(base + "/src/lang/lua.lua",
        "local SearchEngine = {}\n"
        "SearchEngine.__index = SearchEngine\n\n"
        "function SearchEngine.new()\n"
        "    local self = setmetatable({}, SearchEngine)\n"
        "    self.index = {}\n"
        "    return self\n"
        "end\n\n"
        "function SearchEngine:add(doc)\n"
        "    table.insert(self.index, doc)\n"
        "end\n");

    // --- File with PHP ---
    write_file(base + "/src/lang/php.php",
        "<?php\n"
        "class SearchController {\n"
        "    public function search($query) {\n"
        "        $results = $this->searchEngine->search($query);\n"
        "        return json_encode($results);\n"
        "    }\n"
        "}\n"
        "?>\n");

    // --- File with R script ---
    write_file(base + "/src/lang/r_script.r",
        "search_tfidf <- function(query, documents, top_k=10) {\n"
        "  tfidf <- TFIDF$new(documents)\n"
        "  scores <- tfidf$cosine_similarity(query)\n"
        "  ranked <- order(scores, decreasing=TRUE)[1:top_k]\n"
        "  return(ranked)\n"
        "}\n");

    // --- File with Scala ---
    write_file(base + "/src/lang/scala.scala",
        "object SearchEngine {\n"
        "  def search(query: String, topK: Int): List[SearchResult] = {\n"
        "    val vectorStore = new VectorStore()\n"
        "    vectorStore.search(query, topK)\n"
        "  }\n"
        "}\n");

    // --- File with Perl ---
    write_file(base + "/src/lang/perl.pl",
        "use strict;\n"
        "use warnings;\n\n"
        "sub search {\n"
        "    my ($query, $top_k) = @_;\n"
        "    my @results = ();\n"
        "    # Search implementation here\n"
        "    return @results;\n"
        "}\n");

    // --- File with YAML list ---
    write_file(base + "/data/services.yml",
        "services:\n"
        "  - name: authentication\n"
        "    port: 8081\n"
        "  - name: database\n"
        "    port: 5432\n"
        "  - name: search\n"
        "    port: 8080\n"
        "  - name: cache\n"
        "    port: 6379\n");

    // --- File with XML namespace ---
    write_file(base + "/data/namespace.xml",
        "<?xml version=\"1.0\"?>\n"
        "<root xmlns:search=\"https://example.com/search\">\n"
        "  <search:query>authentication</search:query>\n"
        "  <search:results count=\"5\">\n"
        "    <search:item>login.cpp</search:item>\n"
        "  </search:results>\n"
        "</root>\n");

    // --- File with CSV with quotes ---
    write_file(base + "/data/quoted.csv",
        "id,text,category\n"
        "1,\"Hello, World\",greeting\n"
        "2,\"This has \"\"quotes\"\" inside\",test\n"
        "3,\"Multi\nline\ncell\",special\n");

    // --- File with CSS animations ---
    write_file(base + "/styles/animations.css",
        "@keyframes fadeIn {\n"
        "  from { opacity: 0; }\n"
        "  to { opacity: 1; }\n"
        "}\n\n"
        ".search-results {\n"
        "  animation: fadeIn 0.3s ease-in;\n"
        "}\n");

    // --- File with HTML with embedded JS ---
    write_file(base + "/web/search.html",
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "    <title>Search Results</title>\n"
        "    <script>\n"
        "        function performSearch(query) {\n"
        "            fetch('/api/search?q=' + query)\n"
        "                .then(r => r.json())\n"
        "                .then(data => displayResults(data));\n"
        "        }\n"
        "    </script>\n"
        "</head>\n"
        "<body>\n"
        "    <h1>Search Results</h1>\n"
        "    <div id=\"results\"></div>\n"
        "</body>\n"
        "</html>\n");

    // --- File with TOML with arrays ---
    write_file(base + "/config/advanced.toml",
        "[search]\n"
        "extensions = [\".cpp\", \".py\", \".js\", \".md\", \".json\"]\n"
        "ignore_dirs = [\".git\", \"node_modules\", \"build\"]\n\n"
        "[image]\n"
        "formats = [\"png\", \"jpg\", \"bmp\", \"gif\"]\n"
        "max_distance = 15\n");

    // --- File with Markdown table ---
    write_file(base + "/docs/guides/comparison.md",
        "# Search Engine Comparison\n\n"
        "| Feature | TF-IDF | BM25 | Word2Vec |\n"
        "|---------|--------|------|----------|\n"
        "| Speed | Fast | Fast | Slow |\n"
        "| Accuracy | Medium | High | High |\n"
        "| Memory | Low | Low | High |\n");

    // --- File with TODO comments ---
    write_file(base + "/src/utils/todos.cpp",
        "// TODO: implement fuzzy search with Levenshtein distance\n"
        "// TODO: add support for WebP image format\n"
        "// FIXME: handle Unicode filenames properly\n"
        "// FIXME: improve indexing speed for large directories\n"
        "// HACK: temporary workaround for path separator issue\n"
        "// NOTE: the cosine similarity threshold is 0.01\n"
        "// OPTIMIZE: use SIMD for vector operations\n");

    // --- File with error messages ---
    write_file(base + "/data/error_messages.txt",
        "Error: File not found: /config/app.json\n"
        "Error: Permission denied: /var/log/aisearch/\n"
        "Error: Invalid image format: unknown\n"
        "Error: Connection refused: localhost:5432\n"
        "Error: Out of memory during indexing\n"
        "Error: Token expired for user admin\n");

    // --- File with keyboard shortcuts ---
    write_file(base + "/data/shortcuts.txt",
        "Ctrl+F - Search in file\n"
        "Ctrl+Shift+F - Search in project\n"
        "Ctrl+P - Quick open file\n"
        "Ctrl+G - Go to line\n"
        "F1 - Command palette\n");

    // --- File with MIME types ---
    write_file(base + "/data/mime_types.txt",
        "text/plain - .txt\n"
        "text/html - .html\n"
        "application/json - .json\n"
        "image/png - .png\n"
        "image/jpeg - .jpg\n"
        "application/octet-stream - .bin\n");

    // --- File with port numbers ---
    write_file(base + "/data/ports.txt",
        "HTTP: 80\n"
        "HTTPS: 443\n"
        "PostgreSQL: 5432\n"
        "Redis: 6379\n"
        "MongoDB: 27017\n"
        "Elasticsearch: 9200\n");

    // --- File with cron expressions ---
    write_file(base + "/data/cron.txt",
        "0 * * * * - Every hour\n"
        "0 0 * * * - Daily at midnight\n"
        "*/15 * * * * - Every 15 minutes\n"
        "0 2 * * 1 - Weekly on Monday at 2am\n");

    // --- File with UUIDs ---
    write_file(base + "/data/uuids.txt",
        "550e8400-e29b-41d4-a716-446655440000\n"
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8\n"
        "f47ac10b-58cc-4372-a567-0e02b2c3d479\n");

    // --- File with HTTP status codes ---
    write_file(base + "/data/http_status.txt",
        "200 OK - Request successful\n"
        "201 Created - Resource created\n"
        "400 Bad Request - Invalid query\n"
        "401 Unauthorized - Authentication required\n"
        "403 Forbidden - Access denied\n"
        "404 Not Found - Resource not found\n"
        "500 Internal Server Error - Search engine error\n");

    // --- File with git commands ---
    write_file(base + "/data/git_commands.txt",
        "git init - Initialize repository\n"
        "git clone <url> - Clone repository\n"
        "git add . - Stage all changes\n"
        "git commit -m \"message\" - Commit changes\n"
        "git push origin main - Push to remote\n"
        "git pull - Pull latest changes\n");

    // --- File with Docker commands ---
    write_file(base + "/data/docker_commands.txt",
        "docker build -t aisearch .\n"
        "docker run -p 8080:8080 aisearch\n"
        "docker-compose up -d\n"
        "docker ps - List containers\n"
        "docker logs <container> - View logs\n");

    // --- File with environment setup ---
    write_file(base + "/docs/guides/setup.md",
        "# Development Setup\n\n"
        "## Prerequisites\n"
        "- C++17 compiler (GCC 9+, Clang 10+, MSVC 2019+)\n"
        "- CMake 3.16+\n"
        "- Python 3.8+ (for testing)\n\n"
        "## Steps\n"
        "1. Clone: `git clone https://github.com/example/aisearch`\n"
        "2. Build: `cmake -B build && cmake --build build`\n"
        "3. Test: `./build/aisearch test_data`\n"
        "4. Run: `./build/aisearch search ./test_data --query \"auth\"`\n");

    // --- File with security notes ---
    write_file(base + "/docs/guides/security.md",
        "# Security Guide\n\n"
        "## Authentication\n"
        "All API endpoints require JWT authentication except /api/auth/login.\n"
        "Tokens expire after 1 hour. Use refresh tokens to maintain sessions.\n\n"
        "## Vulnerabilities\n"
        "- SQL injection: Use parameterized queries\n"
        "- XSS: Escape all user input in HTML output\n"
        "- CSRF: Validate Origin header for state-changing operations\n");

    // --- File with performance benchmarks ---
    write_file(base + "/docs/guides/benchmarks.md",
        "# Performance Benchmarks\n\n"
        "## Search Performance\n"
        "- 1,000 files: 50ms\n"
        "- 10,000 files: 200ms\n"
        "- 100,000 files: 1.5s\n"
        "- 1,000,000 files: 15s\n\n"
        "## Index Build Time\n"
        "- 1,000 files: 100ms\n"
        "- 10,000 files: 800ms\n"
        "- 100,000 files: 8s\n");

    // --- File with API documentation ---
    write_file(base + "/docs/api/rest_api.md",
        "# REST API Documentation\n\n"
        "## Authentication\n"
        "### POST /api/auth/login\n"
        "Request: `{\"username\": \"admin\", \"password\": \"secret\"}`\n"
        "Response: `{\"token\": \"jwt_token\", \"expires\": 3600}`\n\n"
        "## Search\n"
        "### GET /api/search\n"
        "Parameters: query (string), top_k (int, default 10)\n"
        "Response: `{\"total_hits\": 5, \"text_hits\": [...]}`\n");

    // --- File with architecture description ---
    write_file(base + "/docs/guides/architecture.md",
        "# Architecture\n\n"
        "## Components\n"
        "1. **FileMapper**: Scans directories, collects metadata\n"
        "2. **VectorStore**: TF-IDF vectorization, inverted index\n"
        "3. **ImageHasher**: Perceptual hashing, format detection\n"
        "4. **SearchEngine**: Combines all search modes\n"
        "5. **JsonWriter**: Serializes results for AI consumption\n\n"
        "## Data Flow\n"
        "Directory -> FileMapper -> VectorStore + ImageHasher -> SearchEngine -> JSON\n");

    // --- File with troubleshooting ---
    write_file(base + "/docs/guides/troubleshooting.md",
        "# Troubleshooting\n\n"
        "## Common Issues\n\n"
        "### Search returns no results\n"
        "- Check if the directory was indexed\n"
        "- Verify the query terms exist in the content\n"
        "- Try fuzzy search for approximate matches\n\n"
        "### Image not detected\n"
        "- Verify the file has a supported extension (.png, .jpg, .bmp, .gif)\n"
        "- Check if the file has valid magic bytes\n");

    // --- File with FAQ ---
    write_file(base + "/docs/guides/faq.md",
        "# FAQ\n\n"
        "## How does TF-IDF search work?\n"
        "TF-IDF stands for Term Frequency-Inverse Document Frequency.\n"
        "It weights terms by how unique they are across all documents.\n\n"
        "## How does image fingerprinting work?\n"
        "We compute a perceptual hash from sampled pixel data.\n"
        "Similar images have similar hashes (small Hamming distance).\n");

    // --- File with changelog entries ---
    write_file(base + "/docs/guides/changelog.md",
        "# Changelog\n\n"
        "## v2.1.0\n"
        "- Added fuzzy search with Levenshtein distance\n"
        "- Added boolean search (AND, OR, NOT)\n"
        "- Added exact phrase search\n"
        "- Added filename and path search\n"
        "- Added file size filter\n"
        "- Added universal search mode\n"
        "- Fixed cross-platform path handling\n"
        "- Improved image dimension detection\n");

    // --- File with configuration reference ---
    write_file(base + "/docs/guides/config_ref.md",
        "# Configuration Reference\n\n"
        "| Option | Type | Default | Description |\n"
        "|--------|------|---------|-------------|\n"
        "| chunk_size | int | 512 | Text chunk size in characters |\n"
        "| overlap | int | 64 | Overlap between chunks |\n"
        "| top_k | int | 10 | Number of results to return |\n"
        "| max_distance | int | 10 | Max Hamming distance for images |\n");

    // --- File with deployment checklist ---
    write_file(base + "/docs/guides/deploy_checklist.md",
        "# Deployment Checklist\n\n"
        "- [ ] Build with Release configuration\n"
        "- [ ] Run all 200 tests\n"
        "- [ ] Verify JSON output format\n"
        "- [ ] Test with large directory (>1000 files)\n"
        "- [ ] Check memory usage\n"
        "- [ ] Verify cross-platform compatibility\n"
        "- [ ] Update version number\n"
        "- [ ] Create release notes\n");

    // Count files
    size_t file_count = 0;
    for (auto& p : fs::recursive_directory_iterator(base)) {
        if (p.is_regular_file()) file_count++;
    }

    std::cout << "Test data generated: " << file_count << " files in " << base << "/" << std::endl;
    return 0;
}
