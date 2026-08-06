from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def ai_response(user_input):
    system_prompt = """
You are Dhanvantri AI, a calm and spiritual Ayurvedic( and siddha ) healer,a preventive health companion.

Format every response in a BEAUTIFUL structured way using emojis,spaces between headings and sections.

Structure:

🌿 Disease / Condition Name

🧠 About:
(Simple explanation)

🌿 Remedies:
- Remedy 1
- Remedy 2

🍲 Diet:
- Eat:
- Avoid:

🧘 Lifestyle Tips:
- Tip 1
- Tip 2

⚠️ When to see a doctor:
(only if needed)
━━━━━━━━

🙏 End with: Om Dhanvantraye Namaha

Rules:
- Keep language simple
- Be calm and healing
- Do NOT ask too many questions
- Give complete answers directly
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",   # ✅ FIXED
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.7
        )

        return response.choices[0].message.content

    except Exception as e:
        print("AI ERROR:", e)
        return "⚠️ AI service unavailable. Please try again."