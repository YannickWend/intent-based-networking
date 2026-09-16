"""
intent_registry.py — Gestionnaire Multi-Intentions (Semaine 3)
==============================================================
NOUVEAUTÉ SEMAINE 3 :
  - Intégration de l'IntentScheduler (demand-driven QoS)
  - Les missions QoS sont ajoutées en état "DORMANTE" (pas d'exécution immédiate)
  - Le scheduler surveille le réseau et active/désactive automatiquement
  - Les missions BREAK/RESTORE restent exécutées immédiatement (comportement inchangé)
"""

import threading
import time
import json
import uuid
from datetime import datetime
from typing import Dict, Optional, Callable

from Control.mission_watcheur import ControlLayer
from correcteur import corriger_autonomement



# -----------------------------------------------------------------------
# Helper — lecture du manifeste (clés produites par le Formalisateur)
# -----------------------------------------------------------------------

def _lire_hotes(manifeste: dict) -> list:
    """
    Retourne la liste des nodes depuis technical_targets.nodes.
    Chaque node = {"id": "h1", "dpid": 6, "port": 1}
    """
    return manifeste.get("technical_targets", {}).get("nodes", [])

def _lire_ips(manifeste: dict) -> list:
    """Retourne la liste des IPs depuis technical_targets.ips."""
    return manifeste.get("technical_targets", {}).get("ips", [])

def _lire_profil(manifeste: dict) -> str:
    """Retourne le profil QoS depuis qos_specs.profile_name."""
    return manifeste.get("qos_specs", {}).get("profile_name", "") or ""

# Actions QoS qui passent par le scheduler (activation différée)
ACTIONS_SCHEDULEES = {"QOS", "NETWORK_WIDE"}

# Actions exécutées immédiatement (comportement inchangé)
ACTIONS_IMMEDIATES = {"BREAK", "RESTORE", "QUERY"}


# -----------------------------------------------------------------------
# STRUCTURE D'UNE MISSION
# -----------------------------------------------------------------------

class Mission:
    def __init__(self, mission_id: str, manifeste: dict):
        self.mission_id  = mission_id
        self.manifeste   = manifeste
        self.stop_event  = threading.Event()
        self.thread      = None

        # Statut étendu pour la Semaine 3
        # IMMEDIATES  : ACTIVE, STOPPED, CORRECTING
        # SCHEDULEES  : DORMANTE (en attente), ACTIVE (activée par scheduler), STOPPED
        action = manifeste.get("decision_engine", {}).get("detected_action", "")
        self.status = "DORMANTE" if action in ACTIONS_SCHEDULEES else "ACTIVE"

        self.cree_a      = datetime.now().strftime("%H:%M:%S")
        self.corrections = 0

    def to_dict(self) -> dict:
        action = self.manifeste.get("decision_engine", {}).get("detected_action", "?")
        # Utiliser les helpers — clés réelles du manifeste Formalisateur
        nodes  = _lire_hotes(self.manifeste)
        hotes  = [n.get("id", "?") for n in nodes]   # ex: ["h1", "h10"]
        ips    = _lire_ips(self.manifeste)
        profil = _lire_profil(self.manifeste)
        return {
            "mission_id":  self.mission_id,
            "action":      action,
            "hotes":       hotes,
            "profil":      profil,
            "status":      self.status,
            "cree_a":      self.cree_a,
            "corrections": self.corrections,
        }






def _log(msg: str):
    print(msg)
    try:
        from sdn_ai_retroactif import dashboard_logs
        dashboard_logs.append(msg)
    except Exception:
        pass
# -----------------------------------------------------------------------
# INTENT REGISTRY
# -----------------------------------------------------------------------

