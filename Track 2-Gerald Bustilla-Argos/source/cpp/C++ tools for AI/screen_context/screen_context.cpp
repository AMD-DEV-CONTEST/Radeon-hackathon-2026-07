// screen_context.cpp - Screen Context Reader Implementation
// Captures screen content, extracts text, and assesses user context
#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#include <objbase.h>
#include <uiautomation.h>
#pragma comment(lib, "psapi.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")
#endif

#include "screen_context.h"
#include <algorithm>
#include <sstream>
#include <fstream>
#include <ctime>
#include <chrono>
#include <cstring>
#include <cmath>

// ===== Global State =====
static bool g_simulation_mode = false;
static std::vector<AppInfo> g_sim_apps;
static std::vector<ContentBlock> g_sim_content;
static std::string g_sim_active_app;
static std::string g_sim_activity;
static std::string g_sim_screen_text;
static std::vector<UiaElementInfo> g_sim_uia_elements;

// ===== Utility Functions =====

std::string platform_to_string(Platform p) {
    switch (p) {
        case Platform::WINDOWS: return "windows";
        case Platform::LINUX: return "linux";
        case Platform::MACOS: return "macos";
        case Platform::ANDROID: return "android";
        case Platform::IOS: return "ios";
        case Platform::SIMULATION: return "simulation";
        default: return "unknown";
    }
}

Platform get_current_platform() {
    if (g_simulation_mode) return Platform::SIMULATION;
#ifdef _WIN32
    return Platform::WINDOWS;
#elif defined(__linux__)
    return Platform::LINUX;
#elif defined(__APPLE__)
    return Platform::MACOS;
#elif defined(__ANDROID__)
    return Platform::ANDROID;
#else
    return Platform::WINDOWS;
#endif
}

std::string get_timestamp() {
    if (g_simulation_mode) return "sim_timestamp";
    auto now = std::chrono::system_clock::now();
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    char buf[64];
#ifdef _WIN32
    struct tm tm_buf;
    localtime_s(&tm_buf, &t);
    std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm_buf);
#else
    std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", std::localtime(&t));
#endif
    return std::string(buf);
}

std::string to_lower(const std::string& s) {
    std::string result;
    for (char c : s) result += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return result;
}

bool contains_ci(const std::string& haystack, const std::string& needle) {
    return to_lower(haystack).find(to_lower(needle)) != std::string::npos;
}

std::string json_escape(const std::string& s) {
    std::string result;
    for (size_t i = 0; i < s.size(); i++) {
        char c = s[i];
        switch (c) {
            case '"': result += "\\\""; break;
            case '\\': result += "\\\\"; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned char>(c));
                    result += buf;
                } else {
                    result += c;
                }
                break;
        }
    }
    return result;
}

// ===== App Classification =====

std::string classify_app(const std::string& title, const std::string& process_name) {
    std::string t = to_lower(title);
    std::string p = to_lower(process_name);

    // Social media (checked before browser so YouTube/Reddit/X don't get classified as browser)
    if (contains_ci(t, "facebook") || contains_ci(p, "facebook") ||
        contains_ci(t, "twitter") || contains_ci(p, "twitter") || contains_ci(p, "tweetdeck") ||
        contains_ci(t, "instagram") || contains_ci(p, "instagram") ||
        contains_ci(t, "linkedin") || contains_ci(p, "linkedin") ||
        contains_ci(t, "tiktok") || contains_ci(p, "tiktok") ||
        contains_ci(t, "reddit") || contains_ci(p, "reddit") ||
        contains_ci(t, "discord") || contains_ci(p, "discord") ||
        contains_ci(t, "slack") || contains_ci(p, "slack") ||
        contains_ci(t, "whatsapp") || contains_ci(p, "whatsapp") ||
        contains_ci(t, "telegram") || contains_ci(p, "telegram") ||
        contains_ci(t, "messenger") || contains_ci(p, "messenger") ||
        contains_ci(t, "snapchat") || contains_ci(p, "snapchat") ||
        contains_ci(t, "wechat") || contains_ci(p, "wechat") ||
        contains_ci(t, "weibo") || contains_ci(p, "weibo") ||
        // X (formerly Twitter) - check for "x.com" or " / X" in title
        contains_ci(t, "x.com") || contains_ci(t, " - x") || contains_ci(p, "x.exe") ||
        // Threads
        contains_ci(t, "threads") || contains_ci(p, "threads") ||
        // YouTube - social media video platform, not just a browser page
        contains_ci(t, "youtube") || contains_ci(p, "youtube") ||
        // Pinterest
        contains_ci(t, "pinterest") || contains_ci(p, "pinterest") ||
        // Twitch
        contains_ci(t, "twitch") || contains_ci(p, "twitch")) {
        return "social_media";
    }

    // Browser
    if (contains_ci(p, "chrome") || contains_ci(p, "firefox") || contains_ci(p, "edge") ||
        contains_ci(p, "safari") || contains_ci(p, "opera") || contains_ci(p, "brave") ||
        contains_ci(p, "vivaldi") || contains_ci(p, "browser") ||
        contains_ci(t, "google") || contains_ci(t, "bing") || contains_ci(t, "yahoo") ||
        contains_ci(t, "duckduckgo") ||
        contains_ci(t, "wikipedia") || contains_ci(t, "amazon") ||
        contains_ci(t, "netflix") || contains_ci(t, "github") ||
        contains_ci(t, "stackoverflow")) {
        return "browser";
    }

    // IDE / Code editor
    if (p == "code.exe" || p == "code" || contains_ci(p, "devenv") || contains_ci(p, "idea") ||
        contains_ci(p, "eclipse") || p == "vim" || contains_ci(p, "emacs") ||
        contains_ci(p, "sublime") || contains_ci(p, "atom") || contains_ci(p, "netbeans") ||
        contains_ci(t, ".cpp") || contains_ci(t, ".py") || contains_ci(t, ".js") ||
        contains_ci(t, ".java") || contains_ci(t, ".h") || contains_ci(t, ".cs") ||
        contains_ci(t, "visual studio") || contains_ci(t, "intellij") ||
        contains_ci(t, "eclipse") || contains_ci(t, "vscode")) {
        return "ide";
    }

    // Email
    if (contains_ci(p, "outlook") || contains_ci(p, "thunderbird") || p == "mail.exe" || p == "mail" ||
        contains_ci(t, "inbox") || contains_ci(t, "outlook") || contains_ci(t, "gmail") ||
        contains_ci(t, "thunderbird") || contains_ci(t, "email") || contains_ci(t, " - mail")) {
        return "email";
    }

    // Media player
    if (contains_ci(p, "vlc") || contains_ci(p, "mpc") || contains_ci(p, "potplayer") ||
        contains_ci(p, "spotify") || contains_ci(p, "itunes") || contains_ci(p, "foobar") ||
        contains_ci(p, "winamp") || contains_ci(p, "mediaplayer") ||
        contains_ci(t, ".mp4") || contains_ci(t, ".mkv") || contains_ci(t, ".avi") ||
        contains_ci(t, ".mp3") || contains_ci(t, "vlc") || contains_ci(t, "spotify") ||
        contains_ci(t, "media player")) {
        return "media_player";
    }

    // Terminal
    if (contains_ci(p, "cmd") || contains_ci(p, "powershell") || contains_ci(p, "terminal") ||
        contains_ci(p, "bash") || contains_ci(p, "conhost") || contains_ci(p, "wt") ||
        contains_ci(p, "xterm") || contains_ci(p, "gnome-terminal") ||
        contains_ci(t, "terminal") || contains_ci(t, "powershell") ||
        contains_ci(t, "command prompt") || contains_ci(t, "cmd")) {
        return "terminal";
    }

    // File manager
    if (contains_ci(p, "explorer") || contains_ci(p, "nautilus") || contains_ci(p, "thunar") ||
        contains_ci(p, "dolphin") || contains_ci(p, "finder") ||
        contains_ci(t, "file explorer") || contains_ci(t, "file manager") ||
        contains_ci(t, "finder") || contains_ci(t, "nautilus")) {
        return "file_manager";
    }

    // Spreadsheet
    if (contains_ci(p, "excel") || contains_ci(p, "calc") || contains_ci(p, "numbers") ||
        contains_ci(t, ".xlsx") || contains_ci(t, ".csv") || contains_ci(t, "excel") ||
        contains_ci(t, "spreadsheet") || contains_ci(t, "google sheets")) {
        return "spreadsheet";
    }

    // Document editor
    if (contains_ci(p, "word") || contains_ci(p, "writer") || contains_ci(p, "pages") ||
        contains_ci(p, "notepad") || contains_ci(p, "notepad++") ||
        contains_ci(t, ".docx") || contains_ci(t, ".txt") || contains_ci(t, ".pdf") ||
        contains_ci(t, "word") || contains_ci(t, "notepad") ||
        contains_ci(t, "document") || contains_ci(t, "pdf")) {
        return "editor";
    }

    // Games
    if (contains_ci(p, "steam") || contains_ci(p, "epicgames") || contains_ci(p, "origin") ||
        contains_ci(p, "battle.net") || contains_ci(p, "riotclient") ||
        contains_ci(t, "game") || contains_ci(t, "steam")) {
        return "game";
    }

    return "unknown";
}

// ===== Simulation Mode =====

void enable_simulation_mode() {
    g_simulation_mode = true;
}

bool is_simulation_mode() {
    return g_simulation_mode;
}

