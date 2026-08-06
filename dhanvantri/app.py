from flask import Flask, render_template, request, redirect, url_for, session
from medicalbot import get_medical_response
from herbs import HERB_DB
from werkzeug.security import generate_password_hash, check_password_hash
import json, uuid, os, random
from datetime import datetime
from ai_engine import ai_response
from database import connect, create_tables
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from flask import jsonify
app = Flask(__name__)
app.secret_key = "dhanvantri_secret"

# ---------------- EMAIL CONFIG ---------------- #
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'dhanvantribot.healthcompanion@gmail.com'
app.config['MAIL_PASSWORD'] = 'slnturazucnfjztj'

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)

# ---------------- PATHS ---------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "chat_history.json")
USERS_FILE = os.path.join(BASE_DIR, "users.json")

# ---------------- DAILY CONTENT ---------------- #
DAILY_TIPS = [
    "Drink warm water after waking up",
    "Practice 10 minutes of pranayama daily",
    "Eat seasonal fruits",
    "Sleep before 10:30 PM",
    "Drink turmeric milk for immunity"
]

YOGA_POSES = [
    "Surya Namaskar – boosts energy",
    "Vrikshasana – improves balance",
    "Bhujangasana – strengthens spine",
    "Anulom Vilom – improves breathing",
    "Tadasana – improves posture"
]

# ---------------- INIT ---------------- #
def init_files():
    for file in [HISTORY_FILE, USERS_FILE]:
        if not os.path.exists(file):
            with open(file, "w") as f:
                json.dump([], f)

# ---------------- CHAT STORAGE ---------------- #
def format_date(date_str):
    try:
        chat_date = datetime.strptime(date_str, "%d %b %Y").date()
    except:
        return date_str

    today = datetime.now().date()
    if chat_date == today:
        return "Today"
    elif (today - chat_date).days == 1:
        return "Yesterday"
    return chat_date.strftime("%d %b %Y")

def load_chats():
    if not os.path.exists(HISTORY_FILE):
        return []

    with open(HISTORY_FILE, "r") as f:
        chats = json.load(f)

    if "user" in session:
        chats = [c for c in chats if c.get("user") == session["user"]]

    for c in chats:
        c["display_date"] = format_date(c.get("created_at", ""))

    return chats

def save_chats(chats):
    if not os.path.exists(HISTORY_FILE):
        all_chats = []
    else:
        with open(HISTORY_FILE, "r") as f:
            all_chats = json.load(f)

    all_chats = [c for c in all_chats if c.get("user") != session.get("user")]
    all_chats = chats + all_chats

    with open(HISTORY_FILE, "w") as f:
        json.dump(all_chats, f, indent=4)

# ---------------- HERBS ---------------- #
def suggest_herbs(text):
    text = text.lower()
    suggested = []

    for herb, data in HERB_DB.items():
        if any(use in text for use in data["uses"]):
            suggested.append(herb.title())

    return suggested

def generate_chat_title(user_input):
    text = user_input.lower()

    # 🩺 Symptoms
    symptom_titles = {
        "stomach pain": "Stomach Pain Help",
        "fever": "Fever Guidance",
        "cold": "Cold & Sneezing",
        "cough": "Cough Treatment",
        "headache": "Headache Relief",
        "allergy": "Allergy Guidance"
    }

    for key, title in symptom_titles.items():
        if key in text:
            return title

    # 📚 Knowledge
    if "ayurveda" in text or "ayurvedha" in text:
        return "About Ayurveda"

    if "siddha" in text:
        return "About Siddha Medicine"

    # ❤️ Emotions
    if any(word in text for word in ["sad", "depressed", "unhappy"]):
        return "Feeling Sad"

    if any(word in text for word in ["stress", "anxiety", "worried"]):
        return "Stress & Anxiety Help"

    if any(word in text for word in ["tired", "exhausted"]):
        return "Low Energy"

    # 😄 Casual
    if any(word in text for word in ["hi", "hello", "hey"]):
        return "Greeting"

    # 🤖 Fallback → AI generate short title
    try:
        ai_title = ai_response(f"Give a very short 3-5 word title for: {user_input}")
        return ai_title.split("\n")[0][:40]
    except:
        return "Health Chat"
