"""Deterministic telemetry simulation and counterfactual replay for the demo.

This is a teaching model, not a spacecraft dynamics simulator or flight software.
Every result is derived from the explicit rules in ``simulate``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable


SCHEMA_VERSION = "2.0"
SIMULATION_NOTICE = (
    "Ground-based teaching simulation. Not flight-qualified software, not a "
    "hardware diagnosis, and not evidence of a unique root cause on a real CubeSat."
)


@dataclass(frozen=True)
class Fault:
    """One injected scenario fault with a deterministic effect."""

    id: str
    kind: str
    start_tick: int
    label: str
    description: str


@dataclass(frozen=True)
class SimulationResult:
    """Complete, serializable evidence produced by one simulation run."""

    run_id: str
    station: str
    ticks: int
    faults: tuple[Fault, ...]
    telemetry: tuple[dict, ...]
    events: tuple[dict, ...]
    incidents: tuple[dict, ...]


@dataclass(frozen=True)
class ReplayResult:
    """Comparison between an original run and a single-fault removal replay."""

    incident_id: str
    removed_fault: Fault
    outcome: str
    original_event_count: int
    replay_event_count: int
    original_resets: int
    replay_resets: int
    changed_ticks: tuple[int, ...]
    replay: SimulationResult


FAULT_LIBRARY: tuple[Fault, ...] = (
    Fault(
        id="memory_bit_flip",
        kind="memory_bit_flip",
        start_tick=8,
        label="Memory bit flip → stuck heartbeat",
        description=(
            "A simplified memory fault stalls the heartbeat for ticks 8–10. "
            "The watchdog resets the spacecraft after the third miss."
        ),
    ),
    Fault(
        id="thermal_spike",
        kind="thermal_spike",
        start_tick=14,
        label="Thermal sensor spike",
        description="A one-tick sensor spike raises the reported temperature to 92.4 °C.",
    ),
    Fault(
        id="packet_corruption",
        kind="packet_corruption",
        start_tick=18,
        label="Corrupted telemetry packet",
        description="A corrupted payload produces a checksum mismatch at tick 18.",
    ),
    Fault(
        id="rf_interference",
        kind="rf_interference",
        start_tick=12,
        label="RF interference during ground pass",
        description=(
            "A six-tick interference burst reduces SNR by 24 dB during ticks 12–17. "
            "The ground detector uses SNR residual, packet loss, and receiver lock—not the hidden fault label."
        ),
    ),
)


GROUND_STATIONS = (
    "AURORA-1 · Kiruna",
    "AURORA-2 · Punta Arenas",
    "AURORA-3 · Singapore",
)
REQUIRED_SNR_DB = 6.0
INTERFERENCE_RESIDUAL_DB = -8.0
INTERFERENCE_PACKET_LOSS_PERCENT = 50.0
GROUND_EVENT_CODES = {
    "LINK_MARGIN_LOW",
    "RF_INTERFERENCE_SUSPECTED",
    "LINK_LOST",
}


TRIGGER_DETAILS = {
    "WATCHDOG_RESET": {
        "title": "Watchdog reset after missed heartbeats",
        "summary": "Three consecutive missing heartbeats preceded a watchdog reset and SAFE mode.",
    },
    "THERMAL_LIMIT": {
        "title": "Thermal limit alarm",
        "summary": "The reported temperature crossed the demo limit of 80 °C for one tick.",
    },
    "CHECKSUM_MISMATCH": {
        "title": "Telemetry checksum mismatch",
        "summary": "The received packet payload did not match its checksum.",
    },
    "RF_INTERFERENCE_SUSPECTED": {
        "title": "RF interference suspected at ground station",
        "summary": "Measured SNR fell at least 8 dB below expectation while packet loss exceeded 50%.",
    },
    "LINK_LOST": {
        "title": "Ground-station link lost",
        "summary": "The receiver lost lock because SNR fell below the 6 dB demo requirement during a visible pass.",
    },
}


def faults_for_ids(selected_ids: Iterable[str]) -> tuple[Fault, ...]:
    """Return known faults in stable library order and reject unknown IDs."""

    selected = set(selected_ids)
    known = {fault.id for fault in FAULT_LIBRARY}
    unknown = selected - known
    if unknown:
        raise ValueError(f"Unknown fault IDs: {sorted(unknown)}")
    return tuple(fault for fault in FAULT_LIBRARY if fault.id in selected)


def _make_run_id(
    ticks: int,
    station: str,
    faults: tuple[Fault, ...],
    telemetry: list[dict],
) -> str:
    payload = {
        "ticks": ticks,
        "station": station,
        "faults": [asdict(fault) for fault in faults],
        "telemetry": telemetry,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"RUN-{hashlib.sha256(encoded).hexdigest()[:12].upper()}"


def simulate(
    selected_faults: Iterable[Fault],
    ticks: int = 36,
    station: str = GROUND_STATIONS[0],
) -> SimulationResult:
    """Run the deterministic spacecraft and ground-pass model.

    Rules:
    - A memory fault suppresses heartbeats at start_tick through start_tick + 2;
      the third miss triggers a reset and three ticks in SAFE mode.
    - A thermal fault changes only the temperature at its start tick.
    - A packet fault changes only checksum validity at its start tick.
    - RF interference subtracts 24 dB from SNR for six ticks. Ground anomalies are
      detected from SNR residual, packet loss, link margin, and receiver lock.
    """

    if not isinstance(ticks, int) or not 24 <= ticks <= 96:
        raise ValueError("ticks must be an integer between 24 and 96")
    if station not in GROUND_STATIONS:
        raise ValueError(f"Unknown ground station: {station!r}")

    faults = tuple(selected_faults)
    by_kind = {fault.kind: fault for fault in faults}
    if len(by_kind) != len(faults):
        raise ValueError("Only one fault of each kind is supported in this demo")

    telemetry: list[dict] = []
    events: list[dict] = []
    resets = 0
    safe_until = -1
    memory = by_kind.get("memory_bit_flip")
    thermal = by_kind.get("thermal_spike")
    packet = by_kind.get("packet_corruption")
    interference = by_kind.get("rf_interference")
    pass_start = 4
    pass_end = ticks - 5

    for tick in range(ticks):
        heartbeat_ok = True
        checksum_ok = True
        mode = "NOMINAL"
        temperature_c = round(18.0 + 2.4 * math.sin(tick / 4.0), 2)
        battery_v = round(8.15 + 0.12 * math.sin(tick / 5.0), 3)

        if memory and memory.start_tick <= tick <= memory.start_tick + 2:
            heartbeat_ok = False
            events.append({
                "tick": tick,
                "severity": "WARNING",
                "code": "HEARTBEAT_MISSED",
                "message": "No valid housekeeping heartbeat received.",
            })

        reset_this_tick = bool(memory and tick == memory.start_tick + 2)
        if reset_this_tick:
            resets += 1
            safe_until = tick + 2
            events.append({
                "tick": tick,
                "severity": "CRITICAL",
                "code": "WATCHDOG_RESET",
                "message": "Watchdog reset triggered after three missed heartbeats.",
            })

        if tick <= safe_until:
            mode = "SAFE"

        if thermal and tick == thermal.start_tick:
            temperature_c = 92.4
            events.append({
                "tick": tick,
                "severity": "MAJOR",
                "code": "THERMAL_LIMIT",
                "message": "Temperature 92.4 °C exceeds the 80.0 °C demo limit.",
            })

        if packet and tick == packet.start_tick:
            checksum_ok = False
            events.append({
                "tick": tick,
                "severity": "MAJOR",
                "code": "CHECKSUM_MISMATCH",
                "message": "Packet payload checksum does not match the received value.",
            })

        # A simple visible-pass profile. The expected SNR is based on elevation;
        # interference is observable only through its effect on measured link data.
        in_pass = pass_start <= tick <= pass_end
        pass_progress = (tick - pass_start) / (pass_end - pass_start)
        elevation_deg = (
            round(90.0 * math.sin(math.pi * pass_progress), 2) if in_pass else 0.0
        )
        expected_snr_db = round(8.0 + 0.17 * elevation_deg, 2) if in_pass else 0.0
        interference_active = bool(
            interference
            and interference.start_tick <= tick <= interference.start_tick + 5
        )
        snr_db = (
            round(expected_snr_db - (24.0 if interference_active else 0.0), 2)
            if in_pass else 0.0
        )
        snr_residual_db = round(snr_db - expected_snr_db, 2) if in_pass else 0.0
        link_margin_db = round(snr_db - REQUIRED_SNR_DB, 2) if in_pass else 0.0
        packet_loss_percent = (
            round(min(100.0, max(0.4, (REQUIRED_SNR_DB - snr_db) * 16.0)), 1)
            if in_pass else 0.0
        )
        receiver_lock = bool(in_pass and link_margin_db >= 0.0)
        link_status = (
            "TRACKING" if receiver_lock else "SEARCHING" if in_pass else "IDLE"
        )
        interference_suspected = bool(
            in_pass
            and snr_residual_db <= INTERFERENCE_RESIDUAL_DB
            and packet_loss_percent >= INTERFERENCE_PACKET_LOSS_PERCENT
        )
        packets_sent = 10 if in_pass else 0
        packets_lost = round(packets_sent * packet_loss_percent / 100.0)

        if in_pass and link_margin_db < 0:
            events.append({
                "tick": tick,
                "severity": "WARNING",
                "code": "LINK_MARGIN_LOW",
                "message": f"Link margin {link_margin_db:.2f} dB is below zero.",
            })
        if interference_suspected:
            events.append({
                "tick": tick,
                "severity": "MAJOR",
                "code": "RF_INTERFERENCE_SUSPECTED",
                "message": (
                    f"SNR residual {snr_residual_db:.2f} dB with "
                    f"{packet_loss_percent:.1f}% packet loss suggests interference."
                ),
            })
        if in_pass and not receiver_lock:
            events.append({
                "tick": tick,
                "severity": "CRITICAL",
                "code": "LINK_LOST",
                "message": f"{station} receiver has no lock during a visible pass.",
            })

        telemetry.append({
            "tick": tick,
            "mode": mode,
            "battery_v": battery_v,
            "temperature_c": temperature_c,
            "heartbeat_ok": heartbeat_ok,
            "checksum_ok": checksum_ok,
            "reset_count": resets,
            "in_pass": in_pass,
            "elevation_deg": elevation_deg,
            "expected_snr_db": expected_snr_db,
            "snr_db": snr_db,
            "snr_residual_db": snr_residual_db,
            "link_margin_db": link_margin_db,
            "packet_loss_percent": packet_loss_percent,
            "receiver_lock": receiver_lock,
            "link_status": link_status,
            "interference_suspected": interference_suspected,
            "packets_sent": packets_sent,
            "packets_lost": packets_lost,
            "event_count": len([event for event in events if event["tick"] == tick]),
        })

    incidents: list[dict] = []
    # One incident per anomaly type keeps a multi-tick RF burst inspectable as one case.
    triggers: list[dict] = []
    seen_trigger_codes: set[str] = set()
    for event in events:
        if event["code"] in TRIGGER_DETAILS and event["code"] not in seen_trigger_codes:
            triggers.append(event)
            seen_trigger_codes.add(event["code"])
    for index, event in enumerate(triggers, start=1):
        details = TRIGGER_DETAILS[event["code"]]
        incidents.append({
            "id": f"INC-{index:03d}",
            "trigger_code": event["code"],
            "trigger_tick": event["tick"],
            "title": details["title"],
            "summary": details["summary"],
            "candidate_fault_ids": [
                fault.id for fault in faults if fault.start_tick <= event["tick"]
            ],
        })

    run_id = _make_run_id(ticks, station, faults, telemetry)
    return SimulationResult(
        run_id=run_id,
        station=station,
        ticks=ticks,
        faults=faults,
        telemetry=tuple(telemetry),
        events=tuple(events),
        incidents=tuple(incidents),
    )


def get_incident(run: SimulationResult, incident_id: str) -> dict:
    """Fetch one incident or raise a clear validation error."""

    for incident in run.incidents:
        if incident["id"] == incident_id:
            return incident
    raise ValueError(f"Incident {incident_id!r} does not belong to {run.run_id}")


def replay_without_fault(
    original: SimulationResult,
    incident_id: str,
    fault_id: str,
) -> ReplayResult:
    """Remove one known fault and repeat the entire deterministic simulation."""

    incident = get_incident(original, incident_id)
    matching = [fault for fault in original.faults if fault.id == fault_id]
    if not matching:
        raise ValueError(f"Fault {fault_id!r} is not active in {original.run_id}")
    if fault_id not in incident["candidate_fault_ids"]:
        raise ValueError(f"Fault {fault_id!r} is not a candidate for {incident_id}")

    remaining = tuple(fault for fault in original.faults if fault.id != fault_id)
    replay = simulate(remaining, ticks=original.ticks, station=original.station)
    trigger_still_present = any(
        event["code"] == incident["trigger_code"]
        and event["tick"] == incident["trigger_tick"]
        for event in replay.events
    )
    changed_ticks = tuple(
        before["tick"]
        for before, after in zip(original.telemetry, replay.telemetry, strict=True)
        if before != after
    )

    return ReplayResult(
        incident_id=incident_id,
        removed_fault=matching[0],
        outcome="persists" if trigger_still_present else "prevented_in_replay",
        original_event_count=len(original.events),
        replay_event_count=len(replay.events),
        original_resets=original.telemetry[-1]["reset_count"],
        replay_resets=replay.telemetry[-1]["reset_count"],
        changed_ticks=changed_ticks,
        replay=replay,
    )


def simulation_to_dict(run: SimulationResult) -> dict:
    """Convert a run to a stable JSON-compatible evidence object."""

    return {
        "schema_version": SCHEMA_VERSION,
        "simulation_notice": SIMULATION_NOTICE,
        **asdict(run),
    }


def build_incident_report(
    original: SimulationResult,
    incident_id: str,
    replay_result: ReplayResult | None = None,
) -> dict:
    """Build a traceable incident report with optional counterfactual evidence."""

    incident = get_incident(original, incident_id)
    if replay_result and replay_result.incident_id != incident_id:
        raise ValueError("Replay result belongs to a different incident")

    tick = incident["trigger_tick"]
    start = max(0, tick - 3)
    stop = min(original.ticks, tick + 4)
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_type": "qec_flight_recorder_incident",
        "simulation_notice": SIMULATION_NOTICE,
        "original_run": {
            "run_id": original.run_id,
            "ground_station": original.station,
            "ticks": original.ticks,
            "injected_faults": [asdict(fault) for fault in original.faults],
        },
        "incident": incident,
        "observed_evidence": {
            "events": [
                event for event in original.events
                if start <= event["tick"] < stop
            ],
            "telemetry_window": list(original.telemetry[start:stop]),
        },
        "counterfactual": None,
        "limitations": [
            "All telemetry and faults are generated by explicit demo rules.",
            "A prevented incident means only that the trigger disappeared in this model replay.",
            "Real spacecraft diagnosis requires independent telemetry, design knowledge, and verification.",
        ],
    }

    if replay_result:
        report["counterfactual"] = {
            "removed_fault": asdict(replay_result.removed_fault),
            "outcome": replay_result.outcome,
            "replay_run_id": replay_result.replay.run_id,
            "original_event_count": replay_result.original_event_count,
            "replay_event_count": replay_result.replay_event_count,
            "original_resets": replay_result.original_resets,
            "replay_resets": replay_result.replay_resets,
            "changed_ticks": list(replay_result.changed_ticks),
            "replay_events": list(replay_result.replay.events),
        }
    return report


def report_to_json(report: dict) -> str:
    """Serialize an incident report deterministically for download."""

    return json.dumps(report, indent=2, sort_keys=True) + "\n"
