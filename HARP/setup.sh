#!/usr/bin/env bash
set -e

# Interactive helper to setup SO-101 on this machine using HARP/settings.json
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_JSON="$SCRIPT_DIR/settings.json"

if [ ! -f "$SETTINGS_JSON" ]; then
  echo "No settings.json found. Creating a template at $SETTINGS_JSON"
  cat > "$SETTINGS_JSON" <<'JSON'
{
  "follower_port": "/dev/ttyACM1",
  "leader_port": "/dev/ttyACM0",
  "cameras": {
    "wrist": 0,
    "side": 2,
    "top": 4
  },
  "calibrations_dir": "calibrations"
}
JSON
  echo "Created template. Edit it if your ports differ and re-run this script."
fi

# Read values from settings.json using jq for shell-native parsing (falls back to python if jq is unavailable).
# No defaults are provided here: settings.json is expected to contain the keys.
read_settings() {
  if command -v jq >/dev/null 2>&1; then
    jq -r '.follower_port' "$SETTINGS_JSON"
    jq -r '.leader_port' "$SETTINGS_JSON"
    jq -r '.cameras.wrist' "$SETTINGS_JSON"
    jq -r '.cameras.side' "$SETTINGS_JSON"
    jq -r '.cameras.top' "$SETTINGS_JSON"
    jq -r '.calibrations_dir' "$SETTINGS_JSON"
  else
    echo "Warning: 'jq' not found, falling back to python reader" >&2
    python - <<PY
import json, os
p = os.path.join("$SCRIPT_DIR","settings.json")
with open(p) as f:
    j = json.load(f)
# Access keys directly — let the program raise if required keys are missing
print(j['follower_port'])
print(j['leader_port'])
print(j['cameras']['wrist'])
print(j['cameras']['side'])
print(j['cameras']['top'])
print(j['calibrations_dir'])
PY
  fi
}

# Read settings into variables with strict validation (no defaults). If jq is available use it, otherwise use python and let it raise on missing keys.
if command -v jq >/dev/null 2>&1; then
  FOLLOWER_PORT=$(jq -r '.follower_port' "$SETTINGS_JSON")
  LEADER_PORT=$(jq -r '.leader_port' "$SETTINGS_JSON")
  CAM_WRIST=$(jq -r '.cameras.wrist' "$SETTINGS_JSON")
  CAM_SIDE=$(jq -r '.cameras.side' "$SETTINGS_JSON")
  CAM_TOP=$(jq -r '.cameras.top' "$SETTINGS_JSON")
  HARP_DIR=$(jq -r '.calibrations_dir' "$SETTINGS_JSON")
else
  echo "Warning: 'jq' not found, using python reader which will raise on missing keys" >&2
  readarray -t _vals < <(python - <<PY
import json, os,sys
p = os.path.join("$SCRIPT_DIR","settings.json")
with open(p) as f:
    j = json.load(f)
print(j['follower_port'])
print(j['leader_port'])
print(j['cameras']['wrist'])
print(j['cameras']['side'])
print(j['cameras']['top'])
print(j['calibrations_dir'])
PY
)
  FOLLOWER_PORT=${_vals[0]}
  LEADER_PORT=${_vals[1]}
  CAM_WRIST=${_vals[2]}
  CAM_SIDE=${_vals[3]}
  CAM_TOP=${_vals[4]}
  HARP_DIR=${_vals[5]}
fi

# Validate required settings
for varname in FOLLOWER_PORT LEADER_PORT CAM_WRIST CAM_SIDE CAM_TOP HARP_DIR; do
  val=$(eval echo \$$varname)
  if [ -z "$val" ] || [ "$val" = "null" ]; then
    echo "Error: required setting '$varname' is missing or null in $SETTINGS_JSON" >&2
    exit 1
  fi
done

# Ensure HARP dir exists
mkdir -p "$SCRIPT_DIR/$HARP_DIR"

# Set USB device permissions
echo "Setting USB device permissions for leader ($LEADER_PORT) and follower ($FOLLOWER_PORT)"
if command -v sudo >/dev/null 2>&1; then
  sudo chmod 666 "$LEADER_PORT" "$FOLLOWER_PORT" || true
else
  chmod 666 "$LEADER_PORT" "$FOLLOWER_PORT" || true
fi

# Hugging Face CLI check
if command -v hf >/dev/null 2>&1; then
  echo "Checking Hugging Face authentication..."
  whoami_out=$(hf auth whoami 2>&1 || true)
  if [ -z "$whoami_out" ] || echo "$whoami_out" | grep -qi "not logged in\|no token\|no credentials"; then
    echo "No Hugging Face token found. You can run 'hf auth login' now or later."
  else
    echo "Hugging Face auth detected: $whoami_out"
  fi
