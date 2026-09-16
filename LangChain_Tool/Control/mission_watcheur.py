"""
mission_watcheur.py — Couche de Contrôle (ControlLayer)
========================================================
MODIFICATION SEMAINE 2 :
  - ControlLayer accepte un DICT (manifeste direct)
    EN PLUS d'un chemin fichier (str).
  - Le watchdog indépendant de l'IntentRegistry passe directement
    le manifeste sans avoir besoin de l'écrire sur disque.
  - run_diagnostic retourne str (violation) ou None (tout ok).
  - La correction n'est PAS faite ici — c'est le rôle de correcteur.py
"""

import json
import sys
from os.path import dirname, abspath, join

sys.path.insert(0, abspath(join(dirname(__file__), '..')))
sys.path.insert(0, abspath(join(dirname(__file__), '../Extracteur')))

from Control.analiseurs.port_analyser import PortAnalyser
from Control.analiseurs.debit_analyser import DebitAnalyser


class ControlLayer:
    """
    Couche de contrôle IBN.
    Accepte soit un chemin fichier (str) soit un dictionnaire manifeste (dict).

    controlleur = ControlLayer("ordres_mission/mission_active.json")
    """

    def __init__(self, source):
        if isinstance(source, dict):
            self._manifeste      = source
            self._source_fichier = None
        elif isinstance(source, str):
            self._manifeste      = None
            self._source_fichier = source
        else:
            raise TypeError(f"ControlLayer attend str ou dict, reçu {type(source)}")

    def _charger_manifeste(self) -> dict:
        if self._manifeste is not None:
            return self._manifeste
        try:
            with open(self._source_fichier, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            print(f"[CONTROLLEUR] Erreur chargement : {e}")
            return {}

    def run_diagnostic(self):
        """
        Lance le diagnostic de la mission.
        Returns: str (rapport violation) ou None (tout ok)
        """
        manifeste = self._charger_manifeste()
        if not manifeste:
            return None

        try:
            action = manifeste["decision_engine"]["detected_action"]
        except KeyError:
            return None

        if action in ("BREAK", "RESTORE"):
            return self._diagnostic_port(manifeste)
        elif action in ("QOS", "NETWORK_WIDE"):
            return self._diagnostic_debit(manifeste)
        return None


    def _diagnostic_port(self, manifeste: dict):
        try:
            from Control.collecteur import NetworkCollector
            metrics = NetworkCollector().get_all_metrics()
            rapport = PortAnalyser.check_compliance(manifeste, metrics)
            return rapport if rapport.get("violation_detected") else None
        except Exception as e:
            print(f"[CONTROLLEUR] Erreur PortAnalyser : {e}")
            return None

    def _diagnostic_debit(self, manifeste: dict):
        try:
            from Control.collecteur import NetworkCollector
            metrics = NetworkCollector().get_all_metrics()
            action  = manifeste.get("decision_engine", {}).get("detected_action", "")
            if action == "NETWORK_WIDE":
                rapport = DebitAnalyser.check_global_compliance(manifeste, metrics)
            else:
                rapport = DebitAnalyser.check_path_compliance(manifeste, metrics)
            return rapport if rapport.get("violation_detected") else None
        except Exception as e:
            print(f"[CONTROLLEUR] Erreur DebitAnalyser : {e}")
            return None
