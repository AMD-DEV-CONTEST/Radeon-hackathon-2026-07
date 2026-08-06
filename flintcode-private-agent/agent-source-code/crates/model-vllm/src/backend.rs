//! Unified model backend selected from a [`ModelProfile`].

use anyhow::Result;
use tokio::sync::mpsc;

use agent_core::error::AgentError;
use agent_core::event::ModelResult;

use crate::client::{AvailableModel, StreamEvent, VllmClient};
use crate::profile::ModelProfile;
use crate::simulator::SimulatorClient;
use agent_core::agent_loop::ModelBackend;
use agent_core::chat::{ChatMessage, Tool, ToolChoice};

/// Runtime model backend used by Pipeline, CLI, and TUI.
pub enum ModelClient {
    Vllm(VllmClient),
    Simulator(SimulatorClient),
}

impl ModelClient {
    /// Select and initialize the backend configured by the profile.
    pub fn from_profile(profile: ModelProfile) -> std::result::Result<Self, AgentError> {
        if profile.simulator.enabled {
            let scenario = profile.simulator.scenario.as_deref().ok_or_else(|| {
                AgentError::InfrastructureError {
                    detail: "Simulator is enabled but no scenario is configured".to_string(),
                }
            })?;
            return SimulatorClient::load(profile.clone(), scenario).map(Self::Simulator);
        }
        Ok(Self::Vllm(VllmClient::new(profile)))
    }

    pub async fn health_check(&self) -> Result<bool> {
        match self {
            Self::Vllm(client) => client.health_check().await,
            Self::Simulator(_) => Ok(true),
        }
    }

    /// List model IDs exposed by the active backend.
    pub async fn list_models(&self) -> std::result::Result<Vec<AvailableModel>, AgentError> {
        match self {
            Self::Vllm(client) => client.list_models().await,
            Self::Simulator(client) => Ok(vec![AvailableModel {
                id: client.profile().model.name.clone(),
                owned_by: "simulator".to_string(),
            }]),
        }
    }

    pub async fn chat(
        &self,
        messages: Vec<ChatMessage>,
        tools: Option<Vec<Tool>>,
        tool_choice: Option<ToolChoice>,
    ) -> std::result::Result<ModelResult, AgentError> {
        match self {
            Self::Vllm(client) => client.chat(messages, tools, tool_choice).await,
            Self::Simulator(client) => client.chat(messages, tools, tool_choice).await,
        }
    }
}

impl ModelBackend for ModelClient {
    async fn chat(
        &self,
        messages: Vec<ChatMessage>,
        tools: Option<Vec<Tool>>,
    ) -> Result<ModelResult, AgentError> {
        self.chat(messages, tools, None).await
    }
}

impl ModelClient {
    pub async fn chat_stream(
        &self,
        messages: Vec<ChatMessage>,
    ) -> std::result::Result<mpsc::Receiver<StreamEvent>, AgentError> {
        match self {
            Self::Vllm(client) => client.chat_stream(messages).await,
            Self::Simulator(client) => client.chat_stream(messages).await,
        }
    }

    pub fn profile(&self) -> &ModelProfile {
        match self {
            Self::Vllm(client) => client.profile(),
            Self::Simulator(client) => client.profile(),
        }
    }

    pub fn backend_label(&self) -> &'static str {
        match self {
            Self::Vllm(_) => "vLLM",
            Self::Simulator(_) => "SIMULATOR",
        }
    }

    pub fn simulator(&self) -> Option<&SimulatorClient> {
        match self {
            Self::Simulator(client) => Some(client),
            Self::Vllm(_) => None,
        }
    }
}
