//! REST 路由表与 handler。每个路由调 client::Client::call，把 JSON-RPC result 包成 HTTP JSON。

use std::sync::Arc;

use axum::extract::State;
use axum::routing::{get, post};
use axum::Json;
use serde::{Deserialize, Serialize};

use client::Client;
use shared::protocol::Params;

use crate::error::HttpError;

/// 共享状态：RPC 客户端（线程安全，多 handler 复用）。
#[derive(Clone)]
pub struct AppState {
    client: Arc<Client>,
}

pub fn router(client: Client) -> axum::Router {
    let state = AppState { client: Arc::new(client) };
    axum::Router::new()
        .route("/healthz", get(healthz))
        .route("/state", get(get_state))
        .route("/thermal", get(get_thermal))
        .route("/cpu", get(get_cpu))
        .route("/memory", get(get_memory))
        .route("/disk", get(get_disk))
        .route("/net", get(get_net))
        .route("/bpu", get(get_bpu))
        .route("/refresh", post(refresh))
        .route("/exec", post(exec))
        .with_state(state)
}

async fn healthz(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    let v = s.client.call("ping", None).await.map_err(HttpError)?;
    Ok(Json(v))
}

async fn get_state(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    Ok(Json(s.client.call("get_state", None).await.map_err(HttpError)?))
}
async fn get_thermal(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    Ok(Json(s.client.call("get_thermal", None).await.map_err(HttpError)?))
}
async fn get_cpu(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    Ok(Json(s.client.call("get_cpu", None).await.map_err(HttpError)?))
}
async fn get_memory(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    Ok(Json(s.client.call("get_memory", None).await.map_err(HttpError)?))
}
async fn get_disk(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    Ok(Json(s.client.call("get_disk", None).await.map_err(HttpError)?))
}
async fn get_net(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    Ok(Json(s.client.call("get_net", None).await.map_err(HttpError)?))
}
async fn get_bpu(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    Ok(Json(s.client.call("get_bpu", None).await.map_err(HttpError)?))
}
async fn refresh(State(s): State<AppState>) -> Result<Json<serde_json::Value>, HttpError> {
    Ok(Json(s.client.call("refresh_state", None).await.map_err(HttpError)?))
}

/// POST /exec {"cmd":"..."} → exec_shell。
#[derive(Debug, Deserialize)]
struct ExecBody {
    cmd: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct ExecResp {
    exit: Option<i32>,
    stdout: String,
    stderr: String,
}

async fn exec(State(s): State<AppState>, Json(body): Json<ExecBody>) -> Result<Json<ExecResp>, HttpError> {
    let mut map = serde_json::Map::new();
    map.insert("cmd".into(), serde_json::Value::String(body.cmd));
    let v = s
        .client
        .call("exec_shell", Some(Params::Named(map)))
        .await
        .map_err(HttpError)?;
    // 把 JSON-RPC result 反序列化为结构化响应。
    let resp: ExecResp = serde_json::from_value(v)
        .unwrap_or(ExecResp { exit: None, stdout: String::new(), stderr: String::new() });
    Ok(Json(resp))
}
