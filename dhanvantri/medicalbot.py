import random

# ---------------- EMERGENCY ---------------- #
RED_FLAGS = ["chest pain", "breathless", "stroke"]

# ---------------- CONVERSATION ---------------- #
CONVERSATION_DB = {
    "greeting": {
        "keywords": ["hi", "hello", "hey"],
        "response": "🌿 Hello! I am Dhanvantri AI 😊"
    },
    "thanks": {
        "keywords": ["thanks", "thank you"],
        "response": "🌿 You're welcome! Stay healthy."
    },
    "bye": {
        "keywords": ["bye", "goodbye"],
        "response": "🌿 Take care! 🙏"
    }
}

# ---------------- KNOWLEDGE ---------------- #
KNOWLEDGE_DB = {
    "ayurveda": {
        "keywords": ["ayurveda", "ayurvedha"],
        "answer": "🌿 Ayurveda is an ancient Indian system of medicine focusing on balance of body, mind, and spirit using herbs, diet, and lifestyle."
    },
    "siddha": {
        "keywords": ["siddha"],
        "answer": "🪔 Siddha is a traditional healing system from Tamil Nadu using herbs, minerals, and yoga for holistic health."
    }
}

# ---------------- CASUAL ---------------- #
CASUAL_DB = {
    "praise": {
        "keywords": ["awesome", "good", "great", "nice", "cool"],
        "response": "🌿 Thank you 😊 I am always here to help you."
    },
    "how_are_you": {
        "keywords": ["how are you"],
        "response": "🌿 I am here to support your health 😊 How are you feeling today?"
    }
}

# ---------------- EMOTIONS ---------------- #
EMOTION_DB = {
    "sad": {
        "keywords": ["sad", "depressed", "unhappy", "cry"],
        "yoga": "Balasana (Child's Pose)",
        "tip": "Calms the mind and reduces sadness."
    },
    "stress": {
        "keywords": ["stress", "tension", "anxiety", "worried"],
        "yoga": "Anulom Vilom",
        "tip": "Balances nervous system and reduces stress."
    },
    "tired": {
        "keywords": ["tired", "exhausted", "low energy"],
        "yoga": "Shavasana",
        "tip": "Deep relaxation for body and mind."
    },
    "angry": {
        "keywords": ["angry", "frustrated", "irritated"],
        "yoga": "Bhramari Pranayama",
        "tip": "Calms anger and relaxes mind."
    }
}

# ---------------- SYMPTOMS ---------------- #
SYMPTOMS_DB = {
    "fever": {
        "keywords": ["fever", "temperature", "hot body"],
        "severity": "medium",
        "questions": ["How many days?", "Any chills or sweating?"],
        "remedies": ["Tulsi tea", "Rest", "Warm fluids"]
    },
    "headache": {
        "keywords": ["headache", "migraine"],
        "severity": "low",
        "questions": ["Is it one side or full head?"],
        "remedies": ["Peppermint oil", "Rest", "Hydration"]
    },
    "cold": {
        "keywords": ["cold", "runny nose", "sneezing"],
        "severity": "low",
        "questions": ["Any fever?", "Blocked nose?"],
        "remedies": ["Steam inhalation", "Tulsi tea"]
    },
    "cough": {
        "keywords": ["cough", "throat", "dry cough"],
        "severity": "low",
        "questions": ["Dry or wet cough?", "Any chest pain?"],
        "remedies": ["Ginger honey", "Steam inhalation"]
    },
    "allergy": {
        "keywords": ["allergy", "allergic", "itching", "rash", "sneezing"],
        "severity": "low",
        "questions": ["Skin, food, or dust allergy?", "Any itching or redness?"],
        "remedies": ["Neem leaves", "Turmeric milk", "Avoid allergens"]
    },
    "stomach pain": {
        "keywords": ["stomach pain", "abdominal pain", "gas", "acidity", "indigestion"],
        "severity": "low",
        "questions": ["After food or empty stomach?", "Any bloating or nausea?"],
        "remedies": ["Jeera water", "Ginger tea", "Avoid spicy food"]
    },
    "chest pain": {
        "keywords": ["chest pain", "tight chest"],
        "severity": "high",
        "questions": [],
        "remedies": []
    }
}

# ---------------- MAIN FUNCTION ---------------- #
def get_medical_response(user_input):

    text = user_input.lower().strip()

    # 🚨 Emergency
    for flag in RED_FLAGS:
        if flag in text:
            return "🚨 This may be serious. Please visit a hospital immediately."

    # 💬 Conversation
    for data in CONVERSATION_DB.values():
        if any(word in text for word in data["keywords"]):
            return data["response"]

    # 📚 Knowledge
    for data in KNOWLEDGE_DB.values():
        if any(word in text for word in data["keywords"]):
            return data["answer"]

    # 😄 Casual
    for data in CASUAL_DB.values():
        if any(word in text for word in data["keywords"]):
            return data["response"]

    # ❤️ Emotion detection
    detected = []
    for mood, data in EMOTION_DB.items():
        if any(word in text for word in data["keywords"]):
            detected.append((mood, data))

    if detected:
        response = "🌿 I sense your inner state. Let us restore balance 🌸\n\n"
        for mood, data in detected:
            response += f"💫 Don't be {mood.title()}\n"
            response += f"🧘 Yoga: {data['yoga']}\n"
            response += f"🌿 Benefit: {data['tip']}\n\n"

        response += "🙏 This is supportive guidance, not a medical diagnosis.\n"
        response += "🙏 Om Dhanvantraye Namaha"
        return response

    # 🩺 Symptoms
    found = []
    for symptom, data in SYMPTOMS_DB.items():
        if any(kw in text for kw in data["keywords"]):
            found.append((symptom, data))

    if not found:
        return None   # ⚡ IMPORTANT → lets AI handle it

    response = ""

    for symptom, data in found:

        if data["severity"] == "high":
            return "🚨 Serious symptom detected. Please visit a doctor immediately."

        response += f"\n🌿 {symptom.title()}\n"

        response += """
🧠 About:
This may be due to temporary imbalance in body or digestion.

🌿 Remedies:
"""
        for r in data["remedies"]:
            response += f"- {r}\n"

        response += """
🍲 Diet:
- Eat: Light, warm food
- Avoid: Spicy, oily items
\n
🧘 Lifestyle Tips:
- Rest well
- Stay hydrated\n
"""

        if data["questions"]:
            response += "\n❓ Follow-up Questions:\n"
            for q in data["questions"]:
                response += f"- {q}\n"

        response += """
⚠️ Note:
This is a preventive health suggestion, not a replacement for a doctor.

━━━━━━━━
"""

    response += "\n🙏 Om Dhanvantraye Namaha"
    return response