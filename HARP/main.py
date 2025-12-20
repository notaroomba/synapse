#!/usr/bin/env python3
"""WebSocket server to control a LeRobot SO101 arm via JSON messages.

Protocol (JSON messages):
- {"command": "connect", "port": "/dev/ttyUSB0", "use_degrees": true}
- {"command": "disconnect"}
- {"command": "set_positions", "positions": {"shoulder_pan": 10.0, "shoulder_lift": 20.0}}
- {"command": "get_state"}
- {"command": "ping"}

Responses are JSON objects with keys: "status" (ok/error), optional "result" or "error".

Notes:
- `set_positions` expects a dict mapping motor names (without the trailing ".pos") to numeric positions (this server assumes there is NO separate leader device; leader position data should be sent over WebSocket using `set_positions`).
- Positions are interpreted according to the `use_degrees` config passed on connect (or default False).

Dependencies:
- pip install lerobot websockets

"""

import argparse
import asyncio
import json
import logging
import signal
import sys
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import websockets
# Websockets changed API: prefer top-level import where available to avoid deprecation warnings
try:
    from websockets import WebSocketServerProtocol
except Exception:
    from websockets.server import WebSocketServerProtocol

# LeRobot imports
from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig
from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.utils.errors import DeviceNotConnectedError, DeviceAlreadyConnectedError


logger = logging.getLogger("so101_ws")

# Global robot instance (managed by handlers)
ROBOT: SO101Follower | None = None
ROBOT_LOCK = asyncio.Lock()


async def run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

def try_chmod_ports(ports: list[str]) -> dict:
    res = {}
    for port in ports:
        try:
            os.chmod(port, 0o666)
            res[port] = "ok"
        except Exception:
            # fall back to sudo chmod
            try:
                subprocess.run(["sudo", "chmod", "666", port], check=True)
                res[port] = "ok (sudo)"
            except Exception as e:
                res[port] = f"failed: {e}"
    return res


def auto_connect_sync(follower_port: str = "/dev/ttyACM0", camera_index: int = 4, try_chmod: bool = True) -> dict:
    """Blocking auto-connect helper: optionally fix perms and connect the follower with a single top camera config."""
    results = {"chmod": None, "connect": None}
    if try_chmod:
        results["chmod"] = try_chmod_ports([follower_port])

    config = SO101FollowerConfig(port=follower_port, cameras={"top": OpenCVCameraConfig(index_or_path=camera_index, fps=30, width=640, height=480)}, id="harp_arm", calibration_dir=Path(__file__).parent)
    robot = SO101Follower(config)
    robot.connect()
    results["connect"] = "connected"
    return results


async def handle_message(message: str, websocket: WebSocketServerProtocol) -> None:
    global ROBOT
    try:
        data = json.loads(message)
    except json.JSONDecodeError as e:
        await websocket.send(json.dumps({"status": "error", "error": f"invalid json: {e}"}))
        return

    if not isinstance(data, dict) or "command" not in data:
        await websocket.send(json.dumps({"status": "error", "error": "json must be an object containing 'command'"}))
        return

    cmd = data["command"]

    async with ROBOT_LOCK:
        try:
            if cmd == "connect":
                if ROBOT is not None and ROBOT.is_connected:
                    raise DeviceAlreadyConnectedError("robot already connected")

                port = data.get("port") or data.get("robot_port") or "/dev/ttyUSB0"
                use_degrees = bool(data.get("use_degrees", False))
                max_relative_target = data.get("max_relative_target", None)

                config = SO101FollowerConfig(port=port, use_degrees=use_degrees, max_relative_target=max_relative_target, id="harp_arm", calibration_dir=Path(__file__).parent)
                ROBOT = SO101Follower(config)
                await run_blocking(ROBOT.connect)  # may raise on failure
                await websocket.send(json.dumps({"status": "ok", "result": "connected"}))

            elif cmd == "disconnect":
                if ROBOT is None or not ROBOT.is_connected:
                    raise DeviceNotConnectedError("robot not connected")
                await run_blocking(ROBOT.disconnect)
                await websocket.send(json.dumps({"status": "ok", "result": "disconnected"}))

            elif cmd == "set_positions":
                if ROBOT is None or not ROBOT.is_connected:
                    raise DeviceNotConnectedError("robot not connected")
                positions = data.get("positions")
                if not isinstance(positions, dict):
                    await websocket.send(json.dumps({"status": "error", "error": "positions must be a dict"}))
                    return

                action = {f"{name}.pos": float(val) for name, val in positions.items()}
                sent = await run_blocking(ROBOT.send_action, action)
                await websocket.send(json.dumps({"status": "ok", "result": sent}))

            elif cmd == "get_state":
                if ROBOT is None or not ROBOT.is_connected:
                    raise DeviceNotConnectedError("robot not connected")
                obs = await run_blocking(ROBOT.get_observation)
                await websocket.send(json.dumps({"status": "ok", "result": obs}, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o)))

            elif cmd == "ping":
                await websocket.send(json.dumps({"status": "ok", "result": "pong"}))

            elif cmd == "auto_connect":
                follower_port = data.get("follower_port", "/dev/ttyACM0")
                camera_index = int(data.get("camera_index", 4))
                try_chmod = bool(data.get("try_chmod", True))

                res = {}
                if try_chmod:
                    res["chmod"] = await run_blocking(try_chmod_ports, [follower_port])

                # Create the robot instance and connect
                config = SO101FollowerConfig(port=follower_port, cameras={"top": OpenCVCameraConfig(index_or_path=camera_index, fps=30, width=640, height=480)}, id="harp_arm", calibration_dir=Path(__file__).parent)
                ROBOT = SO101Follower(config)
                await run_blocking(ROBOT.connect)
                res["connect"] = "connected"
                await websocket.send(json.dumps({"status": "ok", "result": res}))


            else:
                await websocket.send(json.dumps({"status": "error", "error": f"unknown command: {cmd}"}))

        except Exception as exc:
            logger.exception("command failed")
            await websocket.send(json.dumps({"status": "error", "error": str(exc)}))