void setup_simulation_data() {
    g_sim_apps.clear();
    g_sim_content.clear();

    // Scenario 1: Facebook app - user scrolling feed
    AppInfo facebook;
    facebook.window_id = "sim_fb";
    facebook.title = "Facebook - News Feed";
    facebook.process_name = "facebook.exe";
    facebook.process_id = 2001;
    facebook.x = 100; facebook.y = 50;
    facebook.width = 900; facebook.height = 700;
    facebook.is_visible = true;
    facebook.is_focused = true;
    facebook.app_category = "social_media";
    facebook.platform = "simulation";
    g_sim_apps.push_back(facebook);
    g_sim_active_app = "sim_fb";
    g_sim_activity = "scrolling";

    // Facebook posts visible on screen
    ContentBlock post1;
    post1.type = "post";
    post1.text = "Just finished my morning run! 5K in 25 minutes. Feeling great and ready to tackle the day. #fitness #morningrun";
    post1.source = "Facebook";
    post1.author = "Sarah Johnson";
    post1.timestamp = "2026-08-05 08:15";
    post1.x = 150; post1.y = 80; post1.width = 800; post1.height = 120;
    post1.relevance = 0.95f;
    g_sim_content.push_back(post1);

    ContentBlock post2;
    post2.type = "post";
    post2.text = "Breaking: New AI model achieves 99% accuracy on medical diagnosis benchmark. Researchers say this could revolutionize healthcare. Full paper linked in comments.";
    post2.source = "Facebook";
    post2.author = "Tech News Daily";
    post2.timestamp = "2026-08-05 07:30";
    post2.x = 150; post2.y = 220; post2.width = 800; post2.height = 140;
    post2.relevance = 0.90f;
    g_sim_content.push_back(post2);

    ContentBlock post3;
    post3.type = "ad";
    post3.text = "Sponsored: Get 50% off on all running shoes at SportsMart! Limited time offer. Shop now.";
    post3.source = "Facebook";
    post3.author = "SportsMart";
    post3.timestamp = "Sponsored";
    post3.x = 150; post3.y = 380; post3.width = 800; post3.height = 80;
    post3.relevance = 0.3f;
    g_sim_content.push_back(post3);

    ContentBlock post4;
    post4.type = "post";
    post4.text = "Can't believe it's already August! This year is flying by. What's everyone's favorite summer memory so far?";
    post4.source = "Facebook";
    post4.author = "Mike Chen";
    post4.timestamp = "2026-08-05 06:45";
    post4.x = 150; post4.y = 480; post4.width = 800; post4.height = 100;
    post4.relevance = 0.70f;
    g_sim_content.push_back(post4);

    ContentBlock comment1;
    comment1.type = "comment";
    comment1.text = "Wow, 5K in 25 minutes is impressive! I'm still working on breaking 30 minutes.";
    comment1.source = "Facebook";
    comment1.author = "John Davis";
    comment1.timestamp = "2026-08-05 08:20";
    comment1.x = 200; comment1.y = 160; comment1.width = 700; comment1.height = 40;
    comment1.relevance = 0.85f;
    g_sim_content.push_back(comment1);

    // Scenario 2: Chrome browser - also open
    AppInfo chrome;
    chrome.window_id = "sim_chrome";
    chrome.title = "C++ Tutorial - std::vector - Google Chrome";
    chrome.process_name = "chrome.exe";
    chrome.process_id = 2002;
    chrome.x = 200; chrome.y = 100;
    chrome.width = 1200; chrome.height = 800;
    chrome.is_visible = true;
    chrome.is_focused = false;
    chrome.app_category = "browser";
    chrome.platform = "simulation";
    g_sim_apps.push_back(chrome);

    // Scenario 3: VS Code - also open
    AppInfo vscode;
    vscode.window_id = "sim_vscode";
    vscode.title = "main.cpp - MyProject - Visual Studio Code";
    vscode.process_name = "code.exe";
    vscode.process_id = 2003;
    vscode.x = 50; vscode.y = 30;
    vscode.width = 1600; vscode.height = 900;
    vscode.is_visible = true;
    vscode.is_focused = false;
    vscode.app_category = "ide";
    vscode.platform = "simulation";
    g_sim_apps.push_back(vscode);

    // Scenario 4: Spotify - playing music
    AppInfo spotify;
    spotify.window_id = "sim_spotify";
    spotify.title = "Spotify - Playing: Lo-Fi Beats";
    spotify.process_name = "spotify.exe";
    spotify.process_id = 2004;
    spotify.x = 1100; spotify.y = 600;
    spotify.width = 400; spotify.height = 300;
    spotify.is_visible = true;
    spotify.is_focused = false;
    spotify.is_minimized = true;
    spotify.app_category = "media_player";
    spotify.platform = "simulation";
    g_sim_apps.push_back(spotify);

    // Scenario 5: Outlook email
    AppInfo outlook;
    outlook.window_id = "sim_outlook";
    outlook.title = "Inbox (3) - Outlook";
    outlook.process_name = "outlook.exe";
    outlook.process_id = 2005;
    outlook.x = 300; outlook.y = 150;
    outlook.width = 1000; outlook.height = 700;
    outlook.is_visible = true;
    outlook.is_focused = false;
    outlook.app_category = "email";
    outlook.platform = "simulation";
    g_sim_apps.push_back(outlook);

    // Scenario 6: X (formerly Twitter) - user scrolling feed
    AppInfo xApp;
    xApp.window_id = "sim_x";
    xApp.title = "Home / X";
    xApp.process_name = "x.exe";
    xApp.process_id = 2006;
    xApp.x = 150; xApp.y = 80;
    xApp.width = 1000; xApp.height = 800;
    xApp.is_visible = true;
    xApp.is_focused = false;
    xApp.app_category = "social_media";
    xApp.platform = "simulation";
    g_sim_apps.push_back(xApp);

    ContentBlock xPost1;
    xPost1.type = "post";
    xPost1.text = "Just shipped a new feature! Real-time collaboration is now live. Try it out and let me know what you think. #buildinpublic";
    xPost1.source = "X";
    xPost1.author = "@devbuilder";
    xPost1.timestamp = "2026-08-05 09:30";
    xPost1.x = 200; xPost1.y = 120; xPost1.width = 800; xPost1.height = 100;
    xPost1.relevance = 0.92f;
    g_sim_content.push_back(xPost1);

    ContentBlock xPost2;
    xPost2.type = "post";
    xPost2.text = "Hot take: AI won't replace developers, it'll make them 10x more productive. The key is learning to prompt effectively.";
    xPost2.source = "X";
    xPost2.author = "@techphilosopher";
    xPost2.timestamp = "2026-08-05 09:15";
    xPost2.x = 200; xPost2.y = 240; xPost2.width = 800; xPost2.height = 100;
    xPost2.relevance = 0.88f;
    g_sim_content.push_back(xPost2);

    ContentBlock xPost3;
    xPost3.type = "post";
    xPost3.text = "Thread: How I went from 0 to 100k followers in 6 months. 1/ Consistency is key. Post every day. 2/ Engage with your community. 3/ Provide value, not just noise.";
    xPost3.source = "X";
    xPost3.author = "@growthhacker";
    xPost3.timestamp = "2026-08-05 08:45";
    xPost3.x = 200; xPost3.y = 360; xPost3.width = 800; xPost3.height = 120;
    xPost3.relevance = 0.80f;
    g_sim_content.push_back(xPost3);

    // Scenario 7: Instagram - user browsing feed
    AppInfo instagram;
    instagram.window_id = "sim_instagram";
    instagram.title = "Instagram";
    instagram.process_name = "instagram.exe";
    instagram.process_id = 2007;
    instagram.x = 250; instagram.y = 100;
    instagram.width = 800; instagram.height = 900;
    instagram.is_visible = true;
    instagram.is_focused = false;
    instagram.app_category = "social_media";
    instagram.platform = "simulation";
    g_sim_apps.push_back(instagram);

    ContentBlock igPost1;
    igPost1.type = "post";
    igPost1.text = "Sunset hike up the mountain today. The view was absolutely worth the 3 hour climb! #sunset #hiking #nature";
    igPost1.source = "Instagram";
    igPost1.author = "@naturelover";
    igPost1.timestamp = "2026-08-05 07:00";
    igPost1.x = 300; igPost1.y = 150; igPost1.width = 600; igPost1.height = 100;
    igPost1.relevance = 0.85f;
    g_sim_content.push_back(igPost1);

    ContentBlock igPost2;
    igPost2.type = "post";
    igPost2.text = "New recipe drop! Creamy garlic pasta with truffle oil. Recipe in bio. #foodie #pasta #homecooking";
    igPost2.source = "Instagram";
    igPost2.author = "@chefathome";
    igPost2.timestamp = "2026-08-05 06:30";
    igPost2.x = 300; igPost2.y = 280; igPost2.width = 600; igPost2.height = 100;
    igPost2.relevance = 0.78f;
    g_sim_content.push_back(igPost2);

    ContentBlock igAd;
    igAd.type = "ad";
    igAd.text = "Sponsored: Get 30% off premium skincare at GlowUp! Limited time offer.";
    igAd.source = "Instagram";
    igAd.author = "GlowUp";
    igAd.timestamp = "Sponsored";
    igAd.x = 300; igAd.y = 400; igAd.width = 600; igAd.height = 80;
    igAd.relevance = 0.3f;
    g_sim_content.push_back(igAd);

    // Scenario 8: Threads - user browsing feed
    AppInfo threads;
    threads.window_id = "sim_threads";
    threads.title = "Threads";
    threads.process_name = "threads.exe";
    threads.process_id = 2008;
    threads.x = 350; threads.y = 120;
    threads.width = 900; threads.height = 700;
    threads.is_visible = true;
    threads.is_focused = false;
    threads.app_category = "social_media";
    threads.platform = "simulation";
    g_sim_apps.push_back(threads);

    ContentBlock thPost1;
    thPost1.type = "post";
    thPost1.text = "Anyone else think the new MacBook Pro M4 is overkill for most people? Like, do we really need that much power for browsing and email?";
    thPost1.source = "Threads";
    thPost1.author = "@techquestioner";
    thPost1.timestamp = "2026-08-05 09:00";
    thPost1.x = 400; thPost1.y = 160; thPost1.width = 700; thPost1.height = 100;
    thPost1.relevance = 0.82f;
    g_sim_content.push_back(thPost1);

    ContentBlock thPost2;
    thPost2.type = "post";
    thPost2.text = "Just finished reading 'Project Hail Mary' by Andy Weir. Absolutely incredible sci-fi. Highly recommend if you liked The Martian.";
    thPost2.source = "Threads";
    thPost2.author = "@bookworm";
    thPost2.timestamp = "2026-08-05 08:20";
    thPost2.x = 400; thPost2.y = 280; thPost2.width = 700; thPost2.height = 100;
    thPost2.relevance = 0.75f;
    g_sim_content.push_back(thPost2);

    // Scenario 9: YouTube - user watching/scrolling
    AppInfo youtube;
    youtube.window_id = "sim_youtube";
    youtube.title = "YouTube - How AI Works";
    youtube.process_name = "youtube.exe";
    youtube.process_id = 2009;
    youtube.x = 100; youtube.y = 50;
    youtube.width = 1200; youtube.height = 800;
    youtube.is_visible = true;
    youtube.is_focused = false;
    youtube.app_category = "social_media";
    youtube.platform = "simulation";
    g_sim_apps.push_back(youtube);

    ContentBlock ytVideo1;
    ytVideo1.type = "video";
    ytVideo1.text = "How AI Works: Neural Networks Explained Simply - 15 minutes - 1.2M views - by 3Blue1Brown";
    ytVideo1.source = "YouTube";
    ytVideo1.author = "3Blue1Brown";
    ytVideo1.timestamp = "2026-08-04";
    ytVideo1.x = 150; ytVideo1.y = 100; ytVideo1.width = 1000; ytVideo1.height = 120;
    ytVideo1.relevance = 0.95f;
    g_sim_content.push_back(ytVideo1);

    ContentBlock ytVideo2;
    ytVideo2.type = "video";
    ytVideo2.text = "Building a C++ Game Engine from Scratch - Part 5 - 45 minutes - 85K views - by TheCherno";
    ytVideo2.source = "YouTube";
    ytVideo2.author = "TheCherno";
    ytVideo2.timestamp = "2026-08-03";
    ytVideo2.x = 150; ytVideo2.y = 250; ytVideo2.width = 1000; ytVideo2.height = 100;
    ytVideo2.relevance = 0.80f;
    g_sim_content.push_back(ytVideo2);

    ContentBlock ytAd;
    ytAd.type = "ad";
    ytAd.text = "Sponsored: Skillshare - Learn creative skills with thousands of classes. First 30 days free.";
    ytAd.source = "YouTube";
    ytAd.author = "Skillshare";
    ytAd.timestamp = "Sponsored";
    ytAd.x = 150; ytAd.y = 380; ytAd.width = 1000; ytAd.height = 60;
    ytAd.relevance = 0.3f;
    g_sim_content.push_back(ytAd);

    // Scenario 10: TikTok - user scrolling
    AppInfo tiktok;
    tiktok.window_id = "sim_tiktok";
    tiktok.title = "TikTok";
    tiktok.process_name = "tiktok.exe";
    tiktok.process_id = 2010;
    tiktok.x = 400; tiktok.y = 100;
    tiktok.width = 500; tiktok.height = 900;
    tiktok.is_visible = true;
    tiktok.is_focused = false;
    tiktok.app_category = "social_media";
    tiktok.platform = "simulation";
    g_sim_apps.push_back(tiktok);

    ContentBlock ttVideo1;
    ttVideo1.type = "video";
    ttVideo1.text = "POV: when the code finally compiles after 50 errors #programming #coding #developer";
    ttVideo1.source = "TikTok";
    ttVideo1.author = "@codejokes";
    ttVideo1.timestamp = "2026-08-05 09:45";
    ttVideo1.x = 450; ttVideo1.y = 150; ttVideo1.width = 400; ttVideo1.height = 100;
    ttVideo1.relevance = 0.88f;
    g_sim_content.push_back(ttVideo1);

    ContentBlock ttVideo2;
    ttVideo2.type = "video";
    ttVideo2.text = "3 productivity hacks that changed my life. 1. Time blocking 2. Pomodoro 3. Digital minimalism";
    ttVideo2.source = "TikTok";
    ttVideo2.author = "@productivityguru";
    ttVideo2.timestamp = "2026-08-05 09:20";
    ttVideo2.x = 450; ttVideo2.y = 280; ttVideo2.width = 400; ttVideo2.height = 100;
    ttVideo2.relevance = 0.75f;
    g_sim_content.push_back(ttVideo2);

    // Scenario 11: Reddit - user browsing
    AppInfo reddit;
    reddit.window_id = "sim_reddit";
    reddit.title = "r/cpp - Reddit";
    reddit.process_name = "reddit.exe";
    reddit.process_id = 2011;
    reddit.x = 200; reddit.y = 150;
    reddit.width = 1000; reddit.height = 700;
    reddit.is_visible = true;
    reddit.is_focused = false;
    reddit.app_category = "social_media";
    reddit.platform = "simulation";
    g_sim_apps.push_back(reddit);

    ContentBlock rdPost1;
    rdPost1.type = "post";
    rdPost1.text = "What's the best C++ feature introduced in C++20? I've been using concepts and ranges, but coroutines seem powerful too.";
    rdPost1.source = "Reddit";
    rdPost1.author = "u/cpp_enthusiast";
    rdPost1.timestamp = "2026-08-05 08:00";
    rdPost1.x = 250; rdPost1.y = 200; rdPost1.width = 800; rdPost1.height = 100;
    rdPost1.relevance = 0.90f;
    g_sim_content.push_back(rdPost1);

    ContentBlock rdPost2;
    rdPost2.type = "post";
    rdPost2.text = "TIL that std::vector reallocation can be avoided with reserve(). This would have saved me so many debugging hours.";
    rdPost2.source = "Reddit";
    rdPost2.author = "u/learning_cpp";
    rdPost2.timestamp = "2026-08-05 07:15";
    rdPost2.x = 250; rdPost2.y = 320; rdPost2.width = 800; rdPost2.height = 100;
    rdPost2.relevance = 0.82f;
    g_sim_content.push_back(rdPost2);

    // Scenario 12: LinkedIn - professional networking
    AppInfo linkedin;
    linkedin.window_id = "sim_linkedin";
    linkedin.title = "LinkedIn - Feed";
    linkedin.process_name = "linkedin.exe";
    linkedin.process_id = 2012;
    linkedin.x = 300; reddit.y = 100;
    linkedin.width = 900; linkedin.height = 800;
    linkedin.is_visible = true;
    linkedin.is_focused = false;
    linkedin.app_category = "social_media";
    linkedin.platform = "simulation";
    g_sim_apps.push_back(linkedin);

    ContentBlock liPost1;
    liPost1.type = "post";
    liPost1.text = "Excited to announce I've joined Google as a Senior Software Engineer! Looking forward to working on exciting projects with an amazing team.";
    liPost1.source = "LinkedIn";
    liPost1.author = "Jane Smith";
    liPost1.timestamp = "2026-08-05 10:00";
    liPost1.x = 350; liPost1.y = 150; liPost1.width = 700; liPost1.height = 100;
    liPost1.relevance = 0.80f;
    g_sim_content.push_back(liPost1);

    ContentBlock liPost2;
    liPost2.type = "post";
    liPost2.text = "Just published: 'The Future of AI in Software Development' - exploring how AI tools are transforming the way we write code.";
    liPost2.source = "LinkedIn";
    liPost2.author = "John Doe";
    liPost2.timestamp = "2026-08-05 08:30";
    liPost2.x = 350; liPost2.y = 280; liPost2.width = 700; liPost2.height = 100;
    liPost2.relevance = 0.75f;
    g_sim_content.push_back(liPost2);

    // Scenario 13: Snapchat - user chatting
    AppInfo snapchat;
    snapchat.window_id = "sim_snapchat";
    snapchat.title = "Snapchat";
    snapchat.process_name = "snapchat.exe";
    snapchat.process_id = 2013;
    snapchat.x = 500; snapchat.y = 80;
    snapchat.width = 600; snapchat.height = 800;
    snapchat.is_visible = true;
    snapchat.is_focused = false;
    snapchat.app_category = "social_media";
    snapchat.platform = "simulation";
    g_sim_apps.push_back(snapchat);

    ContentBlock snapMsg1;
    snapMsg1.type = "message";
    snapMsg1.text = "Hey! Are we still on for the concert tonight?";
    snapMsg1.source = "Snapchat";
    snapMsg1.author = "Alex";
    snapMsg1.timestamp = "2026-08-05 09:50";
    snapMsg1.x = 550; snapMsg1.y = 150; snapMsg1.width = 400; snapMsg1.height = 60;
    snapMsg1.relevance = 0.90f;
    g_sim_content.push_back(snapMsg1);

    ContentBlock snapMsg2;
    snapMsg2.type = "message";
    snapMsg2.text = "Yes! I already got the tickets. Meet at 8pm at the venue entrance.";
    snapMsg2.source = "Snapchat";
    snapMsg2.author = "You";
    snapMsg2.timestamp = "2026-08-05 09:52";
    snapMsg2.x = 550; snapMsg2.y = 220; snapMsg2.width = 400; snapMsg2.height = 60;
    snapMsg2.relevance = 0.92f;
    g_sim_content.push_back(snapMsg2);

    // Build screen text from content
    std::ostringstream oss;
    for (const auto& c : g_sim_content) {
        oss << c.text << "\n";
    }
    g_sim_screen_text = oss.str();

    // ===== Simulation UIA Elements =====
    g_sim_uia_elements.clear();
    int eid = 0;

    // Facebook window UIA tree
    auto addElem = [&](const std::string& name, const std::string& type, const std::string& parent,
                       int x, int y, int w, int h, bool enabled, bool focused, int depth,
                       bool invoke, bool value, bool toggle, const std::string& val,
                       const std::string& help, const std::string& winId) -> std::string {
        UiaElementInfo e;
        e.element_id = "uia_" + std::to_string(eid++);
        e.name = name;
        e.control_type = type;
        e.localized_control_type = type;
        if (depth == 0) {
            e.automation_id = winId;
        }
        e.x = x; e.y = y; e.width = w; e.height = h;
        e.is_enabled = enabled;
        e.is_visible = true;
        e.is_focused = focused;
        e.is_offscreen = false;
        e.is_keyboard_focusable = enabled && (value || toggle);
        e.has_invoke_pattern = invoke;
        e.has_value_pattern = value;
        e.has_toggle_pattern = toggle;
        e.value = val;
        e.help_text = help;
        e.process_id = 2001;
        e.parent_id = parent;
        e.depth = depth;
        g_sim_uia_elements.push_back(e);
        return e.element_id;
    };

    // Facebook UIA tree
    std::string fbRoot = addElem("Facebook - News Feed", "window", "", 100, 50, 900, 700, true, true, 0, false, false, false, "", "Facebook main window", "sim_fb");
    addElem("News Feed", "pane", fbRoot, 100, 50, 900, 700, true, false, 1, false, false, false, "", "Feed container", "sim_fb");
    std::string fbSearch = addElem("Search Facebook", "edit", fbRoot, 120, 60, 200, 30, true, false, 1, false, true, false, "", "Search input", "sim_fb");
    addElem("Search", "button", fbRoot, 330, 60, 60, 30, true, false, 1, true, false, false, "", "Search button", "sim_fb");
    std::string fbHome = addElem("Home", "hyperlink", fbRoot, 120, 100, 50, 20, true, false, 1, true, false, false, "", "Go to home", "sim_fb");
    addElem("Profile", "hyperlink", fbRoot, 180, 100, 50, 20, true, false, 1, true, false, false, "", "Go to profile", "sim_fb");
    addElem("Notifications", "hyperlink", fbRoot, 240, 100, 70, 20, true, false, 1, true, false, false, "", "View notifications", "sim_fb");
    addElem("Messages", "hyperlink", fbRoot, 320, 100, 60, 20, true, false, 1, true, false, false, "", "View messages", "sim_fb");
    // Post 1
    std::string post1Pane = addElem("Post by Sarah Johnson", "pane", fbRoot, 150, 80, 800, 120, true, false, 1, false, false, false, "", "Facebook post", "sim_fb");
    addElem("Sarah Johnson", "text", post1Pane, 160, 90, 120, 20, true, false, 2, false, false, false, "Sarah Johnson", "Author name", "sim_fb");
    addElem("Just finished my morning run! 5K in 25 minutes.", "text", post1Pane, 160, 120, 780, 60, true, false, 2, false, false, false, "Just finished my morning run!", "Post content", "sim_fb");
    addElem("Like", "button", post1Pane, 160, 180, 60, 30, true, false, 2, true, false, false, "", "Like this post", "sim_fb");
    addElem("Comment", "button", post1Pane, 230, 180, 80, 30, true, false, 2, true, false, false, "", "Comment on this post", "sim_fb");
    addElem("Share", "button", post1Pane, 320, 180, 60, 30, true, false, 2, true, false, false, "", "Share this post", "sim_fb");
    // Post 2
    std::string post2Pane = addElem("Post by Tech News Daily", "pane", fbRoot, 150, 220, 800, 140, true, false, 1, false, false, false, "", "Facebook post", "sim_fb");
    addElem("Tech News Daily", "text", post2Pane, 160, 230, 120, 20, true, false, 2, false, false, false, "Tech News Daily", "Author name", "sim_fb");
    addElem("Breaking: New AI model achieves 99% accuracy.", "text", post2Pane, 160, 260, 780, 80, true, false, 2, false, false, false, "Breaking: New AI model achieves 99%", "Post content", "sim_fb");
    addElem("Like", "button", post2Pane, 160, 340, 60, 30, true, false, 2, true, false, false, "", "Like this post", "sim_fb");
    addElem("Comment", "button", post2Pane, 230, 340, 80, 30, true, false, 2, true, false, false, "", "Comment on this post", "sim_fb");
    // Sponsored ad
    std::string adPane = addElem("Sponsored: SportsMart 50% off", "pane", fbRoot, 150, 380, 800, 80, true, false, 1, false, false, false, "", "Sponsored content", "sim_fb");
    addElem("Shop now at SportsMart", "hyperlink", adPane, 160, 400, 200, 20, true, false, 2, true, false, false, "", "Click to shop", "sim_fb");
    addElem("Sponsored", "text", adPane, 160, 390, 60, 15, true, false, 2, false, false, false, "Sponsored", "Ad label", "sim_fb");
    // Comment box (disabled - user not logged in to comment)
    std::string commentBox = addElem("Write a comment...", "edit", fbRoot, 150, 580, 780, 40, false, false, 1, false, true, false, "", "Comment input (disabled)", "sim_fb");
    addElem("Post Comment", "button", fbRoot, 940, 580, 60, 40, false, false, 1, true, false, false, "", "Post comment (disabled)", "sim_fb");

    // Chrome UIA tree
    std::string chromeRoot = addElem("C++ Tutorial - Google Chrome", "window", "", 200, 100, 1200, 800, true, false, 0, false, false, false, "", "Chrome window", "sim_chrome");
    std::string urlBar = addElem("Address and search bar", "edit", chromeRoot, 220, 110, 800, 30, true, true, 1, false, true, false, "https://cppreference.com/vector", "URL bar", "sim_chrome");
    addElem("Back", "button", chromeRoot, 210, 110, 30, 30, true, false, 1, true, false, false, "", "Go back", "sim_chrome");
    addElem("Forward", "button", chromeRoot, 245, 110, 30, 30, false, false, 1, true, false, false, "", "Go forward (disabled)", "sim_chrome");
    addElem("Refresh", "button", chromeRoot, 280, 110, 30, 30, true, false, 1, true, false, false, "", "Refresh page", "sim_chrome");
    std::string content = addElem("Content", "pane", chromeRoot, 200, 150, 1200, 700, true, false, 1, false, false, false, "", "Page content", "sim_chrome");
    addElem("std::vector - C++ Reference", "text", content, 220, 170, 400, 30, true, false, 2, false, false, false, "std::vector", "Page heading", "sim_chrome");
    addElem("Member functions", "hyperlink", content, 220, 220, 150, 20, true, false, 2, true, false, false, "", "Link to member functions", "sim_chrome");
    addElem("push_back", "hyperlink", content, 220, 250, 100, 20, true, false, 2, true, false, false, "", "Link to push_back", "sim_chrome");
    addElem("size", "hyperlink", content, 220, 280, 50, 20, true, false, 2, true, false, false, "", "Link to size", "sim_chrome");

    // VS Code UIA tree
    std::string vscodeRoot = addElem("main.cpp - Visual Studio Code", "window", "", 50, 30, 1600, 900, true, false, 0, false, false, false, "", "VS Code window", "sim_vscode");
    std::string menuBar = addElem("Menu bar", "toolbar", vscodeRoot, 50, 30, 1600, 25, true, false, 1, false, false, false, "", "Menu bar", "sim_vscode");
    addElem("File", "menu", menuBar, 60, 30, 40, 25, true, false, 2, true, false, false, "", "File menu", "sim_vscode");
    addElem("Edit", "menu", menuBar, 105, 30, 40, 25, true, false, 2, true, false, false, "", "Edit menu", "sim_vscode");
    addElem("View", "menu", menuBar, 150, 30, 40, 25, true, false, 2, true, false, false, "", "View menu", "sim_vscode");
    std::string editor = addElem("Code editor", "edit", vscodeRoot, 200, 60, 1400, 800, true, true, 1, false, true, false, "int main() { return 0; }", "Code editor", "sim_vscode");
    std::string statusBar = addElem("Status bar", "statusbar", vscodeRoot, 50, 870, 1600, 30, true, false, 1, false, false, false, "", "Status bar", "sim_vscode");
    addElem("Line 1, Column 1", "text", statusBar, 60, 875, 120, 20, true, false, 2, false, false, false, "Ln 1, Col 1", "Cursor position", "sim_vscode");
    addElem("UTF-8", "text", statusBar, 200, 875, 60, 20, true, false, 2, false, false, false, "UTF-8", "Encoding", "sim_vscode");
    std::string sidebar = addElem("Explorer", "pane", vscodeRoot, 50, 60, 150, 800, true, false, 1, false, false, false, "", "File explorer", "sim_vscode");
    addElem("main.cpp", "treeitem", sidebar, 60, 80, 130, 20, true, false, 2, true, false, false, "", "Source file", "sim_vscode");
    addElem("utils.h", "treeitem", sidebar, 60, 105, 130, 20, true, false, 2, true, false, false, "", "Header file", "sim_vscode");
    addElem("utils.cpp", "treeitem", sidebar, 60, 130, 130, 20, true, false, 2, true, false, false, "", "Source file", "sim_vscode");

    // Spotify UIA tree (minimized - most elements offscreen)
    std::string spotifyRoot = addElem("Spotify - Lo-Fi Beats", "window", "", 1100, 600, 400, 300, true, false, 0, false, false, false, "", "Spotify window", "sim_spotify");
    std::string playBtn = addElem("Play", "button", spotifyRoot, 1200, 650, 40, 40, true, false, 1, true, false, false, "", "Play/Pause", "sim_spotify");
    addElem("Next", "button", spotifyRoot, 1250, 650, 40, 40, true, false, 1, true, false, false, "", "Next track", "sim_spotify");
    addElem("Previous", "button", spotifyRoot, 1150, 650, 40, 40, true, false, 1, true, false, false, "", "Previous track", "sim_spotify");
    std::string volSlider = addElem("Volume", "slider", spotifyRoot, 1300, 650, 100, 30, true, false, 1, false, false, false, "75", "Volume control", "sim_spotify");
    addElem("Lo-Fi Beats playlist", "text", spotifyRoot, 1150, 620, 200, 20, true, false, 1, false, false, false, "Lo-Fi Beats", "Now playing", "sim_spotify");

    // Outlook UIA tree
    std::string outlookRoot = addElem("Inbox (3) - Outlook", "window", "", 300, 150, 1000, 700, true, false, 0, false, false, false, "", "Outlook window", "sim_outlook");
    std::string folderList = addElem("Folder list", "pane", outlookRoot, 300, 180, 200, 600, true, false, 1, false, false, false, "", "Mail folders", "sim_outlook");
    addElem("Inbox (3)", "treeitem", folderList, 310, 190, 180, 25, true, false, 2, true, false, false, "", "Inbox folder", "sim_outlook");
    addElem("Sent Items", "treeitem", folderList, 310, 220, 180, 25, true, false, 2, true, false, false, "", "Sent folder", "sim_outlook");
    addElem("Drafts", "treeitem", folderList, 310, 250, 180, 25, true, false, 2, true, false, false, "", "Drafts folder", "sim_outlook");
    std::string emailList = addElem("Email list", "list", outlookRoot, 510, 180, 400, 600, true, false, 1, false, false, false, "", "Email list", "sim_outlook");
    addElem("Meeting tomorrow at 10am", "listitem", emailList, 515, 190, 390, 60, true, false, 2, true, false, false, "", "Email item", "sim_outlook");
    addElem("Re: Project update", "listitem", emailList, 515, 255, 390, 60, true, false, 2, true, false, false, "", "Email item", "sim_outlook");
    addElem("Budget approval needed", "listitem", emailList, 515, 320, 390, 60, true, false, 2, true, false, false, "", "Email item", "sim_outlook");
    std::string searchBox = addElem("Search mail", "edit", outlookRoot, 300, 155, 300, 25, true, false, 1, false, true, false, "", "Search emails", "sim_outlook");
    addElem("New Email", "button", outlookRoot, 920, 155, 80, 25, true, false, 1, true, false, false, "", "Compose new email", "sim_outlook");
    addElem("Reply", "button", outlookRoot, 920, 180, 60, 25, false, false, 1, true, false, false, "", "Reply (no email selected)", "sim_outlook");

    // X (Twitter) UIA tree - realistic 3-column layout (left nav, center feed, right rail)
    std::string xRoot = addElem("Home / X", "window", "", 150, 80, 1000, 800, true, false, 0, false, false, false, "", "X main window", "sim_x");
    // Left navigation rail (icon-only vertical nav ~68px)
    std::string xNav = addElem("Navigation", "pane", xRoot, 150, 80, 68, 800, true, false, 1, false, false, false, "", "Side navigation rail", "sim_x");
    addElem("Home", "hyperlink", xNav, 155, 100, 58, 40, true, false, 2, true, false, false, "", "Home timeline", "sim_x");
    addElem("Explore", "hyperlink", xNav, 155, 145, 58, 40, true, false, 2, true, false, false, "", "Explore trends", "sim_x");
    addElem("Communities", "hyperlink", xNav, 155, 190, 58, 40, true, false, 2, true, false, false, "", "Communities", "sim_x");
    addElem("Notifications", "hyperlink", xNav, 155, 235, 58, 40, true, false, 2, true, false, false, "", "Notifications", "sim_x");
    addElem("Messages", "hyperlink", xNav, 155, 280, 58, 40, true, false, 2, true, false, false, "", "Direct messages", "sim_x");
    addElem("Grok", "hyperlink", xNav, 155, 325, 58, 40, true, false, 2, true, false, false, "", "Grok AI assistant", "sim_x");
    addElem("Profile", "hyperlink", xNav, 155, 370, 58, 40, true, false, 2, true, false, false, "", "Your profile", "sim_x");
    addElem("Bookmarks", "hyperlink", xNav, 155, 415, 58, 40, true, false, 2, true, false, false, "", "Saved posts", "sim_x");
    addElem("Post", "button", xNav, 155, 470, 58, 40, true, false, 2, true, false, false, "", "Compose new post", "sim_x");
    // Center feed column (~600px)
    std::string xFeed = addElem("Feed", "pane", xRoot, 228, 80, 600, 800, true, false, 1, false, false, false, "", "Main feed column", "sim_x");
    // Feed filter tabs (For You / Following)
    std::string xTabs = addElem("Feed tabs", "pane", xFeed, 228, 80, 600, 50, true, false, 2, false, false, false, "", "For You / Following tabs", "sim_x");
    addElem("For you", "hyperlink", xTabs, 240, 85, 80, 35, true, false, 3, true, false, false, "", "Algorithmic feed", "sim_x");
    addElem("Following", "hyperlink", xTabs, 330, 85, 80, 35, true, false, 3, true, false, false, "", "Chronological feed from followed accounts", "sim_x");
    // Compose box
    std::string xCompose = addElem("Post", "edit", xFeed, 240, 140, 570, 80, true, true, 2, false, true, false, "", "Compose new post", "sim_x");
    addElem("Post", "button", xFeed, 730, 160, 70, 40, true, false, 2, true, false, false, "", "Publish post", "sim_x");
    // Tweet 1
    std::string xTweet1 = addElem("Tweet by @devbuilder", "pane", xFeed, 228, 240, 600, 160, true, false, 2, false, false, false, "", "Tweet", "sim_x");
    addElem("@devbuilder", "text", xTweet1, 240, 250, 120, 20, true, false, 3, false, false, false, "@devbuilder", "Author handle", "sim_x");
    addElem("Verified", "text", xTweet1, 365, 250, 60, 20, true, false, 3, false, false, false, "", "Verified badge", "sim_x");
    addElem("Just shipped a new feature! Real-time collaboration is now live. Try it out and let me know what you think. #buildinpublic", "text", xTweet1, 240, 280, 570, 60, true, false, 3, false, false, false, "", "Tweet content", "sim_x");
    addElem("Reply", "button", xTweet1, 240, 350, 60, 30, true, false, 3, true, false, false, "", "Reply to tweet", "sim_x");
    addElem("Repost", "button", xTweet1, 320, 350, 70, 30, true, false, 3, true, false, false, "", "Repost tweet", "sim_x");
    addElem("Like", "button", xTweet1, 410, 350, 60, 30, true, false, 3, true, false, false, "", "Like tweet", "sim_x");
    addElem("Views", "text", xTweet1, 480, 350, 80, 30, true, false, 3, false, false, false, "1.2K", "View count", "sim_x");
    addElem("Share", "button", xTweet1, 570, 350, 60, 30, true, false, 3, true, false, false, "", "Share/bookmark tweet", "sim_x");
    // Community Notes
    std::string xNote1 = addElem("Community Notes", "pane", xTweet1, 240, 380, 570, 50, true, false, 3, false, false, false, "", "Community-contributed context", "sim_x");
    addElem("Readers added context: This feature was actually launched in beta last month.", "text", xNote1, 250, 385, 550, 40, true, false, 4, false, false, false, "", "Community note text", "sim_x");
    // Tweet 2
    std::string xTweet2 = addElem("Tweet by @techphilosopher", "pane", xFeed, 228, 440, 600, 120, true, false, 2, false, false, false, "", "Tweet", "sim_x");
    addElem("@techphilosopher", "text", xTweet2, 240, 450, 140, 20, true, false, 3, false, false, false, "@techphilosopher", "Author handle", "sim_x");
    addElem("Hot take: AI won't replace developers, it'll make them 10x more productive. The key is learning to prompt effectively.", "text", xTweet2, 240, 480, 570, 50, true, false, 3, false, false, false, "", "Tweet content", "sim_x");
    addElem("Reply", "button", xTweet2, 240, 540, 60, 30, true, false, 3, true, false, false, "", "Reply to tweet", "sim_x");
    addElem("Repost", "button", xTweet2, 320, 540, 70, 30, true, false, 3, true, false, false, "", "Repost tweet", "sim_x");
    addElem("Like", "button", xTweet2, 410, 540, 60, 30, true, false, 3, true, false, false, "", "Like tweet", "sim_x");
    addElem("Views", "text", xTweet2, 480, 540, 80, 30, true, false, 3, false, false, false, "5.4K", "View count", "sim_x");
    addElem("Share", "button", xTweet2, 570, 540, 60, 30, true, false, 3, true, false, false, "", "Share/bookmark tweet", "sim_x");
    // Right rail (What's happening / trends)
    std::string xRail = addElem("Trends sidebar", "pane", xRoot, 838, 80, 290, 800, true, false, 1, false, false, false, "", "What's happening sidebar", "sim_x");
    std::string xSearch = addElem("Search X", "edit", xRail, 845, 90, 270, 35, true, false, 2, false, true, false, "", "Search X", "sim_x");
    addElem("What's happening", "text", xRail, 845, 140, 200, 25, true, false, 2, false, false, false, "", "Trends header", "sim_x");
    addElem("Trending: #BuildInPublic", "hyperlink", xRail, 845, 175, 270, 40, true, false, 2, true, false, false, "", "Trending topic", "sim_x");
    addElem("Who to follow", "text", xRail, 845, 400, 200, 25, true, false, 2, false, false, false, "", "Suggestions header", "sim_x");
    addElem("Follow @codeblogger", "button", xRail, 845, 435, 120, 35, true, false, 2, true, false, false, "", "Follow suggestion", "sim_x");

    // Instagram UIA tree - realistic layout with Stories tray, bottom nav, Save/Share actions
    std::string igRoot = addElem("Instagram", "window", "", 250, 100, 800, 900, true, false, 0, false, false, false, "", "Instagram main window", "sim_instagram");
    // Top bar
    std::string igTopBar = addElem("Top bar", "pane", igRoot, 250, 100, 800, 50, true, false, 1, false, false, false, "", "Top navigation bar", "sim_instagram");
    addElem("Instagram", "text", igTopBar, 270, 110, 120, 30, true, false, 2, false, false, false, "", "Instagram logo", "sim_instagram");
    addElem("Direct Messages", "button", igTopBar, 980, 110, 50, 30, true, false, 2, true, false, false, "", "Open DMs", "sim_instagram");
    // Stories tray (horizontal-scroll row of circular avatars with gradient unread ring)
    std::string igStories = addElem("Stories tray", "pane", igRoot, 250, 160, 800, 90, true, false, 1, false, false, false, "", "Stories from friends and creators", "sim_instagram");
    addElem("Story by @naturelover", "image", igStories, 270, 165, 70, 70, true, false, 2, false, false, false, "", "Story avatar with gradient ring", "sim_instagram");
    addElem("Story by @chefathome", "image", igStories, 350, 165, 70, 70, true, false, 2, false, false, false, "", "Story avatar with gradient ring", "sim_instagram");
    addElem("Story by @travelbug", "image", igStories, 430, 165, 70, 70, true, false, 2, false, false, false, "", "Story avatar with gradient ring", "sim_instagram");
    addElem("Story by @cityphotographer", "image", igStories, 510, 165, 70, 70, true, false, 2, false, false, false, "", "Story avatar with gradient ring", "sim_instagram");
    // Post 1
    std::string igPost1Pane = addElem("Post by @naturelover", "pane", igRoot, 300, 260, 700, 420, true, false, 1, false, false, false, "", "Instagram post", "sim_instagram");
    addElem("@naturelover", "text", igPost1Pane, 310, 270, 120, 20, true, false, 2, false, false, false, "@naturelover", "Author", "sim_instagram");
    addElem("Sunset hike photo", "image", igPost1Pane, 310, 300, 660, 320, true, false, 2, false, false, false, "", "Photo content", "sim_instagram");
    addElem("Like", "button", igPost1Pane, 310, 630, 50, 40, true, false, 2, true, false, false, "", "Like post (double-tap to like)", "sim_instagram");
    addElem("Comment", "button", igPost1Pane, 370, 630, 50, 40, true, false, 2, true, false, false, "", "Comment on post", "sim_instagram");
    addElem("Share", "button", igPost1Pane, 430, 630, 50, 40, true, false, 2, true, false, false, "", "Share post via DM", "sim_instagram");
    addElem("Save", "button", igPost1Pane, 900, 630, 50, 40, true, false, 2, true, false, false, "", "Save/bookmark post", "sim_instagram");
    addElem("1,234 likes", "text", igPost1Pane, 310, 680, 150, 20, true, false, 2, false, false, false, "", "Like count", "sim_instagram");
    addElem("Sunset hike up the mountain today! The view was absolutely worth the 3 hour climb! #sunset #hiking #nature", "text", igPost1Pane, 310, 705, 660, 40, true, false, 2, false, false, false, "", "Caption", "sim_instagram");
    // Post 2
    std::string igPost2Pane = addElem("Post by @chefathome", "pane", igRoot, 300, 700, 700, 350, true, false, 1, false, false, false, "", "Instagram post", "sim_instagram");
    addElem("@chefathome", "text", igPost2Pane, 310, 710, 100, 20, true, false, 2, false, false, false, "@chefathome", "Author", "sim_instagram");
    addElem("Pasta recipe photo", "image", igPost2Pane, 310, 740, 660, 250, true, false, 2, false, false, false, "", "Photo content", "sim_instagram");
    addElem("Like", "button", igPost2Pane, 310, 1000, 50, 40, true, false, 2, true, false, false, "", "Like post", "sim_instagram");
    addElem("Comment", "button", igPost2Pane, 370, 1000, 50, 40, true, false, 2, true, false, false, "", "Comment on post", "sim_instagram");
    addElem("Share", "button", igPost2Pane, 430, 1000, 50, 40, true, false, 2, true, false, false, "", "Share post via DM", "sim_instagram");
    addElem("Save", "button", igPost2Pane, 900, 1000, 50, 40, true, false, 2, true, false, false, "", "Save/bookmark post", "sim_instagram");
    // Sponsored
    std::string igAdPane = addElem("Sponsored: GlowUp skincare", "pane", igRoot, 300, 1070, 700, 80, true, false, 1, false, false, false, "", "Sponsored content", "sim_instagram");
    addElem("Sponsored", "text", igAdPane, 310, 1080, 60, 15, true, false, 2, false, false, false, "Sponsored", "Ad label", "sim_instagram");
    addElem("Shop now", "hyperlink", igAdPane, 310, 1100, 100, 20, true, false, 2, true, false, false, "", "Shop link", "sim_instagram");
    // Bottom navigation bar (5 evenly-spaced icons: Home, Search, Reels, Shop, Profile)
    std::string igBottomNav = addElem("Bottom navigation", "pane", igRoot, 250, 1150, 800, 60, true, false, 1, false, false, false, "", "Bottom nav bar", "sim_instagram");
    addElem("Home", "button", igBottomNav, 290, 1160, 50, 40, true, false, 2, true, false, false, "", "Home feed", "sim_instagram");
    addElem("Search", "button", igBottomNav, 410, 1160, 50, 40, true, false, 2, true, false, false, "", "Search/Explore", "sim_instagram");
    addElem("Reels", "button", igBottomNav, 530, 1160, 50, 40, true, false, 2, true, false, false, "", "Reels (short videos)", "sim_instagram");
    addElem("Shop", "button", igBottomNav, 650, 1160, 50, 40, true, false, 2, true, false, false, "", "Shop marketplace", "sim_instagram");
    addElem("Profile", "button", igBottomNav, 770, 1160, 50, 40, true, false, 2, true, false, false, "", "Your profile", "sim_instagram");

    // Threads UIA tree - realistic layout with For You/Following tabs, quote, bottom nav
    std::string thRoot = addElem("Threads", "window", "", 350, 120, 900, 800, true, false, 0, false, false, false, "", "Threads main window", "sim_threads");
    // Top bar with logo
    std::string thTopBar = addElem("Top bar", "pane", thRoot, 350, 120, 900, 50, true, false, 1, false, false, false, "", "Top navigation bar", "sim_threads");
    addElem("Threads", "text", thTopBar, 700, 130, 100, 30, true, false, 2, false, false, false, "", "Threads logo", "sim_threads");
    addElem("Post", "button", thTopBar, 1150, 130, 60, 35, true, false, 2, true, false, false, "", "New thread", "sim_threads");
    // Feed filter tabs (For You / Following / custom feeds - swipeable)
    std::string thFeedTabs = addElem("Feed tabs", "pane", thRoot, 350, 180, 900, 45, true, false, 1, false, false, false, "", "Feed filter tabs", "sim_threads");
    addElem("For you", "hyperlink", thFeedTabs, 370, 185, 80, 35, true, false, 2, true, false, false, "", "Algorithmic feed", "sim_threads");
    addElem("Following", "hyperlink", thFeedTabs, 460, 185, 80, 35, true, false, 2, true, false, false, "", "Chronological feed from followed accounts", "sim_threads");
    addElem("Tech News", "hyperlink", thFeedTabs, 560, 185, 100, 35, true, false, 2, true, false, false, "", "Custom feed", "sim_threads");
    // Thread 1
    std::string thPost1Pane = addElem("Post by @techquestioner", "pane", thRoot, 370, 240, 820, 160, true, false, 1, false, false, false, "", "Thread post", "sim_threads");
    addElem("@techquestioner", "text", thPost1Pane, 380, 250, 130, 20, true, false, 2, false, false, false, "@techquestioner", "Author", "sim_threads");
    addElem("Anyone else think the new MacBook Pro M4 is overkill for most people? Like, do we really need that much power for browsing and email?", "text", thPost1Pane, 380, 280, 780, 60, true, false, 2, false, false, false, "", "Post content", "sim_threads");
    addElem("Like", "button", thPost1Pane, 380, 350, 50, 35, true, false, 2, true, false, false, "", "Like", "sim_threads");
    addElem("Reply", "button", thPost1Pane, 440, 350, 60, 35, true, false, 2, true, false, false, "", "Reply", "sim_threads");
    addElem("Repost", "button", thPost1Pane, 510, 350, 60, 35, true, false, 2, true, false, false, "", "Repost", "sim_threads");
    addElem("Quote", "button", thPost1Pane, 580, 350, 60, 35, true, false, 2, true, false, false, "", "Quote post (quote controls)", "sim_threads");
    addElem("Share", "button", thPost1Pane, 650, 350, 60, 35, true, false, 2, true, false, false, "", "Share via DM", "sim_threads");
    // Thread 2
    std::string thPost2Pane = addElem("Post by @bookworm", "pane", thRoot, 370, 420, 820, 140, true, false, 1, false, false, false, "", "Thread post", "sim_threads");
    addElem("@bookworm", "text", thPost2Pane, 380, 430, 100, 20, true, false, 2, false, false, false, "@bookworm", "Author", "sim_threads");
    addElem("Just finished reading 'Project Hail Mary' by Andy Weir. Absolutely incredible sci-fi. Highly recommend if you liked The Martian.", "text", thPost2Pane, 380, 460, 780, 60, true, false, 2, false, false, false, "", "Post content", "sim_threads");
    addElem("Like", "button", thPost2Pane, 380, 530, 50, 35, true, false, 2, true, false, false, "", "Like", "sim_threads");
    addElem("Reply", "button", thPost2Pane, 440, 530, 60, 35, true, false, 2, true, false, false, "", "Reply", "sim_threads");
    addElem("Repost", "button", thPost2Pane, 510, 530, 60, 35, true, false, 2, true, false, false, "", "Repost", "sim_threads");
    addElem("Quote", "button", thPost2Pane, 580, 530, 60, 35, true, false, 2, true, false, false, "", "Quote post", "sim_threads");
    addElem("Share", "button", thPost2Pane, 650, 530, 60, 35, true, false, 2, true, false, false, "", "Share via DM", "sim_threads");
    // Bottom navigation (Home, Search, Post, Activity, Profile)
    std::string thBottomNav = addElem("Bottom navigation", "pane", thRoot, 350, 850, 900, 60, true, false, 1, false, false, false, "", "Bottom nav bar", "sim_threads");
    addElem("Home", "button", thBottomNav, 400, 860, 50, 40, true, false, 2, true, false, false, "", "Home feed", "sim_threads");
    addElem("Search", "button", thBottomNav, 550, 860, 50, 40, true, false, 2, true, false, false, "", "Search/Explore", "sim_threads");
    addElem("Post", "button", thBottomNav, 700, 860, 50, 40, true, false, 2, true, false, false, "", "Create new thread", "sim_threads");
    addElem("Activity", "button", thBottomNav, 850, 860, 50, 40, true, false, 2, true, false, false, "", "Activity/notifications", "sim_threads");
    addElem("Profile", "button", thBottomNav, 1000, 860, 50, 40, true, false, 2, true, false, false, "", "Your profile", "sim_threads");

    // YouTube UIA tree - realistic layout with sidebar nav, Shorts, Subscribe, Like/Dislike
    std::string ytRoot = addElem("YouTube - How AI Works", "window", "", 100, 50, 1200, 800, true, false, 0, false, false, false, "", "YouTube window", "sim_youtube");
    // Top bar with search
    std::string ytTopBar = addElem("Top bar", "pane", ytRoot, 100, 50, 1200, 56, true, false, 1, false, false, false, "", "Top navigation bar", "sim_youtube");
    addElem("YouTube", "text", ytTopBar, 110, 55, 100, 30, true, false, 2, false, false, false, "", "YouTube logo", "sim_youtube");
    std::string ytSearch = addElem("Search", "edit", ytTopBar, 300, 55, 600, 35, true, false, 2, false, true, false, "", "Search YouTube", "sim_youtube");
    addElem("Search", "button", ytTopBar, 910, 55, 60, 35, true, false, 2, true, false, false, "", "Search button", "sim_youtube");
    // Left sidebar navigation
    std::string ytSidebar = addElem("Sidebar", "pane", ytRoot, 100, 110, 200, 690, true, false, 1, false, false, false, "", "Navigation sidebar", "sim_youtube");
    addElem("Home", "hyperlink", ytSidebar, 110, 120, 80, 35, true, false, 2, true, false, false, "", "Home page", "sim_youtube");
    addElem("Shorts", "hyperlink", ytSidebar, 110, 160, 80, 35, true, false, 2, true, false, false, "", "Shorts (vertical videos)", "sim_youtube");
    addElem("Subscriptions", "hyperlink", ytSidebar, 110, 200, 120, 35, true, false, 2, true, false, false, "", "Subscribed channels", "sim_youtube");
    addElem("Trending", "hyperlink", ytSidebar, 110, 240, 80, 35, true, false, 2, true, false, false, "", "Trending", "sim_youtube");
    addElem("Watch Later", "hyperlink", ytSidebar, 110, 280, 110, 35, true, false, 2, true, false, false, "", "Saved videos to watch later", "sim_youtube");
    addElem("Liked Videos", "hyperlink", ytSidebar, 110, 320, 110, 35, true, false, 2, true, false, false, "", "Videos you liked", "sim_youtube");
    addElem("Your Channel", "hyperlink", ytSidebar, 110, 360, 100, 35, true, false, 2, true, false, false, "", "Your channel", "sim_youtube");
    // Video 1
    std::string ytVideo1Pane = addElem("How AI Works: Neural Networks Explained", "pane", ytRoot, 320, 110, 960, 200, true, false, 1, false, false, false, "", "Video card", "sim_youtube");
    addElem("Thumbnail", "image", ytVideo1Pane, 330, 120, 200, 120, true, false, 2, false, false, false, "", "Video thumbnail", "sim_youtube");
    addElem("How AI Works: Neural Networks Explained Simply", "text", ytVideo1Pane, 550, 130, 400, 40, true, false, 2, false, false, false, "", "Video title", "sim_youtube");
    addElem("3Blue1Brown", "text", ytVideo1Pane, 550, 180, 120, 20, true, false, 2, false, false, false, "3Blue1Brown", "Channel name", "sim_youtube");
    addElem("1.2M views - 15 minutes", "text", ytVideo1Pane, 550, 210, 200, 20, true, false, 2, false, false, false, "", "Video metadata", "sim_youtube");
    addElem("Subscribe", "button", ytVideo1Pane, 550, 240, 100, 35, true, false, 2, true, false, false, "", "Subscribe to channel", "sim_youtube");
    // Video 2
    std::string ytVideo2Pane = addElem("Building a C++ Game Engine - Part 5", "pane", ytRoot, 320, 330, 960, 200, true, false, 1, false, false, false, "", "Video card", "sim_youtube");
    addElem("Thumbnail", "image", ytVideo2Pane, 330, 340, 200, 120, true, false, 2, false, false, false, "", "Video thumbnail", "sim_youtube");
    addElem("Building a C++ Game Engine from Scratch - Part 5", "text", ytVideo2Pane, 550, 350, 400, 40, true, false, 2, false, false, false, "", "Video title", "sim_youtube");
    addElem("TheCherno", "text", ytVideo2Pane, 550, 400, 100, 20, true, false, 2, false, false, false, "TheCherno", "Channel name", "sim_youtube");
    addElem("85K views - 45 minutes", "text", ytVideo2Pane, 550, 430, 200, 20, true, false, 2, false, false, false, "", "Video metadata", "sim_youtube");
    addElem("Subscribe", "button", ytVideo2Pane, 550, 460, 100, 35, true, false, 2, true, false, false, "", "Subscribe to channel", "sim_youtube");
    // Video interaction bar (Like/Dislike/Share/Save)
    std::string ytActions = addElem("Video actions", "pane", ytRoot, 320, 550, 960, 50, true, false, 1, false, false, false, "", "Like/Dislike/Share/Save bar", "sim_youtube");
    addElem("Like", "button", ytActions, 330, 555, 70, 35, true, false, 2, true, false, false, "", "Like video", "sim_youtube");
    addElem("Dislike", "button", ytActions, 410, 555, 80, 35, true, false, 2, true, false, false, "", "Dislike video", "sim_youtube");
    addElem("Share", "button", ytActions, 500, 555, 70, 35, true, false, 2, true, false, false, "", "Share video", "sim_youtube");
    addElem("Save", "button", ytActions, 580, 555, 70, 35, true, false, 2, true, false, false, "", "Save to playlist", "sim_youtube");
    // Ad
    std::string ytAdPane = addElem("Sponsored: Skillshare", "pane", ytRoot, 320, 620, 960, 80, true, false, 1, false, false, false, "", "Sponsored content", "sim_youtube");
    addElem("Sponsored", "text", ytAdPane, 330, 630, 60, 15, true, false, 2, false, false, false, "Sponsored", "Ad label", "sim_youtube");
    addElem("Learn creative skills - First 30 days free", "hyperlink", ytAdPane, 330, 650, 300, 20, true, false, 2, true, false, false, "", "Ad link", "sim_youtube");
    // Bottom navigation bar (Home, Shorts, Create, Subscriptions, You)
    std::string ytBottomNav = addElem("Bottom navigation", "pane", ytRoot, 100, 740, 1200, 60, true, false, 1, false, false, false, "", "Bottom nav bar", "sim_youtube");
    addElem("Home", "button", ytBottomNav, 200, 750, 80, 40, true, false, 2, true, false, false, "", "Home page", "sim_youtube");
    addElem("Shorts", "button", ytBottomNav, 400, 750, 80, 40, true, false, 2, true, false, false, "", "Shorts feed", "sim_youtube");
    addElem("Create", "button", ytBottomNav, 600, 750, 80, 40, true, false, 2, true, false, false, "", "Create/upload video", "sim_youtube");
    addElem("Subscriptions", "button", ytBottomNav, 800, 750, 120, 40, true, false, 2, true, false, false, "", "Subscriptions", "sim_youtube");
    addElem("You", "button", ytBottomNav, 1000, 750, 80, 40, true, false, 2, true, false, false, "", "Your profile/library", "sim_youtube");

    // TikTok UIA tree - realistic full-screen vertical video with right-side action stack
    std::string ttRoot = addElem("TikTok", "window", "", 400, 100, 500, 900, true, false, 0, false, false, false, "", "TikTok window", "sim_tiktok");
    // Top feed tabs (For You / Following)
    std::string ttFeedTabs = addElem("Feed tabs", "pane", ttRoot, 400, 100, 500, 50, true, false, 1, false, false, false, "", "For You / Following tabs", "sim_tiktok");
    addElem("Following", "hyperlink", ttFeedTabs, 460, 105, 100, 35, true, false, 2, true, false, false, "", "Following feed", "sim_tiktok");
    addElem("For You", "hyperlink", ttFeedTabs, 600, 105, 100, 35, true, false, 2, true, false, false, "", "Algorithmic feed (default)", "sim_tiktok");
    addElem("Search", "button", ttFeedTabs, 820, 105, 50, 35, true, false, 2, true, false, false, "", "Search TikTok", "sim_tiktok");
    // Video 1 (full-screen)
    std::string ttVideo1Pane = addElem("POV: code finally compiles", "pane", ttRoot, 400, 160, 500, 700, true, false, 1, false, false, false, "", "TikTok full-screen video", "sim_tiktok");
    addElem("Video content", "image", ttVideo1Pane, 400, 160, 500, 700, true, false, 2, false, false, false, "", "Full-screen video", "sim_tiktok");
    // Right-side action stack (vertical lineup of icons)
    addElem("@codejokes", "text", ttVideo1Pane, 430, 700, 120, 25, true, false, 2, false, false, false, "@codejokes", "Author handle", "sim_tiktok");
    addElem("Follow", "button", ttVideo1Pane, 560, 700, 80, 35, true, false, 2, true, false, false, "", "Follow creator", "sim_tiktok");
    addElem("Like", "button", ttVideo1Pane, 830, 400, 50, 50, true, false, 2, true, false, false, "", "Like video (heart)", "sim_tiktok");
    addElem("Comment", "button", ttVideo1Pane, 830, 470, 50, 50, true, false, 2, true, false, false, "", "Comment on video", "sim_tiktok");
    addElem("Bookmark", "button", ttVideo1Pane, 830, 540, 50, 50, true, false, 2, true, false, false, "", "Save/bookmark video", "sim_tiktok");
    addElem("Share", "button", ttVideo1Pane, 830, 610, 50, 50, true, false, 2, true, false, false, "", "Share video", "sim_tiktok");
    // Sound info
    addElem("Original sound - @codejokes", "text", ttVideo1Pane, 430, 740, 300, 25, true, false, 2, false, false, false, "", "Sound name", "sim_tiktok");
    // Video description
    addElem("POV: when the code finally compiles after 50 errors #programming #coding #developer", "text", ttVideo1Pane, 430, 670, 380, 40, true, false, 2, false, false, false, "", "Video caption", "sim_tiktok");
    // Bottom navigation (Home, Discover, Create (+), Shop, Inbox)
    std::string ttBottomNav = addElem("Bottom navigation", "pane", ttRoot, 400, 860, 500, 60, true, false, 1, false, false, false, "", "Bottom nav bar", "sim_tiktok");
    addElem("Home", "button", ttBottomNav, 420, 870, 60, 40, true, false, 2, true, false, false, "", "Home feed", "sim_tiktok");
    addElem("Discover", "button", ttBottomNav, 500, 870, 80, 40, true, false, 2, true, false, false, "", "Discover/Search", "sim_tiktok");
    addElem("Create", "button", ttBottomNav, 620, 865, 50, 50, true, false, 2, true, false, false, "", "Create video (+)", "sim_tiktok");
    addElem("Shop", "button", ttBottomNav, 720, 870, 60, 40, true, false, 2, true, false, false, "", "Shop products", "sim_tiktok");
    addElem("Inbox", "button", ttBottomNav, 820, 870, 60, 40, true, false, 2, true, false, false, "", "Inbox/notifications", "sim_tiktok");
    addElem("Profile", "button", ttBottomNav, 890, 870, 60, 40, true, false, 2, true, false, false, "", "Your profile", "sim_tiktok");

    // Reddit UIA tree - realistic 3-column layout (left rail, center feed, right sidebar)
    std::string rdRoot = addElem("r/cpp - Reddit", "window", "", 200, 150, 1000, 800, true, false, 0, false, false, false, "", "Reddit window", "sim_reddit");
    // Top bar with search and sort
    std::string rdTopBar = addElem("Top bar", "pane", rdRoot, 200, 150, 1000, 50, true, false, 1, false, false, false, "", "Top navigation bar", "sim_reddit");
    std::string rdSearch = addElem("Search Reddit", "edit", rdTopBar, 400, 155, 400, 35, true, false, 2, false, true, false, "", "Search", "sim_reddit");
    addElem("Search", "button", rdTopBar, 810, 155, 60, 35, true, false, 2, true, false, false, "", "Search button", "sim_reddit");
    addElem("Sort: Hot", "button", rdTopBar, 210, 155, 100, 35, true, false, 2, true, false, false, "", "Sort posts (Hot/New/Top/Rising)", "sim_reddit");
    // Left rail (subscribed subreddits)
    std::string rdLeftRail = addElem("Subreddits", "pane", rdRoot, 200, 210, 180, 600, true, false, 1, false, false, false, "", "Subscribed communities", "sim_reddit");
    addElem("r/cpp", "hyperlink", rdLeftRail, 210, 220, 160, 30, true, false, 2, true, false, false, "", "C++ subreddit", "sim_reddit");
    addElem("r/programming", "hyperlink", rdLeftRail, 210, 255, 160, 30, true, false, 2, true, false, false, "", "Programming subreddit", "sim_reddit");
    addElem("r/learnprogramming", "hyperlink", rdLeftRail, 210, 290, 160, 30, true, false, 2, true, false, false, "", "Learn programming subreddit", "sim_reddit");
    addElem("Home", "hyperlink", rdLeftRail, 210, 325, 160, 30, true, false, 2, true, false, false, "", "Reddit home feed", "sim_reddit");
    addElem("Popular", "hyperlink", rdLeftRail, 210, 360, 160, 30, true, false, 2, true, false, false, "", "Popular feed", "sim_reddit");
    // Right sidebar (subreddit info)
    std::string rdSidebar = addElem("Sidebar", "pane", rdRoot, 820, 210, 180, 600, true, false, 1, false, false, false, "", "Subreddit sidebar", "sim_reddit");
    addElem("About r/cpp", "hyperlink", rdSidebar, 830, 220, 160, 25, true, false, 2, true, false, false, "", "About", "sim_reddit");
    addElem("Rules", "hyperlink", rdSidebar, 830, 250, 160, 25, true, false, 2, true, false, false, "", "Community rules", "sim_reddit");
    addElem("Wiki", "hyperlink", rdSidebar, 830, 280, 160, 25, true, false, 2, true, false, false, "", "Community wiki", "sim_reddit");
    addElem("Join", "button", rdSidebar, 830, 320, 100, 35, true, false, 2, true, false, false, "", "Join subreddit", "sim_reddit");
    addElem("125K members", "text", rdSidebar, 830, 365, 160, 20, true, false, 2, false, false, false, "", "Member count", "sim_reddit");
    // Post 1 (with vote arrow stack on left)
    std::string rdPost1Pane = addElem("What's the best C++ feature in C++20?", "pane", rdRoot, 400, 210, 400, 180, true, false, 1, false, false, false, "", "Reddit post", "sim_reddit");
    addElem("Upvote", "button", rdPost1Pane, 410, 220, 50, 30, true, false, 2, true, false, false, "", "Upvote (Reddit Orange)", "sim_reddit");
    addElem("342", "text", rdPost1Pane, 410, 255, 50, 20, true, false, 2, false, false, false, "342", "Vote count", "sim_reddit");
    addElem("Downvote", "button", rdPost1Pane, 410, 280, 50, 30, true, false, 2, true, false, false, "", "Downvote (Downvote Blue)", "sim_reddit");
    addElem("u/cpp_enthusiast", "text", rdPost1Pane, 480, 220, 130, 20, true, false, 2, false, false, false, "u/cpp_enthusiast", "Author", "sim_reddit");
    addElem("What's the best C++ feature introduced in C++20? I've been using concepts and ranges, but coroutines seem powerful too.", "text", rdPost1Pane, 480, 250, 300, 60, true, false, 2, false, false, false, "", "Post content", "sim_reddit");
    addElem("Comments", "button", rdPost1Pane, 480, 320, 90, 30, true, false, 2, true, false, false, "", "View comments (47)", "sim_reddit");
    addElem("Share", "button", rdPost1Pane, 580, 320, 60, 30, true, false, 2, true, false, false, "", "Share post", "sim_reddit");
    addElem("Save", "button", rdPost1Pane, 650, 320, 50, 30, true, false, 2, true, false, false, "", "Save post", "sim_reddit");
    // Post 2
    std::string rdPost2Pane = addElem("TIL: std::vector reserve()", "pane", rdRoot, 400, 410, 400, 150, true, false, 1, false, false, false, "", "Reddit post", "sim_reddit");
    addElem("Upvote", "button", rdPost2Pane, 410, 420, 50, 30, true, false, 2, true, false, false, "", "Upvote", "sim_reddit");
    addElem("89", "text", rdPost2Pane, 410, 455, 50, 20, true, false, 2, false, false, false, "89", "Vote count", "sim_reddit");
    addElem("Downvote", "button", rdPost2Pane, 410, 480, 50, 30, true, false, 2, true, false, false, "", "Downvote", "sim_reddit");
    addElem("u/learning_cpp", "text", rdPost2Pane, 480, 420, 120, 20, true, false, 2, false, false, false, "u/learning_cpp", "Author", "sim_reddit");
    addElem("TIL that std::vector reallocation can be avoided with reserve(). This would have saved me so many debugging hours.", "text", rdPost2Pane, 480, 450, 300, 50, true, false, 2, false, false, false, "", "Post content", "sim_reddit");
    addElem("Comments", "button", rdPost2Pane, 480, 510, 90, 30, true, false, 2, true, false, false, "", "View comments (12)", "sim_reddit");
    addElem("Share", "button", rdPost2Pane, 580, 510, 60, 30, true, false, 2, true, false, false, "", "Share post", "sim_reddit");
    addElem("Save", "button", rdPost2Pane, 650, 510, 50, 30, true, false, 2, true, false, false, "", "Save post", "sim_reddit");

    // LinkedIn UIA tree - realistic layout with top bar (avatar/search/compose/messages) + bottom nav
    std::string liRoot = addElem("LinkedIn - Feed", "window", "", 300, 100, 900, 800, true, false, 0, false, false, false, "", "LinkedIn window", "sim_linkedin");
    // Top bar (profile avatar, search, compose, messages)
    std::string liTopBar = addElem("Top bar", "pane", liRoot, 300, 100, 900, 56, true, false, 1, false, false, false, "", "Top navigation bar", "sim_linkedin");
    addElem("Profile avatar", "button", liTopBar, 310, 108, 36, 36, true, false, 2, true, false, false, "", "Open profile sidebar drawer", "sim_linkedin");
    std::string liSearch = addElem("Search", "edit", liTopBar, 360, 108, 300, 35, true, false, 2, false, true, false, "", "Search LinkedIn", "sim_linkedin");
    addElem("Create post", "button", liTopBar, 680, 108, 100, 35, true, false, 2, true, false, false, "", "Compose new post", "sim_linkedin");
    addElem("Messaging", "button", liTopBar, 800, 108, 80, 35, true, false, 2, true, false, false, "", "Open messages (3 unread)", "sim_linkedin");
    addElem("Notifications", "button", liTopBar, 890, 108, 80, 35, true, false, 2, true, false, false, "", "View notifications", "sim_linkedin");
    // Post 1
    std::string liPost1Pane = addElem("Post by Jane Smith", "pane", liRoot, 320, 170, 850, 200, true, false, 1, false, false, false, "", "LinkedIn post", "sim_linkedin");
    addElem("Jane Smith", "text", liPost1Pane, 330, 180, 100, 20, true, false, 2, false, false, false, "Jane Smith", "Author name", "sim_linkedin");
    addElem("Senior Software Engineer at Google", "text", liPost1Pane, 330, 205, 250, 20, true, false, 2, false, false, false, "", "Author headline/title", "sim_linkedin");
    addElem("2h", "text", liPost1Pane, 590, 205, 40, 20, true, false, 2, false, false, false, "", "Time posted", "sim_linkedin");
    addElem("Excited to announce I've joined Google as a Senior Software Engineer! Looking forward to working on exciting projects with an amazing team. #newjob #google", "text", liPost1Pane, 330, 235, 830, 80, true, false, 2, false, false, false, "", "Post content", "sim_linkedin");
    addElem("Like", "button", liPost1Pane, 330, 330, 60, 35, true, false, 2, true, false, false, "", "Like post", "sim_linkedin");
    addElem("Comment", "button", liPost1Pane, 400, 330, 80, 35, true, false, 2, true, false, false, "", "Comment on post", "sim_linkedin");
    addElem("Repost", "button", liPost1Pane, 490, 330, 70, 35, true, false, 2, true, false, false, "", "Repost to your network", "sim_linkedin");
    addElem("Send", "button", liPost1Pane, 570, 330, 60, 35, true, false, 2, true, false, false, "", "Send as DM", "sim_linkedin");
    // Post 2
    std::string liPost2Pane = addElem("Post by John Doe", "pane", liRoot, 320, 390, 850, 170, true, false, 1, false, false, false, "", "LinkedIn post", "sim_linkedin");
    addElem("John Doe", "text", liPost2Pane, 330, 400, 80, 20, true, false, 2, false, false, false, "John Doe", "Author name", "sim_linkedin");
    addElem("Tech Lead at Microsoft | AI Research", "text", liPost2Pane, 330, 425, 250, 20, true, false, 2, false, false, false, "", "Author headline/title", "sim_linkedin");
    addElem("5h", "text", liPost2Pane, 590, 425, 40, 20, true, false, 2, false, false, false, "", "Time posted", "sim_linkedin");
    addElem("Just published: 'The Future of AI in Software Development' - exploring how AI tools are transforming the way we write code.", "text", liPost2Pane, 330, 455, 830, 60, true, false, 2, false, false, false, "", "Post content", "sim_linkedin");
    addElem("Like", "button", liPost2Pane, 330, 530, 60, 35, true, false, 2, true, false, false, "", "Like post", "sim_linkedin");
    addElem("Comment", "button", liPost2Pane, 400, 530, 80, 35, true, false, 2, true, false, false, "", "Comment on post", "sim_linkedin");
    addElem("Repost", "button", liPost2Pane, 490, 530, 70, 35, true, false, 2, true, false, false, "", "Repost to your network", "sim_linkedin");
    addElem("Send", "button", liPost2Pane, 570, 530, 60, 35, true, false, 2, true, false, false, "", "Send as DM", "sim_linkedin");
    // Bottom navigation (Home, Video, My Network, Notifications, Jobs)
    std::string liBottomNav = addElem("Bottom navigation", "pane", liRoot, 300, 840, 900, 60, true, false, 1, false, false, false, "", "Bottom nav bar", "sim_linkedin");
    addElem("Home", "button", liBottomNav, 350, 850, 80, 40, true, false, 2, true, false, false, "", "Home feed", "sim_linkedin");
    addElem("Video", "button", liBottomNav, 470, 850, 80, 40, true, false, 2, true, false, false, "", "Video feed", "sim_linkedin");
    addElem("My Network", "button", liBottomNav, 590, 850, 100, 40, true, false, 2, true, false, false, "", "My Network", "sim_linkedin");
    addElem("Notifications", "button", liBottomNav, 730, 850, 110, 40, true, false, 2, true, false, false, "", "Notifications", "sim_linkedin");
    addElem("Jobs", "button", liBottomNav, 880, 850, 80, 40, true, false, 2, true, false, false, "", "Job search", "sim_linkedin");

    // Snapchat UIA tree - realistic layout with bottom nav (Chat/Camera/Stories/Spotlight/Map)
    std::string snapRoot = addElem("Snapchat", "window", "", 500, 80, 600, 900, true, false, 0, false, false, false, "", "Snapchat window", "sim_snapchat");
    // Top bar (profile/Bitmoji avatar, search)
    std::string snapTopBar = addElem("Top bar", "pane", snapRoot, 500, 80, 600, 50, true, false, 1, false, false, false, "", "Top navigation bar", "sim_snapchat");
    addElem("Profile avatar", "button", snapTopBar, 510, 85, 40, 40, true, false, 2, true, false, false, "", "Open profile (Bitmoji avatar)", "sim_snapchat");
    addElem("Search", "button", snapTopBar, 1000, 85, 50, 40, true, false, 2, true, false, false, "", "Search friends", "sim_snapchat");
    // Chat messages section
    std::string snapChatSection = addElem("Chat section", "pane", snapRoot, 510, 140, 580, 500, true, false, 1, false, false, false, "", "Chat conversations list", "sim_snapchat");
    std::string snapChat1 = addElem("Chat with Alex", "pane", snapChatSection, 510, 150, 580, 80, true, false, 2, false, false, false, "", "Chat conversation", "sim_snapchat");
    addElem("Alex", "text", snapChat1, 530, 155, 60, 20, true, false, 3, false, false, false, "Alex", "Contact name", "sim_snapchat");
    addElem("Hey! Are we still on for the concert tonight?", "text", snapChat1, 530, 180, 540, 30, true, false, 3, false, false, false, "", "Latest message preview", "sim_snapchat");
    addElem("New Snap", "text", snapChat1, 1020, 165, 60, 20, true, false, 3, false, false, false, "", "Unread indicator", "sim_snapchat");
    std::string snapChat2 = addElem("Chat with Sarah", "pane", snapChatSection, 510, 240, 580, 80, true, false, 2, false, false, false, "", "Chat conversation", "sim_snapchat");
    addElem("Sarah", "text", snapChat2, 530, 245, 60, 20, true, false, 3, false, false, false, "Sarah", "Contact name", "sim_snapchat");
    addElem("Yes! I already got the tickets. Meet at 8pm at the venue entrance.", "text", snapChat2, 530, 270, 540, 30, true, false, 3, false, false, false, "", "Latest message preview", "sim_snapchat");
    // Chat input
    std::string snapInput = addElem("Send a chat", "edit", snapRoot, 510, 660, 480, 40, true, true, 1, false, true, false, "", "Type a message", "sim_snapchat");
    addElem("Send", "button", snapRoot, 1000, 660, 60, 40, true, false, 1, true, false, false, "", "Send message", "sim_snapchat");
    // Bottom navigation (Chat, Camera, Stories, Spotlight, Map)
    std::string snapBottomNav = addElem("Bottom navigation", "pane", snapRoot, 500, 720, 600, 60, true, false, 1, false, false, false, "", "Bottom nav bar", "sim_snapchat");
    addElem("Chat", "button", snapBottomNav, 530, 730, 60, 40, true, false, 2, true, false, false, "", "Chat list", "sim_snapchat");
    addElem("Camera", "button", snapBottomNav, 620, 725, 70, 50, true, false, 2, true, false, false, "", "Open camera (capture button)", "sim_snapchat");
    addElem("Stories", "button", snapBottomNav, 720, 730, 80, 40, true, false, 2, true, false, false, "", "Friend Stories", "sim_snapchat");
    addElem("Spotlight", "button", snapBottomNav, 820, 730, 80, 40, true, false, 2, true, false, false, "", "Spotlight (short videos)", "sim_snapchat");
    addElem("Map", "button", snapBottomNav, 920, 730, 60, 40, true, false, 2, true, false, false, "", "Snap Map (friend locations)", "sim_snapchat");
}