class IntentRegistry:
    """
    Gestionnaire de missions IBN actives.
    - Missions QoS : ajoutées en DORMANTE, activées par l'IntentScheduler
    - Missions BREAK/RESTORE : exécutées immédiatement, watchdog actif
    """

    def __init__(self, log_callback: Optional[Callable] = None):
        self._missions: Dict[str, Mission] = {}
        self._lock    = threading.Lock()
        self._log_cb  = log_callback or (lambda r: print(f"[REGISTRY LOG] {r}"))
        self._scheduler = None

    def demarrer_scheduler(self):
        """Démarre l'IntentScheduler en arrière-plan."""
        from intent_scheduler import IntentScheduler
        self._scheduler = IntentScheduler(self)
        self._scheduler.demarrer()
    
    # -------------------------------------------------------------------
    # AJOUTER UNE MISSION
    # -------------------------------------------------------------------

    def ajouter(self, manifeste: dict) -> tuple:
        """
        Ajoute une nouvelle mission au registry.

        Pour les missions QoS : ajoutées en état DORMANTE.
        Pour BREAK/RESTORE : ajoutées en état ACTIVE avec watchdog immédiat.

        Returns:
            (mission_id, conflit_detecte, message_conflit)
        """
        conflit, msg_conflit = self._detecter_conflit(manifeste)
        if conflit:
            return None, True, msg_conflit

        mission_id = f"M{str(uuid.uuid4())[:6].upper()}"
        mission    = Mission(mission_id, manifeste)

        action = manifeste.get("decision_engine", {}).get("detected_action", "")

        if action in ACTIONS_IMMEDIATES:
            # Watchdog immédiat pour BREAK/RESTORE
            mission.thread = threading.Thread(
                target=self._boucle_surveillance,
                args=(mission,),
                daemon=True
            )
            mission.thread.start()
            statut_msg = "ACTIVE (watchdog démarré)"
        else:
            # QoS : dormante, le scheduler s'en occupe
            statut_msg = "DORMANTE (scheduler en attente)"

        with self._lock:
            self._missions[mission_id] = mission

        nodes  = _lire_hotes(manifeste)
        hotes  = [n.get("id", "?") for n in nodes]
        profil = _lire_profil(manifeste)
        _log(f" [REGISTRY] Mission {mission_id} ajoutée — action={action} profil={profil} hôtes={hotes} → {statut_msg}")


        return mission_id, False, ""

    # -------------------------------------------------------------------
    # SUPPRIMER UNE MISSION
    # -------------------------------------------------------------------

    def supprimer(self, mission_id: str) -> bool:
        """Arrête et supprime une mission par son ID."""
        with self._lock:
            mission = self._missions.get(mission_id)
            if not mission:
                return False
            mission.stop_event.set()
            mission.status = "STOPPED"
            if mission.thread and mission.thread.is_alive():
                mission.thread.join(timeout=5)
            del self._missions[mission_id]
        _log(f"[REGISTRY] Mission {mission_id} supprimée.")

        return True

    def arreter_tout(self):
        """Arrête toutes les missions et le scheduler."""
        if self._scheduler:
            self._scheduler.arreter()
        with self._lock:
            ids = list(self._missions.keys())
        for mid in ids:
            self.supprimer(mid)
        print("[REGISTRY] Toutes les missions arrêtées.")

    # -------------------------------------------------------------------
    # ÉTAT DU REGISTRY
    # -------------------------------------------------------------------

    def liste_missions(self) -> list:
        with self._lock:
            return [m.to_dict() for m in self._missions.values()]

    def nb_missions(self) -> int:
        with self._lock:
            return len(self._missions)

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        with self._lock:
            return self._missions.get(mission_id)

    # -------------------------------------------------------------------
    # DÉTECTION DE CONFLITS
    # -------------------------------------------------------------------

    def _detecter_conflit(self, nouveau_manifeste: dict) -> tuple:
        """Vérifie les conflits avec les missions existantes."""
        nouvelle_action = nouveau_manifeste.get(
            "decision_engine", {}).get("detected_action", "").upper()
        nouveaux_hotes  = {
            n.get("id") for n in
            _lire_hotes(nouveau_manifeste)
            if n.get("id")
        }

        with self._lock:
            missions_actives = list(self._missions.values())

        for mission in missions_actives:
            if mission.status == "STOPPED":
                continue

            action_existante = mission.manifeste.get(
                "decision_engine", {}).get("detected_action", "").upper()
            hotes_existants  = {
                n.get("id") for n in
                _lire_hotes(mission.manifeste)
                if n.get("id")
            }

            hotes_communs = nouveaux_hotes & hotes_existants
            if not hotes_communs:
                continue

            if nouvelle_action == "BREAK" and action_existante in ("QOS", "RESTORE"):
                return (True,
                    f"CONFLIT : Mission {mission.mission_id} "
                    f"({action_existante}) est active sur {hotes_communs}. "
                    f"Supprimez d'abord la mission {mission.mission_id}.")

            if nouvelle_action == "RESTORE" and action_existante == "BREAK":
                return (True,
                    f"CONFLIT : Mission {mission.mission_id} "
                    f"maintient un lien COUPÉ sur {hotes_communs}. "
                    f"Supprimez d'abord la mission {mission.mission_id}.")

            if nouvelle_action == "QOS" and action_existante == "QOS":
                nouveau_profil  = _lire_profil(nouveau_manifeste).upper()
                profil_existant = _lire_profil(mission.manifeste).upper()
                if nouveau_profil != profil_existant:
                    return (True,
                        f"CONFLIT QoS : Mission {mission.mission_id} "
                        f"a déjà {profil_existant} sur {hotes_communs}. "
                        f"Supprimez d'abord la mission {mission.mission_id}.")

        return False, ""

    # -------------------------------------------------------------------
    # BOUCLE DE SURVEILLANCE (BREAK/RESTORE uniquement)
    # -------------------------------------------------------------------
    
    

    
    
    
    def _boucle_surveillance(self, mission: Mission):
        """
        Thread watchdog pour les missions BREAK/RESTORE.
        Les missions QoS sont gérées par l'IntentScheduler.
        """
        controlleur = ControlLayer(mission.manifeste)
        intervalle  = {"BREAK": 5, "RESTORE": 5}.get(
            mission.manifeste.get("decision_engine", {}).get("detected_action", ""),
            10
        )

        print(f"[WATCHDOG-{mission.mission_id}] Surveillance démarrée "
              f"(intervalle={intervalle}s)")

        while not mission.stop_event.is_set():
            try:
                rapport = controlleur.run_diagnostic()
                if rapport:
                    _log(f"[WATCHDOG-{mission.mission_id}] Violation détectée !")

                    mission.status = "CORRECTING"
                    rapport_correction = corriger_autonomement(mission.manifeste, rapport)
                    mission.corrections += 1
                    mission.status = "ACTIVE"

                    log_ia = (
                        f"[LOG CORRECTION AUTONOME — Mission {mission.mission_id}]\n"
                        f"{rapport_correction}\n"
                        f"Aucune action requise de ta part. "
                        f"Informe l'utilisateur si nécessaire."
                    )
                    self._log_cb(log_ia)

            except Exception as e:
                print(f"[WATCHDOG-{mission.mission_id}] Erreur : {e}")

            for _ in range(intervalle):
                if mission.stop_event.is_set():
                    break
                time.sleep(1)

        print(f"[WATCHDOG-{mission.mission_id}] Arrêté.")
