// filepath: hackathon_ui_operator_distill/native/verifier_bridge.cpp
// Screen-AI Verification Bridge — Native C++ implementation
// Used by CustomVerifier in pipeline/screenai_pipelines.js
// Build target: ai_pc_operator/data/native/verifier_bridge.node (Node addon)
//
// Build instructions (Windows, MSVC):
//   cl /LD /EHsc verifier_bridge.cpp /I<node-gyp headers> /link /OUT:verifier_bridge.node
//
// Build instructions (Linux/macOS):
//   g++ -shared -fPIC -std=c++17 verifier_bridge.cpp -o verifier_bridge.node
//
// The JS CustomVerifier falls back to pure-JS implementations when this
// native module is not present, so absence is non-fatal.

#include "verifier_bridge.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <vector>
#include <string>
#include <sstream>
#include <iomanip>

namespace screenai {

// Minimal SHA-256 implementation (no external deps)
static const uint32_t K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};

static inline uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

static void sha256_transform(uint32_t state[8], const uint8_t block[64]) {
    uint32_t w[64];
    for (int i = 0; i < 16; i++) {
        w[i] = ((uint32_t)block[i*4] << 24) | ((uint32_t)block[i*4+1] << 16) |
               ((uint32_t)block[i*4+2] << 8) | ((uint32_t)block[i*4+3]);
    }
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = rotr(w[i-15], 7) ^ rotr(w[i-15], 18) ^ (w[i-15] >> 3);
        uint32_t s1 = rotr(w[i-2], 17) ^ rotr(w[i-2], 19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a=state[0],b=state[1],c=state[2],d=state[3];
    uint32_t e=state[4],f=state[5],g=state[6],h=state[7];
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t t1 = h + S1 + ch + K[i] + w[i];
        uint32_t S0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
        uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + mj;
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }
    state[0]+=a; state[1]+=b; state[2]+=c; state[3]+=d;
    state[4]+=e; state[5]+=f; state[6]+=g; state[7]+=h;
}

std::string sha256_file(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return "";
    uint32_t state[8] = {
        0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
        0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19
    };
    std::vector<uint8_t> block(64);
    uint64_t total = 0;
    while (f.read(reinterpret_cast<char*>(block.data()), 64) || f.gcount() > 0) {
        std::streamsize got = f.gcount();
        total += got;
        if (got < 64) {
            block[got] = 0x80;
            for (size_t i = got + 1; i < 64; i++) block[i] = 0;
            if (got >= 56) {
                sha256_transform(state, block.data());
                std::memset(block.data(), 0, 64);
            }
            uint64_t bits = total * 8;
            for (int i = 0; i < 8; i++) block[63 - i] = (uint8_t)(bits >> (i * 8));
            sha256_transform(state, block.data());
            break;
        }
        sha256_transform(state, block.data());
    }
    std::ostringstream oss;
    for (int i = 0; i < 8; i++) oss << std::hex << std::setw(8) << std::setfill('0') << state[i];
    return oss.str();
}

bool read_image_dimensions(const std::string& path, int& width, int& height) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    uint8_t header[24];
    f.read(reinterpret_cast<char*>(header), 24);
    if (f.gcount() < 24) return false;
    // PNG
    if (header[0] == 0x89 && header[1] == 'P' && header[2] == 'N' && header[3] == 'G') {
        width  = (header[16] << 24) | (header[17] << 16) | (header[18] << 8) | header[19];
        height = (header[20] << 24) | (header[21] << 16) | (header[22] << 8) | header[23];
        return true;
    }
    // JPEG: scan for SOF marker
    if (header[0] == 0xFF && header[1] == 0xD8) {
        f.seekg(0, std::ios::beg);
        std::vector<uint8_t> buf(65536);
        f.read(reinterpret_cast<char*>(buf.data()), buf.size());
        std::streamsize n = f.gcount();
        size_t i = 2;
        while (i + 9 < (size_t)n) {
            if (buf[i] == 0xFF && buf[i+1] >= 0xC0 && buf[i+1] <= 0xC3) {
                height = (buf[i+5] << 8) | buf[i+6];
                width  = (buf[i+7] << 8) | buf[i+8];
                return true;
            }
            size_t seg = (buf[i+2] << 8) | buf[i+3];
            i += 2 + seg;
        }
    }
    return false;
}

