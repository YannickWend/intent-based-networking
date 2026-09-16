import re

# ORDRE DE PRIORITÉ EXPLICITE (du plus spécifique au plus général)
# 1. BRONZE      → mots de restriction (limiter, ralentir, réduire…)
# 2. GOLD        → priorité / latence / réactivité / critique
# 3. SILVER      → débit / téléchargement / bande passante / vitesse
# 4. STANDARD    → reset / neutre / par défaut

INTENTIONS_MAP = {


    "BRONZE": [
        "limite", "limiter", "ralentis", "ralentir",
        "réduis", "réduire", "restreins", "restreindre",
        "bridé", "bride", "brider",
        "moins de bande passante", "bande passante réduite",
        "baisse le débit", "baisse la vitesse",
        "vitesse réduite", "débit réduit",
        "invité", "invités", "guest", "secondaire",
        "faible priorité", "basse priorité",
        "background", "fond de tâche", "tâche de fond",
        "non prioritaire", "moins important",
        "économiser la bande passante", "réduire la voilure",
        "accès limité", "connexion basique"
    ],

    "GOLD": [
        "latence minimale", "latence faible", "faible latence", "zéro latence",
        "temps réel", "temps-réel", "réactivité", "réactif",
        "ping faible", "ping minimal", "délai minimal",
        "priorité maximale", "priorité absolue", "priorité haute", "haute priorité",
        "priorité critique", "plus haute priorité", "première priorité",
        "critique", "urgent", "urgence", "essentiel", "indispensable",
        "sans délai", "immédiatement",
        "stable", "stabilité", "fiable", "fiabilité",
        "connexion stable", "connexion fiable", "connexion garantie",
        "connexion sûre", "bonne connexion",
        "priorise", "prioriser", "prioritaire", "privilégie",
        "donne la priorité", "met en priorité", "favorise",
        "passe en premier", "doit être prioritaire",
        "sensible au délai", "sensible à la latence",
        "application critique", "service critique", "trafic critique",
        "doit répondre", "répondre vite", "répond rapidement"
    ],

    "SILVER": [
        "débit maximal", "débit maximum", "débit max", "débit élevé",
        "vitesse maximale", "vitesse maximum", "vitesse max", "pleine vitesse",
        "plein débit", "maximum de bande passante", "bande passante maximale",
        "bande passante max", "toute la bande passante", "full speed",
        "gros fichier", "gros téléchargement", "fichier lourd",
        "téléchargement lourd", "transfert lourd", "transfert massif",
        "transfert de fichier", "transférer", "transfert",
        "upload", "download", "télécharger", "téléchargement",
        "backup", "sauvegarde", "synchronisation", "synchro",
        "maximise", "maximiser", "maximum", "à fond",
        "boost", "booste", "booste le débit", "augmente le débit",
        "a besoin de vitesse", "a besoin de débit",
        "besoin de bande passante", "connexion rapide",
        "internet rapide", "le plus vite possible"
    ],

    "STANDARD": [
        "normal", "par défaut", "standard", "rétablir", "reset",
        "initialiser", "remettre à zéro", "neutre", "comme avant",
        "réinitialise", "réinitialiser", "mode normal", "mode standard",
        "revenir à la normale", "enlève la qos", "supprime la qos",
        "retire la priorité", "annule la priorité"
    ]
}


def extract_intent_profile(text):
    text_lower = text.lower()

    for profile, keywords in INTENTIONS_MAP.items():
        if any(kw in text_lower for kw in keywords):
            return profile

    # Patterns regex en fallback
    if re.search(r"donne.*priorit|priorit.*absolu|passe.*premier", text_lower):
        return "GOLD"
    if re.search(r"maximis.*flux|tout.*débit|besoin.*vite", text_lower):
        return "SILVER"
    if re.search(r"limit.*connexion|rédu.*bande", text_lower):
        return "BRONZE"
    if re.search(r"appel|réunion|conférence", text_lower):
        return "MULTIMEDIA"

    return None
