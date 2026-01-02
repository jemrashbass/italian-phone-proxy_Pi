"""
Whisper API integration for Italian speech-to-text.

Uses OpenAI's Whisper API for transcription with Italian language hints.
Includes confidence tracking for analytics.
"""
import io
import logging
import math
import os
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class WhisperService:
    """
    Speech-to-text using OpenAI Whisper API.
    
    Optimized for Italian with English speaker accent.
    Tracks transcription confidence for analytics.
    """
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "whisper-1"
        
        # Confidence tracking for analytics
        self.last_confidence: float = 0.0
        self.last_language: str = "it"
        self.last_duration: float = 0.0
        
        # Italian transcription hints
        # Common words/phrases to help with recognition
        self.prompt_hint = (
            "Pronto, buongiorno, buonasera, grazie, prego, "
            "codice fiscale, codice cliente, POD, PDR, "
            "bolletta, fattura, contatore, lettura, "
            "appuntamento, installazione, fibra, "
            "San Giuliano Terme, Pisa, Via Barachini"
        )
    
    def _logprob_to_confidence(self, avg_logprob: float) -> float:
        """
        Convert Whisper's average log probability to a 0-1 confidence score.
        
        Whisper's avg_logprob typically ranges from -1.0 (high confidence) 
        to -2.0 or lower (low confidence). We map this to 0-1 scale.
        
        Mapping:
            -0.5 or higher -> 1.0 (very confident)
            -1.0 -> ~0.85
            -1.5 -> ~0.60
            -2.0 -> ~0.35
            -3.0 or lower -> ~0.05
        """
        if avg_logprob >= -0.5:
            return 1.0
        elif avg_logprob <= -3.0:
            return 0.05
        else:
            # Sigmoid-like mapping for the -0.5 to -3.0 range
            # This gives a smooth curve that matches intuitive confidence levels
            normalized = (avg_logprob + 0.5) / 2.5  # Maps -0.5 to 0, -3.0 to -1
            confidence = 1.0 / (1.0 + math.exp(-5 * (normalized + 0.5)))
            return round(confidence, 3)
    
    async def transcribe(
        self, 
        audio_data: bytes,
        language: str = "it",
        prompt: Optional[str] = None
    ) -> Optional[str]:
        """
        Transcribe audio to text.
        
        Args:
            audio_data: WAV format audio bytes
            language: Language code (default: Italian)
            prompt: Optional context prompt for better recognition
            
        Returns:
            Transcribed text or None if failed
            
        Side effects:
            Updates self.last_confidence with transcription confidence (0-1)
            Updates self.last_language with detected language
            Updates self.last_duration with audio duration in seconds
        """
        if not audio_data:
            self.last_confidence = 0.0
            return None
        
        try:
            # Create file-like object for API
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"  # Whisper needs a filename
            
            # Use prompt hint for better Italian recognition
            full_prompt = self.prompt_hint
            if prompt:
                full_prompt = f"{prompt}. {self.prompt_hint}"
            
            # Use verbose_json to get confidence data
            response = await self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                language=language,
                prompt=full_prompt,
                response_format="verbose_json"
            )
            
            # Extract confidence from segments
            if hasattr(response, 'segments') and response.segments:
                # Average the avg_logprob across all segments
                logprobs = [s.get('avg_logprob', -2.0) for s in response.segments if 'avg_logprob' in s]
                if logprobs:
                    avg_logprob = sum(logprobs) / len(logprobs)
                    self.last_confidence = self._logprob_to_confidence(avg_logprob)
                else:
                    self.last_confidence = 0.0
            else:
                # No segments available
                self.last_confidence = 0.0
            
            # Store other metadata
            self.last_language = getattr(response, 'language', language)
            self.last_duration = getattr(response, 'duration', 0.0)
            
            # Extract transcript text
            transcript = response.text.strip() if hasattr(response, 'text') and response.text else None
            
            if transcript:
                logger.info(f"Whisper transcription (confidence: {self.last_confidence:.2f}): {transcript}")
            else:
                logger.debug("Empty transcription result")
                self.last_confidence = 0.0
            
            return transcript
            
        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            self.last_confidence = 0.0
            return None
    
    async def transcribe_with_timestamps(
        self,
        audio_data: bytes,
        language: str = "it"
    ) -> Optional[dict]:
        """
        Transcribe audio with word-level timestamps.
        
        Useful for future features like highlighting words in real-time.
        
        Returns:
            Dict with 'text', 'words', 'confidence', 'language', 'duration'
        """
        if not audio_data:
            return None
        
        try:
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"
            
            response = await self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                language=language,
                prompt=self.prompt_hint,
                response_format="verbose_json",
                timestamp_granularities=["word"]
            )
            
            # Calculate confidence
            confidence = 0.0
            if hasattr(response, 'segments') and response.segments:
                logprobs = [s.get('avg_logprob', -2.0) for s in response.segments if 'avg_logprob' in s]
                if logprobs:
                    avg_logprob = sum(logprobs) / len(logprobs)
                    confidence = self._logprob_to_confidence(avg_logprob)
            
            # Update instance state
            self.last_confidence = confidence
            self.last_language = getattr(response, 'language', language)
            self.last_duration = getattr(response, 'duration', 0.0)
            
            return {
                "text": response.text,
                "words": response.words if hasattr(response, 'words') else [],
                "language": response.language,
                "duration": response.duration,
                "confidence": confidence
            }
            
        except Exception as e:
            logger.error(f"Whisper transcription with timestamps failed: {e}")
            self.last_confidence = 0.0
            return None


# Singleton instance
_whisper_service: Optional[WhisperService] = None


def get_whisper_service() -> WhisperService:
    """Get or create the Whisper service singleton."""
    global _whisper_service
    if _whisper_service is None:
        _whisper_service = WhisperService()
    return _whisper_service