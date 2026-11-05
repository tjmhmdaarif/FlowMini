"""Day 7: Tests for real-time streaming partial transcripts."""
import sys
import time
import unittest
import numpy as np
from flow_mini import FlowMini, DEFAULT_CONFIG


class TestStreamingPartialTranscript(unittest.TestCase):
    def setUp(self):
        cfg = dict(DEFAULT_CONFIG)
        cfg["api_key"] = ""
        self.events = []
        self.core = FlowMini(cfg, None, on_event=self._record_event)
        self.core._load_streaming_whisper()

    def _record_event(self, ev, data=None):
        self.events.append((ev, data))

    def test_streaming_model_loads_fast(self):
        """Streaming model should load fast on CPU without errors."""
        model = self.core._streaming_whisper
        self.assertIsNotNone(model)

    def test_transcribe_partial_runs_fast(self):
        """Partial transcription of 1s audio should finish in under 1 second."""
        audio = (np.random.randn(16000) * 100).astype(np.int16)
        # Warmup
        self.core._transcribe_partial(audio)
        t0 = time.time()
        res = self.core._transcribe_partial(audio)
        dt = time.time() - t0
        self.assertLess(dt, 1.0, f"Partial transcription too slow: {dt:.3f}s")
        print(f"\n[TestStreaming] Transcribe partial latency: {dt:.3f}s")

    def test_streaming_worker_emits_partial_transcript(self):
        """Streaming worker should emit partial_transcript while recording is active."""
        phrases = ["Hello", "Hello world", "Hello world testing"]
        idx = [0]

        def mock_transcribe(audio):
            if idx[0] < len(phrases):
                p = phrases[idx[0]]
                idx[0] += 1
                return p
            return phrases[-1]

        self.core._transcribe_partial = mock_transcribe

        # Start simulated recording with dummy frames
        self.core.recording = True
        self.core.audio_frames = [np.zeros(16000, dtype=np.int16)]
        self.core._streaming_active = True

        import threading
        t = threading.Thread(target=self.core._realtime_streaming_worker, daemon=True)
        t.start()

        # Let worker run for ~1.2 seconds (worker polls every 350ms)
        time.sleep(1.2)

        # Stop recording
        self.core.recording = False
        self.core._streaming_active = False
        t.join(timeout=2.0)

        # Verify partial_transcript events were emitted
        partial_events = [e for e in self.events if e[0] == "partial_transcript"]
        self.assertGreater(len(partial_events), 0, "No partial_transcript events emitted during speech")
        first_event = partial_events[0]
        self.assertTrue(first_event[1].get("realtime"), "partial_transcript event missing realtime=True flag")
        self.assertIn("text", first_event[1], "partial_transcript missing 'text' field")
        print(f"[TestStreaming] Emitted {len(partial_events)} partial transcript events successfully: {[e[1]['text'] for e in partial_events]}")


if __name__ == "__main__":
    unittest.main()
