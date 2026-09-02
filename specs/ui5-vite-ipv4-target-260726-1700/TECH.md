# UI-5 Vite IPv4 Target Fix

- Level: S1
- Status: implemented

The Vite default API target uses `127.0.0.1:9000`, matching the application's
default IPv4 bind. This avoids `localhost` resolving to unavailable IPv6 `::1`.
