"""
System Configuration Service.

Provides runtime-adjustable parameters for the Italian Phone Proxy.
Parameters are persisted to disk and can be modified without restart.

Key parameter groups:
- Audio: silence detection, speech thresholds
- Claude: model, tokens, context limits
- TTS: voice selection, speed
- Analytics: quality thresholds
"""
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)

CONFIG_DIR = Path("/app/data/config")
CONFIG_FILE = CONFIG_DIR / "system.json"
HISTORY_FILE = CONFIG_DIR / "config_history.jsonl"


@dataclass
class AudioConfig:
    """Audio processing parameters."""
    silence_duration_ms: int = 1200  # How long silence before processing
    min_speech_duration_ms: int = 500  # Minimum speech to process
    silence_threshold: int = 500  # RMS threshold for silence detection
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass 
class ClaudeConfig:
    """Claude API parameters."""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 80  # Max response tokens
    context_turns: int = 4  # Number of turns to keep in history (4 turns = 8 messages)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TTSConfig:
    """Text-to-Speech parameters."""
    provider: str = "openai"
    voice: str = "onyx"  # OpenAI voice: alloy, echo, fable, onyx, nova, shimmer
    speed: float = 0.9  # Speech rate (0.25 to 4.0)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalyticsConfig:
    """Analytics threshold parameters."""
    slow_response_threshold_ms: int = 4000  # Flag turns slower than this
    confidence_threshold: float = 0.80  # Flag low confidence below this
    echo_similarity_threshold: float = 0.60  # Echo detection sensitivity
    repeat_similarity_threshold: float = 0.80  # Repeat detection sensitivity
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SystemConfig:
    """Complete system configuration."""
    audio: AudioConfig = field(default_factory=AudioConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)
    
    # Metadata
    version: int = 1
    updated_at: str = ""
    updated_by: str = ""
    
    def to_dict(self) -> dict:
        return {
            "audio": self.audio.to_dict(),
            "claude": self.claude.to_dict(),
            "tts": self.tts.to_dict(),
            "analytics": self.analytics.to_dict(),
            "version": self.version,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SystemConfig":
        """Create config from dictionary."""
        config = cls()
        
        # Load each section, using defaults if missing
        if "audio" in data:
            config.audio = AudioConfig(**data["audio"])
        else:
            config.audio = AudioConfig()
            
        if "claude" in data:
            config.claude = ClaudeConfig(**data["claude"])
        else:
            config.claude = ClaudeConfig()
            
        if "tts" in data:
            config.tts = TTSConfig(**data["tts"])
        else:
            config.tts = TTSConfig()
            
        if "analytics" in data:
            config.analytics = AnalyticsConfig(**data["analytics"])
        else:
            config.analytics = AnalyticsConfig()
        
        config.version = data.get("version", 1)
        config.updated_at = data.get("updated_at", "")
        config.updated_by = data.get("updated_by", "")
        
        return config


@dataclass
class ConfigChange:
    """Record of a configuration change."""
    timestamp: str
    parameter: str  # e.g., "audio.silence_duration_ms"
    old_value: Any
    new_value: Any
    source: str  # "manual", "recommendation", "api"
    recommendation_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)


