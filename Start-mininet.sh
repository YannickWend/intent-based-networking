#!/bin/bash

# Dossier du projet
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR

#Nettoyage
sudo mn -c > /dev/null 2>&1
sudo fuser -k 5000/tcp > /dev/null 2>&1
sudo fuser -k 6653/tcp > /dev/null 2>&1 
sudo fuser -k 8080/tcp > /dev/null 2>&1




#Démarrage de OpenVswitch
sudo service openvswitch-switch start


#Lancement de la topologie
sudo python3 automatisation/topologie/mininet-topology.py


