"""
Whisper API integration for Italian speech-to-text.

Uses OpenAI's Whisper API for transcription with Italian language hints.
"""
import io
import logging
import os
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class WhisperService:
    """
    Speech-to-text using OpenAI Whisper API.
    
    Optimized for Italian with English speaker accent.
    """
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "whisper-1"
        
        # Italian transcription hints
        # Common words/phrases to help with recognition
        self.prompt_hint = (
            "Pronto, buongiorno, buonasera, grazie, prego, "
            "codice fiscale, codice cliente, POD, PDR, "
            "bolletta, fattura, contatore, lettura, "
            "appuntamento, installazione, fibra, "
            "San Giuliano Terme, Pisa, Via Barachini"
        )
    
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
        """
        if not audio_data:
            return None
        
        try:
            # Create file-like object for API
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"  # Whisper needs a filename
            
            # Use prompt hint for better Italian recognition
            full_prompt = self.prompt_hint
            if prompt:
                full_prompt = f"{prompt}. {self.prompt_hint}"
            
            response = await self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                language=language,
                prompt=full_prompt,
                response_format="text"
            )
            
            transcript = response.strip() if response else None
            
            if transcript:
                logger.info(f"Whisper transcription: {transcript}")
            else:
                logger.debug("Empty transcription result")
            
            return transcript
            
        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
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
            Dict with 'text' and 'words' (list of {word, start, end})
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
            
            return {
                "text": response.text,
                "words": response.words if hasattr(response, 'words') else [],
                "language": response.language,
                "duration": response.duration
            }
            
        except Exception as e:
            logger.error(f"Whisper transcription with timestamps failed: {e}")
            return None


# Singleton instance
_whisper_service: Optional[WhisperService] = None


def get_whisper_service() -> WhisperService:
    """Get or create the Whisper service singleton."""
    global _whisper_service
    if _whisper_service is None:
        _whisper_service = WhisperService()
    return _whisper_service
