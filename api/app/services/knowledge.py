"""
Knowledge base management.
"""
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

KNOWLEDGE_PATH = Path("/app/data/config/knowledge.json")


class KnowledgeService:
    """Manage the knowledge base for the phone agent."""
    
    def __init__(self):
        self.data: Dict[str, Any] = {}
        self._default_structure()
    
    def _default_structure(self):
        """Initialize default knowledge structure."""
        self.data = {
            "identity": {
                "name": "",
                "codice_fiscale": "",
                "opening_phrase": "Mi scusi, sono inglese e il mio italiano non è perfetto"
            },
            "location": {
                "address": {
                    "via": "",
                    "numero": "",
                    "cap": "",
                    "comune": "",
                    "provincia": ""
                },
                "address_variants": [],
                "directions": {
                    "from_main_road": "",
                    "landmarks": [],
                    "house_description": ""
                },
                "coordinates": {
                    "lat": "",
                    "lon": ""
                },
                "google_maps_url": "",
                "gate_code": ""
            },
            "accounts": {},
            "house": {
                "neighbour_name": "",
                "neighbour_relation": "",
                "safe_place": "",
                "meter_locations": {}
            },
            "preferences": {
                "available_days": [],
                "preferred_time": "",
                "unavailable_dates": []
            },
            "verification_data": {},
            "metadata": {
                "last_updated": None,
                "extraction_history": []
            }
        }
    
    def load(self):
        """Load knowledge from file."""
        if KNOWLEDGE_PATH.exists():
            try:
                with open(KNOWLEDGE_PATH) as f:
                    saved = json.load(f)
                    self._deep_merge(self.data, saved)
                logger.info("Knowledge loaded from file")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to load knowledge file: {e}")
                logger.info("Using default knowledge structure")
        else:
            # Ensure parent directory exists
            KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.save()
            logger.info("Created new knowledge file")
    
    def save(self):
        """Save knowledge to file."""
        self.data["metadata"]["last_updated"] = datetime.now().isoformat()
        
        KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(KNOWLEDGE_PATH, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        
        logger.info("Knowledge saved to file")
    
    def merge(self, extraction: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Merge extraction into knowledge base.
        
        Returns list of conflicts detected.
        """
        conflicts = []
        
        # Track this extraction
        self.data["metadata"]["extraction_history"].append({
            "date": datetime.now().isoformat(),
            "document_type": extraction.get("document_type"),
            "provider": extraction.get("provider")
        })
        
        # Merge identity
        if extraction.get("account_holder"):
            holder = extraction["account_holder"]
            if holder.get("name"):
                if self.data["identity"]["name"] and self.data["identity"]["name"] != holder["name"]:
                    conflicts.append({
                        "field": "identity.name",
                        "existing": self.data["identity"]["name"],
                        "new": holder["name"]
                    })
                self.data["identity"]["name"] = holder["name"]
            
            if holder.get("codice_fiscale"):
                self.data["identity"]["codice_fiscale"] = holder["codice_fiscale"]
        
        # Merge address (store variants)
        if extraction.get("address"):
            addr = extraction["address"]
            if addr.get("full_as_printed"):
                if addr["full_as_printed"] not in self.data["location"]["address_variants"]:
                    self.data["location"]["address_variants"].append(addr["full_as_printed"])
            
            # Update canonical address if empty
            if not self.data["location"]["address"]["via"] and addr.get("via"):
                self.data["location"]["address"] = {
                    "via": addr.get("via", ""),
                    "numero": addr.get("numero", ""),
                    "cap": addr.get("cap", ""),
                    "comune": addr.get("comune", ""),
                    "provincia": addr.get("provincia", "")
                }
        
        # Merge account info - use identifiers for uniqueness, not provider name
        provider = extraction.get("provider", "unknown")
        doc_type = extraction.get("document_type", "other")
        identifiers = extraction.get("account_identifiers", {})
        
        # Find existing account by unique identifier
        account_key = None
        unique_id = (
            identifiers.get("pod") or 
            identifiers.get("pdr") or 
            identifiers.get("codice_utenza") or
            identifiers.get("codice_cliente")
        )
        
        if unique_id:
            # Search existing accounts for matching identifier
            for key, acc in self.data["accounts"].items():
                existing_ids = acc.get("identifiers", {})
                if (existing_ids.get("pod") == unique_id or
                    existing_ids.get("pdr") == unique_id or
                    existing_ids.get("codice_utenza") == unique_id or
                    existing_ids.get("codice_cliente") == unique_id):
                    account_key = key
                    break
        
        # If no match found, create new key
        if not account_key:
            provider_slug = provider.lower().replace(" ", "_")[:20] if provider != "unknown" else "unknown"
            account_key = f"{provider_slug}_{doc_type}"
            # Ensure uniqueness
            if account_key in self.data["accounts"]:
                account_key = f"{account_key}_{unique_id[:8] if unique_id else 'new'}"
        
        # Get existing account or create new one
        existing_account = self.data["accounts"].get(account_key, {})
        existing_history = existing_account.get("history", [])
        
        # Build history entry from this bill
        billing_info = extraction.get("billing_info", {})
        meter_info = extraction.get("meter_info", {})
        
        if billing_info or meter_info:
            history_entry = {
                "document_date": extraction.get("document_date"),
                "period_start": billing_info.get("period_start"),
                "period_end": billing_info.get("period_end"),
                "amount": billing_info.get("amount"),
                "due_date": billing_info.get("due_date"),
                "reading": meter_info.get("readings", {}).get("value") if meter_info.get("readings") else None,
                "reading_date": meter_info.get("readings", {}).get("date") if meter_info.get("readings") else None,
                "extracted_at": datetime.now().isoformat()
            }
            
            # Avoid duplicates - check by document_date and amount
            is_duplicate = any(
                h.get("document_date") == history_entry["document_date"] and 
                h.get("amount") == history_entry["amount"]
                for h in existing_history
            )
            
            if not is_duplicate:
                existing_history.append(history_entry)
                # Sort by document_date descending (newest first)
                existing_history.sort(
                    key=lambda x: x.get("document_date") or "0000-00-00", 
                    reverse=True
                )
        
        # Update provider name if we have a better one (longer/more complete)
        existing_provider = existing_account.get("provider", "")
        if len(provider) > len(existing_provider):
            new_provider = provider
        else:
            new_provider = existing_provider or provider
        
        self.data["accounts"][account_key] = {
            "provider": new_provider,
            "type": doc_type,
            "identifiers": identifiers if identifiers else existing_account.get("identifiers", {}),
            "meter": extraction.get("meter_info", {}) or existing_account.get("meter", {}),
            "contract": extraction.get("contract_info", {}) or existing_account.get("contract", {}),
            "contact": extraction.get("contact_info", {}) or existing_account.get("contact", {}),
            "current_bill": extraction.get("billing_info", {}),
            "history": existing_history,
            "updated": datetime.now().isoformat()
        }
        
        # Merge verification Q&A
        if extraction.get("verification_qa"):
            for qa in extraction["verification_qa"]:
                # Use unique_id in key for consistency
                key = f"{unique_id or provider}_{qa['question'][:30]}"
                self.data["verification_data"][key] = {
                    "provider": provider,
                    "question": qa["question"],
                    "answer": qa["answer"],
                    "updated": datetime.now().isoformat()
                }
        
        # Update meter locations if we have them
        if extraction.get("meter_info", {}).get("matricola"):
            if doc_type in ["electricity", "gas", "water"]:
                self.data["house"]["meter_locations"][doc_type] = {
                    "matricola": extraction["meter_info"]["matricola"],
                    "location": self.data["house"]["meter_locations"].get(doc_type, {}).get("location", "")
                }
        
        return conflicts
    
    def _deep_merge(self, base: dict, update: dict):
        """Recursively merge update into base."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
    
    def get_for_prompt(self) -> str:
        """Format knowledge for inclusion in system prompt."""
        return json.dumps(self.data, indent=2, ensure_ascii=False)
    
    def get_address_formatted(self) -> str:
        """Get the address in Italian format."""
        addr = self.data["location"]["address"]
        parts = []
        
        if addr.get("via"):
            parts.append(f"{addr['via']}")
        if addr.get("numero"):
            parts[-1] = f"{parts[-1]}, {addr['numero']}"
        if addr.get("cap") and addr.get("comune"):
            parts.append(f"{addr['cap']} {addr['comune']}")
        if addr.get("provincia"):
            parts[-1] = f"{parts[-1]} ({addr['provincia']})"
        
        return "\n".join(parts) if parts else ""
    
    def get_account(self, provider: str) -> Optional[Dict[str, Any]]:
        """Get account info for a specific provider."""
        # Try exact match first
        for key, account in self.data["accounts"].items():
            if provider.lower() in key.lower():
                return account
        return None
    
    def get_account_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Get account info by POD, PDR, or codice_cliente."""
        for key, account in self.data["accounts"].items():
            ids = account.get("identifiers", {})
            if (ids.get("pod") == identifier or
                ids.get("pdr") == identifier or
                ids.get("codice_utenza") == identifier or
                ids.get("codice_cliente") == identifier):
                return account
        return None
