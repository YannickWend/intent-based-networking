import re
from network_config import ROLES

def extract_hosts(text):
 
    text_lower = text.lower()
    
    all_keywords = [
        "tous les hotes", "tout le monde", "tous les postes", "tous les terminaux", 
        "chaque machine", "tous les utilisateurs", "l'ensemble des pc", 
        "l'ensemble des stagiaires", "tous les stagiaires",
        # AJOUTS
        "l'ensemble du réseau", "l'ensemble du reseau",
        "tout le réseau", "tout le reseau", "le réseau entier",
        "global", "partout", "network wide"
    ]
    exclude_keywords = ["sauf", "excepté", "hormis"]

    mentioned = []

    # 1. Extraction par ID (h1, h2...) ou par Rôle (Directeur, RH...)
    for h_id, info in ROLES.items():
        role = info["role"].lower()
        
        # On crée des patterns plus robustes
        # \b assure que "RH" ne matche pas dans "ORCHESTRE"
        pattern_id = rf'\b{h_id}\b'
        pattern_role = rf'\b{role}\b'
        
        if re.search(pattern_id, text_lower) or re.search(pattern_role, text_lower):
            if h_id not in mentioned:
                mentioned.append(h_id)

    # 2. Gestion des mots-clés globaux (tous les hôtes...)
    # Cette partie n'est pas trop bien donc peut induire à des erreurs.
    if any(kw in text_lower for kw in all_keywords):
        if any(ex in text_lower for ex in exclude_keywords):
            # Logique d'exclusion (ex: "Tous sauf h1")
            return list(set(ROLES.keys()) - set(mentioned))
        return list(ROLES.keys())
    
    return mentioned
