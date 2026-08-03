#[tokio::main]
async fn main() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    println!("Port: {}", port);
    tokio::spawn(async move {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        loop {
            if let Ok((mut stream, _)) = listener.accept().await {
                let mut buf = [0; 1024];
                let _ = stream.read(&mut buf).await;
                let body = "<!DOCTYPE html><html><body><div id=\"dashboard-ready\"></div></body></html>";
                let resp = format!("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n{}", body);
                let _ = stream.write_all(resp.as_bytes()).await;
            }
        }
    });
    tokio::time::sleep(std::time::Duration::from_secs(60)).await;
}
