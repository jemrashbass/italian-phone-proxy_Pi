"""
Extraction prompt for Italian utility documents.
"""

EXTRACTION_PROMPT = """Analizza questo documento italiano (bolletta, fattura, o documento d'identità) ed estrai tutte le informazioni utili.

Rispondi SOLO con JSON valido, senza testo aggiuntivo. Usa questa struttura:

{
  "document_type": "electricity|gas|water|isp|mobile|identity|other",
  "provider": "nome del fornitore",
  "document_date": "YYYY-MM-DD",
  
  "account_holder": {
    "name": "nome completo come stampato",
    "codice_fiscale": "se visibile"
  },
  
  "address": {
    "via": "nome via/strada",
    "numero": "numero civico",
    "cap": "codice postale",
    "comune": "città",
    "provincia": "sigla provincia",
    "full_as_printed": "indirizzo completo come stampato"
  },
  
  "account_identifiers": {
    "codice_cliente": "",
    "numero_contratto": "",
    "pod": "per elettricità - IT001E...",
    "pdr": "per gas - 14 cifre",
    "codice_utenza": "per acqua"
  },
  
  "meter_info": {
    "matricola": "numero contatore",
    "readings": {
      "date": "YYYY-MM-DD",
      "value": "lettura",
      "unit": "kWh|m³|etc"
    }
  },
  
  "billing_info": {
    "amount": "importo in euro (numero)",
    "currency": "EUR",
    "period_start": "YYYY-MM-DD",
    "period_end": "YYYY-MM-DD",
    "due_date": "YYYY-MM-DD",
    "payment_method": "metodo di pagamento se indicato"
  },
  
  "contract_info": {
    "type": "tipo contratto/tariffa",
    "power_kw": "per elettricità - potenza impegnata",
    "start_date": "YYYY-MM-DD"
  },
  
  "contact_info": {
    "phone": "numero servizio clienti",
    "email": "",
    "website": ""
  },
  
  "verification_qa": [
    {
      "question": "domanda che potrebbero fare per verificare identità",
      "answer": "risposta dal documento"
    }
  ],
  
  "notes": "altre informazioni utili non categorizzate"
}

Regole:
- Usa null per campi non trovati
- Date in formato ISO (YYYY-MM-DD)
- Importi come numeri senza simbolo valuta
- POD elettricità inizia sempre con IT001E
- PDR gas è sempre 14 cifre
- Codice fiscale è 16 caratteri alfanumerici
- Includi verification_qa con domande tipo "Qual è l'importo dell'ultima bolletta?" o "Qual è il numero del contatore?"

Estrai tutte le informazioni visibili nel documento."""
