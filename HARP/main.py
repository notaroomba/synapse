import asyncio
import argparse
import json
import logging
import os
import websockets
from websockets.exceptions import PayloadTooBig
from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

# Global robot reference (set when a handler connects)
GLOBAL_ROBOT = None

# Optional ROS2 support
import threading
try:
    import rclpy
    from std_msgs.msg import String as RosString
except Exception:
    rclpy = None
    RosString = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Load settings.json early so CLI defaults and runtime logic can reference it.
CONFIG = {}
try:
    _settings_path = os.path.join(os.path.dirname(__file__), "settings.json")
    if os.path.isfile(_settings_path):
        with open(_settings_path, "r") as _sf:
            CONFIG = json.load(_sf)
except Exception:
    CONFIG = {}

# WebRTC optional dependencies — set to None if not available so code can gracefully handle missing libs.
RTCPeerConnection = None
VideoStreamTrack = None
av = None
CameraVideoTrack = None
OpenCVCameraWrapper = None
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    import av
    # Keep CameraVideoTrack / OpenCVCameraWrapper as None here — project-specific wrappers can be implemented if needed.
except Exception:
    # Not available; leave variables as None
    pass


def parse_unity_line(line: str) -> dict | None:
    """Extract JSON object from a line and parse it."""
    try:
        start = line.index("{")
        raw = line[start:]
        return json.loads(raw)
    except ValueError:
        return None
    except json.JSONDecodeError:
        logging.warning("Failed to decode JSON from line: %s", line)
        return None


def unity_to_so101_action(msg: dict, robot=None) -> dict:
    """Map incoming Unity 0-180 values to the robot's motor range (in degrees when possible).

    If `robot` is provided and has calibration, map 0->motor_min and 180->motor_max (in the robot's
    normalized units, e.g., degrees when `use_degrees=True`). Otherwise fall back to mapping to
    [0, 180].
    """
    # Use robot default motor names when available (e.g. those in harp_arm.json). If `robot` is None
    # fall back to a sensible set.
    if robot is not None and hasattr(robot, "bus"):
        motor_names = list(robot.bus.motors.keys())
    else:
        motor_names = [
            "shoulder_pan",
            "shoulder_lift",
            "elbow_flex",
            "wrist_flex",
            "wrist_roll",
            "gripper",
        ]

    action: dict[str, float] = {}

    # Try to build per-motor normalized mins/maxes if robot calibration is available
    name_to_min_norm: dict[str, float] = {}
    name_to_max_norm: dict[str, float] = {}
    try:
        if robot is not None and hasattr(robot, "bus") and robot.bus.calibration:
            id_to_min = {robot.bus.motors[motor].id: robot.bus.calibration[motor].range_min for motor in robot.bus.motors}
            id_to_max = {robot.bus.motors[motor].id: robot.bus.calibration[motor].range_max for motor in robot.bus.motors}
            id_to_min_norm = robot.bus._normalize(id_to_min)
            id_to_max_norm = robot.bus._normalize(id_to_max)
            # convert to motor-name keyed dicts
            name_to_min_norm = {motor: id_to_min_norm[robot.bus.motors[motor].id] for motor in robot.bus.motors}
            name_to_max_norm = {motor: id_to_max_norm[robot.bus.motors[motor].id] for motor in robot.bus.motors}
    except Exception:
        logging.exception("Could not compute normalized min/max from calibration; falling back to [-180,180]")

    # Map incoming values by centering at the motor's minimum. For calibrated motors
    # compute raw_target = min + (v/180) * (max - min) where v in [-90, 90]. Do not clamp inputs.
    ids_to_raw: dict[int, float] = {}
    for motor in motor_names:
        if motor not in msg:
            continue
        raw_val = msg[motor]
        try:
            v = float(raw_val)
        except (TypeError, ValueError):
            logging.warning("Invalid numeric value for %s: %r", motor, raw_val)
            continue

        # If motor has calibration, compute a raw encoder target centered on the minimum
        if robot is not None and hasattr(robot, "bus") and motor in robot.bus.motors and motor in robot.bus.calibration:
            motor_id = robot.bus.motors[motor].id
            cal = robot.bus.calibration[motor]
            raw_min = cal.range_min
            raw_max = cal.range_max
            span = raw_max - raw_min
            raw_target = raw_min + (v / 180.0) * span
            ids_to_raw[motor_id] = raw_target
        else:
            # No calibration: pass through degrees (-90..90 expected by Unity)
            action[f"{motor}.pos"] = v

    # Normalize raw targets through the bus and set action values
    if ids_to_raw and robot is not None and hasattr(robot, "bus"):
        try:
            ids_to_norm = robot.bus._normalize({int(k): int(v) for k, v in ids_to_raw.items()})
            for motor in motor_names:
                if motor in robot.bus.motors:
                    mid = robot.bus.motors[motor].id
                    if mid in ids_to_norm:
                        action[f"{motor}.pos"] = ids_to_norm[mid]
        except Exception:
            logging.exception("Failed to normalize raw targets; keeping fallback degree values for uncalibrated motors")


    # Defaults for joints Unity doesn't provide
    action.setdefault("wrist_roll.pos", 0.0)
    action.setdefault("gripper.pos", 0.0)
    return action









