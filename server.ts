import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI, Type } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const PORT = process.env.PORT ? parseInt(process.env.PORT) : 3000;

app.use(express.json({ limit: "10mb" }));

// Initialize Google GenAI with recommended header
const getAI = () => {
  const apiKey = process.env.GEMINI_API_KEY || "";
  return new GoogleGenAI({
    apiKey,
    httpOptions: {
      headers: {
        "User-Agent": "aistudio-build",
      },
    },
  });
};

// 1. Resume Based Questions Generator
app.post("/api/gemini/resume-questions", async (req, res) => {
  try {
    const { resumeText, targetRole, experienceLevel } = req.body;
    const ai = getAI();

    const prompt = `You are a Senior Technical Interviewer at a top tech company. Analyze the following candidate resume/profile for a ${targetRole || "Software Engineer"} (${experienceLevel || "Junior/Entry level"}).
Resume/Profile Text:
"""
${resumeText || "BCA student with knowledge of React, Node.js, SQL, Linux basic commands, HTML/CSS."}
"""

Generate 5 highly targeted interview questions directly based on this resume:
1. Technical Depth Question
2. Project/Experience Deep Dive Question
3. Problem Solving / Scenario Question
4. Core CS / Fundamentals Question
5. Behavioral / Mindset Question

Return ONLY JSON array of objects in this structure:
[
  {
    "id": "q1",
    "category": "Technical",
    "question": "Question string...",
    "hint": "Brief hint on what interviewer looks for...",
    "expectedTopics": ["topic1", "topic2"]
  }
]`;

    const response = await ai.models.generateContent({
      model: "gemini-3.6-flash",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
      },
    });

    const jsonText = response.text || "[]";
    const questions = JSON.parse(jsonText);
    res.json({ questions });
  } catch (error: any) {
    console.error("Error generating resume questions:", error);
    res.status(500).json({
      error: "Failed to generate questions from resume",
      details: error.message,
    });
  }
});

// 2. Interactive Voice Interview Response Generator & Live Evaluation
app.post("/api/gemini/interview-turn", async (req, res) => {
  try {
    const { candidateAnswer, currentQuestion, conversationHistory, targetRole, eyeContactScore } = req.body;
    const ai = getAI();

    const prompt = `You are conducting a professional mock technical interview for a ${targetRole || "Software Developer"}.
Current Question: "${currentQuestion}"
Candidate Answer: "${candidateAnswer}"
Live Eye Contact Metric: ${eyeContactScore ?? 85}%
Conversation History: ${JSON.stringify(conversationHistory || [])}

Tasks:
1. Rate the candidate's response to the current question (0 to 100).
2. Give concise construct feedback (2-3 sentences max: what was good, what was missing).
3. Generate the NEXT natural follow-up interview question (or transition to the next topic).
4. Identify 1 key technical concept used in the answer.

Return ONLY JSON in this format:
{
  "rating": 82,
  "feedback": "Great explanation of React state updates. However, mention useEffect cleanup functions or dependency array nuances for full credit.",
  "nextQuestion": "How do you optimize render performance in a React application when dealing with large lists?",
  "detectedConcept": "React Hooks & State Management"
}`;

    const response = await ai.models.generateContent({
      model: "gemini-3.6-flash",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
      },
    });

    const jsonText = response.text || "{}";
    const result = JSON.parse(jsonText);
    res.json(result);
  } catch (error: any) {
    console.error("Error in interview turn:", error);
    res.status(500).json({ error: "Interview step evaluation failed", details: error.message });
  }
});