// ===== App Enumeration =====

#ifdef _WIN32
struct EnumWindowsData {
    std::vector<AppInfo>* apps;
};

static BOOL CALLBACK EnumWindowsProc(HWND hwnd, LPARAM lParam) {
    EnumWindowsData* data = reinterpret_cast<EnumWindowsData*>(lParam);
    if (!data) return TRUE;

    if (!IsWindowVisible(hwnd)) return TRUE;

    wchar_t title_w[512] = {0};
    GetWindowTextW(hwnd, title_w, 512);
    if (wcslen(title_w) == 0) return TRUE;

    // Convert wide to narrow
    char title[512] = {0};
    WideCharToMultiByte(CP_UTF8, 0, title_w, -1, title, 512, nullptr, nullptr);

    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);

    char process_name[MAX_PATH] = {0};
    HANDLE hProcess = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, pid);
    if (hProcess) {
        GetModuleBaseNameA(hProcess, 0, process_name, MAX_PATH);
        CloseHandle(hProcess);
    }

    RECT rect;
    GetWindowRect(hwnd, &rect);

    HWND hForeground = GetForegroundWindow();
    DWORD fg_pid = 0;
    GetWindowThreadProcessId(hForeground, &fg_pid);

    AppInfo app;
    app.window_id = "win_" + std::to_string(reinterpret_cast<uintptr_t>(hwnd));
    app.title = title;
    app.process_name = process_name;
    app.process_id = static_cast<int>(pid);
    app.x = rect.left;
    app.y = rect.top;
    app.width = rect.right - rect.left;
    app.height = rect.bottom - rect.top;
    app.is_visible = true;
    app.is_focused = (pid == fg_pid);
    app.is_minimized = IsIconic(hwnd) != 0;
    app.app_category = classify_app(app.title, app.process_name);
    app.platform = "windows";

    data->apps->push_back(app);
    return TRUE;
}
#endif

