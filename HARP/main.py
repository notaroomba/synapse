import asyncio
import argparse
import json
import logging
import websockets
from websockets.exceptions import PayloadTooBig

from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


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

    for motor in motor_names:
        if motor in msg:
            raw_val = msg[motor]
            try:
                v = float(raw_val)
            except (TypeError, ValueError):
                logging.warning("Invalid numeric value for %s: %r", motor, raw_val)
                continue

            # Clamp value to -360..360
            if v < -360.0 or v > 360.0:
                logging.warning("Unity value for %s out of -360..360 range: %s; clamping", motor, v)
            v = max(-360.0, min(360.0, v))

            # Map -360->min_norm, 360->max_norm
            if name_to_min_norm and name_to_max_norm and motor in name_to_min_norm:
                deg_min = name_to_min_norm[motor]
                deg_max = name_to_max_norm[motor]
            else:
                # fallback symmetric range
                deg_min = -180.0
                deg_max = 180.0

            # When input range is [-360, 360], map linearly to [deg_min, deg_max]
            mapped = deg_min + ((v + 360.0) / 720.0) * (deg_max - deg_min)

            # Clamp mapped to [deg_min, deg_max]
            mapped = max(min(mapped, max(deg_min, deg_max)), min(deg_min, deg_max))

            # Additionally clamp to global safe range [0, 180]
            mapped = max(0.0, min(180.0, mapped))

            action[f"{motor}.pos"] = mapped

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

    try:
        logging.info("Connecting to SO-101 on %s", cfg.port)
        robot.connect()
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
            if msg.get("type") != "headset" or msg.get("arm") != "left":
                await websocket.send("IGNORED: not matching type/arm")
                continue

            action = unity_to_so101_action(msg, robot)
            if not action:
                await websocket.send("IGNORED: no action")
                continue

            
            # print("From Unity:", message)

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
        try:
            robot.disconnect()
            logging.info("Robot disconnected")
        except Exception:
            logging.exception("Error disconnecting robot")


# Parse CLI args early so handler can use them
parser = argparse.ArgumentParser(description="Unity → SO-101 WebSocket bridge")
parser.add_argument("--recalibrate", action="store_true", help="Run interactive calibration on startup and save to calibration file")
parser.add_argument("--calibration-file", default="harp_arm.json", help="Calibration file to read/write (default: harp_arm.json)")
parser.add_argument("--port", default="/dev/ttyACM1", help="Serial port for the SO-101 arm (default: /dev/ttyACM1)")
args = parser.parse_args()


async def main():
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


asyncio.run(main())