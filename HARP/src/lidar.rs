use anyhow::Result;
use byteorder::{LittleEndian, ReadBytesExt};
use serde::Deserialize;
use std::io::Cursor;

#[derive(Deserialize, Debug, Clone)]
pub struct Header {
    pub version: String,
    #[serde(rename = "type")]
    pub msg_type: String,
    pub frame_id: Option<String>,
    pub timestamp: Option<u64>,
    pub count: usize,
    pub layout: String,
    pub stride: usize,
    pub endianness: Option<String>,
    pub seq: Option<u32>,
    pub is_last_chunk: Option<bool>,
    pub compression: Option<String>,
}

/// Parse a single framed message from the binary format:
/// [u32 header_len_le][header_json bytes][payload bytes]
/// Returns (header, points, optional confidences)
pub struct LidarFrame {
    pub points: Vec<[f32;3]>,
    pub colors: Option<Vec<[u8;3]>>,
    pub timestamp: Option<u64>,
    pub frame_id: Option<String>,
}

pub fn parse_frame(buf: &[u8]) -> Result<(Header, Vec<[f32; 3]>, Option<Vec<u8>>)> {
    let mut cur = Cursor::new(buf);
    let header_len = cur.read_u32::<LittleEndian>()? as usize;
    if buf.len() < 4 + header_len {
        anyhow::bail!("buffer too small for header_len");
    }
    let header_bytes = &buf[4..4 + header_len];
    let header: Header = serde_json::from_slice(header_bytes)?;
    let payload = &buf[4 + header_len..];

    // For now, don't handle compression in these tests (could be extended)
    match header.layout.as_str() {
        "float32_xyz" => {
            // payload is consecutive float32 x,y,z
            let mut pcur = Cursor::new(payload);
            let mut points = Vec::with_capacity(header.count);
            for _ in 0..header.count {
                let x = pcur.read_f32::<LittleEndian>()?;
                let y = pcur.read_f32::<LittleEndian>()?;
                let z = pcur.read_f32::<LittleEndian>()?;
                points.push([x, y, z]);
            }
            Ok((header, points, None))
        }
        "float32_xyz_conf" => {
            // stride expected e.g. 16: 3*4 bytes + 1 byte conf + 3 bytes padding
            let mut pcur = Cursor::new(payload);
            let mut points = Vec::with_capacity(header.count);
            let mut confs = Vec::with_capacity(header.count);
            for _ in 0..header.count {
                let x = pcur.read_f32::<LittleEndian>()?;
                let y = pcur.read_f32::<LittleEndian>()?;
                let z = pcur.read_f32::<LittleEndian>()?;
                let conf = pcur.read_u8()?;
                // skip padding bytes if any (stride - 13)
                let pad = header.stride.saturating_sub(13);
                for _ in 0..pad {
                    let _ = pcur.read_u8();
                }
                points.push([x, y, z]);
                confs.push(conf);
            }
            Ok((header, points, Some(confs)))
        }
        other => anyhow::bail!("unsupported layout: {}", other),
    }
}