std::vector<AppInfo> list_open_apps() {
    if (g_simulation_mode) {
        return g_sim_apps;
    }

    std::vector<AppInfo> apps;

#ifdef _WIN32
    EnumWindowsData data;
    data.apps = &apps;
    EnumWindows(EnumWindowsProc, reinterpret_cast<LPARAM>(&data));
#elif defined(__APPLE__)
    // macOS: use NSWorkspace
    // Stub for now
#elif defined(__linux__)
    // Linux: use XGetInputFocus / _NET_CLIENT_LIST
    // Stub for now
#endif

    return apps;
}

AppInfo get_active_app() {
    if (g_simulation_mode) {
        for (const auto& app : g_sim_apps) {
            if (app.is_focused) return app;
        }
        if (!g_sim_apps.empty()) return g_sim_apps[0];
        return AppInfo();
    }

    auto apps = list_open_apps();
    for (const auto& app : apps) {
        if (app.is_focused) return app;
    }
    if (!apps.empty()) return apps[0];
    return AppInfo();
}

// ===== Screen Capture =====

ScreenCaptureInfo capture_screen(const std::string& output_path) {
    ScreenCaptureInfo info;

    if (g_simulation_mode) {
        info.success = true;
        info.file_path = output_path.empty() ? "sim_screen_capture.bmp" : output_path;
        info.width = 1920;
        info.height = 1080;
        info.format = "bmp";
        return info;
    }

#ifdef _WIN32
    int width = GetSystemMetrics(SM_CXSCREEN);
    int height = GetSystemMetrics(SM_CYSCREEN);

    HDC hdcScreen = GetDC(nullptr);
    HDC hdcMem = CreateCompatibleDC(hdcScreen);
    HBITMAP hBitmap = CreateCompatibleBitmap(hdcScreen, width, height);
    HBITMAP hOld = static_cast<HBITMAP>(SelectObject(hdcMem, hBitmap));

    BitBlt(hdcMem, 0, 0, width, height, hdcScreen, 0, 0, SRCCOPY);
    SelectObject(hdcMem, hOld);

    std::string path = output_path.empty() ? "screen_capture.bmp" : output_path;

    // Save as BMP
    BITMAPFILEHEADER bmfHeader;
    BITMAPINFOHEADER bi;
    bi.biSize = sizeof(BITMAPINFOHEADER);
    bi.biWidth = width;
    bi.biHeight = height;
    bi.biPlanes = 1;
    bi.biBitCount = 24;
    bi.biCompression = BI_RGB;
    bi.biSizeImage = 0;
    bi.biXPelsPerMeter = 0;
    bi.biYPelsPerMeter = 0;
    bi.biClrUsed = 0;
    bi.biClrImportant = 0;

    DWORD dwBmpSize = ((width * 24 + 31) / 32) * 4 * height;
    char* lpbitmap = new char[dwBmpSize];
    GetDIBits(hdcMem, hBitmap, 0, height, lpbitmap,
              reinterpret_cast<BITMAPINFO*>(&bi), DIB_RGB_COLORS);

    std::ofstream file(path, std::ios::binary);
    if (file.is_open()) {
        bmfHeader.bfOffBits = sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER);
        bmfHeader.bfSize = bmfHeader.bfOffBits + dwBmpSize;
        bmfHeader.bfType = 0x4D42;

        file.write(reinterpret_cast<char*>(&bmfHeader), sizeof(BITMAPFILEHEADER));
        file.write(reinterpret_cast<char*>(&bi), sizeof(BITMAPINFOHEADER));
        file.write(lpbitmap, dwBmpSize);
        file.close();

        info.success = true;
        info.file_path = path;
        info.width = width;
        info.height = height;
        info.format = "bmp";
    } else {
        info.error = "Failed to open output file";
    }

    delete[] lpbitmap;
    DeleteDC(hdcMem);
    ReleaseDC(nullptr, hdcScreen);
    DeleteObject(hBitmap);
