import os
import json
import re
import traceback
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
print("DEBUG GROQ_API_KEY exists:", bool(GROQ_API_KEY))
print("DEBUG GEMINI_API_KEY exists:", bool(GEMINI_API_KEY))

groq_client = None
gemini_model = None

if GROQ_API_KEY:
    try:
        from groq import Groq
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception as e:
        print("DEBUG Groq init failed:", repr(e))
        traceback.print_exc()
        groq_client = None

if GEMINI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-2.5-flash')
    except Exception as e:
        print("DEBUG Gemini init failed:", repr(e))
        traceback.print_exc()
        gemini_model = None


def _call_ai(prompt: str, expect_json: bool = True) -> str:
    """Call AI with Groq first, fallback to Gemini."""
    if groq_client:
        try:
            print("DEBUG Trying Groq...")
            messages = [{"role": "user", "content": prompt}]
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.3,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            print("DEBUG Groq request failed:", repr(e))
            traceback.print_exc()
            pass

    if gemini_model:
        try:
            print("DEBUG Trying Gemini...")
            response = gemini_model.generate_content(prompt)
            return response.text
        except Exception as e:
            print("DEBUG Gemini request failed:", repr(e))
            traceback.print_exc()
            pass

    raise RuntimeError("AI provider configuration failed. Set GROQ_API_KEY or GEMINI_API_KEY.")


def _extract_json(text: str):
    """Extract JSON from AI response, handling markdown code blocks."""
    text = text.strip()
    # Remove markdown code blocks
    text = re.sub(r'```(?:json)?\n?', '', text)
    text = re.sub(r'```', '', text)
    text = text.strip()
    # Find JSON object/array
    match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)


# ─── ACADEMIC MODULE AI FUNCTIONS ────────────────────────────────────────────

def generate_academic_quiz(subject: str, topic: str, content: str = "") -> dict:
    content_section = f"\n\nContent to base questions on:\n{content[:3000]}" if content else ""

    prompt = f"""You are an expert educational AI. Generate a comprehensive quiz for the following academic topic.

Subject: {subject}
Topic: {topic}{content_section}

Generate exactly this JSON structure (no extra text, valid JSON only):
{{
  "mcqs": [
    {{
      "id": 1,
      "question": "Question text here?",
      "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
      "correct_answer": "A) Option 1",
      "explanation": "Brief explanation of why this is correct",
      "concept": "specific concept tested"
    }}
  ],
  "theory_questions": [
    {{
      "id": 1,
      "question": "Explain... or Describe... or Discuss...",
      "expected_answer": "Complete model answer with key points",
      "key_points": ["point 1", "point 2", "point 3"],
      "concept": "specific concept tested"
    }}
  ],
  "short_answer_questions": [
    {{
      "id": 1,
      "question": "Define... or What is... or How does...",
      "expected_answer": "Concise model answer",
      "keywords": ["keyword1", "keyword2"],
      "concept": "specific concept tested"
    }}
  ]
}}

Generate: 7 MCQs, 4 theory questions, 4 short answer questions. Make them progressively harder. Cover different sub-concepts of {topic}."""

    raw = _call_ai(prompt)
    return _extract_json(raw)


def analyze_academic_mistakes(subject: str, topic: str, wrong_questions: list) -> dict:
    if not wrong_questions:
        return {
            "weak_concepts": [],
            "analysis": "Excellent performance! No significant weak areas identified.",
            "specific_gaps": {}
        }

    questions_text = "\n".join([
        f"- Q: {q.get('question','')}\n  Concept: {q.get('concept','')}\n  Student answered: {q.get('student_answer','')}\n  Correct: {q.get('correct_answer','')}"
        for q in wrong_questions[:10]
    ])

    prompt = f"""You are an expert educational analyst. Analyze these incorrect answers from a student quiz.

Subject: {subject}
Topic: {topic}

Incorrect answers:
{questions_text}

Analyze the mistakes and return ONLY this JSON (no extra text):
{{
  "weak_concepts": ["concept1", "concept2", "concept3"],
  "analysis": "A detailed 2-3 sentence explanation of what the student struggles with and why",
  "specific_gaps": {{
    "concept_name": "Specific description of the gap in this concept"
  }},
  "root_causes": ["Root cause 1", "Root cause 2"]
}}

Be specific - don't just say 'Trees = Weak'. Say 'Binary Tree Traversal: Student confuses inorder with preorder sequence'."""

    raw = _call_ai(prompt)
    return _extract_json(raw)


