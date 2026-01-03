"""
Insights API for call analytics.

Uses Claude to analyze call performance data and generate
structured recommendations for system parameter optimization.
"""
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Any
import anthropic

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    """A single parameter change recommendation."""
    id: str
    parameter: str  # e.g., "audio.silence_duration_ms"
    current_value: Any
    recommended_value: Any
    reasoning: str
    expected_impact: str  # e.g., "-300ms latency"
    priority: int  # 1 = highest priority
    confidence: str  # "high", "medium", "low"
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CallInsights:
    """Complete analysis of a call's performance."""
    call_sid: str
    analyzed_at: str
    
    # Overall assessment
    assessment: str
    performance_rating: str  # "good", "acceptable", "needs_improvement", "poor"
    
    # Key metrics summary
    key_metrics: dict
    
    # Issues identified
    issues: list[str]
    
    # Recommendations
    recommendations: list[Recommendation]
    
    # Quick wins (low-effort, high-impact)
    quick_wins: list[str]
    
    # Items needing investigation
    requires_investigation: list[str]
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d["recommendations"] = [r.to_dict() if isinstance(r, Recommendation) else r for r in self.recommendations]
        return d


class InsightsService:
    """
    Service for generating insights from call analytics.
    
    Uses Claude to analyze performance data and suggest optimizations.
    """
    
    ANALYSIS_PROMPT = """You are an expert system performance analyst for a voice AI phone agent system.
Analyze the following call analytics data and provide actionable recommendations.

## SYSTEM CONTEXT
This is an Italian Phone Proxy - an AI that answers phone calls in Italian on behalf of a non-native speaker.
The call pipeline is:
1. Caller speaks → Audio captured
2. Silence detected → Processing triggered  
3. Whisper API → Speech-to-text (STT)
4. Claude API → Generate response
5. OpenAI TTS → Text-to-speech
6. Audio sent to caller

## CURRENT SYSTEM CONFIGURATION
{config_json}

## CALL ANALYTICS DATA
{analytics_json}

## TURN-BY-TURN DATA
{turns_json}

## YOUR TASK
Analyze this data and provide:

1. **Assessment**: A 2-3 sentence summary of call performance
2. **Performance Rating**: One of: "good", "acceptable", "needs_improvement", "poor"
3. **Issues**: List specific problems identified (e.g., "Claude latency exceeds 3s on 5/9 turns")
4. **Recommendations**: Specific parameter changes with:
   - Which parameter to change (use exact path like "audio.silence_duration_ms")
   - Current and recommended values
   - Why this change helps
   - Expected impact (be specific: "-500ms latency", "20% fewer slow flags")
   - Priority (1=do first, 2=do second, etc.)
   - Confidence level ("high", "medium", "low")
5. **Quick Wins**: Low-effort changes that could help immediately
6. **Requires Investigation**: Issues that need more data or debugging

## RESPONSE FORMAT
Respond with a JSON object matching this structure exactly:
```json
{{
  "assessment": "string",
  "performance_rating": "good|acceptable|needs_improvement|poor",
  "key_metrics": {{
    "avg_latency_ms": number,
    "bottleneck_component": "whisper|claude|tts",
    "bottleneck_percentage": number,
    "quality_issues_count": number
  }},
  "issues": ["issue 1", "issue 2"],
  "recommendations": [
    {{
      "id": "rec_1",
      "parameter": "path.to.parameter",
      "current_value": current,
      "recommended_value": recommended,
      "reasoning": "why this helps",
      "expected_impact": "-Xms latency",
      "priority": 1,
      "confidence": "high|medium|low"
    }}
  ],
  "quick_wins": ["quick win 1"],
  "requires_investigation": ["thing to investigate"]
}}
```

Be specific and actionable. Base recommendations on the actual data provided.
If metrics look good, say so - don't invent problems.
"""
    
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        self.model = "claude-sonnet-4-20250514"
    
    async def analyze_call(
        self,
        call_data: dict,
        current_config: dict
    ) -> CallInsights:
        """
        Analyze a call and generate insights.
        
        Args:
            call_data: Full call data from analytics service (summary, turns, events)
            current_config: Current system configuration
            
        Returns:
            CallInsights object with recommendations
        """
        call_sid = call_data.get("call_sid", "unknown")
        analytics = call_data.get("analytics", {})
        turns = call_data.get("turns", [])
        
        # Build the analysis prompt
        prompt = self.ANALYSIS_PROMPT.format(
            config_json=json.dumps(current_config, indent=2),
            analytics_json=json.dumps(analytics, indent=2),
            turns_json=json.dumps(turns, indent=2)
        )
        
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Extract response text
            response_text = response.content[0].text if response.content else "{}"
            
            # Parse JSON from response
            insights_data = self._parse_response(response_text)
            
            # Build recommendations
            recommendations = []
            for i, rec in enumerate(insights_data.get("recommendations", [])):
                recommendations.append(Recommendation(
                    id=rec.get("id", f"rec_{i+1}"),
                    parameter=rec.get("parameter", ""),
                    current_value=rec.get("current_value"),
                    recommended_value=rec.get("recommended_value"),
                    reasoning=rec.get("reasoning", ""),
                    expected_impact=rec.get("expected_impact", ""),
                    priority=rec.get("priority", i+1),
                    confidence=rec.get("confidence", "medium")
                ))
            
            return CallInsights(
                call_sid=call_sid,
                analyzed_at=datetime.utcnow().isoformat() + "Z",
                assessment=insights_data.get("assessment", "Analysis unavailable"),
                performance_rating=insights_data.get("performance_rating", "unknown"),
                key_metrics=insights_data.get("key_metrics", {}),
                issues=insights_data.get("issues", []),
                recommendations=recommendations,
                quick_wins=insights_data.get("quick_wins", []),
                requires_investigation=insights_data.get("requires_investigation", [])
            )
            
        except Exception as e:
            logger.error(f"Failed to analyze call {call_sid}: {e}")
            return CallInsights(
                call_sid=call_sid,
                analyzed_at=datetime.utcnow().isoformat() + "Z",
                assessment=f"Analysis failed: {str(e)}",
                performance_rating="unknown",
                key_metrics={},
                issues=["Analysis failed - see logs"],
                recommendations=[],
                quick_wins=[],
                requires_investigation=["Check API connectivity and logs"]
            )
    
    def _parse_response(self, text: str) -> dict:
        """Parse JSON from Claude's response, handling markdown code blocks."""
        # Try to extract JSON from code block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse insights JSON: {e}")
            logger.debug(f"Raw response: {text}")
            return {}
    
    async def compare_calls(
        self,
        before_call: dict,
        after_call: dict,
        config_changes: list[dict]
    ) -> dict:
        """
        Compare two calls to measure impact of configuration changes.
        
        Args:
            before_call: Analytics from call before changes
            after_call: Analytics from call after changes
            config_changes: List of configuration changes made between calls
            
        Returns:
            Comparison analysis
        """
        before_analytics = before_call.get("analytics", {})
        after_analytics = after_call.get("analytics", {})
        
        # Calculate deltas
        latency_delta = (after_analytics.get("avg_total_ms", 0) - 
                        before_analytics.get("avg_total_ms", 0))
        
        whisper_delta = (after_analytics.get("avg_whisper_ms", 0) -
                        before_analytics.get("avg_whisper_ms", 0))
        
        claude_delta = (after_analytics.get("avg_claude_ms", 0) -
                       before_analytics.get("avg_claude_ms", 0))
        
        tts_delta = (after_analytics.get("avg_tts_ms", 0) -
                    before_analytics.get("avg_tts_ms", 0))
        
        tokens_delta = (after_analytics.get("avg_response_tokens", 0) -
                       before_analytics.get("avg_response_tokens", 0))
        
        return {
            "before_call_sid": before_call.get("call_sid"),
            "after_call_sid": after_call.get("call_sid"),
            "config_changes": config_changes,
            "impact": {
                "total_latency_delta_ms": latency_delta,
                "whisper_delta_ms": whisper_delta,
                "claude_delta_ms": claude_delta,
                "tts_delta_ms": tts_delta,
                "tokens_delta": tokens_delta,
                "improved": latency_delta < 0
            },
            "before_metrics": {
                "avg_total_ms": before_analytics.get("avg_total_ms", 0),
                "avg_whisper_ms": before_analytics.get("avg_whisper_ms", 0),
                "avg_claude_ms": before_analytics.get("avg_claude_ms", 0),
                "avg_tts_ms": before_analytics.get("avg_tts_ms", 0),
                "avg_response_tokens": before_analytics.get("avg_response_tokens", 0)
            },
            "after_metrics": {
                "avg_total_ms": after_analytics.get("avg_total_ms", 0),
                "avg_whisper_ms": after_analytics.get("avg_whisper_ms", 0),
                "avg_claude_ms": after_analytics.get("avg_claude_ms", 0),
                "avg_tts_ms": after_analytics.get("avg_tts_ms", 0),
                "avg_response_tokens": after_analytics.get("avg_response_tokens", 0)
            }
        }


# Singleton instance
_insights_service: Optional[InsightsService] = None


def get_insights_service() -> InsightsService:
    """Get or create the insights service singleton."""
    global _insights_service
    if _insights_service is None:
        _insights_service = InsightsService()
    return _insights_service