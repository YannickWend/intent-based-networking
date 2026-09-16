from network_config import LINKS, ROLES

def get_switch_details(sw_list):
    """
    Prend une liste de switchs (ex: ['s1', 's3']) et retourne 
    leurs connexions (hôtes et inter-switchs) via LINKS.
    """
    if not sw_list or not isinstance(sw_list, list):
        return {}

    results = {}

    for sw_id in sw_list:
        details = {
            "ports_hotes": [],
            "ports_inter_switchs": []
        }

        for link in LINKS:
            target = None
            port = None
            
            # On identifie si le switch est node1 ou node2
            if link['node1'] == sw_id:
                target = link['node2']
                port = link['port1']
            elif link['node2'] == sw_id:
                target = link['node1']
                port = link['port2']

            if target:
                if target.startswith('h'):
                    details["ports_hotes"].append({
                        "port": port, 
                        "connected_to": target, 
                        "role": ROLES.get(target, {}).get('role', 'Inconnu')
                    })
                else:
                    details["ports_inter_switchs"].append({
                        "port": port, 
                        "connected_to": target
                    })

        results[sw_id] = details

    return results
