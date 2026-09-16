from extracteur_connection_hotes import get_locations
from network_config import ROUTES, ROLES

"""

Ce code correspond a une version précédente de la salution donc n'est plus trop d'actualité. Peut-etre utile pour la suite donc on l'a gardé.

"""

def get_path_between(text):
    """Trouve le chemin entre les deux premiers hôtes mentionnés dans le texte."""
    locations = get_locations(text)
    
    if not isinstance(locations, list):
        return {"error": "Erreur technique lors de la localisation des hôtes", "status": "error"}

    # Vérification : il nous faut au moins 2 hôtes pour un chemin
    if len(locations) < 2:
        return {
            "error": "Besoin d'au moins deux hôtes reconnus pour calculer un chemin", 
            "hotes_detectes": [loc['id'] for loc in locations],
            "status": "missing_info"
        }

    # On prend les deux premières localisations trouvées
    loc_a = locations[0]
    loc_b = locations[1]

    s_start = f"s{loc_a['dpid']}"
    s_end = f"s{loc_b['dpid']}"

    # Cas : Même switch
    if s_start == s_end:
        return {
            "source": loc_a['id'],
            "destination": loc_b['id'],
            "switches_path": [loc_a['dpid']], 
            "status": "same_switch"
        }

    # Recherche dans ROUTES
    route_key = f"{s_start}-{s_end}"
    reverse_key = f"{s_end}-{s_start}"
    
    path = ROUTES.get(route_key)
    
    if path:
        return {
            "source": loc_a['id'],
            "destination": loc_b['id'],
            "switches_path": path,
            "status": "success"
        }
    
    # Tentative en sens inverse si la clé directe n'existe pas
    path_reverse = ROUTES.get(reverse_key)
    if path_reverse:
        return {
            "source": loc_a['id'],
            "destination": loc_b['id'],
            "switches_path": path_reverse[::-1],
            "status": "success"
        }
    
    return {
        "error": f"Aucune route logique n'est définie entre {s_start} et {s_end} dans la configuration.",
        "status": "no_route"
    }
    
 
