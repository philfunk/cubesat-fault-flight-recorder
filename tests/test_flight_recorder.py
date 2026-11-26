from dataclasses import asdict
import json

import pytest

from flight_recorder import (
    build_incident_report,
    faults_for_ids,
    replay_without_fault,
    report_to_json,
    simulate,
    simulation_to_dict,
)


def test_nominal_run_has_no_anomalies():
    run = simulate(faults_for_ids([]))

    assert len(run.telemetry) == 36
    assert run.events == ()
    assert run.incidents == ()
    assert run.telemetry[-1]["reset_count"] == 0
    assert all(row["mode"] == "NOMINAL" for row in run.telemetry)


def test_memory_fault_produces_three_misses_then_safe_mode():
    run = simulate(faults_for_ids(["memory_bit_flip"]))

    missed = [event for event in run.events if event["code"] == "HEARTBEAT_MISSED"]
    assert [event["tick"] for event in missed] == [8, 9, 10]
    assert run.incidents[0]["trigger_code"] == "WATCHDOG_RESET"
    assert run.incidents[0]["trigger_tick"] == 10
    assert [run.telemetry[tick]["mode"] for tick in (10, 11, 12)] == ["SAFE"] * 3
    assert run.telemetry[13]["mode"] == "NOMINAL"


def test_thermal_and_packet_faults_create_separate_incidents():
    run = simulate(faults_for_ids(["thermal_spike", "packet_corruption"]))

    assert [incident["trigger_code"] for incident in run.incidents] == [
        "THERMAL_LIMIT",
        "CHECKSUM_MISMATCH",
    ]
    assert run.telemetry[14]["temperature_c"] == 92.4
    assert run.telemetry[18]["checksum_ok"] is False


def test_unchanged_simulation_is_exactly_reproducible():
    faults = faults_for_ids(["memory_bit_flip", "packet_corruption"])

    first = simulate(faults)
    second = simulate(faults)

    assert asdict(first) == asdict(second)
    assert first.run_id == second.run_id


def test_removing_memory_fault_prevents_watchdog_reset_only():
    original = simulate(faults_for_ids(["memory_bit_flip", "packet_corruption"]))

    replay = replay_without_fault(original, "INC-001", "memory_bit_flip")

    assert replay.outcome == "prevented_in_replay"
    assert replay.original_resets == 1
    assert replay.replay_resets == 0
    # The reset count remains different after SAFE mode ends, so all later rows differ.
    assert replay.changed_ticks == tuple(range(8, 36))
    assert any(
        event["code"] == "CHECKSUM_MISMATCH" for event in replay.replay.events
    )


def test_removing_packet_fault_prevents_checksum_incident_only():
    original = simulate(faults_for_ids(["memory_bit_flip", "packet_corruption"]))

    replay = replay_without_fault(original, "INC-002", "packet_corruption")

    assert replay.outcome == "prevented_in_replay"
    assert replay.replay_resets == 1
    assert all(row["checksum_ok"] for row in replay.replay.telemetry)


def test_unrelated_fault_removal_leaves_incident_present():
    original = simulate(faults_for_ids(["memory_bit_flip", "packet_corruption"]))

    replay = replay_without_fault(original, "INC-002", "memory_bit_flip")

    assert replay.outcome == "persists"
    assert replay.replay.incidents[0]["trigger_code"] == "CHECKSUM_MISMATCH"


def test_report_links_original_and_replay_evidence():
    original = simulate(faults_for_ids(["memory_bit_flip"]))

    replay = replay_without_fault(original, "INC-001", "memory_bit_flip")
    report = build_incident_report(original, "INC-001", replay)
    decoded = json.loads(report_to_json(report))

    assert report["original_run"]["run_id"] == original.run_id
    assert report["counterfactual"]["replay_run_id"] == replay.replay.run_id
    assert report["counterfactual"]["outcome"] == "prevented_in_replay"
    assert report["observed_evidence"]["events"][-1]["code"] == "WATCHDOG_RESET"
    assert decoded["simulation_notice"]


