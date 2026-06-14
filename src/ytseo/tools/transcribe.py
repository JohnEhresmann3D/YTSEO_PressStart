"""Audio transcription using faster-whisper."""

from pathlib import Path

from ytseo.core.config import MODELS_DIR, WHISPER_MODEL
from ytseo.core.models import TranscriptionResult, TranscriptionSegment

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
            download_root=str(MODELS_DIR),
        )
    return _model


def transcribe_audio(audio_path: str, language: str | None = None) -> TranscriptionResult:
    """Transcribe an audio file using faster-whisper.

    Args:
        audio_path: Path to the audio file (WAV recommended).
        language: Language code (e.g. 'en'). None for auto-detection.

    Returns:
        TranscriptionResult with full text, detected language, and segments.
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    model = _get_model()
    segments_iter, info = model.transcribe(
        str(path),
        language=language,
        beam_size=5,
        vad_filter=True,
    )

    segments = []
    full_text_parts = []
    for seg in segments_iter:
        segments.append(TranscriptionSegment(
            start=round(seg.start, 2),
            end=round(seg.end, 2),
            text=seg.text.strip(),
        ))
        full_text_parts.append(seg.text.strip())

    return TranscriptionResult(
        text=" ".join(full_text_parts),
        language=info.language,
        segments=segments,
    )
