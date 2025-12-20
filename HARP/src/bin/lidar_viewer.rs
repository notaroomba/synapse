use std::sync::mpsc::{self, TryRecvError};
use std::thread;
use std::time::Duration;

use kiss3d::window::Window;
use nalgebra::Point3;
use tungstenite::connect;
use url::Url;

use harp::lidar;
use kiss3d::pollster::block_on;

fn main() {
    // Channel for incoming binary frames
    let (tx, rx) = mpsc::channel::<Vec<u8>>();

    // Spawn a thread to connect to WebSocket server and forward binary messages
    thread::spawn(move || {
        let (mut socket, _resp) = connect(Url::parse("ws://127.0.0.1:8081").unwrap()).expect("Can't connect");
        println!("Connected to server for point cloud viewer");
        loop {
            match socket.read_message() {
                Ok(msg) => match msg {
                    tungstenite::Message::Binary(bin) => {
                        let _ = tx.send(bin);
                    }
                    tungstenite::Message::Text(txt) => {
                        let _ = tx.send(txt.into_bytes());
                    }
                    tungstenite::Message::Close(_) => break,
                    _ => {}
                },
                Err(e) => {
                    eprintln!("WebSocket read error: {}", e);
                    break;
                }
            }
        }
    });

    let mut window = Window::new("LiDAR Viewer (points)");
    let mut points_mesh = Vec::<Point3<f32>>::new();
    let mut colors_mesh = Vec::<[u8;3]>::new();

    // main render loop
    while block_on(window.render()) {
        // Try to get latest frame (non-blocking), process only latest available
        let mut latest_buf: Option<Vec<u8>> = None;
        loop {
            match rx.try_recv() {
                Ok(b) => latest_buf = Some(b),
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => break,
            }
        }

        if let Some(buf) = latest_buf {
            // Try binary framed format first, then JSON text lidar
            match lidar::parse_frame(&buf) {
                Ok((_hdr, pts, maybe_confs)) => {
                    // convert to Point3 and downsample if too many
                    let limit = 10000usize.min(pts.len());
                    points_mesh.clear();
                    colors_mesh.clear();
                    let step = (pts.len() as f32 / limit as f32).max(1.0) as usize;
                    for (i, p) in pts.iter().enumerate().step_by(step) {
                        points_mesh.push(Point3::new(p[0], p[1], p[2]));
                        // color from conf if present (grayscale)
                        if let Some(ref confs) = maybe_confs {
                            let c = confs.get(i).cloned().unwrap_or(200);
                            colors_mesh.push([c,c,c]);
                        } else {
                            colors_mesh.push([200,200,200]);
                        }
                    }
                }
                Err(_) => {
                    // try JSON lidar
                    match lidar::parse_lidar_json(&buf) {
                        Ok((pts, maybe_colors)) => {
                            let limit = 10000usize.min(pts.len());
                            points_mesh.clear();
                            colors_mesh.clear();
                            let step = (pts.len() as f32 / limit as f32).max(1.0) as usize;
                            for (i, p) in pts.iter().enumerate().step_by(step) {
                                points_mesh.push(Point3::new(p[0], p[1], p[2]));
                                if let Some(ref cs) = maybe_colors {
                                    colors_mesh.push(cs[i]);
                                } else {
                                    colors_mesh.push([200,200,200]);
                                }
                            }
                        }
                        Err(e) => eprintln!("parse_frame/json error in viewer: {}", e),
                    }
                }
            }
        }

        // draw points: small loop draw with per-point colors if available
        for (i, p) in points_mesh.iter().enumerate() {
            let color = if i < colors_mesh.len() {
                let c = colors_mesh[i];
                Point3::new(c[0] as f32 / 255.0, c[1] as f32 / 255.0, c[2] as f32 / 255.0)
            } else {
                Point3::new(1.0, 0.8, 0.2)
            };
            window.draw_point(p, &color);
        }

        // Sleep a bit to avoid hogging CPU when no frames
        thread::sleep(Duration::from_millis(8));
    }
}