#else
    info.error = "Screen capture not implemented on this platform";
#endif

    return info;
}

ScreenCaptureInfo capture_window(const std::string& window_id, const std::string& output_path) {
    ScreenCaptureInfo info;

    if (g_simulation_mode) {
        for (const auto& app : g_sim_apps) {
            if (app.window_id == window_id) {
                info.success = true;
                info.file_path = output_path.empty() ? ("sim_window_" + window_id + ".bmp") : output_path;
                info.width = app.width;
                info.height = app.height;
                info.format = "bmp";
                return info;
            }
        }
        info.error = "Window not found in simulation";
        return info;
    }

#ifdef _WIN32
    // Parse window_id back to HWND
    // window_id format: "win_<ptr>"
    if (window_id.substr(0, 4) == "win_") {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id.substr(4)));

        RECT rect;
        GetWindowRect(hwnd, &rect);
        int width = rect.right - rect.left;
        int height = rect.bottom - rect.top;

        if (width <= 0 || height <= 0) {
            info.error = "Invalid window dimensions";
            return info;
        }

        HDC hdcWindow = GetDC(hwnd);
        HDC hdcMem = CreateCompatibleDC(hdcWindow);
        HBITMAP hBitmap = CreateCompatibleBitmap(hdcWindow, width, height);
        HBITMAP hOld = static_cast<HBITMAP>(SelectObject(hdcMem, hBitmap));

        PrintWindow(hwnd, hdcMem, PW_RENDERFULLCONTENT);
        SelectObject(hdcMem, hOld);

        std::string path = output_path.empty() ? ("window_" + window_id + ".bmp") : output_path;

        BITMAPFILEHEADER bmfHeader;
        BITMAPINFOHEADER bi;
        bi.biSize = sizeof(BITMAPINFOHEADER);
        bi.biWidth = width;
        bi.biHeight = height;
        bi.biPlanes = 1;
        bi.biBitCount = 24;
        bi.biCompression = BI_RGB;
        bi.biSizeImage = 0;

        DWORD dwBmpSize = ((width * 24 + 31) / 32) * 4 * height;
        char* lpbitmap = new char[dwBmpSize];
        GetDIBits(hdcMem, hBitmap, 0, height, lpbitmap,
                  reinterpret_cast<BITMAPINFO*>(&bi), DIB_RGB_COLORS);

        std::ofstream file(path, std::ios::binary);
        if (file.is_open()) {
            bmfHeader.bfOffBits = sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER);
            bmfHeader.bfSize = bmfHeader.bfOffBits + dwBmpSize;
            bmfHeader.bfType = 0x4D42;

            file.write(reinterpret_cast<char*>(&bmfHeader), sizeof(BITMAPFILEHEADER));
            file.write(reinterpret_cast<char*>(&bi), sizeof(BITMAPINFOHEADER));
            file.write(lpbitmap, dwBmpSize);
            file.close();

            info.success = true;
            info.file_path = path;
            info.width = width;
            info.height = height;
            info.format = "bmp";
        } else {
            info.error = "Failed to open output file";
        }

        delete[] lpbitmap;
        DeleteDC(hdcMem);
        ReleaseDC(hwnd, hdcWindow);
        DeleteObject(hBitmap);
    } else {
        info.error = "Invalid window_id format";
    }
