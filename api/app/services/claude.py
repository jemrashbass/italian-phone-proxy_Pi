"""
Claude API integration for phone conversations.

Handles the conversation loop with streaming responses.
"""
import logging
import os
from typing import Optional, AsyncGenerator
from dataclasses import dataclass, field

import anthropic

from app.prompts.system import build_system_prompt, get_quick_response

logger = logging.getLogger(__name__)


@dataclass
class ConversationState:
    """
    Tracks the state of an ongoing phone conversation.
    """
    call_sid: str
    caller_number: str
    system_prompt: str
    history: list[dict] = field(default_factory=list)
    turn_count: int = 0
    
    def add_caller_message(self, text: str):
        """Add caller's transcribed speech to history."""
        self.history.append({"role": "user", "content": text})
        self.turn_count += 1
    
    def add_assistant_message(self, text: str):
        """Add AI's response to history."""
        self.history.append({"role": "assistant", "content": text})
    
    def get_messages(self) -> list[dict]:
        """Get messages for Claude API call."""
        return self.history.copy()


class ClaudeConversationService:
    """
    Manages phone conversations using Claude API.
    """
    
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        # Using Sonnet for good balance of speed and quality
        self.model = "claude-sonnet-4-20250514"
        self.max_tokens = 150  # Keep responses short for phone
        
        # Active conversations by call_sid
        self._conversations: dict[str, ConversationState] = {}
    
    def start_conversation(
        self,
        call_sid: str,
        caller_number: str,
        knowledge: dict
    ) -> ConversationState:
        """
        Initialize a new conversation for an incoming call.
        """
        system_prompt = build_system_prompt(knowledge, caller_number)
        
        state = ConversationState(
            call_sid=call_sid,
            caller_number=caller_number,
            system_prompt=system_prompt
        )
        
        self._conversations[call_sid] = state
        logger.info(f"Started conversation for call {call_sid} from {caller_number}")
        
        return state
    
    def get_conversation(self, call_sid: str) -> Optional[ConversationState]:
        """Get existing conversation state."""
        return self._conversations.get(call_sid)
    
    def end_conversation(self, call_sid: str) -> Optional[ConversationState]:
        """End a conversation and return final state."""
        state = self._conversations.pop(call_sid, None)
        if state:
            logger.info(f"Ended conversation {call_sid} after {state.turn_count} turns")
        return state
    
    async def respond(
        self,
        call_sid: str,
        caller_text: str
    ) -> Optional[str]:
        """
        Generate a response to caller's speech.
        
        Args:
            call_sid: Twilio call identifier
            caller_text: Transcribed speech from caller
            
        Returns:
            AI response text or None if failed
        """
        state = self._conversations.get(call_sid)
        if not state:
            logger.error(f"No conversation found for call {call_sid}")
            return None
        
        if not caller_text or not caller_text.strip():
            return None
        
        # Check for quick response first
        quick = get_quick_response(caller_text)
        if quick:
            logger.info(f"Using quick response for: {caller_text}")
            state.add_caller_message(caller_text)
            state.add_assistant_message(quick)
            return quick
        
        # Add caller message to history
        state.add_caller_message(caller_text)
        
        try:
            # Call Claude API
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=state.system_prompt,
                messages=state.get_messages()
            )
            
            # Extract response text
            response_text = response.content[0].text if response.content else None
            
            if response_text:
                state.add_assistant_message(response_text)
                logger.info(f"Claude response: {response_text}")
            
            return response_text
            
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            # Return a safe fallback
            fallback = "Mi scusi, un momento per favore."
            state.add_assistant_message(fallback)
            return fallback
    
    async def respond_streaming(
        self,
        call_sid: str,
        caller_text: str
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming response for lower latency.
        
        Yields text chunks as they're generated.
        """
        state = self._conversations.get(call_sid)
        if not state:
            logger.error(f"No conversation found for call {call_sid}")
            return
        
        if not caller_text or not caller_text.strip():
            return
        
        # Check quick response
        quick = get_quick_response(caller_text)
        if quick:
            state.add_caller_message(caller_text)
            state.add_assistant_message(quick)
            yield quick
            return
        
        state.add_caller_message(caller_text)
        
        try:
            full_response = ""
            
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=state.system_prompt,
                messages=state.get_messages()
            ) as stream:
                async for text in stream.text_stream:
                    full_response += text
                    yield text
            
            if full_response:
                state.add_assistant_message(full_response)
                logger.info(f"Claude streaming response: {full_response}")
                
        except anthropic.APIError as e:
            logger.error(f"Claude API streaming error: {e}")
            fallback = "Mi scusi, un momento per favore."
            state.add_assistant_message(fallback)
            yield fallback
    
    def get_opening_greeting(self, knowledge: dict) -> str:
        """
        Get the opening greeting for a new call.
        
        This is pre-generated so we can respond immediately.
        """
        identity = knowledge.get("identity", {})
        name = identity.get("name", "")
        first_name = name.split()[0] if name else "qui"
        
        return (
            f"Pronto. Sì, sono {first_name}. "
            "Mi scusi, sono inglese e il mio italiano non è perfetto — "
            "parlo lentamente ma capisco bene. Mi dica pure."
        )
    
    def get_stalling_phrase(self) -> str:
        """Get a phrase to use while processing (buying time)."""
        import random
        phrases = [
            "Un momento...",
            "Un attimo per favore...",
            "Sì, un momento...",
        ]
        return random.choice(phrases)
    
    def get_clarification_request(self) -> str:
        """Get a phrase to ask caller to repeat."""
        import random
        phrases = [
            "Mi scusi, può ripetere?",
            "Mi scusi, non ho capito bene.",
            "Può ripetere più lentamente?",
        ]
        return random.choice(phrases)


# Singleton instance
_claude_service: Optional[ClaudeConversationService] = None


def get_claude_service() -> ClaudeConversationService:
    """Get or create the Claude service singleton."""
    global _claude_service
    if _claude_service is None:
        _claude_service = ClaudeConversationService()
    return _claude_service
