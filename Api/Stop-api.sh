#!/bin/bash

API_SCRIPT="network-manager.py"

echo "=== Arrêt de l'API Network Manager ==="

# On cherche le processus par son nom et on le tue
if sudo pkill -f $API_SCRIPT
then
    echo " [OK] API arrêtée avec succès."
else
    echo " [INFO] Aucun processus API en cours d'exécution."
fi