def test_invalid_inputs_fail_cleanly():
    run = simulate(faults_for_ids(["memory_bit_flip"]))

    with pytest.raises(ValueError, match="Unknown fault"):
        faults_for_ids(["not_a_fault"])
    with pytest.raises(ValueError, match="does not belong"):
        replay_without_fault(run, "INC-999", "memory_bit_flip")
    with pytest.raises(ValueError, match="not active"):
        replay_without_fault(run, "INC-001", "packet_corruption")
    with pytest.raises(ValueError, match="between 24 and 96"):
        simulate([], ticks=5)


def test_run_export_contains_all_evidence():
    run = simulate(faults_for_ids(["thermal_spike"]))
    exported = simulation_to_dict(run)

    assert exported["run_id"] == run.run_id
    assert len(exported["telemetry"]) == 36
    assert exported["incidents"][0]["trigger_tick"] == 14


def test_nominal_ground_pass_tracks_without_lost_packets():
    run = simulate(faults_for_ids([]))
    visible = [row for row in run.telemetry if row["in_pass"]]

    assert visible
    assert all(row["receiver_lock"] for row in visible)
    assert all(row["link_status"] == "TRACKING" for row in visible)
    assert sum(row["packets_lost"] for row in visible) == 0
    assert not any(row["interference_suspected"] for row in visible)


def test_rf_interference_is_detected_from_observable_link_evidence():
    run = simulate(faults_for_ids(["rf_interference"]))
    affected = [row for row in run.telemetry if row["interference_suspected"]]

    assert [row["tick"] for row in affected] == [12, 13, 14, 15, 16, 17]
    assert all(row["snr_residual_db"] == -24.0 for row in affected)
    assert all(row["packet_loss_percent"] == 100.0 for row in affected)
    assert all(not row["receiver_lock"] for row in affected)
    assert [incident["trigger_code"] for incident in run.incidents] == [
        "RF_INTERFERENCE_SUSPECTED",
        "LINK_LOST",
    ]


def test_removing_rf_interference_restores_link_and_clears_ground_incidents():
    original = simulate(faults_for_ids(["rf_interference", "packet_corruption"]))

    replay = replay_without_fault(original, "INC-001", "rf_interference")

    assert replay.outcome == "prevented_in_replay"
    assert not any(
        incident["trigger_code"] in {"RF_INTERFERENCE_SUSPECTED", "LINK_LOST"}
        for incident in replay.replay.incidents
    )
    assert all(row["receiver_lock"] for row in replay.replay.telemetry if row["in_pass"])
    assert any(
        incident["trigger_code"] == "CHECKSUM_MISMATCH"
        for incident in replay.replay.incidents
    )


def test_unrelated_spacecraft_fault_does_not_clear_rf_incident():
    original = simulate(faults_for_ids(["memory_bit_flip", "rf_interference"]))

    replay = replay_without_fault(original, "INC-002", "memory_bit_flip")

    assert replay.outcome == "persists"
    assert replay.replay.telemetry[12]["interference_suspected"] is True


def test_ground_station_and_link_evidence_are_exported():
    run = simulate(
        faults_for_ids(["rf_interference"]),
        station="AURORA-2 · Punta Arenas",
    )
    replay = replay_without_fault(run, "INC-001", "rf_interference")
    report = build_incident_report(run, "INC-001", replay)
    exported = simulation_to_dict(run)

    assert exported["station"] == "AURORA-2 · Punta Arenas"
    assert report["original_run"]["ground_station"] == run.station
    assert report["counterfactual"]["outcome"] == "prevented_in_replay"
    assert report["observed_evidence"]["telemetry_window"][3]["snr_db"] == -3.73
    with pytest.raises(ValueError, match="Unknown ground station"):
        simulate([], station="UNKNOWN")