async def handler(websocket):
    print("Unity connected")

    # Create and connect robot (blocking calls done inside the handler as requested)
    from pathlib import Path

    harp_path = Path(args.calibration_file)
    if harp_path.is_file():
        logging.info("Found %s, using it to configure robot calibration.", harp_path)
        cfg = SO101FollowerConfig(
            port=args.port,
            id=harp_path.stem,
            calibration_dir=harp_path.parent,
            use_degrees=True,
        )
    else:
        logging.info("Calibration file %s not found; will create it if requested.", harp_path)
        cfg = SO101FollowerConfig(port=args.port, id=harp_path.stem, calibration_dir=harp_path.parent, use_degrees=True)

    robot = SO101Follower(cfg)

    global GLOBAL_ROBOT
    try:
        logging.info("Connecting to SO-101 on %s", cfg.port)
        robot.connect()
        GLOBAL_ROBOT = robot
    except Exception:
        logging.exception("Failed to connect to SO-101")
        await websocket.send("ERROR: failed to connect robot")
        return


    # If requested, run interactive calibration now and save to the specified calibration file
    if args.recalibrate:
        try:
            logging.info("Starting interactive calibration (this may ask for user input)...")
            robot.calibrate()
            logging.info("Calibration finished and saved to %s", robot.calibration_fpath)
            try:
                await websocket.send("CALIBRATED")
            except Exception:
                logging.debug("Could not send CALIBRATED message to client")
        except Exception:
            logging.exception("Calibration failed")
            try:
                await websocket.send("ERROR: calibration failed")
            except Exception:
                logging.debug("Could not send ERROR message to client")

    # Configure per-motor max_relative_target to avoid overloads using calibration ranges.
    # We set a conservative fraction of the normalized per-motor range (5% default).
    try:
        FRACTION = 0.05
        if hasattr(robot, "bus") and robot.bus.calibration:
            # Build raw maps for mins/maxs keyed by id
            id_to_min = {robot.bus.motors[motor].id: robot.bus.calibration[motor].range_min for motor in robot.bus.motors}
            id_to_max = {robot.bus.motors[motor].id: robot.bus.calibration[motor].range_max for motor in robot.bus.motors}
            norm_min = robot.bus._normalize(id_to_min)
            norm_max = robot.bus._normalize(id_to_max)
            max_relative = {}
            for motor_name, motor_obj in robot.bus.motors.items():
                id_ = motor_obj.id
                span = abs(norm_max[id_] - norm_min[id_])
                # Avoid zero span
                cap = max(1e-3, span * FRACTION)
                max_relative[motor_name] = cap
            robot.config.max_relative_target = max_relative
            logging.info("Set per-motor max_relative_target from calibration: %s", max_relative)
    except Exception:
        logging.exception("Failed to compute safety limits from calibration; continuing without per-motor limiter")

    try:
        async for message in websocket:

            msg = parse_unity_line(message)
            if msg is None:
                await websocket.send("IGNORED: no json")
                continue

            # Only act on headset type messages for left arm (adjust if needed)
            # WebRTC offer handling over websocket (client sends {"type":"webrtc-offer","sdp": <offer>, "camera": <optional>})
            if args.webrtc and isinstance(msg, dict) and msg.get("type") == "webrtc-offer":
                if RTCPeerConnection is None or VideoStreamTrack is None or av is None:
                    await websocket.send(json.dumps({"type": "webrtc-answer", "error": "webrtc dependencies missing"}))
                else:
                    try:
                        sdp = msg.get("sdp")
                        # Determine camera preference: explicit in message > CLI arg > settings.json camera_name > camera_index
                        cam_name = msg.get("camera") or args.stream_camera_name or CONFIG.get("camera_name")
                        # choose camera: robot camera preferred
                        cam = None
                        if cam_name and hasattr(robot, "cameras") and cam_name in robot.cameras:
                            cam = robot.cameras[cam_name]
                        elif cam_name and cam_name.startswith("opencv:"):
                            idx = int(cam_name.split(":", 1)[1])
                            cam = OpenCVCameraWrapper(idx)
                        elif CONFIG.get("camera_index") is not None:
                            cam_idx = int(CONFIG.get("camera_index"))
                            cam = OpenCVCameraWrapper(cam_idx)
                            cam_name = f"opencv:{cam_idx}"

                        if cam is None:
                            await websocket.send(json.dumps({"type": "webrtc-answer", "error": "no camera available"}))
                        else:
                            pc = RTCPeerConnection()
                            track = CameraVideoTrack(cam, fps=args.webrtc_fps)
                            pc.addTrack(track)

                            offer = RTCSessionDescription(sdp=sdp, type="offer")
                            await pc.setRemoteDescription(offer)
                            answer = await pc.createAnswer()
                            await pc.setLocalDescription(answer)

                            # keep track of pcs to close them later
                            if not hasattr(websocket, "peer_conns"):
                                websocket.peer_conns = []
                            websocket.peer_conns.append(pc)

                            await websocket.send(json.dumps({"type": "webrtc-answer", "sdp": pc.localDescription.sdp}))
                    except Exception:
                        logging.exception("Failed to handle webrtc offer")
                        await websocket.send(json.dumps({"type": "webrtc-answer", "error": "internal"}))
                continue

            if msg.get("type") != "headset" or msg.get("arm") != "left":
                await websocket.send("IGNORED: not matching type/arm")
                continue

            action = unity_to_so101_action(msg, robot)
            if not action:
                await websocket.send("IGNORED: no action")
                continue

            try:
                sent = robot.send_action(action)
                logging.info("Sent action: %s -> actual: %s", action, sent)
                await websocket.send("ACK")
            except Exception:
                logging.exception("Failed to send action to SO-101")
                await websocket.send("ERROR: send failed")

    except PayloadTooBig as e:
        # This happens when an incoming frame exceeds the server's max_size. We try to notify the client and close.
        logging.warning("Received oversized payload from client: %s", e)
        try:
            await websocket.send("ERROR: payload too big")
        except Exception:
            logging.debug("Failed to send payload-too-big message to client")
    except Exception as e:
        logging.exception("Websocket handler error: %s", e)
    finally:
        # Close any active WebRTC PeerConnections for this websocket
        try:
            if hasattr(websocket, "peer_conns"):
                for pc in websocket.peer_conns:
                    try:
                        await pc.close()
                    except Exception:
                        logging.debug("Error closing PeerConnection")
        except Exception:
            logging.debug("PeerConnection cleanup failed")
        try:
            GLOBAL_ROBOT = None
            robot.disconnect()
            logging.info("Robot disconnected")
        except Exception:
            logging.exception("Error disconnecting robot")


