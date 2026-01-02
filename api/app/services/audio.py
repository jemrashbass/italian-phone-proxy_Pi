"""
Audio utilities for Twilio Media Streams.

Handles:
- mulaw 8kHz ↔ PCM conversion
- Audio buffering with silence detection
- Base64 encoding/decoding for Twilio
"""
import audioop
import base64
import io
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

# Twilio Media Streams uses mulaw 8kHz mono
TWILIO_SAMPLE_RATE = 8000
TWILIO_SAMPLE_WIDTH = 1  # mulaw is 8-bit
PCM_SAMPLE_WIDTH = 2  # 16-bit PCM for Whisper

# Silence detection thresholds
SILENCE_THRESHOLD = 500  # RMS threshold for silence (adjust as needed)
SILENCE_DURATION_MS = 1200  # ms of silence to trigger end of speech
MIN_SPEECH_DURATION_MS = 500  # Minimum speech duration to process


@dataclass
class AudioBuffer:
    """
    Buffer incoming audio and detect speech boundaries.
    
    Accumulates audio until silence is detected, then triggers callback.
    """
    sample_rate: int = TWILIO_SAMPLE_RATE
    silence_threshold: int = SILENCE_THRESHOLD
    silence_duration_ms: int = SILENCE_DURATION_MS
    min_speech_duration_ms: int = MIN_SPEECH_DURATION_MS
    
    # Internal state
    _buffer: bytes = field(default_factory=bytes)
    _speech_started: bool = False
    _silence_start: Optional[float] = None
    _speech_start: Optional[float] = None
    _peak_rms: int = 0  # Track peak RMS for analytics
    
    def reset(self):
        """Clear the buffer and reset state."""
        self._buffer = bytes()
        self._speech_started = False
        self._silence_start = None
        self._speech_start = None
        self._peak_rms = 0
    
    def get_rms(self, audio_chunk: bytes) -> int:
        """
        Calculate RMS level of audio chunk.
        
        Used for silence detection and analytics instrumentation.
        
        Args:
            audio_chunk: mulaw audio bytes
            
        Returns:
            RMS level as integer (0 if calculation fails)
        """
        if len(audio_chunk) < 2:
            return 0
        
        try:
            # Convert mulaw to linear PCM for RMS calculation
            linear = audioop.ulaw2lin(audio_chunk, PCM_SAMPLE_WIDTH)
            return audioop.rms(linear, PCM_SAMPLE_WIDTH)
        except audioop.error:
            return 0
    
    def is_speech(self, audio_chunk: bytes) -> bool:
        """
        Check if audio chunk contains speech (above silence threshold).
        
        Useful for analytics to detect when caller starts speaking.
        
        Args:
            audio_chunk: mulaw audio bytes
            
        Returns:
            True if audio is above silence threshold
        """
        rms = self.get_rms(audio_chunk)
        return rms > self.silence_threshold
    
    def get_peak_rms(self) -> int:
        """
        Get the peak RMS level recorded during current speech segment.
        
        Useful for analytics to understand audio quality.
        """
        return self._peak_rms
    
    def get_speech_duration_ms(self) -> int:
        """
        Get duration of current speech segment in milliseconds.
        
        Returns 0 if no speech in progress.
        """
        if self._speech_start is None:
            return 0
        return int((time.time() - self._speech_start) * 1000)
    
    def add_audio(self, mulaw_audio: bytes) -> Optional[bytes]:
        """
        Add mulaw audio to buffer.
        
        Returns:
            PCM audio bytes if speech segment complete, None otherwise
        """
        if not mulaw_audio:
            return None
        
        # Convert mulaw to PCM for RMS calculation
        try:
            pcm_audio = audioop.ulaw2lin(mulaw_audio, PCM_SAMPLE_WIDTH)
        except audioop.error as e:
            logger.warning(f"Audio conversion error: {e}")
            return None
        
        # Calculate RMS (volume level)
        try:
            rms = audioop.rms(pcm_audio, PCM_SAMPLE_WIDTH)
        except audioop.error:
            rms = 0
        
        current_time = time.time()
        is_speech = rms > self.silence_threshold
        
        if is_speech:
            # Speech detected
            self._silence_start = None
            
            # Track peak RMS for analytics
            if rms > self._peak_rms:
                self._peak_rms = rms
            
            if not self._speech_started:
                self._speech_started = True
                self._speech_start = current_time
                logger.debug("Speech started")
            
            # Add to buffer
            self._buffer += mulaw_audio
            
        else:
            # Silence detected
            if self._speech_started:
                # Still add audio during short silences (natural pauses)
                self._buffer += mulaw_audio
                
                if self._silence_start is None:
                    self._silence_start = current_time
                
                silence_duration = (current_time - self._silence_start) * 1000
                
                if silence_duration >= self.silence_duration_ms:
                    # End of speech segment
                    speech_duration = (current_time - self._speech_start) * 1000
                    
                    if speech_duration >= self.min_speech_duration_ms:
                        # Return the buffered audio
                        result = self._buffer
                        self.reset()
                        logger.debug(f"Speech segment complete: {len(result)} bytes, {speech_duration:.0f}ms")
                        return result
                    else:
                        # Too short, probably noise
                        logger.debug(f"Discarding short segment: {speech_duration:.0f}ms")
                        self.reset()
        
        return None
    
    def flush(self) -> Optional[bytes]:
        """
        Force flush any remaining audio in buffer.
        
        Call this when call ends to process any remaining speech.
        """
        if self._buffer and self._speech_started:
            result = self._buffer
            self.reset()
            return result
        return None


