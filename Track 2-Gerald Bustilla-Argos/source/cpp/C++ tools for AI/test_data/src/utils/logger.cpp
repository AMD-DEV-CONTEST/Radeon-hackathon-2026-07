// Logging utility with multiple log levels
#include "logger.h"

void Logger::log(Level level, const std::string& message) {
    if (level < min_level_) return;
    
    std::lock_guard<std::mutex> lock(mutex_);
    std::string formatted = format_message(level, message);
    
    if (console_output_) std::cout << formatted << std::endl;
    if (file_output_) file_ << formatted << std::endl;
}
