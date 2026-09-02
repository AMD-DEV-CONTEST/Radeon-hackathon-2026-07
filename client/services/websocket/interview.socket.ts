"use client";

import {
  SOCKET_EVENTS,
  type InterviewEndedPayload,
  type InterviewStartedPayload,
  type ProgressUpdatedPayload,
  type QuestionChangedPayload,
  type SocketPayloadMap,
} from "@/services/websocket/events";
import { socketManager } from "@/services/websocket/socket";

type SocketListener<T> = (payload: T) => void;

class InterviewSocketClient {
  private static instance: InterviewSocketClient | null = null;
  private interviewId: string | null = null;

  static getInstance(): InterviewSocketClient {
    InterviewSocketClient.instance ??= new InterviewSocketClient();
    return InterviewSocketClient.instance;
  }

  getInterviewId(): string | null {
    return this.interviewId;
  }

  isConnected(): boolean {
    return socketManager.isConnected();
  }

  connect(interviewId: string): void {
    if (this.interviewId && this.interviewId !== interviewId) {
      socketManager.emit(SOCKET_EVENTS.leaveInterview, {
        interviewId: this.interviewId,
      });
      socketManager.release();
    }

    this.interviewId = interviewId;
    socketManager.connect();
    socketManager.emit(SOCKET_EVENTS.joinInterview, { interviewId });
  }

  disconnect(): void {
    if (this.interviewId) {
      socketManager.emit(SOCKET_EVENTS.leaveInterview, {
        interviewId: this.interviewId,
      });
      socketManager.release();
    }
    this.interviewId = null;
  }

  onStarted(listener: SocketListener<InterviewStartedPayload>): () => void {
    return socketManager.on(SOCKET_EVENTS.interviewStarted, listener);
  }

  onEnded(listener: SocketListener<InterviewEndedPayload>): () => void {
    return socketManager.on(SOCKET_EVENTS.interviewEnded, listener);
  }

  onQuestionChanged(
    listener: SocketListener<QuestionChangedPayload>
  ): () => void {
    return socketManager.on(SOCKET_EVENTS.questionChanged, listener);
  }

  onProgressUpdated(
    listener: SocketListener<ProgressUpdatedPayload>
  ): () => void {
    return socketManager.on(SOCKET_EVENTS.progressUpdated, listener);
  }

  on<E extends keyof SocketPayloadMap>(
    event: E,
    listener: SocketListener<SocketPayloadMap[E]>
  ): () => void {
    return socketManager.on(event, listener);
  }

  emit<E extends keyof SocketPayloadMap>(
    event: E,
    payload: SocketPayloadMap[E]
  ): void {
    socketManager.emit(event, payload);
  }
}

export const interviewSocket = InterviewSocketClient.getInstance();
