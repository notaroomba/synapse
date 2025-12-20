#!/usr/bin/env bash
set -e

# Try to source conda activation scripts (adjust paths if needed)
if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
  . "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
  . "$HOME/anaconda3/etc/profile.d/conda.sh"
fi

echo "Activating conda environment 'lerobot'..."
conda activate lerobot || { echo "Failed to activate conda env 'lerobot' - adjust script as needed."; }

# Default ports (adjust as needed)
FOLLOWER_PORT=/dev/ttyACM0
CAMERA_INDEX=4

# USB port permissions (may require sudo)
echo "Setting device permissions (may require your sudo password)..."
if command -v sudo >/dev/null 2>&1; then
  sudo chmod 666 "$FOLLOWER_PORT" || true
else
  chmod 666 "$FOLLOWER_PORT" || true
fi

echo "Checking Hugging Face authentication..."
if command -v hf >/dev/null 2>&1; then
  whoami_out=$(hf auth whoami 2>&1 || true)
  if [ -z "$whoami_out" ] || echo "$whoami_out" | grep -qi "not logged in\|no token\|no credentials"; then
    echo "No Hugging Face token found. Running 'hf auth login' (interactive)."
    echo "Note: A token is required and can be created at https://huggingface.co/settings/tokens"
    # This will prompt the user to login interactively
    hf auth login || true
  else
    echo "Hugging Face auth detected:"
    echo "$whoami_out"
    echo "If you want to clear credentials run: hf auth logout"
  fi
else
  echo "Warning: 'hf' CLI not found. Install 'huggingface_hub' or the 'hf' CLI to authenticate: https://huggingface.co/docs/huggingface_hub/cli"
fi

# echo "Detecting cameras (opencv)..."
# lerobot-find-cameras opencv || true


# cat <<'EOF'

# === Calibration Commands (interactive) ===
# # Calibrate follower (interactive)
# lerobot-calibrate \
#     --robot.type=so101_follower \
#     --robot.port=$FOLLOWER_PORT \
#     --robot.id=harp_arm

# === Teleoperation via WebSocket (example Python client) ===
# # Example Python snippet to send leader positions (teleop) to websocket server:
# python - <<'PY'
# import asyncio, json
# import websockets

# async def send_positions():
#     uri = "ws://localhost:8765"
#     async with websockets.connect(uri) as ws:
#         # send positions as motor name -> target (units depend on your robot config)
#         await ws.send(json.dumps({"command": "set_positions", "positions": {"shoulder_pan": 10.0, "shoulder_lift": 20.0}}))
#         resp = await ws.recv()
#         print(resp)

# asyncio.run(send_positions())
# PY

# === Record Dataset Example (note) ===
# # To record datasets, you can run `lerobot-record` with the follower specified and then drive the follower via this websocket server by sending `set_positions` messages.
# HF_USER=$(hf auth whoami | cut -c 16-)
# lerobot-record \
#     --robot.type=so101_follower \
#     --robot.port=$FOLLOWER_PORT \
#     --robot.id=harp_arm \
#     --robot.cameras='{top: {type: opencv, index_or_path: $CAMERA_INDEX, width: 640, height: 480, fps: 30}}' \
#     --display_data=true \
#     --dataset.repo_id=${HF_USER}/record-test \
#     --dataset.num_episodes=10 \
#     --dataset.episode_time_s=30 \
#     --dataset.reset_time_s=10 \
#     --dataset.single_task="pickup the cube and place it to the bin" \
#     --dataset.root=${HOME}/so101_dataset/

# EOF

# Detect whether the script is sourced. If it is, apply changes to the current shell and return.
# If not sourced, instruct the user to `source` to apply to current shell; otherwise offer to spawn a subshell.

sourced=0
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  sourced=1
fi

if [ "$sourced" -eq 1 ]; then
  echo "Script sourced: 'lerobot' environment is active in this shell."
  # Variables such as FOLLOWER_PORT and CAMERA_INDEX will remain set in the current shell.
  return 0 2>/dev/null || exit 0
fi

# Not sourced: inform the user how to apply changes to the current shell
echo
echo "Note: this script was executed, not sourced. To apply these changes to your current shell, run:"
echo "  source ./setup_so101.sh"
read -r -p "Press Enter to start a new interactive shell with the 'lerobot' environment active (Ctrl-C to skip): " || true

# Build an init snippet that sources conda and activates the env
init_snippet=''
if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
  init_snippet='[ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ] && . "$HOME/miniconda3/etc/profile.d/conda.sh"; conda activate lerobot || true;'
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
  init_snippet='[ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ] && . "$HOME/anaconda3/etc/profile.d/conda.sh"; conda activate lerobot || true;'
else
  init_snippet='conda activate lerobot || true;'
fi

# Start a new interactive bash using a temporary rcfile that activates the env
# We write the init snippet to a temp file and use it as the rcfile so that no other login rc is executed afterwards
tmprc=$(mktemp)
printf '%s\n' "$init_snippet" > "$tmprc"
chmod 600 "$tmprc" || true
bash --rcfile "$tmprc" -i
rm -f "$tmprc" || true

