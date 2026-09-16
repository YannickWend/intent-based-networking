import json
import os

def generate_mininet_script():
    # Détermination des chemins
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, "topologie", "topology.json")
    # Destination du script généré
    output_path = os.path.join(script_dir, "topologie", "mininet-topology.py")

    # Lecture des données de topologie
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Erreur : {json_path} introuvable. Veuillez lancer générator.py d'abord.")
        return

    # Construction du contenu du script Mininet
    # On utilise des doubles {{ }} pour les variables qui doivent rester dans le script final
    script_content = f"""#!/usr/bin/python
import json
import os
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.nodelib import NAT
from mininet.link import TCLink

TOPOLOGY_JSON = "{json_path}"

def add_dynamic_host(net, hostname, switch_name, ip_addr):
    if hostname in net: return
    try:
        # 1. Ajout dans Mininet
        h = net.addHost(hostname, ip=ip_addr)
        s = net.nameToNode[switch_name]
        res_link = net.addLink(h, s, cls=TCLink)
        
        # Récupérer le numéro de port que Mininet a attribué au switch
        actual_port = s.ports[res_link.intf2] 
        switch_intf = res_link.intf2.name

        h.configDefault()
        s.cmd(f'ip link set {{switch_intf}} up')
        s.cmd(f'ovs-vsctl add-port {{switch_name}} {{switch_intf}}')
        
        # 2. Mise à jour du fichier JSON (Correction des accolades ici)
        if os.path.exists(TOPOLOGY_JSON):
            with open(TOPOLOGY_JSON, 'r+') as f:
                data = json.load(f)
                if hostname not in data['hosts']:
                    data['hosts'].append(hostname)
                    # ON UTILISE DES DOUBLES ACCOLADES POUR LE DICTIONNAIRE
                    new_link = {{
                        "node1": switch_name, "port1": actual_port, 
                        "node2": hostname, "port2": 0
                    }}
                    data['links'].append(new_link)
                    f.seek(0)
                    json.dump(data, f, indent=4)
                    f.truncate()
            print(f"*** Fichier topology.json mis a jour pour le dashboard")
        print(f"*** Hote {{hostname}} ajoute sur {{switch_name}} port {{actual_port}}")
    except Exception as e:
        print(f"*** Erreur lors de l'ajout: {{e}}")

def myNetwork():
    # Utilisation de TCLink indispensable pour gérer la bande passante (QoS)
    net = Mininet(topo=None, build=False, link=TCLink, autoSetMacs=True, ipBase='10.0.0.0/8')

    print('*** Ajout du contrôleur distant (Port 6653)')
    c0 = net.addController(name='c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    print('*** Ajout des switches OVS')
"""

    # Ajout dynamique des switches
    for s in data['switches']:
        script_content += f"    {s} = net.addSwitch('{s}', cls=OVSSwitch, protocols='OpenFlow13')\n"

    script_content += "\n    print('*** Ajout des hôtes')\n"
    # Ajout dynamique des hôtes
    for h in data['hosts']:
    # On ajoute defaultRoute='via 10.0.0.254'
    	script_content += f"    {h} = net.addHost('{h}', defaultRoute='via 10.0.0.254')\n"

    script_content += "\n    print('*** Ajout des liens (Ports fixes)')\n"
    for link in data['links']:
        # On force port1 et port2 avec les valeurs du JSON
        script_content += f"    net.addLink({link['node1']}, {link['node2']}, port1={link['port1']}, port2={link['port2']}, cls=TCLink)\n"
	
	
	
	

    script_content += """
    print('*** Ajout du noeud NAT pour l\\'acces Internet')
    nat0 = net.addHost('nat0', cls=NAT, ip='10.0.0.254', inNamespace=False)
    net.addLink(nat0, s8)
    """
    script_content += """
    print('*** Démarrage du réseau')
    net.build()
    net.start()

    print('*** Configuration OVSDB pour la QoS (Port 6640)')
"""

    # Activation OVSDB pour chaque switch
    for s in data['switches']:
        script_content += f"    {s}.cmd('ovs-vsctl set-manager ptcp:6640')\n"

    script_content += """
    print('\\n=== CONSOLE PRETE ===')
    print('Pour ajouter un hote x au sy, tape exactement :')
    print('py net.add_dynamic_host("hx", "sy", "10.0.0.x")')
    print('-----------------------------------------------------------------------')
    
    # METHODE UNIVERSELLE : On attache la fonction a l'objet net
    import types
    net.add_dynamic_host = types.MethodType(add_dynamic_host, net)
    
    CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    myNetwork()
"""

    # Écriture du fichier final
    try:
        with open(output_path, 'w') as f:
            f.write(script_content)
        print(f"✅ Script Mininet généré avec succès : {output_path}")
        os.chmod(output_path, 0o755)
    except Exception as e:
        print(f"❌ Erreur lors de l'écriture du script : {e}")

if __name__ == "__main__":
    generate_mininet_script()
