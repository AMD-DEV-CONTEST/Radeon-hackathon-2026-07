"use client";

import {
  SOCKET_EVENTS,
  type AiResponsePayload,
  type AiThinkingPayload,
  type InterviewSpeakingPayload,
  type TranscriptUpdatedPayload,
} from "@/services/websocket/events";
import { socketManager } from "@/services/websocket/socket";

type SocketListener<T> = (payload: T) => void;

/**
 * Transcript channel listeners.
 * Room membership is owned by `interviewSocket`; this client only
 * acquires a shared socket connection and registers typed handlers.
 */
class TranscriptSocketClient {
  private static instance: TranscriptSocketClient | null = null;
  private interviewId: string | null = null;
  private acquired = false;

  static getInstance(): TranscriptSocketClient {
    TranscriptSocketClient.instance ??= new TranscriptSocketClient();
    return TranscriptSocketClient.instance;
  }

  getInterviewId(): string | null {
    return this.interviewId;
  }

  subscribe(interviewId: string): void {
    this.interviewId = interviewId;
    if (!this.acquired) {
      socketManager.connect();
      this.acquired = true;
    }
  }

  unsubscribe(): void {
    this.interviewId = null;
    if (this.acquired) {
      socketManager.release();
      this.acquired = false;
    }
  }

  onTranscriptUpdated(
    listener: SocketListener<TranscriptUpdatedPayload>
  ): () => void {
    return socketManager.on(SOCKET_EVENTS.transcriptUpdated, listener);
  }

  onAiThinking(listener: SocketListener<AiThinkingPayload>): () => void {
    return socketManager.on(SOCKET_EVENTS.aiThinking, listener);
  }

  onAiResponse(listener: SocketListener<AiResponsePayload>): () => void {
    return socketManager.on(SOCKET_EVENTS.aiResponse, listener);
  }

  onCandidateSpeaking(
    listener: SocketListener<InterviewSpeakingPayload>
  ): () => void {
    return socketManager.on(SOCKET_EVENTS.candidateSpeaking, listener);
  }
}

export const transcriptSocket = TranscriptSocketClient.getInstance();