async def ws_handler(websocket: WebSocketServerProtocol, path: str) -> None:
    peer = f"{websocket.remote_address}"
    logger.info("client connected: %s", peer)
    try:
        async for message in websocket:
            logger.debug("received: %s", message)
            await handle_message(message, websocket)
    except websockets.ConnectionClosedOK:
        logger.info("connection closed cleanly: %s", peer)
    except Exception:
        logger.exception("connection error with %s", peer)
    finally:
        logger.info("client disconnected: %s", peer)


async def main(host: str, port: int, skip_calibrate: bool = False, calibration_path: str | Path | None = None, follower_port: str = "/dev/ttyACM0", try_chmod_on_start: bool = True) -> None:
    """Main entry: optionally run startup calibration then start the WebSocket server."""
    global ROBOT
    logger.info("starting WebSocket server on %s:%d", host, port)

    # Decide calibration file path
    if calibration_path is None:
        calibration_path = Path(__file__).parent / "so101_calibration.json"
    else:
        calibration_path = Path(calibration_path)

    # Startup calibration: if not skipped and no file exists, run interactive calibration
    if not skip_calibrate:
        if not calibration_path.exists():
            logger.info("Calibration file %s not found; running interactive calibration", calibration_path)
            if try_chmod_on_start:
                logger.info("Trying to adjust device permissions for %s", follower_port)
                await run_blocking(try_chmod_ports, [follower_port])

            # Create and connect robot with a stable id and HARP calibration_dir
            cfg = SO101FollowerConfig(port=follower_port, id="harp_arm", calibration_dir=Path(__file__).parent)
            ROBOT = SO101Follower(cfg)
            try:
                await run_blocking(ROBOT.connect)
            except Exception:
                logger.exception("failed to connect to robot for calibration")
                raise

            # Run the interactive calibration routine (user will be prompted)
            try:
                await run_blocking(ROBOT.calibrate)
            except Exception:
                logger.exception("calibration failed")
                raise

            # Save calibration using Robot helper (writes to ROBOT.calibration_fpath)
            try:
                ROBOT._save_calibration()
                logger.info("Saved calibration to %s", ROBOT.calibration_fpath)
            except Exception:
                logger.exception("failed to save calibration to %s", ROBOT.calibration_fpath)

        else:
            logger.info("Calibration file %s already exists; skipping startup calibration", calibration_path)

    stop = asyncio.Event()

    async def _shutdown():
        logger.info("shutdown requested")
        stop.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(_shutdown()))
    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(_shutdown()))

    async with websockets.serve(ws_handler, host, port):
        await stop.wait()

    # Clean up robot connection if any
    if ROBOT is not None and ROBOT.is_connected:
        try:
            await run_blocking(ROBOT.disconnect)
            logger.info("robot disconnected on shutdown")
        except Exception:
            logger.exception("error disconnecting robot on shutdown")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SO101 WebSocket control server")
    parser.add_argument("--host", default="0.0.0.0", help="WebSocket listen host")
    parser.add_argument("--port", default=8765, type=int, help="WebSocket listen port")
    parser.add_argument("--log-level", default="INFO", help="log level")

    parser.add_argument("--follower-port", default="/dev/ttyACM0", help="Serial port for the SO101 follower")
    parser.add_argument("--calibration-path", default=str(Path(__file__).parent / "harp_arm.json"), help="Path to save calibration JSON (not used if saving via Robot._save_calibration)")
    parser.add_argument("--skip-calibrate", action="store_true", help="Skip startup calibration even if calibration file is missing")
    parser.add_argument("--no-chmod", action="store_true", help="Do not try to chmod device ports before connecting")

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="[%(levelname)s] %(name)s: %(message)s")

    try:
        asyncio.run(main(args.host, args.port, skip_calibrate=args.skip_calibrate, calibration_path=args.calibration_path, follower_port=args.follower_port, try_chmod_on_start=(not args.no_chmod)))
    except KeyboardInterrupt:
        logger.info("exiting on keyboard interrupt")
    except Exception:
        logger.exception("fatal error")
        sys.exit(1)
