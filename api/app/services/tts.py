"""
Text-to-Speech service using OpenAI TTS API.

Generates Italian speech for phone responses.
"""
import io
import logging
import os
from typing import Optional, Literal

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# OpenAI TTS voices
# - alloy: neutral
# - echo: male
# - fable: storytelling  
# - onyx: deep male
# - nova: female (good for Italian)
# - shimmer: soft female

TTSVoice = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
TTSModel = Literal["tts-1", "tts-1-hd"]


class TTSService:
    """
    Text-to-speech using OpenAI TTS API.
    
    Generates Italian audio responses for phone calls.
    """
    
    def __init__(
        self,
        voice: TTSVoice = "onyx",  # (changed from nova female) good for Italian
        model: TTSModel = "tts-1",  # Faster, good enough for phone
        speed: float = 0.95  # Slightly slower for clarity
    ):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.voice = voice
        self.model = model
        self.speed = speed
        
        # Output format - pcm gives us raw audio we can process
        # OpenAI TTS outputs 24kHz 16-bit mono PCM
        self.output_format = "pcm"
        self.sample_rate = 24000  # OpenAI TTS sample rate
    
    async def synthesize(self, text: str) -> Optional[bytes]:
        """
        Convert text to speech.
        
        Args:
            text: Italian text to speak
            
        Returns:
            Raw PCM audio bytes (24kHz 16-bit mono) or None if failed
        """
        if not text or not text.strip():
            return None
        
        try:
            logger.info(f"TTS synthesizing: {text[:50]}...")
            
            response = await self.client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format=self.output_format,
                speed=self.speed
            )
            
            # Read the raw PCM data
            audio_data = response.read()
            
            logger.debug(f"TTS generated {len(audio_data)} bytes")
            return audio_data
            
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            return None
    
    async def synthesize_streaming(self, text: str):
        """
        Stream TTS audio in chunks.
        
        Yields PCM audio chunks as they're generated.
        Useful for reducing latency on longer responses.
        """
        if not text or not text.strip():
            return
        
        try:
            logger.info(f"TTS streaming: {text[:50]}...")
            
            async with self.client.audio.speech.with_streaming_response.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format=self.output_format,
                speed=self.speed
            ) as response:
                async for chunk in response.iter_bytes(chunk_size=4096):
                    yield chunk
                    
        except Exception as e:
            logger.error(f"TTS streaming failed: {e}")


class TTSCache:
    """
    Simple in-memory cache for common phrases.
    
    Pre-generate audio for frequently used phrases to reduce latency.
    """
    
    def __init__(self, tts_service: TTSService):
        self.tts = tts_service
        self._cache: dict[str, bytes] = {}
    
    async def preload_phrases(self, phrases: list[str]):
        """Pre-generate audio for common phrases."""
        for phrase in phrases:
            if phrase not in self._cache:
                audio = await self.tts.synthesize(phrase)
                if audio:
                    self._cache[phrase] = audio
                    logger.info(f"Cached TTS for: {phrase[:30]}...")
    
    async def get(self, text: str) -> Optional[bytes]:
        """Get audio, using cache if available."""
        if text in self._cache:
            logger.debug(f"TTS cache hit: {text[:30]}...")
            return self._cache[text]
        
        # Generate and cache
        audio = await self.tts.synthesize(text)
        if audio:
            self._cache[text] = audio
        return audio
    
    def clear(self):
        """Clear the cache."""
        self._cache.clear()


# Common Italian phrases to pre-cache
COMMON_PHRASES = [
    "Pronto. Un momento per favore.",
    "Mi scusi, può ripetere?",
    "Un attimo, per favore.",
    "Sì, confermo.",
    "No grazie, non mi interessa.",
    "Perfetto, grazie mille.",
    "Arrivederci.",
    "Mi scusi, non ho capito bene.",
    "Un momento che verifico.",
]


# Singleton instances
_tts_service: Optional[TTSService] = None
_tts_cache: Optional[TTSCache] = None


def get_tts_service() -> TTSService:
    """Get or create the TTS service singleton."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service


async def get_tts_cache() -> TTSCache:
    """Get or create the TTS cache singleton, preloading common phrases."""
    global _tts_cache, _tts_service
    
    if _tts_cache is None:
        if _tts_service is None:
            _tts_service = TTSService()
        _tts_cache = TTSCache(_tts_service)
        await _tts_cache.preload_phrases(COMMON_PHRASES)
    
    return _tts_cache