def grade_theory_answer(question: str, expected: str, student_answer: str, key_points: list) -> dict:
    if not student_answer.strip():
        return {"score": 0, "feedback": "No answer provided.", "covered_points": []}

    prompt = f"""Grade this student's theory answer fairly.

Question: {question}
Expected Answer: {expected}
Key Points to Cover: {json.dumps(key_points)}

Student's Answer: "{student_answer}"

Return ONLY this JSON:
{{
  "score": 0.0,
  "feedback": "Specific constructive feedback on what was good and what was missing",
  "covered_points": ["points the student correctly covered"],
  "missed_points": ["points the student missed"]
}}

Score is a float from 0.0 to 1.0. Be fair but accurate."""

    try:
        raw = _call_ai(prompt)
        return _extract_json(raw)
    except Exception:
        return {"score": 0, "feedback": "Could not grade answer.", "covered_points": []}


def grade_short_answer(question: str, expected: str, student_answer: str, keywords: list) -> dict:
    if not student_answer.strip():
        return {"score": 0, "feedback": "No answer provided."}

    # Keyword-based scoring
    answer_lower = student_answer.lower()
    matched = [kw for kw in keywords if kw.lower() in answer_lower]
    keyword_score = len(matched) / max(len(keywords), 1)

    prompt = f"""Grade this short answer.

Question: {question}
Expected: {expected}
Keywords: {keywords}
Student answered: "{student_answer}"

Return ONLY this JSON:
{{
  "score": {keyword_score:.2f},
  "feedback": "Brief specific feedback (1 sentence)"
}}

Adjust score based on overall understanding shown, not just keywords. Score 0.0-1.0."""

    try:
        raw = _call_ai(prompt)
        return _extract_json(raw)
    except Exception:
        return {"score": keyword_score, "feedback": f"Matched {len(matched)}/{len(keywords)} key concepts."}


def generate_study_recommendations(subject: str, topic: str, weak_areas: list, score: float) -> str:
    if not weak_areas:
        return f"Excellent work! You have a strong understanding of {topic} in {subject}. Continue practicing advanced problems to maintain your proficiency."

    prompt = f"""You are a personalized academic coach. Generate a specific, actionable study recommendation.

Subject: {subject}
Topic: {topic}
Student Score: {score:.0f}%
Weak Areas: {', '.join(weak_areas)}

Write a personalized 3-4 sentence recommendation. Be specific about:
1. What the student struggles with
2. Specific resources or strategies to improve
3. Concrete action steps (e.g., "solve 10 practice problems on X")
4. Suggested revision order

Write as a direct message to the student. Do NOT use JSON - just write the recommendation text."""

    return _call_ai(prompt, expect_json=False)


# ─── CAREER MODULE AI FUNCTIONS ──────────────────────────────────────────────

def identify_career_skills(career_goal: str) -> dict:
    prompt = f"""You are a career development expert. Identify all skills required for the following career role.

Career Goal: {career_goal}

Return ONLY this JSON:
{{
  "career_title": "Standardized career title",
  "overview": "1-2 sentence description of this career",
  "required_skills": [
    {{
      "name": "Skill Name",
      "category": "technical|soft|domain",
      "importance": "critical|high|medium",
      "description": "Brief description of what this skill involves"
    }}
  ],
  "industry_context": "Brief note on industry expectations"
}}

Include 6-10 skills. Mix technical and soft skills. Order by importance. Be specific to the career (e.g., for Data Scientist include Python, SQL, Statistics, ML, not just 'Programming')."""

    raw = _call_ai(prompt)
    return _extract_json(raw)


