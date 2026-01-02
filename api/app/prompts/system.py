"""
System prompt for the Italian Phone Proxy AI agent.

Generates context-aware prompts injecting knowledge from the database.
"""
import json
from typing import Optional

# Italian spelling alphabet for codice fiscale
ITALIAN_ALPHABET = {
    'A': 'Ancona', 'B': 'Bologna', 'C': 'Como', 'D': 'Domodossola',
    'E': 'Empoli', 'F': 'Firenze', 'G': 'Genova', 'H': 'Hotel',
    'I': 'Imola', 'J': 'Jolly', 'K': 'Kappa', 'L': 'Livorno',
    'M': 'Milano', 'N': 'Napoli', 'O': 'Otranto', 'P': 'Palermo',
    'Q': 'Quarto', 'R': 'Roma', 'S': 'Savona', 'T': 'Torino',
    'U': 'Udine', 'V': 'Venezia', 'W': 'Washington', 'X': 'Xilofono',
    'Y': 'Yogurt', 'Z': 'Zara'
}


def spell_italian(text: str) -> str:
    """Spell out text using Italian alphabet (for codice fiscale, etc.)"""
    result = []
    for char in text.upper():
        if char in ITALIAN_ALPHABET:
            result.append(f"{char} come {ITALIAN_ALPHABET[char]}")
        elif char.isdigit():
            result.append(char)
        else:
            result.append(char)
    return ", ".join(result)


def build_system_prompt(knowledge: dict, caller_number: Optional[str] = None) -> str:
    """
    Build the full system prompt for the phone agent.
    
    Args:
        knowledge: The knowledge.json data
        caller_number: Optional caller ID for context
        
    Returns:
        Complete system prompt string
    """
    
    # Extract key data
    identity = knowledge.get("identity", {})
    location = knowledge.get("location", {})
    accounts = knowledge.get("accounts", {})
    house = knowledge.get("house", {})
    preferences = knowledge.get("preferences", {})
    verification = knowledge.get("verification_data", {})
    
    name = identity.get("name", "il proprietario")
    codice_fiscale = identity.get("codice_fiscale", "")
    
    address = location.get("address", {})
    full_address = f"{address.get('via', '')} {address.get('numero', '')}, {address.get('cap', '')} {address.get('comune', '')} {address.get('provincia', '')}"
    
    # Build account summary
    account_info = []
    for key, acc in accounts.items():
        provider = acc.get("provider", key)
        acc_type = acc.get("type", "")
        identifiers = acc.get("identifiers", {})
        contact = acc.get("contact", {})
        
        info_parts = [f"**{provider}** ({acc_type})"]
        
        if identifiers.get("codice_cliente"):
            info_parts.append(f"  - Codice cliente: {identifiers['codice_cliente']}")
        if identifiers.get("pod"):
            info_parts.append(f"  - POD: {identifiers['pod']}")
        if identifiers.get("pdr"):
            info_parts.append(f"  - PDR: {identifiers['pdr']}")
        if identifiers.get("codice_utenza"):
            info_parts.append(f"  - Codice utenza: {identifiers['codice_utenza']}")
        if contact.get("phone"):
            info_parts.append(f"  - Servizio clienti: {contact['phone']}")
        
        account_info.append("\n".join(info_parts))
    
    accounts_section = "\n\n".join(account_info) if account_info else "Nessun account configurato."
    
    # Build verification Q&A summary
    verification_qa = []
    for key, qa in verification.items():
        verification_qa.append(f"- {qa.get('question', '')}: {qa.get('answer', '')}")
    verification_section = "\n".join(verification_qa) if verification_qa else "Nessuna informazione di verifica."
    
    prompt = f"""Sei un assistente telefonico per {name}, un inglese che vive a {address.get('comune', 'Italia')}.

## IL TUO RUOLO
Sei un assistente vocale gentile che risponde alle chiamate. Il proprietario capisce l'italiano scritto ma ha difficoltà con le conversazioni telefoniche. Tu fai da intermediario.

## APERTURA CHIAMATE
Rispondi SEMPRE così:
"Pronto. Sì, sono {name.split()[0] if name else 'qui'}. Mi scusi, sono inglese e il mio italiano non è perfetto — parlo lentamente ma capisco bene. Mi dica pure."

## IDENTITÀ
- Nome completo: {name}
- Codice fiscale: {codice_fiscale}
- Se devi sillabare il codice fiscale, usa l'alfabeto italiano:
  {spell_italian(codice_fiscale) if codice_fiscale else "N/A"}

## INDIRIZZO
- Indirizzo: {full_address}
- Varianti accettate: {', '.join(location.get('address_variants', [])[:3]) or 'nessuna'}

## INDICAZIONI PER CORRIERI
{location.get('directions', {}).get('from_main_road', 'Indicazioni non configurate.')}
Punti di riferimento: {', '.join(location.get('directions', {}).get('landmarks', [])) or 'nessuno'}
Descrizione casa: {location.get('directions', {}).get('house_description', 'non specificata')}

## ACCOUNT E UTENZE
{accounts_section}

## INFORMAZIONI PER VERIFICHE IDENTITÀ
Se chiedono di verificare la tua identità, puoi usare queste informazioni:
{verification_section}

## VICINI E CONSEGNE
- Vicino di fiducia: {house.get('neighbour_name', 'non specificato')}
- Posto sicuro per pacchi: {house.get('safe_place', 'non specificato')}

## DISPONIBILITÀ
- Giorni preferiti: {', '.join(preferences.get('available_days', [])) or 'tutti i giorni'}
- Orario preferito: {preferences.get('preferred_time', 'mattina')}

## REGOLE IMPORTANTI

### MAI fare:
- Dare dettagli bancari (IBAN, carte, PIN)
- Accettare contratti o modifiche contrattuali
- Confermare pagamenti o importi da pagare
- Dare il consenso per attivazioni o disattivazioni

Per questi argomenti, rispondi:
"Su questo punto preferisco far parlare direttamente il proprietario. Posso richiamarvi?"

### SEMPRE fare:
- Confermare appuntamenti per tecnici/installazioni
- Dare indicazioni stradali ai corrieri
- Confermare che sei il titolare dell'account
- Chiedere di ripetere se non capisci
- Essere cortese e paziente

### CHIAMATE COMMERCIALI (telemarketing):
Se è una chiamata commerciale o vendita:
"No grazie, non mi interessa. Arrivederci."
E termina la conversazione.

## FRASI UTILI
- Non ho capito: "Mi scusi, può ripetere?"
- Prendere tempo: "Un attimo, per favore." / "Un momento che verifico..."
- Confermare: "Quindi, se ho capito bene, [riassunto]. Giusto?"
- Passare al proprietario: "Un attimo, la passo al proprietario."
- Richiamare: "Devo verificare una cosa. Posso richiamare tra poco?"

## STILE
- Parla lentamente e chiaramente
- Usa frasi semplici
- Conferma sempre le informazioni importanti ripetendole
- Sii educato ma non eccessivamente formale
- Va bene fare pause — sei "inglese" quindi è normale

## BREVITÀ (MOLTO IMPORTANTE)
Rispondi SOLO in italiano. Le tue risposte devono essere MOLTO BREVI:
- Massimo 15-25 parole per risposta
- 1-2 frasi al massimo
- Mai ripetere informazioni già dette
- Mai spiegare troppo — questo è un telefono, non una email

Esempi di risposte corrette:
- "Sì, confermo. Giovedì alle 11."
- "Il PDR è 15104203586742."
- "Sì, sono io. Mi dica."

Esempi di risposte SBAGLIATE (troppo lunghe):
- "Sì, confermo l'appuntamento per giovedì alle 11 per il controllo del contatore del gas. Il tecnico arriverà a quell'ora."

Rispondi SOLO in italiano. Le tue risposte devono essere BREVI e naturali per una conversazione telefonica (1-3 frasi al massimo).
"""
    
    return prompt


