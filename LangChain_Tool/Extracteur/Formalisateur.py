"""
Extracteur/Formalisateur.py

intégration du classificateur ML dans _identifier_action().

"""

import json
import os
import re
from recognizers_number import recognize_number, Culture

# Imports compatibles : exécution directe ET import comme package
try:
    from extracteur import Extracteur
    from classificateur_intention import IntentClassifier
except ModuleNotFoundError:
    from Extracteur.extracteur import Extracteur
    from Extracteur.classificateur_intention import IntentClassifier


class SuperFormalisateur:
    def __init__(self):
        self.ext     = Extracteur()
        self.culture = Culture.French

        # ← AJOUT 2 : initialisation du classificateur (charge ou entraîne)
        self.classificateur = IntentClassifier()

        # Chargement de la configuration externe
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, "config_sdn.json")
        with open(config_path, "r", encoding='utf-8') as f:
            self.config = json.load(f)

    def generer_ordre_mission(self, text, test_id=0):
        # test_id peut être un int (legacy) ou un str (uuid court)
        # On formate l'identifiant pour qu'il soit toujours lisible
        if isinstance(test_id, int):
            mission_id_str = f"MISSION_{test_id:03d}"
        else:
            mission_id_str = f"MISSION_{str(test_id).upper()[:6]}"

        text_lower = text.lower()

        locations  = self.ext.get_connections(text)
        hotes_ids  = [l['id'] for l in locations]

        action_type = self._identifier_action(text_lower)
        regles      = self.config["ACTION_RULES"].get(
            action_type,
            {"tool": "parametres_utilisateur", "action": "query", "min_hosts": 0}
        )

        profil_str = self.ext.get_qos_profile(text) or self.ext.get_intent_profile(text)
        qos_info   = self.config["QOS_MAP"].get(profil_str, {"id": None, "desc": "Inconnu"})

        nombres      = recognize_number(text, self.culture)
        queue_forcee = None
        if nombres and ("queue" in text_lower or "file" in text_lower):
            queue_forcee = int(float(nombres[0].resolution["value"]))

        chemin_data = self.ext.get_paths(text) if len(hotes_ids) >= 2 else None

        manifeste = {
            "mission_id": mission_id_str,
            "intent":     text,
            "decision_engine": {
                "detected_action":  action_type,
                "target_tool":      regles["tool"],
                "technical_action": regles["action"]
            },
            "technical_targets": {
                "hosts_count": len(locations),
                "nodes":       locations,
                "ips":         self.ext.get_ips(hotes_ids)
            },
            "qos_specs": {
                "profile_name": profil_str,
                "queue_id":     queue_forcee if queue_forcee is not None else qos_info["id"],
                "description":  qos_info["desc"]
            },
            "routing": {
                "path": chemin_data["switches_path"]
                        if chemin_data and "switches_path" in chemin_data else []
            },
            "ai_guidance": {
                "execution_ready": self._valider_mission(
                    action_type, locations, profil_str, queue_forcee, chemin_data
                ),
                "instructions": self._formuler_instructions(
                    action_type, regles, locations, qos_info, queue_forcee, chemin_data
                )
            }
        }

        """with open(f"ordres_mission/mission_{test_id}.json", "w", encoding='utf-8') as f:
            json.dump(manifeste, f, indent=4, ensure_ascii=False)"""

        return manifeste

    def _identifier_action(self, text):
        """
        Détecte le type d'action dans le texte.

        Ordre de priorité :
          1. Classificateur ML  (si confiance >= 65%)
          2. Lexiques JSON      (fallback déterministe — ton code original intact)
        """

        # ← AJOUT 3 : tentative ML en priorité
        prediction_ml = self.classificateur.predire(text)
        if prediction_ml:
            return prediction_ml

        # ← FALLBACK : ton code original exactement
        if any(kw in text for kw in ["réseau", "tout", "tous", "partout"]):
            if any(kw in text for kw in self.config["LEXIQUES"]["QOS"]):
                return "NETWORK_WIDE"

        for category, keywords in self.config["LEXIQUES"].items():
            if any(kw in text for kw in keywords):
                return category

        return "QUERY"


    def _valider_mission(self, action, locs, profil, q_forcee, chemin):
        if action == "NETWORK_WIDE" and profil:
            return True
        if action in ["BREAK", "RESTORE"] and len(locs) >= 1:
            # Vérifier aussi que le premier node a bien un dpid et un port
            node0 = locs[0] if locs else None
            if node0 and node0.get("dpid") and node0.get("port") is not None:
                return True
            return False
        if action == "QOS" and len(locs) >= 2 and (profil or q_forcee is not None) and chemin:
            return True
        return False


    def _formuler_instructions(self, action, regles, locs, qos, q_forcee, chemin):
        if action == "NETWORK_WIDE":
            return (
                f"Appeler set_network_wide_policy(profile='{qos['id'] or q_forcee}') "
                f"pour l'intégralité du réseau."
            )
        if action in ["BREAK", "RESTORE"]:
            if locs and locs[0] and locs[0].get("dpid") and locs[0].get("port"):
                return (
                    f"Utiliser {regles['tool']} avec action='{regles['action']}' "
                    f"sur DPID {locs[0]['dpid']} Port {locs[0]['port']}."
                )
            elif locs and locs[0]:
                return (
                    f"Utiliser {regles['tool']} avec action='{regles['action']}'. "
                    f"Paramètres partiels : {locs[0]}. Vérifie le nom de l'hôte."
                )
            else:
                return (
                    f"Action {action} demandée mais aucun hôte/switch identifié. "
                    "Précise le nom de l'hôte cible (ex: 'h3', 'le directeur')."
                )
        if action == "QOS":
            q_id = q_forcee if q_forcee is not None else qos["id"]
            return (
                f"Utiliser {regles['tool']} sur le chemin "
                f"{chemin.get('switches_path')} avec Queue ID {q_id}."
            )
        return "Analyser les paramètres réseau actuels via parametres_utilisateur."
        
        
