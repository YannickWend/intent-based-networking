from network_config import ROLES

def get_ip_from_hosts(hosts_list):
    """
    Prend une liste d'identifiants (ex: ['h1', 'h10']) 
    et retourne la liste des adresses IP correspondantes.
    """
    if not hosts_list or not isinstance(hosts_list, list):
        return []
    
    ips = []
    for h_id in hosts_list:
        # On récupère l'IP directement depuis le dictionnaire ROLES
        if h_id in ROLES and "ip" in ROLES[h_id]:
            ips.append(ROLES[h_id]["ip"])
            
    return ips