else
  echo "Warning: 'hf' CLI not found. Install 'huggingface_hub' or 'hf' CLI to upload datasets."
fi

# Display helpful commands and offer to run ones requiring user input
pause_and_run() {
  local prompt="$1"
  local cmd="$2"
  echo
  echo "${prompt}"
  echo "Command: $cmd"
  read -r -p "Press ENTER to run, or Ctrl-C to skip: " || true
  eval "$cmd"
}

# Calibration commands (interactive) — write calibration files to the specified calibrations dir
CAL_DIR="$SCRIPT_DIR/$HARP_DIR"
mkdir -p "$CAL_DIR"
calib_follower_cmd="lerobot-calibrate --robot.type=so101_follower --robot.port=$FOLLOWER_PORT --robot.id=follower --robot.calibration_dir=$CAL_DIR"
calib_leader_cmd="lerobot-calibrate --teleop.type=so101_leader --teleop.port=$LEADER_PORT --teleop.id=leader --teleop.calibration_dir=$CAL_DIR"

echo "=== Calibration ==="
echo "Calibration directory: $CAL_DIR"
echo "Follower calibration command: $calib_follower_cmd"
echo "Leader calibration command: $calib_leader_cmd"
read -r -p "Run follower calibration now? [y/N]: " yn || true
if [[ "$yn" =~ ^[Yy]$ ]]; then
  pause_and_run "Running follower calibration (follow on-screen interactive prompts)" "$calib_follower_cmd"
fi
read -r -p "Run leader calibration now? [y/N]: " yn || true
if [[ "$yn" =~ ^[Yy]$ ]]; then
  pause_and_run "Running leader calibration (follow on-screen interactive prompts)" "$calib_leader_cmd"
fi

# Teleoperate commands (pause before running to let user prepare)
teleop_cmd="lerobot-teleoperate --robot.type=so101_follower --robot.port=$FOLLOWER_PORT --robot.id=follower --teleop.type=so101_leader --teleop.port=$LEADER_PORT --teleop.id=leader --robot.calibration_dir=$CAL_DIR"
teleop_cam_cmd="lerobot-teleoperate --robot.type=so101_follower --robot.port=$FOLLOWER_PORT --robot.id=follower --robot.cameras=\"{wrist: {type: opencv, index_or_path: $CAM_WRIST, width: 640, height: 480, fps: 30}, side: {type: opencv, index_or_path: $CAM_SIDE, width: 640, height: 480, fps: 30}, top: {type: opencv, index_or_path: $CAM_TOP, width: 640, height: 480, fps: 30}}\" --teleop.type=so101_leader --teleop.port=$LEADER_PORT --teleop.id=leader --display_data=true --robot.calibration_dir=$CAL_DIR"

echo "\n=== Teleoperate ==="
echo "Simple teleop: $teleop_cmd"
echo "Teleop with cameras: $teleop_cam_cmd"
read -r -p "Run simple teleop now? [y/N]: " yn || true
if [[ "$yn" =~ ^[Yy]$ ]]; then
  pause_and_run "Starting teleop (open a second terminal to observe outputs)." "$teleop_cmd"
fi
read -r -p "Run teleop with cameras now? [y/N]: " yn || true
if [[ "$yn" =~ ^[Yy]$ ]]; then
  pause_and_run "Starting teleop with cameras (this will open camera displays)." "$teleop_cam_cmd"
fi

# Recording dataset guidance
echo "\n=== Dataset recording (manual step) ==="
echo "To record a dataset you typically:"
echo "  1) Ensure Hugging Face CLI is authenticated (hf auth login)."
echo "  2) Prepare camera and scene, then run the lerobot-record command."
echo "Example command (not run automatically):"
echo "  lerobot-record --robot.type=so101_follower --robot.port=$FOLLOWER_PORT --robot.id=my_awesome_follower_arm --robot.cameras=\"{wrist: {type: opencv, index_or_path: $CAM_WRIST, width: 640, height: 480, fps: 30}, side: {type: opencv, index_or_path: $CAM_SIDE, width: 640, height: 480, fps: 30}, top: {type: opencv, index_or_path: $CAM_TOP, width: 640, height: 480, fps: 30}}\" --teleop.type=so101_leader --teleop.port=$LEADER_PORT --teleop.id=my_awesome_leader_arm --display_data=true --dataset.repo_id=HF_USER/record-test --dataset.num_episodes=10 --dataset.episode_time_s=30"

echo "\nSetup complete. Save any changes to $SETTINGS_JSON and re-run this script to pick them up."