def generate_career_questions(skill: str, career_goal: str, skill_description: str) -> dict:
    prompt = f"""You are a technical interviewer for {career_goal} roles. Generate assessment questions for the skill: {skill}.
Skill description: {skill_description}

Return ONLY this JSON:
{{
  "theory_questions": [
    {{
      "id": 1,
      "question": "Theory/conceptual question",
      "expected_answer": "Complete model answer",
      "key_points": ["key point 1", "key point 2"]
    }},
    {{
      "id": 2,
      "question": "Another conceptual question",
      "expected_answer": "Complete model answer",
      "key_points": ["key point 1", "key point 2"]
    }}
  ],
  "coding_questions": [
    {{
      "id": 1,
      "question": "Write code to...",
      "language": "python",
      "starter_code": "# Write your solution here\\n",
      "expected_output": "What running the code should produce",
      "test_cases": ["Test case 1 description", "Test case 2 description"],
      "solution": "Complete working solution code"
    }}
  ]
}}

Generate 2 theory questions and 1 coding question (if skill is technical, else 0 coding questions). For soft skills, use only theory questions."""

    raw = _call_ai(prompt)
    return _extract_json(raw)


def analyze_career_gaps(career_goal: str, skill_scores: dict) -> dict:
    scores_text = "\n".join([f"- {skill}: {score:.0f}%" for skill, score in skill_scores.items()])

    prompt = f"""You are a career readiness analyst. Analyze this student's skill scores for their career goal.

Career Goal: {career_goal}
Skill Scores:
{scores_text}

Return ONLY this JSON:
{{
  "overall_readiness": 75.0,
  "strong_skills": ["skill1", "skill2"],
  "moderate_skills": ["skill3"],
  "weak_skills": ["skill4", "skill5"],
  "critical_gaps": [
    {{
      "skill": "Skill Name",
      "current_level": 40,
      "gap_description": "Specific description of what is missing"
    }}
  ],
  "analysis": "2-3 sentence overall assessment of career readiness",
  "roadmap": [
    {{
      "step": 1,
      "action": "Specific action to take",
      "duration": "Estimated time (e.g., 2 weeks)",
      "resources": ["Resource 1", "Resource 2"]
    }}
  ]
}}

Overall readiness is the weighted average (strong=100%, moderate=60%, weak=25%). Roadmap should have 4-6 steps ordered by priority."""

    raw = _call_ai(prompt)
    return _extract_json(raw)


def generate_career_recommendations(career_goal: str, gaps: dict, skill_scores: dict) -> str:
    strong = gaps.get('strong_skills', [])
    weak = gaps.get('weak_skills', [])

    prompt = f"""You are a career coach. Write a personalized career development message for a student.

Career Goal: {career_goal}
Strong Areas: {', '.join(strong) if strong else 'None identified'}
Weak Areas: {', '.join(weak) if weak else 'None'}
Overall Readiness: {gaps.get('overall_readiness', 0):.0f}%

Write 3-4 sentences that:
1. Acknowledge their strengths specifically
2. Address their most critical gaps
3. Give a concrete next step
4. End with encouragement

Write directly to the student. No JSON. No bullet points. Just paragraph text."""

    return _call_ai(prompt, expect_json=False)


def grade_career_answer(skill: str, question: str, expected: str, student_answer: str, key_points: list) -> dict:
    if not student_answer.strip():
        return {"score": 0, "feedback": "No answer provided."}

    prompt = f"""Grade this career assessment answer for the skill: {skill}

Question: {question}
Expected Answer: {expected}
Key Points: {json.dumps(key_points)}
Student's Answer: "{student_answer}"

Return ONLY JSON:
{{
  "score": 0.75,
  "feedback": "Specific 1-2 sentence feedback"
}}

Score is 0.0 to 1.0."""

    try:
        raw = _call_ai(prompt)
        return _extract_json(raw)
    except Exception:
        return {"score": 0, "feedback": "Could not grade response."}
