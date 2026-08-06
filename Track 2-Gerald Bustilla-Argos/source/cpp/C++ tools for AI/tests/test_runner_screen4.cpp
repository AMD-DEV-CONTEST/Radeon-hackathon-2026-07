// test_runner_screen4.cpp - Master runner for all 8 social media platform test suites
// Runs all 8 platform-specific executables (100 tests each = 800 total)
#include <iostream>
#include <string>

static int exec_and_report(const std::string& exe_name, const std::string& label) {
    std::cout << std::endl << "========================================" << std::endl;
    std::cout << " Running: " << label << std::endl;
    std::cout << "========================================" << std::endl;
    std::string cmd = exe_name + " 2>&1";
    int rc = 0;
#ifdef _WIN32
    rc = system(cmd.c_str());
#else
    rc = system(cmd.c_str());
#endif
    if (rc != 0) {
        std::cout << " *** " << label << " had failures (exit code " << rc << ") ***" << std::endl;
    }
    return rc;
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << " SOCIAL MEDIA PLATFORM BUG-HUNTING SUITE" << std::endl;
    std::cout << "  800 Tests - 100 per platform x 8 platforms" << std::endl;
    std::cout << "========================================" << std::endl;

    int total_failures = 0;
    total_failures += exec_and_report("test_runner_screen4_x.exe", "X (Twitter) - 100 tests");
    total_failures += exec_and_report("test_runner_screen4_ig.exe", "Instagram - 100 tests");
    total_failures += exec_and_report("test_runner_screen4_th.exe", "Threads - 100 tests");
    total_failures += exec_and_report("test_runner_screen4_yt.exe", "YouTube - 100 tests");
    total_failures += exec_and_report("test_runner_screen4_tt.exe", "TikTok - 100 tests");
    total_failures += exec_and_report("test_runner_screen4_rd.exe", "Reddit - 100 tests");
    total_failures += exec_and_report("test_runner_screen4_li.exe", "LinkedIn - 100 tests");
    total_failures += exec_and_report("test_runner_screen4_sc.exe", "Snapchat - 100 tests");

    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << " SUITE 4 OVERALL SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    if (total_failures == 0) {
        std::cout << "  ALL 800 TESTS PASSED (100%)" << std::endl;
    } else {
        std::cout << "  " << total_failures << " platform(s) had failures" << std::endl;
    }
    std::cout << "========================================" << std::endl;

    return total_failures > 0 ? 1 : 0;
}