double image_byte_diff_ratio(const std::string& path1, const std::string& path2) {
    std::ifstream f1(path1, std::ios::binary);
    std::ifstream f2(path2, std::ios::binary);
    if (!f1 || !f2) return 1.0;
    const size_t CHUNK = 65536;
    std::vector<uint8_t> b1(CHUNK), b2(CHUNK);
    size_t total = 0, diff = 0;
    while (true) {
        f1.read(reinterpret_cast<char*>(b1.data()), CHUNK);
        f2.read(reinterpret_cast<char*>(b2.data()), CHUNK);
        std::streamsize n1 = f1.gcount(), n2 = f2.gcount();
        size_t n = (n1 < n2 ? (size_t)n1 : (size_t)n2);
        for (size_t i = 0; i < n; i++) if (b1[i] != b2[i]) diff++;
        total += n;
        if (n1 == 0 && n2 == 0) break;
    }
    if (total == 0) return 0.0;
    return (double)diff / (double)total;
}

VerifyResult verify_native(int check_type,
                           const char* target,
                           const char* options) {
    VerifyResult r;
    r.passed = false;
    r.details = "no result";
    if (target == nullptr) {
        r.details = "null target";
        return r;
    }
    std::string t(target);
    std::string o(options ? options : "");
    switch ((CheckType)check_type) {
        case CheckType::FileExists: {
            std::ifstream f(t);
            r.passed = f.good();
            r.details = r.passed ? "exists" : "missing";
            break;
        }
        case CheckType::FileSize: {
            std::ifstream f(t, std::ios::binary | std::ios::ate);
            if (!f) { r.details = "missing"; break; }
            std::streamsize size = f.tellg();
            r.passed = true;
            std::ostringstream oss;
            oss << "size=" << size;
            r.details = oss.str().c_str();
            // Note: returned pointer is to temporary; safe for immediate JS read
            break;
        }
        case CheckType::FileHash: {
            std::string h = sha256_file(t);
            r.passed = !h.empty();
            r.details = h.empty() ? "hash failed" : h.c_str();
            break;
        }
        case CheckType::ProcessRunning: {
            // Platform-specific process check is delegated to JS layer
            // (native side returns false; JS uses tasklist/pgrep)
            r.passed = false;
            r.details = "use JS ProcessVerifier";
            break;
        }
        case CheckType::WindowExists: {
            // Window enumeration is OS-specific; JS layer handles it
            r.passed = false;
            r.details = "use JS WindowVerifier";
            break;
        }
        case CheckType::PixelMatch: {
            // options: "path2|tolerance"
            size_t sep = o.find('|');
            std::string path2 = (sep == std::string::npos) ? "" : o.substr(0, sep);
            double tol = (sep == std::string::npos) ? 0.0 : std::atof(o.substr(sep + 1).c_str());
            double diff = image_byte_diff_ratio(t, path2);
            r.passed = diff <= tol;
            std::ostringstream oss;
            oss << "diff=" << diff << " tol=" << tol;
            r.details = oss.str().c_str();
            break;
        }
        case CheckType::ImageDimensions: {
            int w = 0, h = 0;
            bool ok = read_image_dimensions(t, w, h);
            r.passed = ok;
            std::ostringstream oss;
            oss << w << "x" << h;
            r.details = oss.str().c_str();
            break;
        }
        case CheckType::StringContains: {
            // options: "needle"
            r.passed = t.find(o) != std::string::npos;
            r.details = r.passed ? "found" : "not found";
            break;
        }
        default:
            r.details = "unknown check type";
            break;
    }
    return r;
}

} // namespace screenai

// Plain C exports for Node addon binding (when compiled as .node)
// These are no-ops when compiled as a static library; the JS layer
// detects absence and falls back to pure-JS verification.
#ifndef SCREENAI_NO_VERIFIER_EXPORTS
extern "C" {
    int screenai_verify(int check_type, const char* target, const char* options) {
        auto r = screenai::verify_native(check_type, target, options);
        return r.passed ? 1 : 0;
    }
    const char* screenai_verify_details(int check_type, const char* target, const char* options) {
        static std::string details;
        auto r = screenai::verify_native(check_type, target, options);
        details = r.details;
        return details.c_str();
    }
}
#endif
