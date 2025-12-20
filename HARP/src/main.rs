use futures_util::{ SinkExt, StreamExt };
use std::error::Error;
use tokio_tungstenite::tungstenite::{ Message, Error as WsError };
use tokio_tungstenite::accept_async;
use serde_json::Value;

use tokio::net::TcpListener;
use crossbeam_channel::unbounded;
use harp::viewer;
use harp::lidar::LidarFrame;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let addr = "0.0.0.0:8081";
    let listener = TcpListener::bind(addr).await?;
    println!("WebSocket server running on {}", addr);

    // Create an in-process channel. Spawn the viewer thread that consumes LidarFrames
    // unless the environment disables it via LIDAR_VIEWER=0 or LIDAR_VIEWER=false.
    let (tx, rx) = unbounded::<LidarFrame>();
    let viewer_enabled = std::env::var("LIDAR_VIEWER").map(|v| !(v == "0" || v.to_lowercase() == "false")).unwrap_or(true);
    let _viewer_handle = if viewer_enabled {
        Some(viewer::spawn_viewer(rx))
    } else {
        println!("LIDAR viewer disabled via LIDAR_VIEWER env var");
        None
    };

    loop {
        let (stream, peer_addr) = listener.accept().await?;
        let tx = tx.clone();
        tokio::spawn(async move {
            if let Err(e) = handle_connection(stream, tx).await {
                // Ignore common client-side connection resets that don't perform a close handshake
                let is_ignored = match &e {
                    WsError::Protocol(p) =>
                        format!("{}", p).contains("Connection reset without closing handshake"),
                    WsError::Io(io_err) if io_err.kind() == std::io::ErrorKind::ConnectionReset =>
                        true,
                    _ => false,
                };

                if !is_ignored {
                    eprintln!("Connection error ({}): {}", peer_addr, e);
                }
            }
        });
    }
}

async fn handle_connection(stream: tokio::net::TcpStream, tx: crossbeam_channel::Sender<LidarFrame>) -> Result<(), WsError> {
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
                // Try to parse as a JSON envelope and specifically support `"type":"lidar"` messages
                match harp::lidar::parse_lidar_json(text.as_bytes()) {
                    Ok((pts, maybe_colors)) => {
                        println!("Parsed lidar JSON frame: count={} colors={}", pts.len(), maybe_colors.as_ref().map(|v| v.len()).unwrap_or(0));
                        let ack = format!("ACK lidar points={}", pts.len());
                        let _ = write.send(Message::Text(ack.into())).await?;
                        // forward to in-process viewer
                        let lf = harp::lidar::to_lidar_frame_from_json(pts, maybe_colors);
                        let _ = tx.send(lf);
                    }
                    Err(_) => {
                        // Not a lidar JSON message - try to extract "type" for logging
                        match serde_json::from_str::<Value>(&text) {
                            Ok(val) => {
                                if let Some(t) = val.get("type").and_then(|v| v.as_str()) {
                                    println!("From Unity: type={}", t);
                                    if t == "headset" {
                                        println!("Headset data: {}", val.get("data").unwrap_or(&Value::Null));
                                    }
                                } else {
                                    println!("From Unity (text): {}", text);
                                }
                            }
                            Err(_) => println!("From Unity (text): {}", text),
                        }
                        let _ = write.send(Message::Text("ACK".into())).await?;
                    }
                }
            }
            Message::Binary(bin) => {
                println!("From Unity (binary) - {} bytes", bin.len());
                // Try to parse as our lidar point-cloud frame
                match harp::lidar::parse_frame(&bin) {
                    Ok((hdr, pts, maybe_confs)) => {
                        println!("Parsed frame: type={} count={} seq={:?} last={} layout={}",
                            hdr.msg_type, hdr.count, hdr.seq, hdr.is_last_chunk.unwrap_or(false), hdr.layout);
                        // For now send a short ack indicating count
                        let ack = format!("ACK points={}", pts.len());
                        let _ = write.send(Message::Text(ack.into())).await?;
                        // forward to in-process viewer
                        let lf = harp::lidar::to_lidar_frame_from_parsed(&hdr, pts, maybe_confs);
                        let _ = tx.send(lf);
                    }
                    Err(e) => {
                        eprintln!("Binary parse error: {}", e);
                        let _ = write.send(Message::Text("ACK".into())).await?;
                    }
                }
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
