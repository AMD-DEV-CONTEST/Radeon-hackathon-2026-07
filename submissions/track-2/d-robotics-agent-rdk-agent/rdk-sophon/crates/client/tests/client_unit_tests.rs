//! Client 单元测试：用 StubTransport pair 测 id 匹配、超时、notification 不误当响应。

use std::time::Duration;
use shared::protocol::{Id, JsonRpcMessage};
use infra::{StubTransport, Transport};
use client::{Client, ClientError};

#[tokio::test]
async fn call_returns_matching_response() {
    // 客户端发 ping，服务端侧回同 id 的响应。
    let (mut server_side, client_side) = StubTransport::pair();
    let client = Client::new(Box::new(client_side)).with_timeout(Duration::from_secs(2));

    let call_fut = client.call("ping", None);
    // 服务端侧读到请求，回响应。
    let server_fut = async move {
        let req = server_side.recv().await.unwrap().unwrap();
        let id = match req { JsonRpcMessage::Request(r) => r.id, _ => panic!("应为请求") };
        let resp = JsonRpcMessage::new_response(id, serde_json::json!({"pong": true}));
        server_side.send(&resp).await.unwrap();
    };
    let (result, _) = tokio::join!(call_fut, server_fut);
    let v = result.unwrap();
    assert_eq!(v["pong"], serde_json::json!(true));
}

#[tokio::test]
async fn call_times_out_when_no_response() {
    // 服务端不回，客户端在超时后报 Timeout。
    let (_server_side, client_side) = StubTransport::pair();
    let client = Client::new(Box::new(client_side)).with_timeout(Duration::from_millis(100));
    let err = client.call("ping", None).await.unwrap_err();
    assert!(matches!(err, ClientError::Timeout { .. }));
    let _ = Id::Num(0);
}

#[tokio::test]
async fn notification_not_treated_as_response() {
    // 服务端先推一条 telemetry notification，再回响应。客户端应跳过 notification 等到响应。
    let (mut server_side, client_side) = StubTransport::pair();
    let client = Client::new(Box::new(client_side)).with_timeout(Duration::from_secs(2));

    let call_fut = client.call("get_state", None);
    let server_fut = async move {
        let req = server_side.recv().await.unwrap().unwrap();
        let id = match req { JsonRpcMessage::Request(r) => r.id, _ => panic!("应为请求") };
        // 先推一条 telemetry notification（无 id）。
        let notif = JsonRpcMessage::new_notification("telemetry", None);
        server_side.send(&notif).await.unwrap();
        // 再回响应。
        let resp = JsonRpcMessage::new_response(id, serde_json::json!({"ok": true}));
        server_side.send(&resp).await.unwrap();
    };
    let (result, _) = tokio::join!(call_fut, server_fut);
    let v = result.unwrap();
    assert_eq!(v["ok"], serde_json::json!(true));
}

#[tokio::test]
async fn server_error_propagates() {
    // 服务端回 error，客户端应返回 ClientError::Server。
    let (mut server_side, client_side) = StubTransport::pair();
    let client = Client::new(Box::new(client_side)).with_timeout(Duration::from_secs(2));

    let call_fut = client.call("exec_shell", None);
    let server_fut = async move {
        let req = server_side.recv().await.unwrap().unwrap();
        let id = match req { JsonRpcMessage::Request(r) => r.id, _ => panic!("应为请求") };
        let err = shared::protocol::Error::new(shared::protocol::ErrorCode::ShellDisabled, "disabled");
        let resp = JsonRpcMessage::new_error(id, err);
        server_side.send(&resp).await.unwrap();
    };
    let (result, _) = tokio::join!(call_fut, server_fut);
    let err = result.unwrap_err();
    match err {
        ClientError::Server { code, message } => {
            assert_eq!(code, shared::protocol::ErrorCode::ShellDisabled as i32);
            assert!(message.contains("disabled"));
        }
        _ => panic!("应为 Server 错误"),
    }
}
