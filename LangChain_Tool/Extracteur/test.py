from extracteur_intention import extract_intent_profile

def main():

    tests = [
        "Assure un débit maximal entre le directeur et le serveur",
        "On a une visioconférence sur le poste de Mariem",
        "Priorise le trafic du serveur de base de données",
        "Je veux une latence minimale pour l'application critique",
        "Limite la connexion des stagiaires pour économiser la bande passante",
        "Remets le réseau en mode standard",
        "Maximise la vitesse pour le téléchargement du backup",
        "On lance un appel Zoom entre h1 et h10"
    ]

    print(f"{'PHRASE UTILISATEUR':<60} | {'PROFIL DÉTECTÉ':<15}")
    print("-" * 80)

    for phrase in tests:
        profil = extract_intent_profile(phrase)
        queue_mapping = {
            "STANDARD": 0, "MULTIMEDIA": 1, "BRONZE": 2, "GOLD": 3, "SILVER": 4
        }
        q_id = queue_mapping.get(profil, "N/A")
        
        print(f"{phrase[:58]:<60} | {str(profil):<15} (Queue ID: {q_id})")

if __name__ == "__main__":
    main()