def mulaw_to_pcm(mulaw_audio: bytes) -> bytes:
    """Convert mulaw audio to 16-bit PCM."""
    return audioop.ulaw2lin(mulaw_audio, PCM_SAMPLE_WIDTH)


def pcm_to_mulaw(pcm_audio: bytes) -> bytes:
    """Convert 16-bit PCM audio to mulaw."""
    return audioop.lin2ulaw(pcm_audio, PCM_SAMPLE_WIDTH)


def resample_audio(audio: bytes, from_rate: int, to_rate: int, sample_width: int = PCM_SAMPLE_WIDTH) -> bytes:
    """Resample audio to different sample rate."""
    if from_rate == to_rate:
        return audio
    return audioop.ratecv(audio, sample_width, 1, from_rate, to_rate, None)[0]


def base64_decode_audio(b64_audio: str) -> bytes:
    """Decode base64 audio from Twilio."""
    return base64.b64decode(b64_audio)


def base64_encode_audio(audio: bytes) -> str:
    """Encode audio to base64 for Twilio."""
    return base64.b64encode(audio).decode('utf-8')


def pcm_to_wav(pcm_audio: bytes, sample_rate: int = 16000, sample_width: int = 2, channels: int = 1) -> bytes:
    """
    Convert raw PCM audio to WAV format.
    
    Whisper API accepts WAV files, so we wrap PCM in WAV header.
    """
    # WAV header
    data_size = len(pcm_audio)
    file_size = data_size + 36  # 44 byte header - 8 bytes for RIFF chunk
    
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    
    wav_header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        file_size,
        b'WAVE',
        b'fmt ',
        16,  # fmt chunk size
        1,   # PCM format
        channels,
        sample_rate,
        byte_rate,
        block_align,
        sample_width * 8,  # bits per sample
        b'data',
        data_size
    )
    
    return wav_header + pcm_audio


def prepare_audio_for_whisper(mulaw_audio: bytes) -> bytes:
    """
    Convert Twilio mulaw 8kHz to WAV format for Whisper API.
    
    Whisper works best with 16kHz, so we:
    1. Convert mulaw to PCM
    2. Resample from 8kHz to 16kHz
    3. Wrap in WAV header
    """
    # mulaw to PCM
    pcm_audio = mulaw_to_pcm(mulaw_audio)
    
    # Resample 8kHz -> 16kHz
    pcm_16k = resample_audio(pcm_audio, TWILIO_SAMPLE_RATE, 16000)
    
    # Wrap in WAV
    wav_audio = pcm_to_wav(pcm_16k, sample_rate=16000)
    
    return wav_audio


def prepare_audio_for_twilio(pcm_audio: bytes, source_rate: int = 24000) -> str:
    """
    Convert TTS output (usually 24kHz PCM) to Twilio format.
    
    OpenAI TTS outputs 24kHz PCM. We need:
    1. Resample to 8kHz
    2. Convert to mulaw
    3. Base64 encode
    """
    # Resample to 8kHz
    pcm_8k = resample_audio(pcm_audio, source_rate, TWILIO_SAMPLE_RATE)
    
    # Convert to mulaw
    mulaw_audio = pcm_to_mulaw(pcm_8k)
    
    # Base64 encode
    return base64_encode_audio(mulaw_audio)