use crossbeam_channel::Receiver;
use kiss3d::window::Window;
use kiss3d::pollster::block_on;
use nalgebra::Point3;
use std::thread;
use std::time::Duration;

use crate::lidar::LidarFrame;

/// Spawn a thread that runs the kiss3d viewer and consumes LidarFrame values from `rx`.
/// Returns the JoinHandle for the spawned thread if the caller wants to join it later.
pub fn spawn_viewer(rx: Receiver<LidarFrame>) -> std::thread::JoinHandle<()> {
    thread::spawn(move || {
        let mut window = Window::new("LiDAR Viewer (in-process)");
        let mut points_mesh = Vec::<Point3<f32>>::new();
        let mut colors_mesh = Vec::<[u8; 3]>::new();

        while block_on(window.render()) {
            // Drain to latest frame
            let mut latest: Option<LidarFrame> = None;
            loop {
                match rx.try_recv() {
                    Ok(f) => latest = Some(f),
                    Err(crossbeam_channel::TryRecvError::Empty) => break,
                    Err(crossbeam_channel::TryRecvError::Disconnected) => return,
                }
            }

            if let Some(frame) = latest {
                // downsample to a reasonable limit
                let limit = 10000usize.min(frame.points.len());
                points_mesh.clear();
                colors_mesh.clear();
                if frame.points.is_empty() { continue; }
                let step = (frame.points.len() as f32 / limit as f32).max(1.0) as usize;
                for (i, p) in frame.points.iter().enumerate().step_by(step) {
                    points_mesh.push(Point3::new(p[0], p[1], p[2]));
                    if let Some(ref cs) = frame.colors {
                        colors_mesh.push(cs[i]);
                    } else {
                        colors_mesh.push([200, 200, 200]);
                    }
                }
            }

            for (i, p) in points_mesh.iter().enumerate() {
                let color = if i < colors_mesh.len() {
                    let c = colors_mesh[i];
                    Point3::new(c[0] as f32 / 255.0, c[1] as f32 / 255.0, c[2] as f32 / 255.0)
                } else {
                    Point3::new(1.0, 0.8, 0.2)
                };
                window.draw_point(p, &color);
            }

            // small sleep to reduce busy loop when there are no frames
            thread::sleep(Duration::from_millis(8));
        }
    })
}