// 3. Coding Round AI Evaluation
app.post("/api/gemini/code-eval", async (req, res) => {
  try {
    const { code, language, questionTitle, questionDescription, testCases } = req.body;
    const ai = getAI();

    const prompt = `You are an automated code evaluator for technical interviews.
Problem: ${questionTitle}
Description: ${questionDescription}
Language: ${language}
Submitted Code:
\`\`\`${language}
${code}
\`\`\`

Evaluate the code on:
- Correctness & Logic
- Time & Space Complexity
- Edge Case handling
- Code Cleanliness & Readability

Return ONLY JSON in this format:
{
  "passed": true,
  "score": 90,
  "timeComplexity": "O(N)",
  "spaceComplexity": "O(1)",
  "summary": "Solid solution using two-pointer approach.",
  "strengths": ["Clean logic", "Optimal time complexity"],
  "improvements": ["Consider null or empty array checks"],
  "testCaseResults": [
    { "input": "[2, 7, 11, 15], target = 9", "expected": "[0, 1]", "passed": true, "notes": "Passed base test case" },
    { "input": "[3, 2, 4], target = 6", "expected": "[1, 2]", "passed": true, "notes": "Passed secondary case" }
  ]
}`;

    const response = await ai.models.generateContent({
      model: "gemini-3.6-flash",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
      },
    });

    const jsonText = response.text || "{}";
    const result = JSON.parse(jsonText);
    res.json(result);
  } catch (error: any) {
    console.error("Error in code evaluation:", error);
    res.status(500).json({ error: "Code evaluation failed", details: error.message });
  }
});

// 4. DevOps Linux Terminal AI Mentor / Hint
app.post("/api/gemini/terminal-hint", async (req, res) => {
  try {
    const { taskDescription, commandHistory, currentCommand } = req.body;
    const ai = getAI();

    const prompt = `You are a DevOps Engineer Mentor explaining Linux CLI concepts to a BCA student.
Task Challenge: "${taskDescription}"
User Recent Commands: ${JSON.stringify(commandHistory || [])}
User Current Attempt: "${currentCommand}"

Provide a clear, simple explanation & hint without giving away the exact answer immediately if they are close, or explain the error if they typed something invalid.

Return ONLY JSON:
{
  "hint": "Remember that grep -i makes the search case-insensitive, and 'systemctl status <service>' shows process states.",
  "suggestedConcept": "Linux grep & systemctl service management",
  "explanation": "In Linux, service logs can be inspected using journalctl or searching /var/log with grep."
}`;

    const response = await ai.models.generateContent({
      model: "gemini-3.6-flash",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
      },
    });

    const jsonText = response.text || "{}";
    res.json(JSON.parse(jsonText));
  } catch (error: any) {
    console.error("Error in terminal hint:", error);
    res.status(500).json({ error: "Terminal hint failed", details: error.message });
  }
});

// 5. Complete Interview AI Scorecard Generator
app.post("/api/gemini/scorecard", async (req, res) => {
  try {
    const { candidateName, targetRole, interviewData } = req.body;
    const ai = getAI();

    const prompt = `Generate a comprehensive hackathon-grade candidate interview scorecard for ${candidateName || "Candidate"} applying for ${targetRole || "Software Developer"}.
Interview Performance Summary:
${JSON.stringify(interviewData)}

Calculate scores (out of 100) for these 5 core dimensions:
1. Technical Knowledge
2. Communication
3. Confidence
4. Eye Contact / Non-Verbal Focus
5. Problem Solving & Coding

Provide detailed strengths, growth areas, topic scores, and overall hiring verdict ("Strong Hire", "Hire", "Needs Practice").

Return ONLY JSON:
{
  "overallScore": 84,
  "verdict": "Hire",
  "radarScores": [
    { "subject": "Technical", "score": 85, "fullMark": 100 },
    { "subject": "Communication", "score": 80, "fullMark": 100 },
    { "subject": "Confidence", "score": 82, "fullMark": 100 },
    { "subject": "Eye Contact", "score": 88, "fullMark": 100 },
    { "subject": "Problem Solving", "score": 85, "fullMark": 100 }
  ],
  "strengths": [
    "Strong understanding of React component lifecycle and state",
    "Good Linux CLI fundamentals in terminal task",
    "Maintained steady eye contact and clear verbal delivery"
  ],
  "areasToImprove": [
    "Deepen knowledge on database indexing and SQL query optimization",
    "Practice edge case validation during coding rounds"
  ],
  "questionBreakdown": [
    {
      "question": "Explain state management in React",
      "score": 85,
      "feedback": "Clear explanation of useState and prop drilling alternatives."
    },
    {
      "question": "DevOps Terminal Task: Process Inspection",
      "score": 90,
      "feedback": "Executed ps aux and grep correctly."
    }
  ]
}`;

    const response = await ai.models.generateContent({
      model: "gemini-3.6-flash",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
      },
    });

    const jsonText = response.text || "{}";
    res.json(JSON.parse(jsonText));
  } catch (error: any) {
    console.error("Error in scorecard:", error);
    res.status(500).json({ error: "Scorecard generation failed", details: error.message });
  }
});

