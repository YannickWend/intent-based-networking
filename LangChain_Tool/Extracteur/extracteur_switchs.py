import re
from network_config import SWITCHES

def extract_switches(text):
    text = text.lower()
    all_keywords = [
    "tous les switchs", "chaque switch", "le réseau", "tous les commutateurs", 
    "tous les équipements", "l'infrastructure", "partout"
    ]
    
    exclude_keywords = ["sauf", "excepté", "hormis"]

    found_ids = re.findall(r'(?:switch\s*|s\s*)(\d+)', text, re.IGNORECASE)
    mentioned = [f"s{num}" for num in found_ids if f"s{num}" in SWITCHES]
    
    if any(kw in text for kw in all_keywords):
        return list(SWITCHES)
    
    return mentioned
