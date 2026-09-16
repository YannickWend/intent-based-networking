import json
import os

def generate_topology():
    # Détermination du chemin du fichier JSON
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, "topologie", "topology.json")
    
    # Vérification et création du dossier topologie si nécessaire
    if not os.path.exists(os.path.dirname(json_path)):
        os.makedirs(os.path.dirname(json_path))

    if os.path.exists(json_path):
        choix = input(f"Le fichier '{json_path}' existe déjà. Voulez-vous le réécrire ? (o/n) : ").strip().lower()
        if choix != 'o':
            return False
    
    print("--- Générateur de Topologie Mininet (Spécial OVS) ---")
    
    topo = {
        "switches": [],
        "hosts": [],
        "links": []
    }

    try:
        nb_switches = int(input("Combien de switches OVS ? "))
        for i in range(1, nb_switches + 1):
            topo["switches"].append(f"s{i}")

        nb_hosts = int(input("Combien de hosts ? "))
        for i in range(1, nb_hosts + 1):
            topo["hosts"].append(f"h{i}")
    except ValueError:
        print("Erreur : Entrez des nombres entiers.")
        return False

    connected_hosts = set()
    existing_links = set()

    print("\n--- Configuration des liens ---")
    print("Tapez 'fin' pour terminer.")
    
    port_counters = {} # Garde une trace du prochain port libre pour chaque switch/hôte

    while True:
        link_input = input(f"Lien {len(topo['links']) + 1} : ").strip().lower()
        if link_input == 'fin': break
        
        nodes = link_input.split()
        if len(nodes) != 2: continue

        n1, n2 = nodes[0], nodes[1]
        
        # Calcul automatique du prochain port disponible pour n1 et n2
        p1 = port_counters.get(n1, 0) + 1
        port_counters[n1] = p1
        
        p2 = port_counters.get(n2, 0) + 1
        port_counters[n2] = p2

        # On stocke le lien avec ses ports prédéterminés
        topo["links"].append({
            "node1": n1, 
            "port1": p1, 
            "node2": n2, 
            "port2": p2
        })
        print(f"✅ Lien {n1}(port {p1}) <-> {n2}(port {p2}) ajouté.")

    # Sauvegarde dans le dossier topologie
    with open(json_path, 'w') as f:
        json.dump(topo, f, indent=4)
    
    print(f"\nFichier JSON généré : {json_path}")
    return True

if __name__ == "__main__":
    generate_topology()
