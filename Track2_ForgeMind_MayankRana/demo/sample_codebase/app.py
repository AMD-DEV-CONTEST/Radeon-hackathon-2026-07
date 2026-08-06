"""
Sample codebase for demo - Flask Todo with bug
"""
from flask import Flask, request, jsonify

app = Flask(__name__)

# Buggy login - missing JWT
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    # BUG: No auth check, no JWT, always returns success
    if username:
        return jsonify({"message": "Logged in", "user": username})
    return jsonify({"error": "Missing username"}), 400

@app.route('/todos', methods=['GET'])
def get_todos():
    # Should be protected but isn't
    return jsonify([{"id": 1, "task": "Demo ForgeMind"}])

if __name__ == '__main__':
    app.run(debug=True)
