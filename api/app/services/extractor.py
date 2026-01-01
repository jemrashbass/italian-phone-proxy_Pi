"""
Document extraction using Claude Vision API.
"""
import anthropic
import base64
from pathlib import Path
import json
import logging
from typing import Optional

from app.prompts.extraction import EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


class DocumentExtractor:
    """Extract structured data from Italian utility bills and documents."""
    
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.model = "claude-sonnet-4-20250514"
    
    async def extract(self, file_path: Path) -> dict:
        """
        Extract information from a document.
        
        Args:
            file_path: Path to PDF or image file
            
        Returns:
            Structured extraction result
        """
        logger.info(f"Extracting from: {file_path}")
        
        # Read and encode file
        with open(file_path, "rb") as f:
            file_data = base64.standard_b64encode(f.read()).decode("utf-8")
        
        # Determine media type
        suffix = file_path.suffix.lower()
        media_types = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }
        media_type = media_types.get(suffix, "application/octet-stream")
        
        logger.info(f"File type: {media_type}, size: {len(file_data)} bytes (base64)")
        
        # Determine content type for API
        content_type = "document" if suffix == ".pdf" else "image"
        
        try:
            # Call Claude Vision
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": content_type,
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": file_data
                                }
                            },
                            {
                                "type": "text",
                                "text": EXTRACTION_PROMPT
                            }
                        ]
                    }
                ]
            )
            
            # Parse JSON response
            response_text = message.content[0].text
            logger.info(f"Received response: {len(response_text)} chars")
            
            # Extract JSON from response (handle markdown code blocks)
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0]
            else:
                json_str = response_text
            
            result = json.loads(json_str.strip())
            logger.info(f"Successfully extracted: {result.get('document_type', 'unknown')}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extraction result: {e}")
            result = {
                "error": "Failed to parse extraction",
                "raw_response": response_text
            }
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            result = {
                "error": f"API error: {str(e)}",
                "raw_response": None
            }
        except Exception as e:
            logger.error(f"Unexpected error during extraction: {e}")
            result = {
                "error": f"Extraction failed: {str(e)}",
                "raw_response": None
            }
        
        return result
