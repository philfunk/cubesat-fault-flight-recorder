---
title: CubeSat Fault Flight Recorder
emoji: 🛰️
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: 1.67.0
app_file: app.py
pinned: false
---

# CubeSat Fault Flight Recorder

A small, working ground-based demo for recording simulated CubeSat and ground-station telemetry, detecting spacecraft or RF-link anomalies, and replaying a run with one injected fault removed.

**This is a teaching simulator, not flight-qualified software or a real spacecraft diagnostic system.**

## What works

- Deterministic housekeeping telemetry over 24–72 ticks.
- Selectable memory, thermal-sensor, packet-corruption, and RF-interference faults.
- Watchdog-reset, thermal-limit, checksum-mismatch, RF-interference, and link-loss incidents.
- Three selectable ground stations and a deterministic visible-pass profile.
- Ground-station monitoring of elevation, measured/expected SNR, SNR residual, link margin, packet loss, and receiver lock.
- Per-tick CubeSat mode and ground-link status inspection.
- Spacecraft and ground-anomaly timelines and raw telemetry tables.
- Battery, temperature, health, SNR, elevation, link-margin, and packet-loss charts.
- Single-fault counterfactual replay with before/after results, including interference removal.
- Complete-run and incident-report JSON downloads plus ground-telemetry CSV export.
- Stable evidence IDs derived from station, run configuration, faults, and telemetry.
- Fifteen automated tests covering the core engine, ground anomalies, replay, and exports.

No AI service, API key, account, database, or internet connection is needed after installation.

## Run the demo

Python 3.10 or newer is recommended.

### 1. Open a terminal in this folder

```bash
cd cubesat-fault-flight-recorder
```

### 2. Create and activate an isolated environment

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install and start

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open **http://localhost:8501** if the browser does not open automatically. To stop the app, press `Ctrl+C` in the terminal.

## One-minute demonstration

The default scenario contains a memory fault, a corrupted telemetry packet, and a six-tick RF-interference burst.

1. Press **Run simulation**. You should see **4 incidents**, **1 watchdog reset**, **2 ground-link anomalies**, and **60 lost packets**.
2. Open **Ground station**. Tick 12 shows **SEARCHING**, **−9.73 dB link margin**, and **100% packet loss**; the SNR residual is **−24 dB**.
3. Open **Incident explorer**, select **RF interference suspected at ground station**, choose the RF fault, and press **Replay without this fault**.
4. The interference and link-loss incidents disappear, the receiver returns to **TRACKING**, and the unrelated spacecraft incidents remain.
5. Replay the same RF incident after removing the memory fault instead; the RF incident persists.
6. Select the checksum incident to compare direct and unrelated fault removal.
7. Press **Download incident report** or export the ground telemetry CSV from the ground-station tab.
8. Change the ground station or enable **Thermal sensor spike** and run again.
9. Disable every fault and run again to verify nominal spacecraft operation and a locked, no-loss ground link.

## Project structure

```text
app.py                         Streamlit user interface
flight_recorder.py             Simulator, replay engine, and JSON reports
.streamlit/config.toml          Local visual theme
requirements.txt               Exact runtime dependencies
requirements-dev.txt           Test dependency
examples/                      Sample exported evidence
tests/test_flight_recorder.py   Automated engine tests
```

Start with `FAULT_LIBRARY` and `simulate()` in `flight_recorder.py` if you want to change the scenario. The user interface calls those functions; it does not contain separate anomaly or replay logic.

## Run the tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Expected result: **15 passed**.

## Interpretation and limits

The fault effects are deliberately simple and explicit. A memory fault suppresses three heartbeats and causes a watchdog reset; a thermal fault creates one high reading; a packet fault creates one checksum mismatch. RF interference subtracts 24 dB from measured SNR for six ticks. The ground detector does not read that hidden fault state: it suspects interference only when the SNR residual is at most −8 dB and packet loss is at least 50%, and reports link loss when the receiver cannot maintain the 6 dB demo threshold during a visible pass.

A “prevented in replay” result means only that the selected trigger disappeared under these simulation rules. It does not establish a unique root cause for real hardware or a real RF environment. The pass profile, link budget, packet-loss curve, and thresholds are teaching assumptions—not calibrated RF models. Operational use would require spacecraft-specific telemetry, link budgets, station configuration, spectrum measurements, command and state models, timing behavior, hardware documentation, and independent validation.