# Parse CLI args early so handler can use them
parser = argparse.ArgumentParser(description="Unity → SO-101 WebSocket bridge")
parser.add_argument("--recalibrate", action="store_true", help="Run interactive calibration on startup and save to calibration file")
default_calib = os.path.join(CONFIG.get("calibrations_dir", "calibrations"), "follower.json")
parser.add_argument("--calibration-file", default=default_calib, help=f"Calibration file to read/write (default: {default_calib})")
# Load JSON settings (settings.json) if present; fall back to sensible defaults
CONFIG = {}
try:
    _settings_path = os.path.join(os.path.dirname(__file__), "settings.json")
    if os.path.isfile(_settings_path):
        with open(_settings_path, "r") as _sf:
            CONFIG = json.load(_sf)
except Exception:
    CONFIG = {}

DEFAULT_PORT = CONFIG.get("follower_port", os.environ.get("FOLLOWER_PORT", "/dev/ttyACM1"))
parser.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port for the SO-101 arm (default: {DEFAULT_PORT})")

# WebRTC streaming options
parser.add_argument("--webrtc", action="store_true", help="Enable WebRTC video streaming for camera previews")
parser.add_argument("--stream-camera-name", default=None, help="Name of the camera to stream (e.g., 'wrist' or 'opencv:0')")
parser.add_argument("--webrtc-fps", type=int, default=int(CONFIG.get("webrtc_fps", 15)), help="Frames per second for WebRTC camera track")

