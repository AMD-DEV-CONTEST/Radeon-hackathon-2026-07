# UI-5 Admin Operations Visibility Fix

- Level: S1
- Status: implemented

`AdminOperations` is rendered directly after the project overview. Its existing
server-authoritative 403 behaviour is unchanged: ordinary users still receive
no operations panel.
