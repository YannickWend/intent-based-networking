import re
from network_config import QOS_PROFILES

def extract_qos(text):
    """
    Parcourt le texte et retourne le premier profil QoS trouvé dans QOS_PROFILES.
    Retourne None si aucun profil n'est détecté.
    """
    text = text.lower()
    
    for profile in QOS_PROFILES.keys():
        if re.search(rf'\b{profile.lower()}\b', text):
            return profile 
            
    return None