parser.add_argument("--enable-tcp", action="store_true", help="Enable ROS TCP endpoint to receive JSON messages from Unity")
parser.add_argument("--tcp-port", type=int, default=9090, help="Port for the TCP endpoint (default: 9090)")
parser.add_argument("--ros-enable", dest="ros_enable", action="store_true", default=True, help="Publish incoming TCP messages to a ROS2 topic (requires rclpy). Enabled by default.")
parser.add_argument("--no-ros", dest="ros_enable", action="store_false", help="Disable ROS2 publishing (opposite of --ros-enable)")
parser.add_argument("--ros-topic", default="/unity", help="ROS2 topic to publish incoming JSON strings to (default: /unity)")
parser.add_argument("--ros-node", default="harp_bridge", help="ROS2 node name (default: harp_bridge)")
args = parser.parse_args()











async def main():
    tcp_server = None
    tcp_ros_helper = None

    if args.enable_tcp:
        tcp_server, tcp_ros_helper = await _start_tcp_server()

    try:
        async with websockets.serve(
            handler,
            "0.0.0.0",
            8081,
            max_size=None,
            ping_interval=None,  # disable server pings
            ping_timeout=None,   # don't time out on missed pongs (infinite keepalive)
        ):
            print("WebSocket server running on port 8081 (accepting large frames, infinite keepalive)")
            await asyncio.Future()  # keep alive
    finally:
        # Cleanup TCP server
        if args.enable_tcp:
            await _stop_tcp_server(tcp_server, tcp_ros_helper)


# TCP server handling for Unity/Meta Quest connections
async def _tcp_client_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, ros_helper=None):
    addr = writer.get_extra_info('peername')
    logging.info("TCP client connected: %s", addr)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                text = line.decode().strip()
            except Exception:
                text = None
            if not text:
                continue
            try:
                msg = json.loads(text)
            except Exception:
                logging.warning("Invalid JSON from TCP client %s: %s", addr, text)
                writer.write(b"ERROR: invalid json\n")
                await writer.drain()
                continue

            # Optionally publish to ROS
            if ros_helper is not None:
                ros_helper.publish(json.dumps(msg))

            # If a robot is connected, map and send action
            if GLOBAL_ROBOT is not None:
                try:
                    action = unity_to_so101_action(msg, GLOBAL_ROBOT)
                    # send in thread to avoid blocking
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, GLOBAL_ROBOT.send_action, action)
                    writer.write(b"ACK\n")
                    await writer.drain()
                except Exception:
                    logging.exception("Failed to send action from TCP message")
                    writer.write(b"ERROR: send failed\n")
                    await writer.drain()
            else:
                writer.write(b"IGNORED: no robot connected\n")
                await writer.drain()
    except asyncio.CancelledError:
        pass
    except Exception:
        logging.exception("TCP client handler error")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logging.info("TCP client disconnected: %s", addr)


class ROSHelper:
    def __init__(self, node_name: str, topic: str):
        if rclpy is None:
            raise RuntimeError("rclpy not available")
        rclpy.init()
        self.node = rclpy.create_node(node_name)
        self.pub = self.node.create_publisher(RosString, topic, 10)
        self._running = True
        self._thread = threading.Thread(target=self._spin_thread, daemon=True)
        self._thread.start()

    def _spin_thread(self):
        while self._running:
            rclpy.spin_once(self.node, timeout_sec=0.1)

    def publish(self, data: str):
        msg = RosString()
        msg.data = data
        self.pub.publish(msg)

    def close(self):
        self._running = False
        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            self.node.destroy_node()
        except Exception:
            pass
        try:
            rclpy.shutdown()
        except Exception:
            pass


async def _start_tcp_server():
    ros_helper = None
    if args.ros_enable:
        if rclpy is None:
            logging.error("ROS support requested but rclpy is not available")
        else:
            import threading

            ros_helper = ROSHelper(args.ros_node, args.ros_topic)
            logging.info("ROS helper started, publishing to %s", args.ros_topic)

    server = await asyncio.start_server(lambda r, w: _tcp_client_handler(r, w, ros_helper), '0.0.0.0', args.tcp_port)
    logging.info("TCP server listening on 0.0.0.0:%d", args.tcp_port)
    return server, ros_helper


async def _stop_tcp_server(server, ros_helper):
    if server is not None:
        server.close()
        await server.wait_closed()
    if ros_helper is not None:
        ros_helper.close()



asyncio.run(main())