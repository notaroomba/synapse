use futures_util::{SinkExt, StreamExt};
use std::error::Error;
use tokio_tungstenite::tungstenite::{Message, Error as WsError};
use tokio_tungstenite::accept_async;

use tokio::net::TcpListener;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let addr = "0.0.0.0:8081";
    let listener = TcpListener::bind(addr).await?;
    println!("WebSocket server running on {}", addr);

    loop {
        let (stream, peer_addr) = listener.accept().await?;
        tokio::spawn(async move {
            if let Err(e) = handle_connection(stream).await {
                // Ignore common client-side connection resets that don't perform a close handshake
                let is_ignored = match &e {
                    WsError::Protocol(p) => format!("{}", p).contains("Connection reset without closing handshake"),
                    WsError::Io(io_err) if io_err.kind() == std::io::ErrorKind::ConnectionReset => true,
                    _ => false,
                };

                if !is_ignored {
                    eprintln!("Connection error ({}): {}", peer_addr, e);
                }
            }
        });
    }
}

async fn handle_connection(stream: tokio::net::TcpStream) -> Result<(), WsError> {
    let peer = stream.peer_addr().ok();
    let ws_stream = accept_async(stream).await?;
    if let Some(p) = peer {
        println!("Unity connected: {}", p);
    } else {
        println!("Unity connected");
    }

    let (mut write, mut read) = ws_stream.split();

    while let Some(msg) = read.next().await {
        let msg = msg?;
        match msg {
            Message::Text(text) => {
                println!("From Unity: {}", text);
                write.send(Message::Text("ACK".into())).await?;
            }
            Message::Binary(bin) => {
                println!("From Unity (binary) - {} bytes", bin.len());
                write.send(Message::Text("ACK".into())).await?;
            }
            Message::Close(frame) => {
                println!("Connection closed: {:?}", frame);
                // Reply with a close if desired and then break
                let _ = write.send(Message::Close(frame)).await;
                break;
            }
            Message::Ping(payload) => {
                // Respond to ping
                let _ = write.send(Message::Pong(payload)).await;
            }
            Message::Pong(_) => {}
            _ => {}
        }
    }

    Ok(())
}
