"""Tests for chunked faster-whisper STT in voice_stt.py."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

try:
    import faster_whisper  # noqa: F401
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False


def _generate_sine_wav(path: str, duration_s: float = 2.0) -> None:
    """Generate a sine wave WAV file for testing."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_s}",
            "-ar", "16000", "-ac", "1",
            path,
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )


def _generate_speech_wav(path: str, text: str = "hello world testing one two three") -> None:
    """Generate speech WAV using flite TTS if available."""
    try:
        subprocess.run(
            ["flite", "-t", text, "-o", path],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback: generate sine wave
        _generate_sine_wav(path, duration_s=3.0)


@unittest.skipUnless(HAS_FASTER_WHISPER, "faster-whisper not installed")
class TestChunkedSTT(unittest.TestCase):
    """Test chunked transcription via faster-whisper."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="cj_stt_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_plan_chunks_short_audio(self) -> None:
        """Short audio produces a single chunk."""
        from voice_stt import plan_chunks

        wav_path = os.path.join(self.tmpdir, "short.wav")
        _generate_sine_wav(wav_path, duration_s=2.0)

        chunks = plan_chunks(wav_path, chunk_duration_s=300)
        self.assertGreaterEqual(len(chunks), 1)
        # Single chunk for short audio
        self.assertEqual(chunks[0]["chunk_index"], 0)
        self.assertGreater(chunks[0]["end_s"], 0)

    def test_plan_chunks_splits_longer_audio(self) -> None:
        """10s audio with 3s chunks produces multiple chunks."""
        from voice_stt import plan_chunks

        wav_path = os.path.join(self.tmpdir, "long.wav")
        _generate_sine_wav(wav_path, duration_s=10.0)

        chunks = plan_chunks(wav_path, chunk_duration_s=3, overlap_s=0.5)
        self.assertGreater(len(chunks), 1)
        # Verify chunk boundaries
        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk["chunk_index"], i)
            if i > 0:
                # Overlap means this chunk starts before previous ended
                prev_end = chunks[i - 1]["end_s"]
                self.assertLess(chunk["start_s"], prev_end)

    def test_transcribe_chunk_produces_segments(self) -> None:
        """A single chunk transcription returns segments."""
        from voice_stt import transcribe_audio_chunked

        wav_path = os.path.join(self.tmpdir, "speech.wav")
        _generate_speech_wav(wav_path)

        result = transcribe_audio_chunked(
            wav_path,
            language="en",
            model_size="tiny",
            chunk_duration_s=300,  # single chunk
        )
        self.assertIn("text", result)
        self.assertIn("segments", result)
        self.assertIn("duration_s", result)
        self.assertIsInstance(result["segments"], list)

    def test_merge_deduplicates_overlap(self) -> None:
        """Merge removes duplicate segments from chunk overlap."""
        from voice_stt import merge_chunk_results

        chunk_results = [
            {
                "chunk_index": 0,
                "start_offset_s": 0.0,
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": "hello"},
                    {"start": 1.5, "end": 2.8, "text": "world"},
                ],
                "text": "hello world",
            },
            {
                "chunk_index": 1,
                "start_offset_s": 2.5,
                "segments": [
                    {"start": 0.0, "end": 0.5, "text": "world"},  # overlap duplicate
                    {"start": 0.5, "end": 2.0, "text": "testing"},
                ],
                "text": "world testing",
            },
        ]
        merged = merge_chunk_results(chunk_results, overlap_s=0.5)
        self.assertIn("segments", merged)
        texts = [s["text"].strip() for s in merged["segments"]]
        # "world" should appear once, not twice
        self.assertEqual(texts.count("world"), 1)

    def test_model_singleton_loads_once(self) -> None:
        """Model is loaded only once (singleton)."""
        from voice_stt import _get_faster_whisper_model

        model1 = _get_faster_whisper_model("tiny")
        model2 = _get_faster_whisper_model("tiny")
        self.assertIs(model1, model2)


if __name__ == "__main__":
    unittest.main()
