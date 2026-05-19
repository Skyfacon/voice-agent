#!/usr/bin/env python3
"""Harness-local checks for the Duplex/VAD WebRTC VAD spike tools."""

from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest

import generate_synthetic_audio as synth
import run_webrtcvad_probe as probe


REQUIRED_CASES = {
    "speech_start_clean",
    "speech_end_clean",
    "short_backchannel",
    "silence_only",
    "noise_or_tone",
    "white_noise",
    "clipped_start",
    "tts_playback_only",
    "user_barge_in_over_tts",
    "near_end_barge_in",
    "client_stop_playback_simulation",
}


class SyntheticFixtureChecks(unittest.TestCase):
    def test_builds_all_required_synthetic_cases_without_raw_files(self) -> None:
        cases = synth.build_synthetic_cases(sample_rate_hz=16000, seed=20260511)

        self.assertEqual(REQUIRED_CASES, set(cases))
        self.assertGreater(len(cases["speech_start_clean"].signal), 0)
        self.assertEqual(cases["speech_start_clean"].expected_start_ms, 500)
        self.assertEqual(cases["speech_start_clean"].expected_end_ms, 1400)
        self.assertIsNotNone(cases["tts_playback_only"].raw_mic_signal)
        self.assertIsNotNone(cases["tts_playback_only"].playback_reference_signal)

    def test_local_wav_export_is_restricted_to_private_tmp(self) -> None:
        cases = synth.build_synthetic_cases(sample_rate_hz=16000, seed=20260511)

        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmpdir:
            written = synth.write_cases_to_wav(cases, pathlib.Path(tmpdir))
            self.assertIn("speech_start_clean", written)
            self.assertTrue(written["speech_start_clean"].is_file())

        with self.assertRaises(ValueError):
            synth.write_cases_to_wav(cases, pathlib.Path.cwd() / "unsafe-audio")


class ObservationSchemaChecks(unittest.TestCase):
    def test_schema_rejects_raw_artifact_flags(self) -> None:
        record = probe.client_stop_playback_observation(
            contract_snapshot="main@61e6afc",
            synthetic_seed=20260511,
        )
        probe.validate_observation(record)

        record["raw_audio_committed"] = True
        with self.assertRaises(ValueError):
            probe.validate_observation(record)

    @unittest.skipIf(importlib.util.find_spec("webrtcvad") is None, "webrtcvad not installed")
    def test_probe_emits_required_cases_and_echo_metadata(self) -> None:
        observations = probe.make_observations(
            contract_snapshot="main@61e6afc",
            frame_ms_values=[20],
            mode_values=[2],
            case_names=["all"],
            synthetic_seed=20260511,
            sample_rate_hz=16000,
        )

        case_names = {record["synthetic_case"] for record in observations}
        self.assertEqual(REQUIRED_CASES, case_names)

        clean = next(
            record
            for record in observations
            if record["synthetic_case"] == "speech_start_clean"
        )
        self.assertEqual(clean["speech_start_ms"], 500)
        self.assertEqual(clean["speech_start_emit_latency_ms"], 40)
        self.assertEqual(clean["speech_end_hangover_ms"], 200)
        self.assertFalse(clean["raw_audio_committed"])
        self.assertFalse(clean["deterministic_replay_reruns_vad"])

        playback = next(
            record
            for record in observations
            if record["synthetic_case"] == "tts_playback_only"
        )
        self.assertEqual(playback["vad_confidence_summary"], 0.0)
        self.assertGreater(playback["raw_vad_confidence_summary"], 0.9)
        self.assertEqual(
            playback["echo_likelihood_mode"],
            "degraded_playback_reference_required",
        )

        client_stop = next(
            record
            for record in observations
            if record["synthetic_case"] == "client_stop_playback_simulation"
        )
        self.assertEqual(client_stop["tts_truncated_owner"], "talker_playback_controller")
        self.assertEqual(client_stop["request_offset_ms"], 1040)
        self.assertEqual(client_stop["actual_stop_offset_ms"], 1100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
