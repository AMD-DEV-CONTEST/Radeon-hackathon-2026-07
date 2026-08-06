package com.divric.parceltracking.service;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;

/**
 * Core AI orchestration service that uses Spring AI's ChatClient to process user messages.
 * Configures the AI model with parcel tracking tools (AgentTools) and a system prompt
 * that instructs the model on when to use tracking vs RAG search capabilities.
 * Logger: traces AI prompt calls and response generation for debugging conversations.
 */
@Service
public class AgentBrainService {

    private final ChatClient chatClient;

    
    public AgentBrainService(ChatClient.Builder chatClientBuilder, AgentTools agentTools) {
        this.chatClient = chatClientBuilder
            .defaultTools(agentTools)
            .defaultSystem("""
                You are a helpful parcel tracking assistant. You have access to tools that can:
                - Track parcels and get their delivery status (tabular data)
                - Search through documents using RAG (vector/embedding data)
                - Ingest new documents into the knowledge base
                
                When a user asks about a parcel, use the tracking tools.
                When they ask questions about parcel policies, procedures, or general knowledge, use the RAG search tool.
                """)
            .build();
    }

    public String processMessage(String message, String sessionId) {
        return chatClient.prompt()
            .user(user -> user.text(message).param("sessionId", sessionId))
            .call()
            .content();
    }
}