#else
    info.error = "Window capture not implemented on this platform";
#endif

    return info;
}

ScreenCaptureInfo capture_region(int x, int y, int width, int height, const std::string& output_path) {
    ScreenCaptureInfo info;

    if (width <= 0 || height <= 0) {
        info.error = "Invalid region dimensions: width and height must be positive";
        return info;
    }

    if (g_simulation_mode) {
        info.success = true;
        info.file_path = output_path.empty() ? "sim_region_capture.bmp" : output_path;
        info.width = width;
        info.height = height;
        info.format = "bmp";
        return info;
    }

#ifdef _WIN32
    HDC hdcScreen = GetDC(nullptr);
    HDC hdcMem = CreateCompatibleDC(hdcScreen);
    HBITMAP hBitmap = CreateCompatibleBitmap(hdcScreen, width, height);
    HBITMAP hOld = static_cast<HBITMAP>(SelectObject(hdcMem, hBitmap));

    BitBlt(hdcMem, 0, 0, width, height, hdcScreen, x, y, SRCCOPY);
    SelectObject(hdcMem, hOld);

    std::string path = output_path.empty() ? "region_capture.bmp" : output_path;

    BITMAPFILEHEADER bmfHeader;
    BITMAPINFOHEADER bi;
    bi.biSize = sizeof(BITMAPINFOHEADER);
    bi.biWidth = width;
    bi.biHeight = height;
    bi.biPlanes = 1;
    bi.biBitCount = 24;
    bi.biCompression = BI_RGB;

    DWORD dwBmpSize = ((width * 24 + 31) / 32) * 4 * height;
    char* lpbitmap = new char[dwBmpSize];
    GetDIBits(hdcMem, hBitmap, 0, height, lpbitmap,
              reinterpret_cast<BITMAPINFO*>(&bi), DIB_RGB_COLORS);

    std::ofstream file(path, std::ios::binary);
    if (file.is_open()) {
        bmfHeader.bfOffBits = sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER);
        bmfHeader.bfSize = bmfHeader.bfOffBits + dwBmpSize;
        bmfHeader.bfType = 0x4D42;

        file.write(reinterpret_cast<char*>(&bmfHeader), sizeof(BITMAPFILEHEADER));
        file.write(reinterpret_cast<char*>(&bi), sizeof(BITMAPINFOHEADER));
        file.write(lpbitmap, dwBmpSize);
        file.close();

        info.success = true;
        info.file_path = path;
        info.width = width;
        info.height = height;
        info.format = "bmp";
    } else {
        info.error = "Failed to open output file";
    }

    delete[] lpbitmap;
    DeleteDC(hdcMem);
    ReleaseDC(nullptr, hdcScreen);
    DeleteObject(hBitmap);
#else
    info.error = "Region capture not implemented on this platform";
#endif

    return info;
}

// ===== Text Extraction =====

OcrResult ocr_screen() {
    OcrResult result;

    if (g_simulation_mode) {
        result.success = true;
        result.full_text = g_sim_screen_text;
        for (const auto& c : g_sim_content) {
            TextRegion region;
            region.text = c.text;
            region.x = c.x;
            region.y = c.y;
            region.width = c.width;
            region.height = c.height;
            region.confidence = 0.95f;
            result.regions.push_back(region);
        }
        return result;
    }

    // On real Windows, we would use Windows.Media.Ocr or Tesseract here
    // For now, we extract text from window titles and UI elements
    auto apps = list_open_apps();
    std::ostringstream oss;
    for (const auto& app : apps) {
        oss << app.title << "\n";
    }
    result.success = true;
    result.full_text = oss.str();
    return result;
}

OcrResult ocr_window(const std::string& window_id) {
    OcrResult result;

    if (g_simulation_mode) {
        // Check if window exists
        bool found = false;
        std::string window_title;
        for (const auto& app : g_sim_apps) {
            if (app.window_id == window_id) {
                found = true;
                window_title = app.title;
                break;
            }
        }
        if (!found) {
            result.error = "Window not found in simulation";
            return result;
        }
        result.success = true;
        // For all sim windows, return matching content blocks as text regions
        bool has_content = false;
        for (const auto& c : g_sim_content) {
            if (c.source == "Facebook" && window_id == "sim_fb") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            } else if (c.source == "X" && window_id == "sim_x") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            } else if (c.source == "Instagram" && window_id == "sim_instagram") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            } else if (c.source == "Threads" && window_id == "sim_threads") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            } else if (c.source == "YouTube" && window_id == "sim_youtube") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            } else if (c.source == "TikTok" && window_id == "sim_tiktok") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            } else if (c.source == "Reddit" && window_id == "sim_reddit") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            } else if (c.source == "LinkedIn" && window_id == "sim_linkedin") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            } else if (c.source == "Snapchat" && window_id == "sim_snapchat") {
                TextRegion region;
                region.text = c.text;
                region.x = c.x; region.y = c.y;
                region.width = c.width; region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
                has_content = true;
            }
        }
        if (!has_content) {
            // For windows without content blocks, return the window title as text
            TextRegion region;
            region.text = window_title;
            region.confidence = 1.0f;
            result.regions.push_back(region);
        }
        std::ostringstream oss;
        for (const auto& r : result.regions) oss << r.text << "\n";
        result.full_text = oss.str();
        return result;
    }

#ifdef _WIN32
    // Extract text from window using GetWindowText and EnumChildWindows
    if (window_id.substr(0, 4) == "win_") {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id.substr(4)));

        wchar_t title[512] = {0};
        GetWindowTextW(hwnd, title, 512);
        char title_narrow[512] = {0};
        WideCharToMultiByte(CP_UTF8, 0, title, -1, title_narrow, 512, nullptr, nullptr);

        result.success = true;
        result.full_text = std::string(title_narrow) + "\n";
        TextRegion region;
        region.text = title_narrow;
        region.confidence = 1.0f;
        result.regions.push_back(region);
        return result;
    }
#endif

    result.error = "Window not found";
    return result;
}

OcrResult ocr_region(int x, int y, int width, int height) {
    OcrResult result;

    if (g_simulation_mode) {
        result.success = true;
        for (const auto& c : g_sim_content) {
            if (c.x >= x && c.x + c.width <= x + width &&
                c.y >= y && c.y + c.height <= y + height) {
                TextRegion region;
                region.text = c.text;
                region.x = c.x;
                region.y = c.y;
                region.width = c.width;
                region.height = c.height;
                region.confidence = 0.95f;
                result.regions.push_back(region);
            }
        }
        std::ostringstream oss;
        for (const auto& r : result.regions) oss << r.text << "\n";
        result.full_text = oss.str();
        return result;
    }

    result.error = "Region OCR requires external OCR engine";
    return result;
}

std::vector<TextRegion> extract_text_from_apps() {
    std::vector<TextRegion> regions;

    if (g_simulation_mode) {
        for (const auto& c : g_sim_content) {
            TextRegion r;
            r.text = c.text;
            r.x = c.x;
            r.y = c.y;
            r.width = c.width;
            r.height = c.height;
            r.confidence = 0.95f;
            regions.push_back(r);
        }
        return regions;
    }

    // Extract text from all open app windows
    auto apps = list_open_apps();
    for (const auto& app : apps) {
        TextRegion r;
        r.text = app.title;
        r.x = app.x;
        r.y = app.y;
        r.width = app.width;
        r.height = app.height;
        r.confidence = 1.0f;
        regions.push_back(r);
    }

    return regions;
}

// ===== Content Analysis =====

std::vector<ContentBlock> extract_content_blocks(const std::string& window_id) {
    std::vector<ContentBlock> blocks;

    if (g_simulation_mode) {
        if (window_id.empty()) {
            return g_sim_content;
        }
        // Check if window exists
        bool found = false;
        AppInfo target_app;
        for (const auto& app : g_sim_apps) {
            if (app.window_id == window_id) {
                found = true;
                target_app = app;
                break;
            }
        }
        if (!found) {
            return blocks;
        }
        // Map window_id to source name for content filtering
        std::string source_name;
        if (window_id == "sim_fb") source_name = "Facebook";
        else if (window_id == "sim_x") source_name = "X";
        else if (window_id == "sim_instagram") source_name = "Instagram";
        else if (window_id == "sim_threads") source_name = "Threads";
        else if (window_id == "sim_youtube") source_name = "YouTube";
        else if (window_id == "sim_tiktok") source_name = "TikTok";
        else if (window_id == "sim_reddit") source_name = "Reddit";
        else if (window_id == "sim_linkedin") source_name = "LinkedIn";
        else if (window_id == "sim_snapchat") source_name = "Snapchat";

        if (!source_name.empty()) {
            for (const auto& c : g_sim_content) {
                if (c.source == source_name) {
                    blocks.push_back(c);
                }
            }
        } else {
            // For other windows, return a single content block with the window title
            ContentBlock block;
            block.type = "window_title";
            block.text = target_app.title;
            block.source = target_app.process_name;
            block.relevance = target_app.is_focused ? 1.0f : 0.3f;
            blocks.push_back(block);
        }
        return blocks;
    }

    // On real platform, would use UI Automation to extract content blocks
    // For now, return window titles as basic content
    auto apps = list_open_apps();
    for (const auto& app : apps) {
        if (!window_id.empty() && app.window_id != window_id) continue;
        ContentBlock block;
        block.type = "window_title";
        block.text = app.title;
        block.source = app.process_name;
        block.relevance = app.is_focused ? 1.0f : 0.3f;
        blocks.push_back(block);
    }

    return blocks;
}

// ===== Context Assessment =====

UserContext get_user_context() {
    UserContext ctx;
    ctx.timestamp = get_timestamp();
    ctx.platform = platform_to_string(get_current_platform());

    if (g_simulation_mode) {
        ctx.active_app = "Facebook - News Feed";
        ctx.active_app_category = "social_media";
        ctx.user_activity = g_sim_activity;
        ctx.visible_content = g_sim_content;
        ctx.open_apps = g_sim_apps;

        // Build assessment
        std::ostringstream assessment;
        assessment << "The user is currently scrolling through their Facebook News Feed. ";
        assessment << "They can see " << g_sim_content.size() << " posts on screen. ";

        int post_count = 0;
        std::string top_post_author;
        std::string top_post_text;
        for (const auto& c : g_sim_content) {
            if (c.type == "post") {
                post_count++;
                if (top_post_author.empty()) {
                    top_post_author = c.author;
                    top_post_text = c.text;
                }
            }
        }

        assessment << "There are " << post_count << " regular posts and 1 sponsored ad. ";
        assessment << "The most recent post is by " << top_post_author << ": \""
                   << top_post_text.substr(0, 80) << "...\". ";
        assessment << "The user also has Chrome (C++ tutorial), VS Code (main.cpp), ";
        assessment << "Spotify (Lo-Fi Beats), and Outlook (3 unread emails) open. ";
        assessment << "The user appears to be casually browsing social media while ";
        assessment << "having coding and email tasks pending.";

        ctx.assessment = assessment.str();

        ctx.suggested_actions.push_back("Ask if the user wants to discuss any of the posts they're viewing");
        ctx.suggested_actions.push_back("Remind user about 3 unread emails in Outlook");
        ctx.suggested_actions.push_back("Offer to help with the C++ code in VS Code");
        ctx.suggested_actions.push_back("Suggest taking a break from social media to focus on coding");

        return ctx;
    }

    // Real platform context
    auto active = get_active_app();
    ctx.active_app = active.title;
    ctx.active_app_category = active.app_category;
    ctx.open_apps = list_open_apps();

    // Determine activity based on app type
    if (active.app_category == "social_media") {
        ctx.user_activity = "browsing social media";
    } else if (active.app_category == "browser") {
        ctx.user_activity = "browsing the web";
    } else if (active.app_category == "ide") {
        ctx.user_activity = "coding";
    } else if (active.app_category == "email") {
        ctx.user_activity = "checking email";
    } else if (active.app_category == "media_player") {
        ctx.user_activity = "watching/listening to media";
    } else if (active.app_category == "terminal") {
        ctx.user_activity = "working in terminal";
    } else if (active.app_category == "file_manager") {
        ctx.user_activity = "managing files";
    } else if (active.app_category == "editor") {
        ctx.user_activity = "reading/editing a document";
    } else {
        ctx.user_activity = "using " + active.process_name;
    }

    ctx.current_focus = active.title;

    // Build assessment
    std::ostringstream assessment;
    assessment << "The user is currently " << ctx.user_activity << " in " << active.title;
    assessment << " (" << active.process_name << "). ";
    assessment << "There are " << ctx.open_apps.size() << " apps open. ";
    if (ctx.open_apps.size() > 1) {
        assessment << "Other open apps: ";
        int count = 0;
        for (const auto& app : ctx.open_apps) {
            if (app.window_id == active.window_id) continue;
            if (count > 0) assessment << ", ";
            assessment << app.title << " (" << app.app_category << ")";
            count++;
            if (count >= 5) { assessment << ", ..."; break; }
        }
        assessment << ".";
    }
    ctx.assessment = assessment.str();

    // Suggest actions
    if (active.app_category == "social_media") {
        ctx.suggested_actions.push_back("Ask if the user wants to discuss content they're viewing");
        ctx.suggested_actions.push_back("Check if user has pending work tasks");
    } else if (active.app_category == "ide") {
        ctx.suggested_actions.push_back("Offer to help with the code the user is working on");
        ctx.suggested_actions.push_back("Suggest running tests or building the project");
    } else if (active.app_category == "email") {
        ctx.suggested_actions.push_back("Offer to help draft email responses");
        ctx.suggested_actions.push_back("Summarize unread emails");
    } else if (active.app_category == "browser") {
        ctx.suggested_actions.push_back("Ask what the user is researching");
        ctx.suggested_actions.push_back("Offer to help find information");
    }

    return ctx;
}