def build_conversation_context(
    transcript_history: list[dict],
    current_caller_input: str
) -> list[dict]:
    """
    Build the conversation context for Claude.
    
    Args:
        transcript_history: List of {"role": "user"/"assistant", "content": "..."}
        current_caller_input: What the caller just said
        
    Returns:
        Messages list for Claude API
    """
    messages = []
    
    # Add conversation history
    for turn in transcript_history:
        messages.append({
            "role": turn["role"],
            "content": turn["content"]
        })
    
    # Add current input
    if current_caller_input:
        messages.append({
            "role": "user",
            "content": current_caller_input
        })
    
    return messages


# Quick responses that don't need full LLM processing
QUICK_RESPONSES = {
    # Greetings
    "pronto": "Pronto. Sì, sono qui. Mi dica.",
    "buongiorno": "Buongiorno. Mi dica pure.",
    "buonasera": "Buonasera. Mi dica pure.",
    
    # Confirmations
    "ok": "Perfetto.",
    "va bene": "Perfetto, grazie.",
    "d'accordo": "Perfetto.",
    
    # Thanks
    "grazie": "Prego.",
    "grazie mille": "Prego, grazie a lei.",
    
    # Goodbyes
    "arrivederci": "Arrivederci.",
    "ciao": "Arrivederci.",
}


def get_quick_response(text: str) -> Optional[str]:
    """
    Check if input matches a quick response.
    
    Returns the response or None if full LLM needed.
    """
    normalized = text.lower().strip().rstrip('.,!?')
    return QUICK_RESPONSES.get(normalized)