// 6. Personalized Learning Roadmap Generator
app.post("/api/gemini/learning-roadmap", async (req, res) => {
  try {
    const { targetRole, weakAreas, overallScore } = req.body;
    const ai = getAI();

    const prompt = `Create a 4-Week Step-by-Step Personalized Skill Improvement Plan for a student aiming to be a ${targetRole || "Software Engineer"}.
Weaknesses Identified: ${JSON.stringify(weakAreas || ["Data Structures edge cases", "Systemctl Linux services", "Eye contact under pressure"])}
Current Score: ${overallScore || 78}/100

Generate a practical roadmap with weekly goals, specific key topics, actionable daily practice tasks, and recommended free learning resources.

Return ONLY JSON:
{
  "role": "${targetRole || "Software Engineer"}",
  "weeklyPlan": [
    {
      "week": 1,
      "title": "Core Technical Fundamentals & Algorithm Polish",
      "objective": "Master two-pointer techniques, array boundary edge cases, and time complexity estimation.",
      "keyTopics": ["Two Pointer Method", "Big O Notation", "Array Boundary Checks"],
      "actionItems": [
        "Solve 5 LeetCode Easy/Medium two-pointer problems",
        "Write unit tests covering empty/null arrays"
      ],
      "recommendedResources": ["GeeksforGeeks DSA Guide", "NeetCode 150 Array Section"]
    },
    {
      "week": 2,
      "title": "DevOps & Linux Command Mastery",
      "objective": "Get hands-on confidence with Linux process inspection, permissions, and log filtering.",
      "keyTopics": ["ps & top commands", "chmod / chown permissions", "journalctl & grep filtering"],
      "actionItems": [
        "Practice bash command challenges in Ubuntu terminal",
        "Configure systemd service script from scratch"
      ],
      "recommendedResources": ["OverTheWire Bandit Wargame", "Linux Journey Fundamentals"]
    },
    {
      "week": 3,
      "title": "Voice Delivery & Communication Practice",
      "objective": "Eliminate filler words, articulate thought process aloud, and maintain camera eye alignment.",
      "keyTopics": ["STAR Method for Answers", "Camera Alignment", "Articulating Code Logic"],
      "actionItems": [
        "Record 3 mock voice answers using InterviewIQ AI",
        "Practice speaking continuously for 90 seconds per answer"
      ],
      "recommendedResources": ["STAR Method Interview Framework", "TED Talk Vocal Presence Tips"]
    },
    {
      "week": 4,
      "title": "Full Mock Interview Simulation & Review",
      "objective": "Combine technical, coding, and verbal skills in a timed end-to-end interview round.",
      "keyTopics": ["System Design Basics", "Mock Round Review", "Resume Refinement"],
      "actionItems": [
        "Complete 2 full InterviewIQ AI voice + coding assessments",
        "Review scorecard breakdown and fine-tune resume project descriptions"
      ],
      "recommendedResources": ["InterviewIQ AI Practice Portal", "BCA Final Year Project Guide"]
    }
  ]
}`;

    const response = await ai.models.generateContent({
      model: "gemini-3.6-flash",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
      },
    });

    const jsonText = response.text || "{}";
    res.json(JSON.parse(jsonText));
  } catch (error: any) {
    console.error("Error in learning roadmap:", error);
    res.status(500).json({ error: "Learning roadmap failed", details: error.message });
  }
});

// Vite middleware for development vs static production server
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`InterviewIQ AI server running on http://localhost:${PORT}`);
  });
}

startServer();
