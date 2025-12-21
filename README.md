<h1 align="center">
  <br>
  <a href="https://github.com/notaroomba/synapse"><img src="assets/banner.png" alt="Synapse Banner" width="300"></a>
  <br>
  Synapse — Surgical Teleoperation Demonstrator
  <br>
</h1>

<p align="center">
  <a href="#key-features">Key Features</a> •
  <a href="#how-it-works">How it Works</a> •
  <a href="#getting-started">Getting Started</a> •
  <a href="#license">License</a>
</p>

<div align="center">

![Hugging Face](https://img.shields.io/badge/Hugging%20Face-%23FF6A00.svg?style=for-the-badge&logo=huggingface&logoColor=white)
![Python](https://img.shields.io/badge/python-%233776AB.svg?style=for-the-badge&logo=python&logoColor=white)
![Bash](https://img.shields.io/badge/bash-%23000000.svg?style=for-the-badge&logo=gnu-bash&logoColor=white)
![LERobot](https://img.shields.io/badge/LERobot-%2300ADEF.svg?style=for-the-badge)

</div>

> **⚠️ Demo only:** Synapse is a research/demo platform showing how machine learning can assist in surgical teleoperation. It is *not* a certified medical device and must never be used for real patient care.

## Key Features ✅

- **Synapse** — a LERobot project that demonstrates a teleoperated surgical robot (codename **SCALPEL**)
- **SCALPEL** — a synchronized control arm with low-latency, precision engineering links for coordinated, high-accuracy teleoperation
- **Trained using SMVLA** with roughly **50 iterations** to reach an MVP behavior
- **Simple code structure** and quick setup: run `./setup.sh` to configure ports and hardware, then `./run_robot.sh` to start
- **WebSocket server (`main.py`)** accepts commands from a Meta Quest 3 headset for low-latency teleoperation
- **Operator override:** the Meta Quest interface can enable a toggle so SCALPEL takes over (autonomous assist mode)
- **Focused demo** of how ML can augment complex surgical tasks where reducing human error is critical

---

## How it works 🔧

- The model was trained on simulated/recorded data using SMVLA and iterated to an MVP in ~50 training passes.
- `main.py` runs a WebSocket server that receives head/hand pose and control inputs from the Meta Quest 3 client.
- **SCALPEL** is implemented as a synchronized control arm with low-latency precision engineering links to ensure coordinated, high-precision motion during teleoperation.
- When the **SCALPEL** takeover button is engaged, the robot switches to an assist/autonomy mode driven by the trained policy.
- `run_robot.sh` starts the model and related runtime components; `setup.sh` walks you through hardware, serial port, and environment configuration.

---

## Getting Started 🚀

For setup and hardware configuration, please consult the **LERobot documentation**: https://lerobot.org/docs. This project follows LERobot conventions for environment setup and deployment; the documentation is the primary source for step-by-step instructions.

---

## Training Notes 🧠

- Training used the **SMVLA** framework and took approximately **50 iterations** to reach a workable MVP policy for the demo tasks.
- The repository contains simple scripts and a minimal training loop to reproduce the basic training flow; see the `train/` folder for details (if present).

---

## Safety & Ethics ⚖️

This repository is strictly a demonstration of research concepts. Synapse is not validated, regulated, or safe for clinical use. Do not use this for real surgeries or clinical decision making.

---

## Credits & License ✨

- Built by the LERobot team (Synapse project)
- Model training using **SMVLA**

License: **MIT**

---

## Project Submission 📁

Please include the following items in this README (in order):

1. **Name of your project**
   - Synapse — Surgical Teleoperation Demonstrator
2. **Team name + Team Number + GitHub Usernames of your teammates**
   - Team **Synapse** • Team **#3**
   - GitHub: `@notaroomba`, `@kalo08`, `@oxstar123`
3. **Picture of your project**
   - Placeholder images available in `/assets` (e.g., `assets/photo1.png`, `assets/photo2.png`)
4. **Description of your project!**
   - Synapse is a teleoperated surgical robot demonstrator that uses ML to assist high-precision tasks. It showcases a synchronized control arm (codename **SCALPEL**) and a secondary arm with a tweezer attachment for fine manipulation.
5. **A full wiring diagram!**
   - Wiring diagram: *Not available* — the demo uses two synchronized robot arms (one with a tweezer attachment). Placeholder: `assets/wiring_diagram.png`
6. **List of hardware components used (BOM-style, prices not necessary)**
   - SCALPEL synchronized control arm ×2 (primary arm + auxiliary arm with tweezer)
   - Tweezer/gripper attachment (for auxiliary arm)
   - Motor drivers / servo controllers
   - Embedded controller or single-board computer (running `main.py` / model runtime)
   - Power supply (regulated DC)
   - IMU / sensors and cameras (optional, used for perception and calibration)
   - Networking / USB interface and cabling
   - Meta Quest 3 headset (operator client)
7. **A full video demo of your project working!**
   - Placeholder video: `assets/demo.mp4` (replace with your recorded demo)
8. **Anything else you'd like to add!**
   - Safety: This is a demo/research platform and not a certified medical device. See the Safety & Ethics section above.
9. **MORE PICTURES!!!**
   - Add additional photos to `/assets` (`assets/photo3.png`, etc.)

---

> For questions or to contribute, open an issue or submit a PR — and please respect the safety disclaimer.

**Summary:** *A brief description of your work*

*< Images or video demonstrating your project >*

## Submission Details

### 1. Mission Description
- *Real world application of your mission*

### 2. Creativity
- *What is novel or unique in your approach?*
- *Innovation in design, methodology, or application*

### 3. Technical implementations
- *Teleoperation / Dataset capture*
    - *<Image/video of teleoperation or dataset capture>*
- *Training*
- *Inference*
    - *<Image/video of inference eval>*

### 4. Ease of use
- *How generalizable is your implementation across tasks or environments?*
- *Flexibility and adaptability of the solution*
- *Types of commands or interfaces needed to control the robot*

## Additional Links
*For example, you can provide links to:*

- *Link to a video of your robot performing the task*
- *URL of your dataset in Hugging Face*
- *URL of your model in Hugging Face*
- *Link to a blog post describing your work*

## Code submission

This is the directory tree of this repo — please place all submission materials into the `missions` directory with the structure below.

```terminal
AMD_Robotics_Hackathon_2025_ProjectTemplate-main/
├── README.md
└── missions
    ├── code
    │   └── <code and script>
    └── wandb
        └── <latest run directory copied from wandb of your training job>
    ├── CAD
    │   └── <CAD files>
    └── calibrations
        └── <calibration files (e.g., leader.json, follower.json)>
```


The `latest-run` is generated by wandb for your training job. Please copy it into the wandb sub directory of you Hackathon Repo.

The whole dir of `latest-run` will look like below:

```terminal
$ tree outputs/train/smolvla_so101_2cube_30k_steps/wandb/
outputs/train/smolvla_so101_2cube_30k_steps/wandb/
├── debug-internal.log -> run-20251029_063411-tz1cpo59/logs/debug-internal.log
├── debug.log -> run-20251029_063411-tz1cpo59/logs/debug.log
├── latest-run -> run-20251029_063411-tz1cpo59
└── run-20251029_063411-tz1cpo59
    ├── files
    │   ├── config.yaml
    │   ├── output.log
    │   ├── requirements.txt
    │   ├── wandb-metadata.json
    │   └── wandb-summary.json
    ├── logs
    │   ├── debug-core.log -> /dataset/.cache/wandb/logs/core-debug-20251029_063411.log
    │   ├── debug-internal.log
    │   └── debug.log
    ├── run-tz1cpo59.wandb
    └── tmp
        └── code
```

**NOTES**

1. The `latest-run` is the soft link, please make sure to copy the real target directory it linked with all sub dirs and files.
2. Only provide (upload) the wandb of your last success pre-trained model for the Mission.