UserContext assess_user_situation() {
    return get_user_context();
}

// ===== Content Search =====

std::vector<ContentSearchResult> search_content(const std::string& query, const std::string& window_id) {
    std::vector<ContentSearchResult> results;

    if (query.empty()) {
        return results;
    }

    auto blocks = extract_content_blocks(window_id);
    std::string lower_query = to_lower(query);

    for (const auto& block : blocks) {
        std::string lower_text = to_lower(block.text);
        size_t pos = lower_text.find(lower_query);
        if (pos != std::string::npos) {
            ContentSearchResult result;
            result.block = block;
            result.match_position = static_cast<int>(pos);
            result.score = 1.0f;

            // Build match context (50 chars before and after)
            int ctx_start = static_cast<int>(pos) > 50 ? static_cast<int>(pos) - 50 : 0;
            int ctx_end = static_cast<int>(pos) + static_cast<int>(query.size()) + 50;
            if (ctx_end > static_cast<int>(block.text.size())) ctx_end = static_cast<int>(block.text.size());
            result.match_context = block.text.substr(ctx_start, ctx_end - ctx_start);

            results.push_back(result);
        } else {
            // Try fuzzy match - check if query words appear in text
            std::istringstream iss(block.text);
            std::string word;
            while (iss >> word) {
                if (to_lower(word).find(lower_query) != std::string::npos ||
                    lower_query.find(to_lower(word)) != std::string::npos) {
                    ContentSearchResult result;
                    result.block = block;
                    result.match_position = 0;
                    result.score = 0.7f;
                    result.match_context = block.text.substr(0, (std::min)(block.text.size(), static_cast<size_t>(100)));
                    results.push_back(result);
                    break;
                }
            }
        }
    }

    // Sort by score descending
    std::sort(results.begin(), results.end(),
              [](const ContentSearchResult& a, const ContentSearchResult& b) {
                  return a.score > b.score;
              });

    return results;
}

// ===== App Summary =====

AppSummary get_app_summary() {
    AppSummary summary;
    summary.platform = platform_to_string(get_current_platform());

    auto apps = list_open_apps();
    summary.total_apps = static_cast<int>(apps.size());

    for (const auto& app : apps) {
        summary.apps_by_category[app.app_category]++;
        if (app.is_focused) {
            summary.focused_app_count++;
            summary.active_app_category = app.app_category;
        }
        if (app.is_minimized) {
            summary.minimized_app_count++;
        }
    }

    return summary;
}

// ===== Screen Content Snapshot =====

ScreenContent get_screen_content() {
    ScreenContent content;
    content.timestamp = get_timestamp();
    content.platform = platform_to_string(get_current_platform());

    content.open_apps = list_open_apps();
    content.visible_text = extract_text_from_apps();

    auto active = get_active_app();
    content.active_window_id = active.window_id;
    content.active_window_title = active.title;
    content.active_process = active.process_name;

    if (g_simulation_mode) {
        content.screen_width = 1920;
        content.screen_height = 1080;
    }
#ifdef _WIN32
    else {
        content.screen_width = GetSystemMetrics(SM_CXSCREEN);
        content.screen_height = GetSystemMetrics(SM_CYSCREEN);
    }
#endif

    return content;
}

// ===== UI Automation (UIA) Integration =====

// Helper: convert wide string to UTF-8
static std::string wide_to_utf8(const wchar_t* wstr) {
    if (!wstr || !*wstr) return "";
    int len = WideCharToMultiByte(CP_UTF8, 0, wstr, -1, nullptr, 0, nullptr, nullptr);
    if (len <= 0) return "";
    std::string result(len - 1, '\0');
    WideCharToMultiByte(CP_UTF8, 0, wstr, -1, &result[0], len, nullptr, nullptr);
    return result;
}

// Helper: convert UIA control type int to string
static std::string uia_control_type_to_string(int controlTypeId) {
    switch (controlTypeId) {
        case 50000: return "button";
        case 50001: return "calendar";
        case 50002: return "checkbox";
        case 50003: return "combobox";
        case 50004: return "edit";
        case 50005: return "hyperlink";
        case 50006: return "image";
        case 50007: return "listitem";
        case 50008: return "list";
        case 50009: return "menu";
        case 50010: return "menubar";
        case 50011: return "menuitem";
        case 50012: return "pane";
        case 50013: return "progressbar";
        case 50014: return "radio";
        case 50015: return "scrollbar";
        case 50016: return "slider";
        case 50017: return "spinner";
        case 50018: return "statusbar";
        case 50019: return "tab";
        case 50020: return "tabitem";
        case 50021: return "text";
        case 50022: return "toolbar";
        case 50023: return "tooltip";
        case 50024: return "tree";
        case 50025: return "treeitem";
        case 50026: return "window";
        case 50027: return "custom";
        case 50028: return "group";
        case 50029: return "thumb";
        case 50030: return "datarow";
        case 50031: return "dataitem";
        case 50032: return "document";
        case 50033: return "splitbutton";
        case 50034: return "appbar";
        default: return "unknown";
    }
}

#ifdef _WIN32
struct UiaWalkerData {
    std::vector<UiaElementInfo>* elements;
    IUIAutomation* pAutomation;
    int depth;
    std::string parentId;
    int elementCounter;
};

static void walk_uia_element(IUIAutomationElement* pElement, UiaWalkerData& data) {
    if (!pElement || data.depth > 50) return;

    UiaElementInfo info;
    info.element_id = "uia_" + std::to_string(data.elementCounter++);
    info.depth = data.depth;
    info.parent_id = data.parentId;

    // Get name
    BSTR nameBstr = nullptr;
    pElement->get_CurrentName(&nameBstr);
    if (nameBstr) { info.name = wide_to_utf8(nameBstr); SysFreeString(nameBstr); }

    // Get control type
    CONTROLTYPEID controlTypeId = 0;
    pElement->get_CurrentControlType(&controlTypeId);
    info.control_type = uia_control_type_to_string(controlTypeId);

    // Get localized control type
    BSTR locTypeBstr = nullptr;
    pElement->get_CurrentLocalizedControlType(&locTypeBstr);
    if (locTypeBstr) { info.localized_control_type = wide_to_utf8(locTypeBstr); SysFreeString(locTypeBstr); }

    // Get automation ID
    BSTR autoIdBstr = nullptr;
    pElement->get_CurrentAutomationId(&autoIdBstr);
    if (autoIdBstr) { info.automation_id = wide_to_utf8(autoIdBstr); SysFreeString(autoIdBstr); }

    // Get class name
    BSTR classBstr = nullptr;
    pElement->get_CurrentClassName(&classBstr);
    if (classBstr) { info.class_name = wide_to_utf8(classBstr); SysFreeString(classBstr); }

    // Get bounding rectangle
    RECT rect;
    pElement->get_CurrentBoundingRectangle(&rect);
    info.x = rect.left;
    info.y = rect.top;
    info.width = rect.right - rect.left;
    info.height = rect.bottom - rect.top;

    // Get enabled state
    BOOL isEnabled = TRUE;
    pElement->get_CurrentIsEnabled(&isEnabled);
    info.is_enabled = (isEnabled != FALSE);

    // Get offscreen state
    BOOL isOffscreen = FALSE;
    pElement->get_CurrentIsOffscreen(&isOffscreen);
    info.is_offscreen = (isOffscreen != FALSE);
    info.is_visible = !info.is_offscreen;

    // Get keyboard focus
    BOOL hasFocus = FALSE;
    pElement->get_CurrentHasKeyboardFocus(&hasFocus);
    info.is_focused = (hasFocus != FALSE);

    // Get keyboard focusable
    BOOL canFocus = FALSE;
    pElement->get_CurrentIsKeyboardFocusable(&canFocus);
    info.is_keyboard_focusable = (canFocus != FALSE);

    // Get process ID
    int procId = 0;
    pElement->get_CurrentProcessId(&procId);
    info.process_id = procId;

    // Get help text
    BSTR helpBstr = nullptr;
    pElement->get_CurrentHelpText(&helpBstr);
    if (helpBstr) { info.help_text = wide_to_utf8(helpBstr); SysFreeString(helpBstr); }

    // Check patterns
    IUIAutomationInvokePattern* pInvoke = nullptr;
    pElement->GetCurrentPatternAs(UIA_InvokePatternId, IID_PPV_ARGS(&pInvoke));
    if (pInvoke) { info.has_invoke_pattern = true; pInvoke->Release(); }

    IUIAutomationValuePattern* pValue = nullptr;
    pElement->GetCurrentPatternAs(UIA_ValuePatternId, IID_PPV_ARGS(&pValue));
    if (pValue) {
        info.has_value_pattern = true;
        BSTR valBstr = nullptr;
        pValue->get_CurrentValue(&valBstr);
        if (valBstr) { info.value = wide_to_utf8(valBstr); SysFreeString(valBstr); }
        pValue->Release();
    }

    IUIAutomationTogglePattern* pToggle = nullptr;
    pElement->GetCurrentPatternAs(UIA_TogglePatternId, IID_PPV_ARGS(&pToggle));
    if (pToggle) { info.has_toggle_pattern = true; pToggle->Release(); }

    IUIAutomationSelectionPattern* pSelection = nullptr;
    pElement->GetCurrentPatternAs(UIA_SelectionPatternId, IID_PPV_ARGS(&pSelection));
    if (pSelection) { info.has_selection_pattern = true; pSelection->Release(); }

    IUIAutomationScrollPattern* pScroll = nullptr;
    pElement->GetCurrentPatternAs(UIA_ScrollPatternId, IID_PPV_ARGS(&pScroll));
    if (pScroll) { info.has_scroll_pattern = true; pScroll->Release(); }

    data.elements->push_back(info);

    // Recurse children
    IUIAutomationTreeWalker* pWalker = nullptr;
    data.pAutomation->get_RawViewWalker(&pWalker);
    if (!pWalker) return;

    IUIAutomationElement* pChild = nullptr;
    pWalker->GetFirstChildElement(pElement, &pChild);
    while (pChild) {
        UiaWalkerData childData = data;
        childData.depth = data.depth + 1;
        childData.parentId = info.element_id;
        childData.elementCounter = data.elementCounter;
        walk_uia_element(pChild, childData);
        data.elementCounter = childData.elementCounter;

        IUIAutomationElement* pNext = nullptr;
        pWalker->GetNextSiblingElement(pChild, &pNext);
        pChild->Release();
        pChild = pNext;
    }
    pWalker->Release();
}
#endif

UiaTreeResult get_uia_tree(const std::string& window_id) {
    UiaTreeResult result;

    if (g_simulation_mode) {
        result.success = true;
        for (const auto& e : g_sim_uia_elements) {
            if (window_id.empty()) {
                result.elements.push_back(e);
            } else {
                // Find the root element for this window and include its subtree
                // Check if this element belongs to the specified window
                // We stored window_id implicitly via process_id mapping
                bool belongs = false;
                if (window_id == "sim_fb" && e.process_id == 2001) belongs = true;
                else if (window_id == "sim_chrome" && e.process_id == 2002) belongs = true;
                else if (window_id == "sim_vscode" && e.process_id == 2003) belongs = true;
                else if (window_id == "sim_spotify" && e.process_id == 2004) belongs = true;
                else if (window_id == "sim_outlook" && e.process_id == 2005) belongs = true;
                // Fix: all sim elements have process_id 2001 (Facebook) due to lambda capture
                // Actually the lambda always sets process_id = 2001. We need a different mapping.
                // Let's use the parent chain to determine window membership
                if (belongs) result.elements.push_back(e);
            }
        }

        if (window_id.empty()) {
            // All elements
            result.total_elements = static_cast<int>(result.elements.size());
        } else {
            // Filter by window - use name matching since process_id is always 2001
            result.elements.clear();
            std::string winTitle;
            for (const auto& app : g_sim_apps) {
                if (app.window_id == window_id) { winTitle = app.title; break; }
            }
            // Find root element matching window_id via automation_id, then include all descendants
            std::string rootId;
            for (const auto& e : g_sim_uia_elements) {
                if (e.depth == 0 && e.automation_id == window_id) {
                    rootId = e.element_id;
                    result.root_element_id = rootId;
                    result.elements.push_back(e);
                    break;
                }
            }
            if (!rootId.empty()) {
                // BFS to find all descendants
                std::vector<std::string> toProcess = {rootId};
                while (!toProcess.empty()) {
                    std::string parentId = toProcess.back();
                    toProcess.pop_back();
                    for (const auto& e : g_sim_uia_elements) {
                        if (e.parent_id == parentId) {
                            result.elements.push_back(e);
                            toProcess.push_back(e.element_id);
                        }
                    }
                }
            }
            result.total_elements = static_cast<int>(result.elements.size());
        }

        // Calculate max depth
        for (const auto& e : result.elements) {
            if (e.depth > result.max_depth) result.max_depth = e.depth;
        }
        return result;
    }

#ifdef _WIN32
    // Real Windows UIA implementation
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    bool needCoUninit = SUCCEEDED(hr);

    IUIAutomation* pAutomation = nullptr;
    hr = CoCreateInstance(__uuidof(CUIAutomation8), nullptr, CLSCTX_INPROC_SERVER,
                          IID_PPV_ARGS(&pAutomation));
    if (FAILED(hr) || !pAutomation) {
        if (needCoUninit) CoUninitialize();
        result.error = "Failed to initialize UI Automation";
        return result;
    }

    IUIAutomationElement* pRoot = nullptr;
    if (window_id.empty()) {
        // Get desktop root
        pAutomation->GetRootElement(&pRoot);
    } else if (window_id.substr(0, 4) == "win_") {
        // Get element from HWND
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id.substr(4)));
        pAutomation->ElementFromHandle(hwnd, &pRoot);
    }

    if (!pRoot) {
        if (pAutomation) pAutomation->Release();
        if (needCoUninit) CoUninitialize();
        result.error = "Failed to get root element";
        return result;
    }

    UiaWalkerData walkerData;
    walkerData.elements = &result.elements;
    walkerData.pAutomation = pAutomation;
    walkerData.depth = 0;
    walkerData.parentId = "";
    walkerData.elementCounter = 0;

    walk_uia_element(pRoot, walkerData);

    result.success = true;
    result.total_elements = static_cast<int>(result.elements.size());
    for (const auto& e : result.elements) {
        if (e.depth > result.max_depth) result.max_depth = e.depth;
    }
    if (!result.elements.empty()) {
        result.root_element_id = result.elements[0].element_id;
    }

    pRoot->Release();
    pAutomation->Release();
    if (needCoUninit) CoUninitialize();
    return result;
#else
    result.error = "UIA not supported on this platform";
    return result;
#endif
}

std::vector<UiaElementInfo> get_uia_elements(const std::string& window_id) {
    auto tree = get_uia_tree(window_id);
    return tree.elements;
}

ElementStateInfo get_element_state(const std::string& element_id) {
    ElementStateInfo state;

    if (element_id.empty()) {
        state.error = "Empty element ID";
        return state;
    }

    if (g_simulation_mode) {
        for (const auto& e : g_sim_uia_elements) {
            if (e.element_id == element_id) {
                state.element_id = e.element_id;
                state.name = e.name;
                state.control_type = e.control_type;
                state.is_enabled = e.is_enabled;
                state.is_visible = e.is_visible;
                state.is_focused = e.is_focused;
                state.is_offscreen = e.is_offscreen;
                state.is_keyboard_focusable = e.is_keyboard_focusable;
                state.value = e.value;
                // Derive toggle/selection/expand states from control type and patterns
                if (e.has_toggle_pattern) {
                    state.toggle_state = e.control_type == "checkbox" ? "on" : "off";
                }
                state.expand_collapse_state = "leaf";
                return state;
            }
        }
        state.error = "Element not found in simulation";
        return state;
    }

#ifdef _WIN32
    // On real Windows, we'd need to find the element by ID and query its state
    // For now, search through the UIA tree
    auto tree = get_uia_tree();
    for (const auto& e : tree.elements) {
        if (e.element_id == element_id) {
            state.element_id = e.element_id;
            state.name = e.name;
            state.control_type = e.control_type;
            state.is_enabled = e.is_enabled;
            state.is_visible = e.is_visible;
            state.is_focused = e.is_focused;
            state.is_offscreen = e.is_offscreen;
            state.is_keyboard_focusable = e.is_keyboard_focusable;
            state.value = e.value;
            return state;
        }
    }
    state.error = "Element not found";
    return state;
#else
    state.error = "UIA not supported on this platform";
    return state;
#endif
}

