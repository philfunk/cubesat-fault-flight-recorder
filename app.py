"""Streamlit interface for the CubeSat Fault Flight Recorder demo."""

from __future__ import annotations

from dataclasses import asdict
import json

import pandas as pd
import streamlit as st

from flight_recorder import (
    FAULT_LIBRARY,
    GROUND_EVENT_CODES,
    GROUND_STATIONS,
    SIMULATION_NOTICE,
    build_incident_report,
    faults_for_ids,
    get_incident,
    replay_without_fault,
    report_to_json,
    simulate,
    simulation_to_dict,
)


st.set_page_config(
    page_title="CubeSat Fault Flight Recorder",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      :root {
        --ink: #eaf0f6;
        --muted: #a5b4c2;
        --line: #2b3b49;
        --panel: #111c25;
        --signal: #65d6b4;
      }
      .stApp { background: #0b141c; color: var(--ink); }
      [data-testid="stSidebar"] { background: #0f1922; border-right: 1px solid var(--line); }
      [data-testid="stSidebar"] * { color: var(--ink); }
      h1, h2, h3 { letter-spacing: -0.025em; }
      .app-kicker {
        color: var(--signal); font-size: 0.78rem; font-weight: 700;
        letter-spacing: 0.14em; text-transform: uppercase; margin-bottom: 0.35rem;
      }
      .run-stamp {
        border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
        padding: 0.75rem 0; margin: 0.75rem 0 1.25rem; color: var(--muted);
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.86rem;
      }
      .replay-result {
        background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
        padding: 1rem; margin: 0.75rem 0;
      }
      div[data-testid="stMetric"] {
        background: var(--panel); border: 1px solid var(--line);
        border-radius: 8px; padding: 0.8rem 1rem;
      }
      div[data-testid="stMetric"] label { color: var(--muted); }
      .stButton button, .stDownloadButton button { min-height: 2.75rem; }
      [data-testid="stBaseButton-primary"],
      [data-testid="stBaseButton-primary"] * {
        color: #0b141c !important; font-weight: 700;
      }
      .small-note { color: var(--muted); font-size: 0.9rem; line-height: 1.55; }
      @media (max-width: 600px) {
        h1 { font-size: 2rem; }
        .run-stamp { font-size: 0.72rem; overflow-wrap: anywhere; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

DEFAULT_FAULTS = ("memory_bit_flip", "packet_corruption", "rf_interference")
if "original_run" not in st.session_state:
    st.session_state.original_run = simulate(faults_for_ids(DEFAULT_FAULTS))

with st.sidebar:
    st.markdown("### Scenario controls")
    st.caption("Choose a station and faults, then run. Nothing changes until you press the button.")
    station = st.selectbox("Ground station", options=GROUND_STATIONS)
    selected_faults = []
    for fault in FAULT_LIBRARY:
        if fault.id == "memory_bit_flip":
            st.markdown("**Spacecraft faults**")
        elif fault.id == "rf_interference":
            st.markdown("**Ground / RF scenario**")
        selected = st.checkbox(
            fault.label,
            value=fault.id in DEFAULT_FAULTS,
            key=f"select_{fault.id}",
            help=fault.description,
        )
        if selected:
            selected_faults.append(fault.id)

    tick_count = st.slider("Telemetry length (ticks)", 24, 72, 36, 6)
    if st.button("Run simulation", type="primary", width="stretch"):
        st.session_state.original_run = simulate(
            faults_for_ids(selected_faults), ticks=tick_count, station=station
        )
        st.session_state.pop("replay_result", None)
        st.session_state.pop("replay_key", None)

    st.markdown("---")
    st.markdown("**Replay rule**")
    st.caption(
        "The app removes one injected fault and repeats the entire simulation. "
        "All other inputs stay unchanged."
    )
    st.download_button(
        "Download complete run JSON",
        data=json.dumps(simulation_to_dict(st.session_state.original_run), indent=2),
        file_name=f"{st.session_state.original_run.run_id.lower()}_run.json",
        mime="application/json",
        width="stretch",
    )

run = st.session_state.original_run

st.markdown('<div class="app-kicker">Ground simulation · deterministic replay</div>', unsafe_allow_html=True)
st.title("CubeSat Fault Flight Recorder")
st.markdown(
    "Monitor the spacecraft and ground link, inspect anomalies, and test whether "
    "removing one modeled fault prevents an incident in replay."
)
st.markdown(
    f'<div class="run-stamp">{run.run_id} &nbsp;·&nbsp; {run.station} '
    f'&nbsp;·&nbsp; {run.ticks} ticks &nbsp;·&nbsp; {len(run.faults)} injected faults</div>',
    unsafe_allow_html=True,
)

ground_anomalies = sum(
    incident["trigger_code"] in GROUND_EVENT_CODES for incident in run.incidents
)
packets_lost = sum(row["packets_lost"] for row in run.telemetry)
metric_columns = st.columns(4)
metric_columns[0].metric("Incidents", len(run.incidents))
metric_columns[1].metric("Watchdog resets", run.telemetry[-1]["reset_count"])
metric_columns[2].metric("Ground-link anomalies", ground_anomalies)
metric_columns[3].metric("Packets lost", packets_lost)

ground_tab, explorer_tab, telemetry_tab, method_tab = st.tabs(
    ["Ground station", "Incident explorer", "Spacecraft telemetry", "How it works"]
)

with ground_tab:
    st.subheader(f"{run.station} · pass monitor")
    st.caption(
        "Anomaly detection uses measured SNR, expected SNR from elevation, link margin, "
        "packet loss, and receiver lock. The hidden fault label is not used by the detector."
    )
    pass_rows = [row for row in run.telemetry if row["in_pass"]]
    ground_metrics = st.columns(4)
    ground_metrics[0].metric("Maximum elevation", f"{max(row['elevation_deg'] for row in pass_rows):.1f}°")
    ground_metrics[1].metric("Minimum pass SNR", f"{min(row['snr_db'] for row in pass_rows):.2f} dB")
    ground_metrics[2].metric(
        "Interference-suspect ticks", sum(row["interference_suspected"] for row in run.telemetry)
    )
    ground_metrics[3].metric("Ground events", sum(event["code"] in GROUND_EVENT_CODES for event in run.events))

    inspected_tick = st.slider("Inspect pass tick", 0, run.ticks - 1, 12)
    inspected = run.telemetry[inspected_tick]
    status_columns = st.columns(4)
    status_columns[0].metric("Receiver", inspected["link_status"])
    status_columns[1].metric("Spacecraft mode", inspected["mode"])
    status_columns[2].metric("Link margin", f"{inspected['link_margin_db']:.2f} dB")
    status_columns[3].metric("Packet loss", f"{inspected['packet_loss_percent']:.1f}%")
    if inspected["interference_suspected"]:
        st.error(
            f"Tick {inspected_tick}: possible RF interference. SNR is "
            f"{inspected['snr_residual_db']:.2f} dB relative to the elevation-based expectation."
        )
    elif inspected["in_pass"] and not inspected["receiver_lock"]:
        st.warning(f"Tick {inspected_tick}: receiver lock lost during a visible pass.")
    elif inspected["in_pass"]:
        st.success(f"Tick {inspected_tick}: link tracking is nominal.")
    else:
        st.info(f"Tick {inspected_tick}: spacecraft is outside this station's simulated pass.")

    ground_telemetry = pd.DataFrame(run.telemetry)
    st.markdown("**Measured versus expected SNR**")
    st.line_chart(
        ground_telemetry,
        x="tick",
        y=["snr_db", "expected_snr_db"],
        x_label="Tick",
        y_label="SNR (dB)",
    )
    st.markdown("**Elevation and link margin**")
    st.line_chart(
        ground_telemetry,
        x="tick",
        y=["elevation_deg", "link_margin_db"],
        x_label="Tick",
        y_label="Degrees / dB",
    )
    st.markdown("**Packet loss**")
    st.line_chart(
        ground_telemetry,
        x="tick",
        y="packet_loss_percent",
        x_label="Tick",
        y_label="Packet loss (%)",
    )

    ground_events = [event for event in run.events if event["code"] in GROUND_EVENT_CODES]
    st.markdown("**Ground-station anomaly timeline**")
    if ground_events:
        st.dataframe(pd.DataFrame(ground_events), width="stretch", hide_index=True)
    else:
        st.success("No ground-link anomalies detected in this run.")
    with st.expander("Ground telemetry table and export"):
        ground_columns = [
            "tick", "in_pass", "elevation_deg", "expected_snr_db", "snr_db",
            "snr_residual_db", "link_margin_db", "packet_loss_percent",
            "receiver_lock", "link_status", "interference_suspected",
            "packets_sent", "packets_lost",
        ]
        st.dataframe(ground_telemetry[ground_columns], width="stretch", hide_index=True)
        st.download_button(
            "Download ground telemetry CSV",
            data=ground_telemetry[ground_columns].to_csv(index=False),
            file_name=f"{run.run_id.lower()}_ground_telemetry.csv",
            mime="text/csv",
        )

with explorer_tab:
    if not run.incidents:
        st.success("No incidents detected. Try enabling a fault and running the simulation again.")
        st.dataframe(pd.DataFrame(run.telemetry), width="stretch", hide_index=True)
    else:
        incident_map = {incident["id"]: incident for incident in run.incidents}
        selection_column, fault_column = st.columns([1, 1])
        with selection_column:
            incident_id = st.selectbox(
                "Incident",
                options=list(incident_map),
                format_func=lambda item: (
                    f"{item} · tick {incident_map[item]['trigger_tick']} · "
                    f"{incident_map[item]['title']}"
                ),
            )
        incident = get_incident(run, incident_id)
        fault_map = {fault.id: fault for fault in run.faults}
        with fault_column:
            fault_id = st.radio(
                "Fault to remove in replay",
                options=incident["candidate_fault_ids"],
                format_func=lambda item: fault_map[item].label,
            )

        st.subheader(incident["title"])
        st.write(incident["summary"])
        window_start = max(0, incident["trigger_tick"] - 3)
        window_stop = min(run.ticks, incident["trigger_tick"] + 4)
        nearby_events = [
            event for event in run.events
            if window_start <= event["tick"] < window_stop
        ]
        st.markdown("**Observed event sequence**")
        st.dataframe(
            pd.DataFrame(nearby_events),
            width="stretch",
            hide_index=True,
            column_config={
                "tick": st.column_config.NumberColumn("Tick", format="%d"),
                "severity": "Severity",
                "code": "Event code",
                "message": "Recorded evidence",
            },
        )

        if st.button("Replay without this fault", type="primary"):
            replay = replay_without_fault(run, incident_id, fault_id)
            st.session_state.replay_result = replay
            st.session_state.replay_key = (run.run_id, incident_id, fault_id)

        current_key = (run.run_id, incident_id, fault_id)
        replay = st.session_state.get("replay_result")
        if st.session_state.get("replay_key") != current_key:
            replay = None

        if replay:
            st.markdown("### Counterfactual replay")
            if replay.outcome == "prevented_in_replay":
                st.success(
                    f"The {incident['trigger_code']} trigger disappeared after removing "
                    f"“{replay.removed_fault.label}” in this simulation."
                )
            else:
                st.warning(
                    "The selected incident still occurs. This fault removal did not "
                    "prevent the trigger in replay."
                )

            before = run.telemetry[incident["trigger_tick"]]
            after = replay.replay.telemetry[incident["trigger_tick"]]
            comparison = pd.DataFrame([
                {
                    "Run": "Original",
                    "Mode at trigger": before["mode"],
                    "Total events": replay.original_event_count,
                    "Watchdog resets": replay.original_resets,
                    "SNR at trigger (dB)": before["snr_db"],
                    "Receiver at trigger": before["link_status"],
                    "Trigger present": "Yes",
                },
                {
                    "Run": "Fault removed",
                    "Mode at trigger": after["mode"],
                    "Total events": replay.replay_event_count,
                    "Watchdog resets": replay.replay_resets,
                    "SNR at trigger (dB)": after["snr_db"],
                    "Receiver at trigger": after["link_status"],
                    "Trigger present": "No" if replay.outcome == "prevented_in_replay" else "Yes",
                },
            ])
            st.dataframe(comparison, width="stretch", hide_index=True)
            st.markdown(
                f'<div class="replay-result"><strong>Changed telemetry ticks:</strong> '
                f'{", ".join(map(str, replay.changed_ticks)) or "None"}<br>'
                f'<strong>Replay evidence ID:</strong> {replay.replay.run_id}</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "This is a controlled intervention in the demo model, not proof of "
                "the unique cause of a real spacecraft anomaly."
            )

        report = build_incident_report(run, incident_id, replay)
        st.download_button(
            "Download incident report",
            data=report_to_json(report),
            file_name=f"{run.run_id.lower()}_{incident_id.lower()}_report.json",
            mime="application/json",
        )

with telemetry_tab:
    st.subheader("Recorded housekeeping telemetry")
    telemetry = pd.DataFrame(run.telemetry)
    st.markdown("**Battery bus voltage**")
    st.line_chart(telemetry, x="tick", y="battery_v", x_label="Tick", y_label="Volts")
    st.markdown("**Reported temperature**")
    st.line_chart(
        telemetry, x="tick", y="temperature_c", x_label="Tick", y_label="°C"
    )
    st.markdown("**Health signals (1 = healthy, 0 = failed)**")
    st.line_chart(
        telemetry,
        x="tick",
        y=["heartbeat_ok", "checksum_ok"],
        x_label="Tick",
        y_label="Health flag",
    )
    with st.expander("Inspect raw telemetry and injected faults"):
        st.dataframe(telemetry, width="stretch", hide_index=True)
        st.json([asdict(fault) for fault in run.faults])

with method_tab:
    st.subheader("A small, inspectable fault model")
    st.markdown(
        """
        1. **Record.** The simulator stores one telemetry row per tick, including
           mode, battery voltage, temperature, heartbeat, checksum, reset count,
           elevation, SNR, link margin, packet loss, and receiver-lock state.
        2. **Detect.** Explicit rules convert spacecraft and ground-link evidence
           into incident records. RF interference is suspected when SNR residual is
           at most −8 dB and packet loss is at least 50%; receiver lock requires
           SNR of at least 6 dB during a visible pass.
        3. **Replay.** Removing a fault creates a new run with otherwise identical
           configuration and deterministic baseline telemetry.
        4. **Compare.** The app checks whether the original trigger remains and lists
           every telemetry tick changed by the intervention.
        5. **Export.** The JSON report links the incident, original evidence, removed
           fault, replay outcome, and both run identifiers.
        """
    )
    for fault in FAULT_LIBRARY:
        st.markdown(f"**{fault.label}**  \n{fault.description}")
    st.info(SIMULATION_NOTICE)

st.markdown("---")
st.caption(SIMULATION_NOTICE)
