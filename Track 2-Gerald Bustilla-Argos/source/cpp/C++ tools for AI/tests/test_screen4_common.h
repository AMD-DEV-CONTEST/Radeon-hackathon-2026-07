// test_screen4_common.h - Shared helpers for social media platform test suites
#pragma once
#include "../screen_context/screen_context.h"
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <algorithm>
#include <cstring>

static int g_tests_passed = 0;
static int g_tests_failed = 0;
static int g_current_test = 0;

static std::string exec_command(const std::string& cmd) {
    std::string result;
#ifdef _WIN32
    FILE* pipe = _popen(cmd.c_str(), "r");
#else
    FILE* pipe = popen(cmd.c_str(), "r");
#endif
    if (!pipe) return "";
    char buffer[4096];
    while (fgets(buffer, sizeof(buffer), pipe)) {
        result += buffer;
    }
#ifdef _WIN32
    _pclose(pipe);
#else
    pclose(pipe);
#endif
    return result;
}

static std::string get_sim_output(const std::string& command) {
    std::string cmd = "screencontext.exe --sim " + command + " 2>&1";
    return exec_command(cmd);
}

static bool check_pass(bool condition, const std::string& test_name) {
    g_current_test++;
    if (condition) {
        g_tests_passed++;
        std::cout << "[" << g_current_test << "] " << test_name;
        for (int i = (int)test_name.size(); i < 65; i++) std::cout << " ";
        std::cout << "PASS" << std::endl;
        return true;
    } else {
        g_tests_failed++;
        std::cout << "[" << g_current_test << "] " << test_name;
        for (int i = (int)test_name.size(); i < 65; i++) std::cout << " ";
        std::cout << "FAIL" << std::endl;
        return false;
    }
}

static bool json_contains(const std::string& json, const std::string& field) {
    return json.find("\"" + field + "\"") != std::string::npos;
}

static bool json_contains_value(const std::string& json, const std::string& field, const std::string& value) {
    std::string search = "\"" + field + "\":\"" + value + "\"";
    return json.find(search) != std::string::npos;
}

static bool json_contains_number(const std::string& json, const std::string& field, int value) {
    std::string search = "\"" + field + "\":" + std::to_string(value);
    return json.find(search) != std::string::npos;
}

static bool json_contains_bool(const std::string& json, const std::string& field, bool value) {
    std::string search = "\"" + field + "\":" + (value ? "true" : "false");
    return json.find(search) != std::string::npos;
}

static int count_occurrences(const std::string& json, const std::string& pattern) {
    int count = 0;
    size_t pos = 0;
    while ((pos = json.find(pattern, pos)) != std::string::npos) {
        count++;
        pos++;
    }
    return count;
}

static int count_type(const std::string& json, const std::string& type) {
    return count_occurrences(json, "\"control_type\":\"" + type + "\"");
}

static int count_depth(const std::string& json, int depth) {
    return count_occurrences(json, "\"depth\":" + std::to_string(depth));
}

static int get_total(const std::string& out, const std::string& field) {
    std::string key = "\"" + field + "\":";
    if (out.find(key) != std::string::npos) {
        size_t pos = out.find(key) + key.size();
        return std::atoi(out.c_str() + pos);
    }
    return 0;
}

static void print_summary(const std::string& suite_name) {
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << " " << suite_name << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << (g_tests_passed + g_tests_failed) << std::endl;
    std::cout << "  Passed: " << g_tests_passed << std::endl;
    std::cout << "  Failed: " << g_tests_failed << std::endl;
    int rate = (g_tests_passed + g_tests_failed) > 0 ?
        (g_tests_passed * 100) / (g_tests_passed + g_tests_failed) : 0;
    std::cout << "  Rate:   " << rate << "%" << std::endl;
    std::cout << "========================================" << std::endl;
}
