"""
control/analyseurs/port_analyser.py

Analyseur de conformité des états de ports physiques.
Utilisé pour les actions BREAK et RESTORE.

Logique :
  - BREAK  → tous les ports ciblés doivent être DOWN
  - RESTORE → tous les ports ciblés doivent être UP (FORWARD)
"""

from datetime import datetime


# Mapping entre la valeur brute Ryu et l'état logique attendu
# Ryu renvoie "FORWARD" pour un port actif, "DOWN" pour un port coupé
RYU_STATE_MAP = {
    "FORWARD": "UP",
    "DOWN":    "DOWN",
    "UNKNOWN": "UNKNOWN"
}

# Ce que chaque action technique attend comme état final
EXPECTED_STATE_MAP = {
    "break":   "DOWN",
    "restore": "UP"
}


class PortAnalyser:

    @staticmethod
    def check_compliance(mission: dict, metrics: dict) -> dict:
        """
        Vérifie si l'état réel des ports correspond à l'intention de la mission.

        Args:
            mission : le manifeste JSON complet (généré par SuperFormalisateur)
            metrics : données collectées par NetworkCollector
                      Format attendu : { "port_states": { "dpid": { "port": "FORWARD/DOWN" } } }

        Returns:
            Un rapport structuré prêt à être consommé par le Rapporteur.
        """
        rapport = {
            "analyseur":          "PORT_ANALYSER",
            "violation_detected": False,
            "affected_nodes":     [],
            "timestamp":          datetime.now().isoformat()
        }

        # --- Extraction des paramètres de la mission ---
        technical_action = mission["decision_engine"]["technical_action"]  # "break" ou "restore"
        expected_logical  = EXPECTED_STATE_MAP.get(technical_action, "UP")
        port_states_raw   = metrics.get("port_states", {})

        # --- Vérification port par port ---
        for target in mission["technical_targets"]["nodes"]:
            dpid     = str(target["dpid"])
            port     = str(target["port"])
            host_id  = target["id"]

            # L'état brut venant de Ryu (ex: "FORWARD", "DOWN")
            raw_state     = port_states_raw.get(dpid, {}).get(port, "UNKNOWN")
            # Traduction vers notre état logique (UP / DOWN / UNKNOWN)
            actual_logical = RYU_STATE_MAP.get(raw_state, "UNKNOWN")

            if actual_logical != expected_logical:
                rapport["violation_detected"] = True
                rapport["affected_nodes"].append({
                    "host":             host_id,
                    "dpid":             dpid,
                    "port":             port,
                    "etat_actuel":      actual_logical,
                    "etat_attendu":     expected_logical,
                    "raw_ryu_state":    raw_state,
                    "severity":         "CRITICAL",
                    # Instruction concrète pour l'IA
                    "recommended_call": (
                        f"manage_link(dpid={dpid}, port={port}, "
                        f"action='{technical_action}')"
                    )
                })

        return rapport
