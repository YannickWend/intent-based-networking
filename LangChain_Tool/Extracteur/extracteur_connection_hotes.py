from network_config import LINKS
from extracteur_hotes import extract_hosts 

def get_locations(text):
    """Extrait les hôtes du texte et retourne leurs Switch/Port depuis LINKS."""
    host_ids = extract_hosts(text)
    results = []

    if not host_ids:
        return []

    for h_id in host_ids:
        # Parcours de la liste LINKS 
        for link in LINKS:
            if link['node1'] == h_id:
                results.append({
                    "id": h_id,
                    "dpid": int(link['node2'].replace('s', '')),
                    "port": link['port2']
                })
                break
            elif link['node2'] == h_id:
                results.append({
                    "id": h_id,
                    "dpid": int(link['node1'].replace('s', '')),
                    "port": link['port1']
                })
                break
        
    return results


