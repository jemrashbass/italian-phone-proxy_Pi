"""
Delivery Detection Service

Analyzes conversation to detect if it's delivery-related and should trigger
automatic location SMS sending.
"""
import re
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DeliveryContext:
    """Context about a detected delivery conversation."""
    is_delivery: bool
    confidence: float  # 0.0 to 1.0
    triggers: list[str]  # Which phrases triggered detection
    should_send_location: bool
    reason: str


# Italian phrases indicating delivery context
DELIVERY_INDICATORS = {
    # Direct delivery words (high confidence)
    "high": [
        r"\bcorriere\b",           # courier
        r"\bconsegna\b",           # delivery
        r"\bpacco\b",              # package
        r"\bspedizione\b",         # shipment
        r"\bcollo\b",              # parcel
        r"\bfattorino\b",          # delivery person
        r"\bpostino\b",            # postman
        r"\bamazon\b",
        r"\bdhl\b",
        r"\bups\b",
        r"\bbrt\b",                # Bartolini (Italian courier)
        r"\bgls\b",
        r"\bsda\b",
        r"\bposte\b",              # Italian postal service
        r"\bfedex\b",
    ],
    # Location/direction words (medium confidence - need combination)
    "medium": [
        r"\bdove\s+(sei|siete|abiti|abitano|trovo)\b",  # where are you / where do you live
        r"\bindirizzo\b",          # address
        r"\bvia\b",                # street
        r"\bnumero\s+civico\b",    # street number
        r"\bcancello\b",           # gate
        r"\bportone\b",            # main door
        r"\bcitofono\b",           # intercom
        r"\bpiano\b",              # floor
        r"\barrivare\b",           # to arrive
        r"\btrovare\b",            # to find
        r"\bposizione\b",          # position/location
        r"\bmappa\b",              # map
        r"\bnavigatore\b",         # GPS navigator
        r"\bgoogle\s*maps?\b",
        r"\bperso\b",              # lost
        r"\bnon\s+trovo\b",        # I can't find
    ],
    # Caller identification (low confidence alone, but confirms delivery)
    "low": [
        r"\bsono\s+il\s+corriere\b",   # I am the courier
        r"\bsono\s+qui\b",              # I am here
        r"\bsono\s+arrivato\b",         # I have arrived
        r"\bsto\s+arrivando\b",         # I am arriving
        r"\bsto\s+cercando\b",          # I am looking for
        r"\bsono\s+fuori\b",            # I am outside
        r"\bsono\s+sotto\b",            # I am downstairs
    ]
}

# Phrases that indicate directions were requested/given
DIRECTION_PHRASES = [
    r"\bcome\s+(arrivo|arrivare|raggiungo|raggiungere)\b",  # how do I get there
    r"\bdirezioni\b",                    # directions
    r"\bspiegare\b.*\bstrada\b",         # explain the way
    r"\bindicazioni\b",                  # directions/indications
    r"\bgira\s+(a\s+)?(destra|sinistra)\b",  # turn right/left
    r"\bdritto\b",                       # straight
    r"\bpoi\b",                          # then
    r"\bdopo\b",                         # after
]


class DeliveryDetector:
    """Detects delivery context in conversations."""
    
    def __init__(self):
        self.conversation_cache: dict[str, list[str]] = {}
        self.detection_cache: dict[str, DeliveryContext] = {}
    
    def analyze_text(self, text: str) -> tuple[float, list[str]]:
        """
        Analyze a single text for delivery indicators.
        
        Returns:
            (confidence_score, list_of_matched_phrases)
        """
        if not text:
            return 0.0, []
        
        text_lower = text.lower()
        matches = []
        score = 0.0
        
        # Check high confidence indicators
        for pattern in DELIVERY_INDICATORS["high"]:
            if re.search(pattern, text_lower):
                score += 0.5
                matches.append(pattern)
        
        # Check medium confidence indicators
        for pattern in DELIVERY_INDICATORS["medium"]:
            if re.search(pattern, text_lower):
                score += 0.25
                matches.append(pattern)
        
        # Check low confidence indicators
        for pattern in DELIVERY_INDICATORS["low"]:
            if re.search(pattern, text_lower):
                score += 0.15
                matches.append(pattern)
        
        return min(score, 1.0), matches
    
    def add_turn(self, call_sid: str, text: str, speaker: str):
        """Add a conversation turn for analysis."""
        if call_sid not in self.conversation_cache:
            self.conversation_cache[call_sid] = []
        
        self.conversation_cache[call_sid].append({
            "text": text,
            "speaker": speaker
        })
    
    def analyze_conversation(self, call_sid: str) -> DeliveryContext:
        """
        Analyze entire conversation for delivery context.
        
        Returns DeliveryContext with detection results.
        """
        if call_sid not in self.conversation_cache:
            return DeliveryContext(
                is_delivery=False,
                confidence=0.0,
                triggers=[],
                should_send_location=False,
                reason="No conversation data"
            )
        
        turns = self.conversation_cache[call_sid]
        all_text = " ".join([t["text"] for t in turns])
        
        # Analyze combined text
        confidence, triggers = self.analyze_text(all_text)
        
        # Check if directions were discussed
        directions_discussed = any(
            re.search(pattern, all_text.lower()) 
            for pattern in DIRECTION_PHRASES
        )
        
        # Determine if we should send location
        # Higher threshold if directions weren't discussed
        threshold = 0.3 if directions_discussed else 0.5
        
        is_delivery = confidence >= threshold
        should_send = is_delivery and (
            confidence >= 0.5 or  # High confidence - definitely send
            directions_discussed   # Directions were discussed - probably needs map
        )
        
        reason = ""
        if should_send:
            reason = f"Delivery detected (confidence: {confidence:.0%})"
            if directions_discussed:
                reason += ", directions discussed"
        elif is_delivery:
            reason = f"Likely delivery but low confidence ({confidence:.0%})"
        else:
            reason = "Not a delivery conversation"
        
        context = DeliveryContext(
            is_delivery=is_delivery,
            confidence=confidence,
            triggers=triggers,
            should_send_location=should_send,
            reason=reason
        )
        
        self.detection_cache[call_sid] = context
        return context
    
    def get_detection(self, call_sid: str) -> Optional[DeliveryContext]:
        """Get cached detection result for a call."""
        return self.detection_cache.get(call_sid)
    
    def clear_call(self, call_sid: str):
        """Clear data for a completed call."""
        self.conversation_cache.pop(call_sid, None)
        self.detection_cache.pop(call_sid, None)


# Singleton instance
_detector: Optional[DeliveryDetector] = None


def get_delivery_detector() -> DeliveryDetector:
    """Get or create the singleton delivery detector."""
    global _detector
    if _detector is None:
        _detector = DeliveryDetector()
    return _detector