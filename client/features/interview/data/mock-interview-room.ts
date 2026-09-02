import type { InterviewRoomSession } from "@/features/interview/types/interview.types";

export const DEFAULT_ROOM_INTERVIEW_ID = "AVX-9942-JS";

export const MOCK_INTERVIEW_ROOM_SESSION: InterviewRoomSession = {
  id: DEFAULT_ROOM_INTERVIEW_ID,
  status: "live",
  phase: "live",
  candidate: {
    id: "AVX-2024-ALEX",
    fullName: "Alex Johnson",
    shortName: "Alex J.",
    title: "Senior Software Engineer",
    level: "L6",
    skills: ["Python", "AWS"],
    avatarInitials: "AJ",
  },
  question: {
    id: "q-04",
    index: 4,
    total: 12,
    topic: "System Design & Scaling",
    difficulty: "hard",
    prompt:
      "How would you architect a real-time analytics system capable of processing 100k events/sec with sub-second latency?",
    evaluatorNotes:
      "Looking for mention of message brokers (Kafka/RabbitMQ), stream processing (Flink/Spark), and optimized storage (ClickHouse/Druid).",
    elapsedSeconds: 222,
  },
  progressPercent: 45,
  estimatedRemainingLabel: "18m 30s",
  latencyMs: 18,
  isMuted: false,
  isCameraOn: true,
  isScreenShareEnabled: false,
  isAiThinking: false,
  isCandidateSpeaking: true,
  speakingSpeedWpm: 142,
  sentiment: "positive",
  aiNotes:
    "Candidate is correctly framing ingestion and stream processing. Probe deeper on backpressure and storage trade-offs.",
  transcript: [
    {
      id: "t-1",
      speaker: "ai",
      speakerLabel: "AI AGENT (VOX-1)",
      timestamp: "14:22:05",
      content:
        "Interesting approach. How would you ensure exactly-once processing semantics while keeping end-to-end latency under one second?",
    },
    {
      id: "t-2",
      speaker: "candidate",
      speakerLabel: "CANDIDATE (ALEX J.)",
      timestamp: "14:22:42",
      accuracy: 98,
      content:
        "I would put Kafka at the edge for durable ingestion, then Flink for windowed aggregations with checkpointing. For serving, ClickHouse handles the low-latency analytical reads, and I'd isolate replay traffic so recovery never stampedes the cluster.",
    },
  ],
  metrics: [
    {
      id: "technical",
      label: "Technical Skill",
      score: 92,
      delta: 2.4,
      icon: "technical",
    },
    {
      id: "communication",
      label: "Communication",
      score: 78,
      delta: 2.4,
      icon: "communication",
    },
    {
      id: "confidence",
      label: "Confidence",
      score: 84,
      delta: 2.4,
      icon: "confidence",
    },
    {
      id: "leadership",
      label: "Leadership",
      score: 65,
      delta: -2.4,
      icon: "leadership",
    },
  ],
  metricSeries: [
    { time: "0m", confidence: 70, communication: 68, technical: 74 },
    { time: "5m", confidence: 76, communication: 72, technical: 80 },
    { time: "10m", confidence: 81, communication: 75, technical: 86 },
    { time: "15m", confidence: 84, communication: 78, technical: 92 },
  ],
  agents: [
    {
      id: "resume",
      name: "Resume Agent",
      status: "completed",
      progress: 100,
      currentTask: "Resume signals locked for session context",
    },
    {
      id: "planner",
      name: "Planner Agent",
      status: "completed",
      progress: 100,
      currentTask: "Adaptive pathing plan active",
    },
    {
      id: "technical",
      name: "Technical Agent",
      status: "active",
      progress: 64,
      currentTask: "Probing stream processing trade-offs",
    },
    {
      id: "behavioral",
      name: "Behavioral Agent",
      status: "waiting",
      progress: 20,
      currentTask: "Standby for leadership follow-ups",
    },
    {
      id: "fact-checker",
      name: "Fact Checker",
      status: "active",
      progress: 58,
      currentTask: "Validating Kafka/Flink claims",
    },
    {
      id: "evaluation",
      name: "Evaluation Agent",
      status: "active",
      progress: 71,
      currentTask: "Updating live scoring matrix",
    },
    {
      id: "hiring",
      name: "Hiring Agent",
      status: "waiting",
      progress: 12,
      currentTask: "Awaiting final recommendation window",
    },
  ],
};

export async function simulateRoomLatency(ms = 380): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