std::vector<InteractiveElement> get_interactive_elements(const std::string& window_id) {
    std::vector<InteractiveElement> result;

    auto elements = get_uia_elements(window_id);

    for (const auto& e : elements) {
        if (!e.is_enabled || e.is_offscreen) continue;

        // Check if element is interactive (has invoke, value, toggle, or selection pattern)
        if (!e.has_invoke_pattern && !e.has_value_pattern &&
            !e.has_toggle_pattern && !e.has_selection_pattern &&
            e.control_type != "hyperlink" && e.control_type != "listitem" &&
            e.control_type != "treeitem" && e.control_type != "tabitem" &&
            e.control_type != "menuitem") {
            continue;
        }

        InteractiveElement interactive;
        interactive.element_id = e.element_id;
        interactive.name = e.name;
        interactive.control_type = e.control_type;
        interactive.x = e.x;
        interactive.y = e.y;
        interactive.width = e.width;
        interactive.height = e.height;
        interactive.is_enabled = e.is_enabled;
        interactive.value = e.value;
        interactive.help_text = e.help_text;

        // Determine action type
        if (e.has_invoke_pattern || e.control_type == "button" ||
            e.control_type == "hyperlink" || e.control_type == "menuitem") {
            interactive.action_type = "click";
        } else if (e.has_value_pattern || e.control_type == "edit") {
            interactive.action_type = "type";
        } else if (e.has_toggle_pattern || e.control_type == "checkbox") {
            interactive.action_type = "toggle";
        } else if (e.has_selection_pattern || e.control_type == "listitem" ||
                   e.control_type == "treeitem" || e.control_type == "tabitem") {
            interactive.action_type = "select";
        } else if (e.has_scroll_pattern || e.control_type == "slider") {
            interactive.action_type = "scroll";
        } else {
            interactive.action_type = "click";
        }

        result.push_back(interactive);
    }

    return result;
}

ActionVerifyResult verify_action(const std::string& element_id, const std::string& action) {
    ActionVerifyResult result;

    if (element_id.empty()) {
        result.error = "Empty element ID";
        return result;
    }

    // Get before state
    auto beforeState = get_element_state(element_id);
    if (!beforeState.error.empty()) {
        result.error = beforeState.error;
        return result;
    }

    result.before_state = beforeState.value;
    result.success = beforeState.is_enabled;

    // In simulation mode, we simulate the action by checking if the element
    // is enabled and the action is valid for its type
    if (g_simulation_mode) {
        if (action == "click" || action == "invoke") {
            result.state_changed = beforeState.is_enabled;
            result.after_state = beforeState.value;
        } else if (action == "type") {
            result.state_changed = beforeState.is_enabled;
            result.after_state = beforeState.value;
        } else if (action == "toggle") {
            result.state_changed = beforeState.is_enabled;
            result.after_state = beforeState.toggle_state == "on" ? "off" : "on";
        } else if (action == "select") {
            result.state_changed = beforeState.is_enabled;
            result.after_state = "selected";
        } else {
            result.error = "Unknown action: " + action;
            return result;
        }

        // Check if element is disabled
        if (!beforeState.is_enabled) {
            result.error = "Element is disabled";
            result.success = false;
        }
    } else {
        // On real Windows, we would perform the action and compare states
        result.after_state = beforeState.value;
        result.state_changed = false;
    }

    return result;
}

std::vector<UiaElementInfo> find_elements_by_type(const std::string& control_type, const std::string& window_id) {
    std::vector<UiaElementInfo> result;
    auto elements = get_uia_elements(window_id);
    std::string lower_type = to_lower(control_type);

    for (const auto& e : elements) {
        if (to_lower(e.control_type) == lower_type) {
            result.push_back(e);
        }
    }
    return result;
}

std::vector<UiaElementInfo> find_elements_by_name(const std::string& name, const std::string& window_id) {
    std::vector<UiaElementInfo> result;
    auto elements = get_uia_elements(window_id);
    std::string lower_name = to_lower(name);

    for (const auto& e : elements) {
        if (to_lower(e.name).find(lower_name) != std::string::npos) {
            result.push_back(e);
        }
    }
    return result;
}

std::vector<UiaElementInfo> get_focused_element_chain(const std::string& window_id) {
    std::vector<UiaElementInfo> result;
    auto elements = get_uia_elements(window_id);

    // Find the focused element
    std::string focusedId;
    for (const auto& e : elements) {
        if (e.is_focused) {
            focusedId = e.element_id;
            result.push_back(e);
            break;
        }
    }

    if (focusedId.empty()) return result;

    // Walk up the parent chain
    std::string currentParent = result.back().parent_id;
    while (!currentParent.empty()) {
        for (const auto& e : elements) {
            if (e.element_id == currentParent) {
                result.push_back(e);
                currentParent = e.parent_id;
                break;
            }
        }
    }

    // Reverse to get root-first order
    std::reverse(result.begin(), result.end());
    return result;
}

// ===== UIA JSON Serialization =====

std::string uia_element_to_json(const UiaElementInfo& elem) {
    std::ostringstream j;
    j << "{";
    j << "\"element_id\":\"" << json_escape(elem.element_id) << "\",";
    j << "\"name\":\"" << json_escape(elem.name) << "\",";
    j << "\"control_type\":\"" << json_escape(elem.control_type) << "\",";
    j << "\"localized_control_type\":\"" << json_escape(elem.localized_control_type) << "\",";
    j << "\"automation_id\":\"" << json_escape(elem.automation_id) << "\",";
    j << "\"class_name\":\"" << json_escape(elem.class_name) << "\",";
    j << "\"bounds\":{\"x\":" << elem.x << ",\"y\":" << elem.y
      << ",\"width\":" << elem.width << ",\"height\":" << elem.height << "},";
    j << "\"is_enabled\":" << (elem.is_enabled ? "true" : "false") << ",";
    j << "\"is_visible\":" << (elem.is_visible ? "true" : "false") << ",";
    j << "\"is_focused\":" << (elem.is_focused ? "true" : "false") << ",";
    j << "\"is_offscreen\":" << (elem.is_offscreen ? "true" : "false") << ",";
    j << "\"is_keyboard_focusable\":" << (elem.is_keyboard_focusable ? "true" : "false") << ",";
    j << "\"has_invoke_pattern\":" << (elem.has_invoke_pattern ? "true" : "false") << ",";
    j << "\"has_value_pattern\":" << (elem.has_value_pattern ? "true" : "false") << ",";
    j << "\"has_toggle_pattern\":" << (elem.has_toggle_pattern ? "true" : "false") << ",";
    j << "\"has_selection_pattern\":" << (elem.has_selection_pattern ? "true" : "false") << ",";
    j << "\"has_scroll_pattern\":" << (elem.has_scroll_pattern ? "true" : "false") << ",";
    j << "\"value\":\"" << json_escape(elem.value) << "\",";
    j << "\"help_text\":\"" << json_escape(elem.help_text) << "\",";
    j << "\"process_id\":" << elem.process_id << ",";
    j << "\"parent_id\":\"" << json_escape(elem.parent_id) << "\",";
    j << "\"depth\":" << elem.depth;
    j << "}";
    return j.str();
}

std::string uia_tree_to_json(const UiaTreeResult& tree) {
    std::ostringstream j;
    j << "{";
    j << "\"success\":" << (tree.success ? "true" : "false") << ",";
    j << "\"root_element_id\":\"" << json_escape(tree.root_element_id) << "\",";
    j << "\"total_elements\":" << tree.total_elements << ",";
    j << "\"max_depth\":" << tree.max_depth << ",";
    j << "\"elements\":[";
    for (size_t i = 0; i < tree.elements.size(); i++) {
        if (i > 0) j << ",";
        j << uia_element_to_json(tree.elements[i]);
    }
    j << "],";
    j << "\"error\":\"" << json_escape(tree.error) << "\"";
    j << "}";
    return j.str();
}

std::string element_state_to_json(const ElementStateInfo& state) {
    std::ostringstream j;
    j << "{";
    j << "\"element_id\":\"" << json_escape(state.element_id) << "\",";
    j << "\"name\":\"" << json_escape(state.name) << "\",";
    j << "\"control_type\":\"" << json_escape(state.control_type) << "\",";
    j << "\"is_enabled\":" << (state.is_enabled ? "true" : "false") << ",";
    j << "\"is_visible\":" << (state.is_visible ? "true" : "false") << ",";
    j << "\"is_focused\":" << (state.is_focused ? "true" : "false") << ",";
    j << "\"is_offscreen\":" << (state.is_offscreen ? "true" : "false") << ",";
    j << "\"is_keyboard_focusable\":" << (state.is_keyboard_focusable ? "true" : "false") << ",";
    j << "\"value\":\"" << json_escape(state.value) << "\",";
    j << "\"toggle_state\":\"" << json_escape(state.toggle_state) << "\",";
    j << "\"selection_state\":\"" << json_escape(state.selection_state) << "\",";
    j << "\"expand_collapse_state\":\"" << json_escape(state.expand_collapse_state) << "\",";
    j << "\"error\":\"" << json_escape(state.error) << "\"";
    j << "}";
    return j.str();
}

std::string interactive_elements_to_json(const std::vector<InteractiveElement>& elements) {
    std::ostringstream j;
    j << "{\"total_elements\":" << elements.size() << ",\"elements\":[";
    for (size_t i = 0; i < elements.size(); i++) {
        if (i > 0) j << ",";
        j << "{";
        j << "\"element_id\":\"" << json_escape(elements[i].element_id) << "\",";
        j << "\"name\":\"" << json_escape(elements[i].name) << "\",";
        j << "\"control_type\":\"" << json_escape(elements[i].control_type) << "\",";
        j << "\"bounds\":{\"x\":" << elements[i].x << ",\"y\":" << elements[i].y
          << ",\"width\":" << elements[i].width << ",\"height\":" << elements[i].height << "},";
        j << "\"is_enabled\":" << (elements[i].is_enabled ? "true" : "false") << ",";
        j << "\"action_type\":\"" << json_escape(elements[i].action_type) << "\",";
        j << "\"value\":\"" << json_escape(elements[i].value) << "\",";
        j << "\"help_text\":\"" << json_escape(elements[i].help_text) << "\"";
        j << "}";
    }
    j << "]}";
    return j.str();
}

std::string action_verify_to_json(const ActionVerifyResult& result) {
    std::ostringstream j;
    j << "{";
    j << "\"success\":" << (result.success ? "true" : "false") << ",";
    j << "\"state_changed\":" << (result.state_changed ? "true" : "false") << ",";
    j << "\"before_state\":\"" << json_escape(result.before_state) << "\",";
    j << "\"after_state\":\"" << json_escape(result.after_state) << "\",";
    j << "\"error\":\"" << json_escape(result.error) << "\"";
    j << "}";
    return j.str();
}

// ===== JSON Serialization =====

std::string app_info_to_json(const AppInfo& app) {
    std::ostringstream j;
    j << "{";
    j << "\"window_id\":\"" << json_escape(app.window_id) << "\",";
    j << "\"title\":\"" << json_escape(app.title) << "\",";
    j << "\"process_name\":\"" << json_escape(app.process_name) << "\",";
    j << "\"process_id\":" << app.process_id << ",";
    j << "\"bounds\":{\"x\":" << app.x << ",\"y\":" << app.y
      << ",\"width\":" << app.width << ",\"height\":" << app.height << "},";
    j << "\"is_visible\":" << (app.is_visible ? "true" : "false") << ",";
    j << "\"is_focused\":" << (app.is_focused ? "true" : "false") << ",";
    j << "\"is_minimized\":" << (app.is_minimized ? "true" : "false") << ",";
    j << "\"app_category\":\"" << json_escape(app.app_category) << "\",";
    j << "\"platform\":\"" << json_escape(app.platform) << "\"";
    j << "}";
    return j.str();
}

std::string apps_to_json(const std::vector<AppInfo>& apps) {
    std::ostringstream j;
    j << "{\"total_apps\":" << apps.size() << ",\"apps\":[";
    for (size_t i = 0; i < apps.size(); i++) {
        if (i > 0) j << ",";
        j << app_info_to_json(apps[i]);
    }
    j << "]}";
    return j.str();
}

std::string screen_content_to_json(const ScreenContent& content) {
    std::ostringstream j;
    j << "{";
    j << "\"timestamp\":\"" << json_escape(content.timestamp) << "\",";
    j << "\"active_window_id\":\"" << json_escape(content.active_window_id) << "\",";
    j << "\"active_window_title\":\"" << json_escape(content.active_window_title) << "\",";
    j << "\"active_process\":\"" << json_escape(content.active_process) << "\",";
    j << "\"screen_width\":" << content.screen_width << ",";
    j << "\"screen_height\":" << content.screen_height << ",";
    j << "\"platform\":\"" << json_escape(content.platform) << "\",";
    j << "\"open_apps\":" << apps_to_json(content.open_apps) << ",";
    j << "\"visible_text\":" << text_regions_to_json(content.visible_text) << ",";
    j << "\"screen_image_path\":\"" << json_escape(content.screen_image_path) << "\"";
    j << "}";
    return j.str();
}

std::string content_block_to_json(const ContentBlock& block) {
    std::ostringstream j;
    j << "{";
    j << "\"type\":\"" << json_escape(block.type) << "\",";
    j << "\"text\":\"" << json_escape(block.text) << "\",";
    j << "\"source\":\"" << json_escape(block.source) << "\",";
    j << "\"author\":\"" << json_escape(block.author) << "\",";
    j << "\"timestamp\":\"" << json_escape(block.timestamp) << "\",";
    j << "\"bounds\":{\"x\":" << block.x << ",\"y\":" << block.y
      << ",\"width\":" << block.width << ",\"height\":" << block.height << "},";
    j << "\"relevance\":" << block.relevance;
    j << "}";
    return j.str();
}

std::string content_blocks_to_json(const std::vector<ContentBlock>& blocks) {
    std::ostringstream j;
    j << "{\"total_blocks\":" << blocks.size() << ",\"blocks\":[";
    for (size_t i = 0; i < blocks.size(); i++) {
        if (i > 0) j << ",";
        j << content_block_to_json(blocks[i]);
    }
    j << "]}";
    return j.str();
}

std::string user_context_to_json(const UserContext& ctx) {
    std::ostringstream j;
    j << "{";
    j << "\"timestamp\":\"" << json_escape(ctx.timestamp) << "\",";
    j << "\"active_app\":\"" << json_escape(ctx.active_app) << "\",";
    j << "\"active_app_category\":\"" << json_escape(ctx.active_app_category) << "\",";
    j << "\"user_activity\":\"" << json_escape(ctx.user_activity) << "\",";
    j << "\"current_focus\":\"" << json_escape(ctx.current_focus) << "\",";
    j << "\"platform\":\"" << json_escape(ctx.platform) << "\",";
    j << "\"visible_content\":" << content_blocks_to_json(ctx.visible_content) << ",";
    j << "\"open_apps\":" << apps_to_json(ctx.open_apps) << ",";
    j << "\"assessment\":\"" << json_escape(ctx.assessment) << "\",";
    j << "\"suggested_actions\":[";
    for (size_t i = 0; i < ctx.suggested_actions.size(); i++) {
        if (i > 0) j << ",";
        j << "\"" << json_escape(ctx.suggested_actions[i]) << "\"";
    }
    j << "]}";
    return j.str();
}

std::string screen_capture_to_json(const ScreenCaptureInfo& info) {
    std::ostringstream j;
    j << "{";
    j << "\"success\":" << (info.success ? "true" : "false") << ",";
    j << "\"file_path\":\"" << json_escape(info.file_path) << "\",";
    j << "\"width\":" << info.width << ",";
    j << "\"height\":" << info.height << ",";
    j << "\"format\":\"" << json_escape(info.format) << "\",";
    j << "\"error\":\"" << json_escape(info.error) << "\"";
    j << "}";
    return j.str();
}

std::string ocr_result_to_json(const OcrResult& result) {
    std::ostringstream j;
    j << "{";
    j << "\"success\":" << (result.success ? "true" : "false") << ",";
    j << "\"full_text\":\"" << json_escape(result.full_text) << "\",";
    j << "\"regions\":" << text_regions_to_json(result.regions) << ",";
    j << "\"error\":\"" << json_escape(result.error) << "\"";
    j << "}";
    return j.str();
}

std::string text_regions_to_json(const std::vector<TextRegion>& regions) {
    std::ostringstream j;
    j << "{\"total_regions\":" << regions.size() << ",\"regions\":[";
    for (size_t i = 0; i < regions.size(); i++) {
        if (i > 0) j << ",";
        j << "{\"text\":\"" << json_escape(regions[i].text) << "\",";
        j << "\"x\":" << regions[i].x << ",\"y\":" << regions[i].y
          << ",\"width\":" << regions[i].width << ",\"height\":" << regions[i].height
          << ",\"confidence\":" << regions[i].confidence << "}";
    }
    j << "]}";
    return j.str();
}

std::string content_search_results_to_json(const std::vector<ContentSearchResult>& results) {
    std::ostringstream j;
    j << "{\"total_results\":" << results.size() << ",\"results\":[";
    for (size_t i = 0; i < results.size(); i++) {
        if (i > 0) j << ",";
        j << "{\"block\":" << content_block_to_json(results[i].block) << ",";
        j << "\"match_context\":\"" << json_escape(results[i].match_context) << "\",";
        j << "\"match_position\":" << results[i].match_position << ",";
        j << "\"score\":" << results[i].score << "}";
    }
    j << "]}";
    return j.str();
}

std::string app_summary_to_json(const AppSummary& summary) {
    std::ostringstream j;
    j << "{";
    j << "\"total_apps\":" << summary.total_apps << ",";
    j << "\"apps_by_category\":{";
    bool first = true;
    for (const auto& pair : summary.apps_by_category) {
        if (!first) j << ",";
        j << "\"" << json_escape(pair.first) << "\":" << pair.second;
        first = false;
    }
    j << "},";
    j << "\"active_app_category\":\"" << json_escape(summary.active_app_category) << "\",";
    j << "\"focused_app_count\":" << summary.focused_app_count << ",";
    j << "\"minimized_app_count\":" << summary.minimized_app_count << ",";
    j << "\"platform\":\"" << json_escape(summary.platform) << "\"";
    j << "}";
    return j.str();
}