# ---------------- AUTH ---------------- #
@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"].strip().lower()
        password = generate_password_hash(request.form["password"])

        conn = connect()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        existing = cur.fetchone()

        if existing:
            error = "User already exists"
        else:
            cur.execute(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, password)
            )
            conn.commit()
            return redirect(url_for("login"))

        conn.close()

    return render_template("signup.html", error=error)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = connect()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user[3], password):
            session["user"] = username
            return redirect(url_for("home"))
        else:
            error = "Invalid username or password"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ---------------- CHAT ROUTES ---------------- #
@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))

    chats = load_chats()

    if not chats:
        return redirect(url_for("new_chat"))

    return redirect(url_for("chat", chat_id=chats[0]["id"]))

@app.route("/new")
def new_chat():
    if "user" not in session:
        return redirect(url_for("login"))

    chats = load_chats()
    chat_id = str(uuid.uuid4())

    chats.insert(0, {
        "id": chat_id,
        "user": session["user"],
        "title": "New Chat",
        "messages": [],
        "created_at": datetime.now().strftime("%d %b %Y")
    })

    save_chats(chats)

    return redirect(url_for("chat", chat_id=chat_id))

@app.route("/delete/<chat_id>")
def delete_chat(chat_id):
    if "user" not in session:
        return redirect(url_for("login"))

    chats = load_chats()
    chats = [c for c in chats if c["id"] != chat_id]

    save_chats(chats)
    return redirect(url_for("home"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = None

    if request.method == "POST":
        email = request.form["email"]

        conn = connect()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE email=?", (email,))
        user = cur.fetchone()

        if user:
            # Generate token
            token = serializer.dumps(email, salt="reset-password")

            reset_link = url_for("reset_password", token=token, _external=True)

            # Send email
            msg = Message("Password Reset - Dhanvantri",
                          sender=app.config['MAIL_USERNAME'],
                          recipients=[email])

            msg.body = f"Click to reset your password:\n{reset_link}"

            mail.send(msg)

            message = "Reset link sent to your email 🌿"
        else:
            message = "Email not found"

        conn.close()

    return render_template("forgot.html", message=message)

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = serializer.loads(token, salt="reset-password", max_age=300)
    except:
        return "❌ Invalid or expired link"

    if request.method == "POST":
        new_password = generate_password_hash(request.form["password"])

        conn = connect()
        cur = conn.cursor()

        cur.execute("UPDATE users SET password=? WHERE email=?",
                    (new_password, email))
        conn.commit()
        conn.close()

        return redirect(url_for("login"))

    return render_template("reset.html")
# ---------------- MAIN CHAT ---------------- #
@app.route("/chat/<chat_id>", methods=["GET"])
def chat(chat_id):

    chats = load_chats()
    chat = next((c for c in chats if c["id"] == chat_id), None)

    if not chat:
        return redirect(url_for("home"))

    return render_template(
        "index.html",
        chats=load_chats(),
        current_chat=chat,
        user=session.get("user"),
        tip=random.choice(DAILY_TIPS),
        yoga=random.choice(YOGA_POSES)
    )
@app.route("/chat", methods=["POST"])
def chat_api():

    data = request.get_json()
    chat_id = data.get("chat_id")
    user_input = data.get("question", "").strip()

    if not chat_id or not user_input:
        return jsonify({"reply": "Missing data"}), 400

    chats = load_chats()
    chat = next((c for c in chats if c["id"] == chat_id), None)

    if not chat:
        return jsonify({"reply": "Chat not found"}), 404

    # AI logic
    rule_based = get_medical_response(user_input)

    if rule_based is not None:
        answer = rule_based
    else:
        answer = ai_response(user_input)

    herbs = suggest_herbs(user_input)
    if herbs:
        answer += "\n\n🌿 Recommended Herbs:\n" + "\n".join(f"- {h}" for h in herbs)

    # save messages
    chat["messages"].append({
        "role": "user",
        "content": user_input,
        "time": datetime.now().strftime("%H:%M")
    })

    chat["messages"].append({
        "role": "bot",
        "content": answer,
        "time": datetime.now().strftime("%H:%M")
    })

    if chat["title"] == "New Chat":
        chat["title"] = generate_chat_title(user_input)

    save_chats(chats)

    return jsonify({"reply": answer})
# ---------------- RUN ---------------- #
if __name__ == "__main__":
    init_files()
    create_tables()
    app.run(debug=True)