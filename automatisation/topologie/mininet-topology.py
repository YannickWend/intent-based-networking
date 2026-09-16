#!/usr/bin/python
import json
import os
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.nodelib import NAT
from mininet.link import TCLink

TOPOLOGY_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topology.json")

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
        s.cmd(f'ip link set {switch_intf} up')
        s.cmd(f'ovs-vsctl add-port {switch_name} {switch_intf}')
        
        # 2. Mise à jour du fichier JSON (Correction des accolades ici)
        if os.path.exists(TOPOLOGY_JSON):
            with open(TOPOLOGY_JSON, 'r+') as f:
                data = json.load(f)
                if hostname not in data['hosts']:
                    data['hosts'].append(hostname)
                    # ON UTILISE DES DOUBLES ACCOLADES POUR LE DICTIONNAIRE
                    new_link = {
                        "node1": switch_name, "port1": actual_port, 
                        "node2": hostname, "port2": 0
                    }
                    data['links'].append(new_link)
                    f.seek(0)
                    json.dump(data, f, indent=4)
                    f.truncate()
            print(f"*** Fichier topology.json mis a jour pour le dashboard")
        print(f"*** Hote {hostname} ajoute sur {switch_name} port {actual_port}")
    except Exception as e:
        print(f"*** Erreur lors de l'ajout: {e}")

def myNetwork():
    # Utilisation de TCLink indispensable pour gérer la bande passante (QoS)
    net = Mininet(topo=None, build=False, link=TCLink, autoSetMacs=True, ipBase='10.0.0.0/8')

    print('*** Ajout du contrôleur distant (Port 6653)')
    c0 = net.addController(name='c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    print('*** Ajout des switches OVS')
    s1 = net.addSwitch('s1', cls=OVSSwitch, protocols='OpenFlow13')
    s2 = net.addSwitch('s2', cls=OVSSwitch, protocols='OpenFlow13')
    s3 = net.addSwitch('s3', cls=OVSSwitch, protocols='OpenFlow13')
    s4 = net.addSwitch('s4', cls=OVSSwitch, protocols='OpenFlow13')
    s5 = net.addSwitch('s5', cls=OVSSwitch, protocols='OpenFlow13')
    s6 = net.addSwitch('s6', cls=OVSSwitch, protocols='OpenFlow13')
    s7 = net.addSwitch('s7', cls=OVSSwitch, protocols='OpenFlow13')
    s8 = net.addSwitch('s8', cls=OVSSwitch, protocols='OpenFlow13')
    s9 = net.addSwitch('s9', cls=OVSSwitch, protocols='OpenFlow13')

    print('*** Ajout des hôtes')
    h1 = net.addHost('h1', defaultRoute='via 10.0.0.254')
    h2 = net.addHost('h2', defaultRoute='via 10.0.0.254')
    h3 = net.addHost('h3', defaultRoute='via 10.0.0.254')
    h4 = net.addHost('h4', defaultRoute='via 10.0.0.254')
    h5 = net.addHost('h5', defaultRoute='via 10.0.0.254')
    h6 = net.addHost('h6', defaultRoute='via 10.0.0.254')
    h7 = net.addHost('h7', defaultRoute='via 10.0.0.254')
    h8 = net.addHost('h8', defaultRoute='via 10.0.0.254')
    h9 = net.addHost('h9', defaultRoute='via 10.0.0.254')
    h10 = net.addHost('h10', defaultRoute='via 10.0.0.254')

    print('*** Ajout des liens avec latence de 1ms')
    # Configuration commune pour tous les liens
    

    # Liens Hôtes -> Switchs
    net.addLink(h10, s1, port1=1, port2=1)
    net.addLink(h9, s2, port1=1, port2=1)
    net.addLink(h8, s2, port1=1, port2=2)
    net.addLink(h7, s2, port1=1, port2=3)
    net.addLink(h6, s3, port1=1, port2=1)
    net.addLink(h5, s3, port1=1, port2=2)
    net.addLink(h4, s3, port1=1, port2=3)
    net.addLink(h3, s4, port1=1, port2=1)
    net.addLink(h2, s5, port1=1, port2=1)
    net.addLink(h1, s6, port1=1, port2=1)

    # Liens Inter-Switchs
    net.addLink(s1, s7, port1=2, port2=1)
    net.addLink(s2, s7, port1=4, port2=2)
    net.addLink(s3, s7, port1=4, port2=3)
    net.addLink(s4, s9, port1=2, port2=1)
    net.addLink(s5, s9, port1=2, port2=2)
    net.addLink(s6, s9, port1=2, port2=3)
    net.addLink(s7, s8, port1=4, port2=1)
    net.addLink(s9, s8, port1=4, port2=2)

    print('*** Ajout du noeud NAT pour l\'acces Internet')
    nat0 = net.addHost('nat0', cls=NAT, ip='10.0.0.254', inNamespace=False)
    net.addLink(nat0, s8)
    
    print('*** Démarrage du réseau')
    net.build()
    net.start()

    print('*** Configuration OVSDB pour la QoS (Port 6640)')
    s1.cmd('ovs-vsctl set-manager ptcp:6640')
    s2.cmd('ovs-vsctl set-manager ptcp:6640')
    s3.cmd('ovs-vsctl set-manager ptcp:6640')
    s4.cmd('ovs-vsctl set-manager ptcp:6640')
    s5.cmd('ovs-vsctl set-manager ptcp:6640')
    s6.cmd('ovs-vsctl set-manager ptcp:6640')
    s7.cmd('ovs-vsctl set-manager ptcp:6640')
    s8.cmd('ovs-vsctl set-manager ptcp:6640')
    s9.cmd('ovs-vsctl set-manager ptcp:6640')

    print('\n=== CONSOLE PRETE ===')
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
