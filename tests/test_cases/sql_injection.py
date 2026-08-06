# Test Case 4: Python SQL Injection and File Operations
# Expected: 1-2 medium/low risks

import sqlite3

# VULN: CWE-89 - SQL Injection via f-string
def login_unsafe(username, password):
    conn = sqlite3.connect("db.sqlite")
    query = f"SELECT * FROM users WHERE name='{username}' AND pass='{password}'"
    return conn.execute(query).fetchone()

# SAFE: parameterized query
def login_safe(username, password):
    conn = sqlite3.connect("db.sqlite")
    query = "SELECT * FROM users WHERE name=? AND pass=?"
    return conn.execute(query, (username, password)).fetchone()

# VULN: CWE-73 - file write without path validation
def write_file(filename, content):
    with open(filename, "w") as f:  # LOW: no path validation
        f.write(content)