class SystemConfigService:
    """
    Service for managing system configuration.
    
    Provides:
    - Load/save configuration to disk
    - Get/set individual parameters
    - Track configuration change history
    - Validate parameter values
    """
    
    # Parameter validation rules
    VALIDATION_RULES = {
        "audio.silence_duration_ms": {"min": 500, "max": 5000, "type": int},
        "audio.min_speech_duration_ms": {"min": 100, "max": 2000, "type": int},
        "audio.silence_threshold": {"min": 100, "max": 2000, "type": int},
        "claude.max_tokens": {"min": 20, "max": 500, "type": int},
        "claude.context_turns": {"min": 1, "max": 20, "type": int},
        "claude.model": {"type": str, "allowed": [
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022"
        ]},
        "tts.voice": {"type": str, "allowed": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]},
        "tts.speed": {"min": 0.5, "max": 1.5, "type": float},
        "analytics.slow_response_threshold_ms": {"min": 1000, "max": 10000, "type": int},
        "analytics.confidence_threshold": {"min": 0.5, "max": 1.0, "type": float},
    }
    
    def __init__(self):
        self._config: SystemConfig = SystemConfig()
        self._loaded = False
    
    @property
    def config(self) -> SystemConfig:
        """Get current configuration."""
        if not self._loaded:
            self.load()
        return self._config
    
    def load(self) -> SystemConfig:
        """Load configuration from disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                self._config = SystemConfig.from_dict(data)
                logger.info(f"Loaded system config v{self._config.version}")
            except Exception as e:
                logger.error(f"Failed to load config, using defaults: {e}")
                self._config = SystemConfig()
        else:
            logger.info("No config file found, using defaults")
            self._config = SystemConfig()
            self.save()  # Create default config file
        
        self._loaded = True
        return self._config
    
    def save(self) -> None:
        """Save configuration to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        self._config.updated_at = datetime.utcnow().isoformat() + "Z"
        
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._config.to_dict(), f, indent=2)
            logger.info("Saved system config")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            raise
    
    def get(self, path: str) -> Any:
        """
        Get a configuration value by dot-notation path.
        
        Example: get("audio.silence_duration_ms") -> 1200
        """
        parts = path.split(".")
        obj = self._config
        
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                raise KeyError(f"Unknown config path: {path}")
        
        return obj
    
    def set(
        self,
        path: str,
        value: Any,
        source: str = "api",
        recommendation_id: Optional[str] = None
    ) -> dict:
        """
        Set a configuration value by dot-notation path.
        
        Args:
            path: Dot-notation path (e.g., "audio.silence_duration_ms")
            value: New value
            source: Who made the change (manual, recommendation, api)
            recommendation_id: Optional ID linking to a recommendation
            
        Returns:
            Change record dict
        """
        # Validate
        self._validate(path, value)
        
        # Get current value
        old_value = self.get(path)
        
        # Handle type coercion for numeric types
        rules = self.VALIDATION_RULES.get(path, {})
        expected_type = rules.get("type")
        if expected_type == float and isinstance(value, int):
            value = float(value)
        elif expected_type == int and isinstance(value, float) and value == int(value):
            value = int(value)
        
        # Set new value
        parts = path.split(".")
        obj = self._config
        
        for part in parts[:-1]:
            obj = getattr(obj, part)
        
        setattr(obj, parts[-1], value)
        
        # Increment version
        self._config.version += 1
        self._config.updated_by = source
        
        # Save
        self.save()
        
        # Record change
        change = ConfigChange(
            timestamp=datetime.utcnow().isoformat() + "Z",
            parameter=path,
            old_value=old_value,
            new_value=value,
            source=source,
            recommendation_id=recommendation_id
        )
        self._record_change(change)
        
        logger.info(f"Config changed: {path} = {value} (was {old_value}) by {source}")
        
        return change.to_dict()
    
    def set_multiple(
        self,
        updates: list[dict],
        source: str = "api"
    ) -> list[dict]:
        """
        Set multiple configuration values at once.
        
        Args:
            updates: List of {"path": "...", "value": ...}
            source: Change source identifier
            
        Returns:
            List of change records
        """
        changes = []
        
        for update in updates:
            change = self.set(
                path=update["path"],
                value=update["value"],
                source=source,
                recommendation_id=update.get("recommendation_id")
            )
            changes.append(change)
        
        return changes
    
    def _validate(self, path: str, value: Any) -> None:
        """Validate a configuration value."""
        rules = self.VALIDATION_RULES.get(path)
        
        if not rules:
            # No specific rules, just check path exists
            try:
                self.get(path)
            except KeyError:
                raise ValueError(f"Unknown config path: {path}")
            return
        
        # Type check - be flexible with numeric types
        expected_type = rules.get("type")
        if expected_type:
            if expected_type == float:
                # Accept both int and float for float parameters
                if not isinstance(value, (int, float)):
                    raise ValueError(f"{path} must be a number, got {type(value).__name__}")
            elif expected_type == int:
                # Accept int, or float if it's a whole number
                if isinstance(value, float) and value == int(value):
                    pass  # Will be converted in set()
                elif not isinstance(value, int):
                    raise ValueError(f"{path} must be {expected_type.__name__}, got {type(value).__name__}")
            elif expected_type == bool:
                if not isinstance(value, bool):
                    raise ValueError(f"{path} must be bool, got {type(value).__name__}")
            elif not isinstance(value, expected_type):
                raise ValueError(f"{path} must be {expected_type.__name__}, got {type(value).__name__}")
        
        # Range check
        if "min" in rules and value < rules["min"]:
            raise ValueError(f"{path} must be >= {rules['min']}")
        if "max" in rules and value > rules["max"]:
            raise ValueError(f"{path} must be <= {rules['max']}")
        
        # Allowed values check
        if "allowed" in rules and value not in rules["allowed"]:
            raise ValueError(f"{path} must be one of: {rules['allowed']}")
    
    def _record_change(self, change: ConfigChange) -> None:
        """Append change to history file."""
        try:
            with open(HISTORY_FILE, "a") as f:
                f.write(json.dumps(change.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to record config change: {e}")
    
    def get_history(self, limit: int = 50) -> list[dict]:
        """Get recent configuration changes."""
        if not HISTORY_FILE.exists():
            return []
        
        changes = []
        try:
            with open(HISTORY_FILE) as f:
                for line in f:
                    if line.strip():
                        changes.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read config history: {e}")
            return []
        
        # Return most recent first
        return list(reversed(changes[-limit:]))
    
    def get_flat_config(self) -> dict:
        """
        Get configuration as flat key-value pairs.
        
        Useful for displaying in UI.
        """
        config = self._config.to_dict()
        flat = {}
        
        for section in ["audio", "claude", "tts", "analytics"]:
            for key, value in config.get(section, {}).items():
                flat[f"{section}.{key}"] = value
        
        return flat
    
    def get_parameter_metadata(self) -> dict:
        """
        Get metadata about all configurable parameters.
        
        Includes validation rules and descriptions.
        """
        return {
            "audio.silence_duration_ms": {
                "label": "Silence Duration (ms)",
                "description": "How long to wait after speech stops before processing",
                "type": "int",
                "min": 500,
                "max": 5000,
                "default": 1200,
                "unit": "ms"
            },
            "audio.min_speech_duration_ms": {
                "label": "Min Speech Duration (ms)",
                "description": "Minimum speech length to process (filters noise)",
                "type": "int",
                "min": 100,
                "max": 2000,
                "default": 500,
                "unit": "ms"
            },
            "audio.silence_threshold": {
                "label": "Silence Threshold (RMS)",
                "description": "Audio level below which is considered silence",
                "type": "int",
                "min": 100,
                "max": 2000,
                "default": 500,
                "unit": "RMS"
            },
            "claude.model": {
                "label": "Claude Model",
                "description": "Which Claude model to use for responses",
                "type": "select",
                "options": [
                    {"value": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4 (recommended)"},
                    {"value": "claude-3-5-sonnet-20241022", "label": "Claude 3.5 Sonnet"},
                    {"value": "claude-3-5-haiku-20241022", "label": "Claude 3.5 Haiku (faster)"}
                ],
                "default": "claude-sonnet-4-20250514"
            },
            "claude.max_tokens": {
                "label": "Max Response Tokens",
                "description": "Maximum tokens in Claude's response (lower = shorter responses)",
                "type": "int",
                "min": 20,
                "max": 500,
                "default": 80,
                "unit": "tokens"
            },
            "claude.context_turns": {
                "label": "Context Turns",
                "description": "Number of conversation turns to include in context",
                "type": "int",
                "min": 1,
                "max": 20,
                "default": 4,
                "unit": "turns"
            },
            "tts.voice": {
                "label": "TTS Voice",
                "description": "OpenAI voice for text-to-speech",
                "type": "select",
                "options": [
                    {"value": "onyx", "label": "Onyx (deep male)"},
                    {"value": "alloy", "label": "Alloy (neutral)"},
                    {"value": "echo", "label": "Echo (male)"},
                    {"value": "fable", "label": "Fable (British)"},
                    {"value": "nova", "label": "Nova (female)"},
                    {"value": "shimmer", "label": "Shimmer (female)"}
                ],
                "default": "onyx"
            },
            "tts.speed": {
                "label": "TTS Speed",
                "description": "Speech rate (0.5 = slow, 1.0 = normal, 1.5 = fast)",
                "type": "float",
                "min": 0.5,
                "max": 1.5,
                "step": 0.1,
                "default": 0.9
            },
            "analytics.slow_response_threshold_ms": {
                "label": "Slow Response Threshold (ms)",
                "description": "Responses slower than this are flagged as SLOW_RESPONSE",
                "type": "int",
                "min": 1000,
                "max": 10000,
                "default": 4000,
                "unit": "ms"
            },
            "analytics.confidence_threshold": {
                "label": "Confidence Threshold",
                "description": "Whisper confidence below this is flagged as LOW_CONFIDENCE",
                "type": "float",
                "min": 0.5,
                "max": 1.0,
                "step": 0.05,
                "default": 0.80
            }
        }


# Singleton instance
_config_service: Optional[SystemConfigService] = None


def get_system_config_service() -> SystemConfigService:
    """Get or create the system config service singleton."""
    global _config_service
    if _config_service is None:
        _config_service = SystemConfigService()
    return _config_service


def get_config() -> SystemConfig:
    """Convenience function to get current config."""
    return get_system_config_service().config