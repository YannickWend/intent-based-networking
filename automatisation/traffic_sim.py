#!/usr/bin/python3
import os
import time
import subprocess

# --- CONFIGURATION ---
# L'IP de h10 (ton serveur de destination)
SERVER_IP = "10.0.0.10" 

# Rôles fixes pour chaque hôte
ROLES = {
    # GROUPE MULTIMEDIA (Flux constants pour tester Q1/Q3)
    "h1": f"ITGSend -a {SERVER_IP} -C 1000 -c 500 -t 3600000", # VoIP (1h)
    "h2": f"ITGSend -a {SERVER_IP} -C 1000 -c 800 -t 3600000", # Vidéo (1h)
    
    # GROUPE NAVIGATION (Flux intermittents pour tester Q0)
    "h3": "while true; do curl -s http://www.google.com > /dev/null; sleep 5; done",
    "h4": f"while true; do curl -s http://{SERVER_IP}/index.html > /dev/null; sleep 10; done",
    
    # GROUPE TÉLÉCHARGEMENT (Flux lourds pour tester Q2/Saturation)
    "h5": f"while true; do wget -q -O /dev/null http://{SERVER_IP}/large_file.iso; sleep 2; done",
    "h6": f"while true; do wget -q -O /dev/null http://{SERVER_IP}/backup.zip; sleep 5; done",

    # GROUPE MAINTENANCE / LATENCE (Test Q3/Q4)
    "h7": f"while true; do ping -c 1 {SERVER_IP}; sleep 1; done",
    "h8": "while true; do curl -s http://www.wikipedia.org > /dev/null; sleep 15; done",
    "h9": f"ITGSend -a {SERVER_IP} -C 500 -c 100 -t 3600000" # Monitoring léger
}

def run_cmd(host, cmd):
    """ Exécute la commande dans l'hôte via mnexec (méthode native Mininet) """
    # On utilise mnexec -a pour cibler l'hôte. 
    # Le script DOIT être lancé avec 'sudo' pour que cela fonctionne sans mot de passe.
    full_cmd = f"mnexec -a {host} bash -c '{cmd}' > /dev/null 2>&1 &"
    try:
        subprocess.Popen(full_cmd, shell=True)
    except Exception as e:
        print(f"❌ Erreur sur {host}: {e}")

def start_simulation():
    print(f"🛠️  Initialisation des rôles sur le serveur {SERVER_IP}...")
    
    # On commence par nettoyer les anciens processus s'il y en a
    os.system("pkill -9 ITGSend > /dev/null 2>&1")
    os.system("pkill -9 wget > /dev/null 2>&1")
    os.system("pkill -9 curl > /dev/null 2>&1")
    
    for host, cmd in ROLES.items():
        run_cmd(host, cmd)
        print(f"✅ {host} configuré et lancé.")

if __name__ == "__main__":
    # Vérification si lancé en root
    if os.geteuid() != 0:
        print("❌ ERREUR : Tu dois lancer ce script avec 'sudo python3 traffic_sim.py'")
        exit(1)

    start_simulation()
    print("\n🚀 Simulation active sur le réseau SDN.")
    print("📈 Regarde ton dashboard pour voir les débits monter !")
    print("⌨️  Appuie sur Ctrl+C pour arrêter proprement la simulation.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt en cours et nettoyage des processus...")
        os.system("pkill -9 ITGSend")
        os.system("pkill -9 wget")
        os.system("pkill -9 curl")
        print("👋 Simulation terminée.")