/// Parse a text WebSocket JSON message of the form:
/// { "type": "lidar", "data": [ points_array, colors_array ] }
/// where points_array = [[x,y,z], ...] and colors_array = [[r,g,b], ...]
/// Colors may be 0-255 integers or 0..1 floats; returns Option<Vec<[u8;3]>> for colors.
pub fn parse_lidar_json(buf: &[u8]) -> Result<(Vec<[f32; 3]>, Option<Vec<[u8; 3]>>)> {
    let v: serde_json::Value = serde_json::from_slice(buf)?;
    let t = v.get("type").and_then(|t| t.as_str()).ok_or_else(|| anyhow::anyhow!("missing type"))?;
    if t != "lidar" {
        anyhow::bail!("not a lidar message: type={}", t);
    }
    let data = v.get("data").ok_or_else(|| anyhow::anyhow!("missing data"))?;
    let arr = data.as_array().ok_or_else(|| anyhow::anyhow!("data must be an array"))?;
    if arr.len() != 2 {
        anyhow::bail!("data must be [points, colors]");
    }
    let points_val = &arr[0];
    let colors_val = &arr[1];

    let points_array = points_val.as_array().ok_or_else(|| anyhow::anyhow!("points not array"))?;
    let mut points = Vec::with_capacity(points_array.len());
    for p in points_array.iter() {
        let pv = p.as_array().ok_or_else(|| anyhow::anyhow!("point not array"))?;
        if pv.len() != 3 { anyhow::bail!("point must have 3 elements"); }
        let x = pv[0].as_f64().ok_or_else(|| anyhow::anyhow!("point coordinate not numeric"))? as f32;
        let y = pv[1].as_f64().ok_or_else(|| anyhow::anyhow!("point coordinate not numeric"))? as f32;
        let z = pv[2].as_f64().ok_or_else(|| anyhow::anyhow!("point coordinate not numeric"))? as f32;
        points.push([x, y, z]);
    }

    let colors_array = colors_val.as_array().ok_or_else(|| anyhow::anyhow!("colors not array"))?;
    if colors_array.len() != points.len() {
        anyhow::bail!("colors length must match points length");
    }
    let mut colors = Vec::with_capacity(colors_array.len());
    for c in colors_array.iter() {
        let cv = c.as_array().ok_or_else(|| anyhow::anyhow!("color not array"))?;
        if cv.len() != 3 { anyhow::bail!("color must have 3 elements"); }
        // Accept either integer 0..255 or float 0..1
        let mut rgb = [0u8; 3];
        for i in 0..3 {
            if let Some(u) = cv[i].as_u64() {
                rgb[i] = u.min(255) as u8;
            } else if let Some(f) = cv[i].as_f64() {
                // assume 0..1
                let ff = (f * 255.0).round();
                rgb[i] = ff.max(0.0).min(255.0) as u8;
            } else {
                anyhow::bail!("color component not numeric");
            }
        }
        colors.push(rgb);
    }

    Ok((points, Some(colors)))
}

/// Convert parsed binary header+points/conf to a `LidarFrame`.
pub fn to_lidar_frame_from_parsed(header: &Header, points: Vec<[f32;3]>, confs: Option<Vec<u8>>) -> LidarFrame {
    let colors = confs.map(|cs| cs.into_iter().map(|c| [c,c,c]).collect());
    LidarFrame {
        points,
        colors,
        timestamp: header.timestamp,
        frame_id: header.frame_id.clone(),
    }
}

/// Build from JSON-parsed points/colors
pub fn to_lidar_frame_from_json(points: Vec<[f32;3]>, colors: Option<Vec<[u8;3]>>) -> LidarFrame {
    LidarFrame {
        points,
        colors,
        timestamp: None,
        frame_id: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use byteorder::{LittleEndian, WriteBytesExt};

    fn make_test_frame(count: usize) -> Vec<u8> {
        // Create header and payload with float32_xyz
        let header = serde_json::json!({
            "version":"1.0",
            "type":"point_cloud",
            "frame_id":"t1",
            "timestamp":1700000000000u64,
            "count":count,
            "layout":"float32_xyz",
            "stride":12,
            "endianness":"le",
            "seq":0,
            "is_last_chunk": true,
            "compression": null
        });
        let header_bytes = header.to_string().into_bytes();
        let mut out = Vec::new();
        out.write_u32::<LittleEndian>(header_bytes.len() as u32).unwrap();
        out.extend_from_slice(&header_bytes);

        // payload: count * 3 float32 values
        for i in 0..count {
            out.write_f32::<LittleEndian>(i as f32 + 0.1).unwrap();
            out.write_f32::<LittleEndian>(i as f32 + 0.2).unwrap();
            out.write_f32::<LittleEndian>(i as f32 + 0.3).unwrap();
        }
        out
    }

    #[test]
    fn test_parse_simple() {
        let buf = make_test_frame(10);
        let (h, pts, confs) = parse_frame(&buf).unwrap();
        assert_eq!(h.count, 10);
        assert_eq!(pts.len(), 10);
        assert!(confs.is_none());
        assert!((pts[3][0] - 3.1).abs() < 1e-6);
    }

    #[test]
    fn test_parse_lidar_json() {
        let msg = serde_json::json!({
            "type": "lidar",
            "data": [
                [[1.0,2.0,3.0],[4.0,5.0,6.0]],
                [[255,0,0],[0,255,0]]
            ]
        });
        let s = msg.to_string();
        let (pts, colors) = parse_lidar_json(s.as_bytes()).unwrap();
        assert_eq!(pts.len(), 2);
        let cols = colors.unwrap();
        assert_eq!(cols[0], [255,0,0]);
        assert_eq!(cols[1], [0,255,0]);
        assert!((pts[1][2] - 6.0).abs() < 1e-6);
    }
}

