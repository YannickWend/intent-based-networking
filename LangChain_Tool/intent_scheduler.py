"""
intent_scheduler.py — Intent Scheduling Demand-Driven
======================================================
Les intentions QoS ne sont plus exécutées immédiatement.
Elles sont stockées en état "EN_ATTENTE" ou "DORMANTE" et activées
automatiquement quand le réseau en a besoin, selon l'état de congestion
détecté par le modèle ML.

Logique :
  - NORMAL              → désactivation si trafic faible
  - CHARGE_ELEVEE       → set_access_qos
  - CONGESTION backbone → set_access_qos
  - CONGESTION access   → set_access_qos
  
  On pourrait ajouter une ou plusieurs méthodes pour impacter le débit ou la latence selon la charge élevée, congestion backbone ou congestion access. Pour l'instant toutes ces
  congestions se gèrent de la meme manière.
"""

import threading
import time
import requests
from datetime import datetime

from Control.collecteur import NetworkCollector
from congestion_detector import CongestionDetector
from intent_registry import _lire_hotes, _lire_ips, _lire_profil


FLASK_BASE = "http://localhost:5000"
INTERVALLE_S = 8

SEUIL_ACTIVATION = 5.0
SEUIL_DESACTIVATION = 1.5


def _log(msg: str):
    print(msg)
    try:
        from sdn_ai_retroactif import dashboard_logs
        dashboard_logs.append(msg)
    except Exception:
        pass


class IntentScheduler:
    """
    Scheduler d'intentions QoS.
    Surveille le réseau en continu et active/désactive les intentions QoS
    selon l'état détecté par CongestionDetector.
    """

    def __init__(self, registry):
        self._registry = registry
        self._collector = NetworkCollector()
        self._detector = CongestionDetector()
        self._stop = threading.Event()
        self._thread = None
        self._last_prediction = None

        if not self._detector.charger():
            print("🔧 [SCHEDULER] Modèle non trouvé — entraînement automatique...")
            self._detector.entrainer(verbose=False)
            print("[SCHEDULER] Modèle prêt.")


    # DEMARRAGE / ARRET


    def demarrer(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._boucle_surveillance,
            daemon=True
        )
        self._thread.start()
        print("[SCHEDULER] Intent Scheduler démarré.")

    def arreter(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        print("[SCHEDULER] Intent Scheduler arrêté.")


    # SNAPSHOT RESEAU


    def _get_snapshot(self):
        """
        Récupère le snapshot réseau courant depuis le collecteur.
        Cette méthode est nécessaire car _cycle_evaluation() l'appelle.
        """
        return self._collector.get_network_snapshot()


    # BOUCLE PRINCIPALE


    def _boucle_surveillance(self):
        print(f"[SCHEDULER] Boucle démarrée, vérification toutes les {INTERVALLE_S}s")

        while not self._stop.is_set():
            try:
                self._cycle_evaluation()
            except Exception as e:
                print(f"[SCHEDULER] Erreur cycle : {e}")

            for _ in range(INTERVALLE_S):
                if self._stop.is_set():
                    break
                time.sleep(1)

    def _cycle_evaluation(self):
        try:
            snapshot = self._get_snapshot()

            if not snapshot:
                return

            if snapshot.get("status") == "OFFLINE":
                return

            prediction = self._detector.predire(snapshot)

            label = prediction.get("label", "NORMAL")
            zone = prediction.get("zone", "normal")

            self._last_prediction = prediction

            if label == "NORMAL":
                self._desactiver_si_trafic_faible()
                return

            for mission_info in self._get_missions_qos():
                self._traiter_mission_qos(mission_info, label, zone, snapshot)

        except Exception as e:
            print(f"[Scheduler] Erreur cycle évaluation : {e}")


    # GESTION DES MISSIONS QoS


    def _get_missions_qos(self) -> list:
        """
        Retourne les missions QoS actives, en attente ou dormantes.
        """
        try:
            toutes = self._registry.liste_missions()
        except Exception as e:
            print(f"[SCHEDULER] Erreur lecture missions : {e}")
            return []

        missions = []

        for m in toutes:
            try:
                action = m.get("action")
                status = m.get("status")

                if action in ("QOS", "NETWORK_WIDE") and status in (
                    "ACTIVE",
                    "EN_ATTENTE",
                    "DORMANTE"
                ):
                    missions.append(m)

            except Exception:
                continue

        return missions

    def _traiter_mission_qos(self, mission_info: dict, label: str, zone: str, snapshot: dict):
        """
        Décide quoi faire pour une mission QoS donnée.
        """
        mission_id = mission_info.get("mission_id")
        if not mission_id:
            return

        mission = self._registry.get_mission(mission_id)
        if not mission:
            return

        manifeste = mission.manifeste

        nodes = _lire_hotes(manifeste)
        ips = _lire_ips(manifeste)
        profil = _lire_profil(manifeste) or "STANDARD"

        hotes = [
            {"ip": ip, "id": node.get("id", "")}
            for node, ip in zip(nodes, ips)
            if ip
        ]

        if not hotes:
            return

        debit_actuel = self._mesurer_debit_hotes(ips)

        if debit_actuel < SEUIL_ACTIVATION:
            if mission.status == "DORMANTE":
                return

            if mission.status == "ACTIVE" and debit_actuel < SEUIL_DESACTIVATION:
                self._desactiver_mission(mission)
                return

        action_choisie = self._choisir_action(label, zone, snapshot, hotes)

        if action_choisie in ("set_access_qos", "set_path_qos"):
            if mission.status == "ACTIVE":
                return

            if action_choisie == "set_access_qos":
                self._appliquer_access_qos(mission, hotes, profil)
            else:
                self._appliquer_path_qos(mission, hotes, profil, manifeste)

        elif action_choisie == "desactiver":
            self._desactiver_mission(mission)

    def _choisir_action(self, label: str, zone: str, snapshot: dict, hotes: list) -> str:
        if label == "NORMAL":
            return "desactiver"

        if label == "CHARGE_ELEVEE":
            return "set_access_qos"

        if label == "CONGESTION":
            if zone == "backbone":
                return "set_access_qos"

            if zone == "access":
                return "set_access_qos"

            if zone == "global":
                return "set_path_qos"

            return "set_access_qos"

        return "attendre"


    # ACTIONS QoS


    def _appliquer_access_qos(self, mission, hotes: list, profil: str):
        """
        Applique la QoS sur les switches d'accès des hôtes ciblés.
        """
        from network_config import HOST_IP_TO_ACCESS_SWITCH, DSCP_MAP

        QOS_TABLE = {
            "STANDARD": 0,
            "MULTIMEDIA": 1,
            "BRONZE": 2,
            "GOLD": 3,
            "SILVER": 4
        }

        profil = profil.upper()
        queue_id = QOS_TABLE.get(profil, 0)
        dscp_val = DSCP_MAP.get(profil, 0)

        ips = [h.get("ip") for h in hotes if h.get("ip")]

        if not ips:
            return

        horodatage = datetime.now().strftime("%H:%M:%S")
        log = []
        success_count = 0

        for ip in ips:
            sw_name = HOST_IP_TO_ACCESS_SWITCH.get(ip)

            if not sw_name:
                log.append(f"{ip}: switch introuvable")
                continue

            dpid = int(sw_name.replace("s", ""))

            try:
                rq = requests.post(
                    f"{FLASK_BASE}/qos/set_qos_profile",
                    json={
                        "dpid": dpid,
                        "ip": ip,
                        "queue": queue_id
                    },
                    timeout=10
                )

                rd = requests.post(
                    f"{FLASK_BASE}/dscp/set",
                    json={
                        "ip_src": ip,
                        "profile": profil
                    },
                    timeout=5
                )

                qos_ok = rq.status_code == 200

                try:
                    dscp_ok = rd.json().get("status") == "ok"
                except Exception:
                    dscp_ok = False

                if qos_ok and dscp_ok:
                    success_count += 1

                log.append(
                    f"{ip}({sw_name}): "
                    f"queue={queue_id} {'OK' if qos_ok else 'ERR'}, "
                    f"DSCP={dscp_val} {'OK' if dscp_ok else 'ERR'}"
                )

            except Exception as e:
                log.append(f"{ip}: échec({e})")

        if success_count > 0:
            mission.status = "ACTIVE"
            _log(
                f"[{horodatage}] [SCHEDULER-{mission.mission_id}] "
                f"QoS {profil} activée → {' | '.join(log)}"
            )
        else:
            mission.status = "DORMANTE"
            _log(
                f"[{horodatage}] [SCHEDULER-{mission.mission_id}] "
                f"Échec activation QoS {profil} → {' | '.join(log)}"
            )

    def _appliquer_path_qos(self, mission, hotes: list, profil: str, manifeste: dict):
        """
        Applique la QoS sur tout le chemin si la congestion est globale.
        """
        ips = [h.get("ip") for h in hotes if h.get("ip")]

        if len(ips) < 2:
            ips = _lire_ips(mission.manifeste)

        if len(ips) < 2:
            self._appliquer_access_qos(mission, hotes, profil)
            return

        QOS_TABLE = {
            "STANDARD": 0,
            "MULTIMEDIA": 1,
            "BRONZE": 2,
            "GOLD": 3,
            "SILVER": 4
        }

        profil = profil.upper()
        queue_id = QOS_TABLE.get(profil, 0)

        ip_a, ip_b = ips[0], ips[1]

        chemin = manifeste.get("routing", {}).get("path", [])

        if not chemin:
            self._appliquer_access_qos(mission, hotes, profil)
            return

        horodatage = datetime.now().strftime("%H:%M:%S")
        log = []
        success_count = 0

        for dpid in chemin:
            try:
                dpid_int = int(str(dpid).replace("s", ""))

                for ip in [ip_a, ip_b]:
                    r = requests.post(
                        f"{FLASK_BASE}/qos/set_qos_profile",
                        json={
                            "dpid": dpid_int,
                            "ip": ip,
                            "queue": queue_id
                        },
                        timeout=10
                    )

                    if r.status_code == 200:
                        success_count += 1

                log.append(f"s{dpid_int}: OK")

            except Exception as e:
                log.append(f"s{dpid}: ERR({e})")

        if success_count > 0:
            mission.status = "ACTIVE"
            _log(
                f"[{horodatage}] [SCHEDULER-{mission.mission_id}] "
                f"QoS {profil} chemin complet → {', '.join(log)}"
            )
        else:
            mission.status = "DORMANTE"
            _log(
                f"[{horodatage}] [SCHEDULER-{mission.mission_id}] "
                f"Échec QoS chemin complet → {', '.join(log)}"
            )


    # MESURE TRAFIC


    def _mesurer_debit_hotes(self, ips: list) -> float:
        """
        Mesure le débit réel des hôtes via leurs switches d'accès.
        Retourne le débit max observé en Mbps.
        """
        from network_config import HOST_IP_TO_ACCESS_SWITCH

        try:
            snapshot = self._get_snapshot()

            if not snapshot or snapshot.get("status") == "OFFLINE":
                return 0.0

            switches = snapshot.get("switches", {})
            max_debit = 0.0

            for ip in ips:
                sw_name = HOST_IP_TO_ACCESS_SWITCH.get(ip)

                if not sw_name:
                    continue

                sw_num = sw_name.replace("s", "")
                sw_data = switches.get(sw_num, {})

                debit = sw_data.get("tx_mbps", 0.0) + sw_data.get("rx_mbps", 0.0)
                max_debit = max(max_debit, debit)

            return max_debit

        except Exception as e:
            print(f"[SCHEDULER] Erreur mesure débit : {e}")
            return 0.0


    # DESACTIVATION


    def _desactiver_mission(self, mission):
        """
        Désactive une mission QoS en retirant le marquage DSCP.
        """
        ips_a_desactiver = _lire_ips(mission.manifeste)

        if mission.status == "DORMANTE":
            return

        horodatage = datetime.now().strftime("%H:%M:%S")

        for ip in ips_a_desactiver:
            if not ip:
                continue

            try:
                requests.post(
                    f"{FLASK_BASE}/dscp/remove",
                    json={"ip_src": ip},
                    timeout=5
                )
            except Exception:
                pass

        mission.status = "DORMANTE"

        _log(
            f"[{horodatage}] [SCHEDULER-{mission.mission_id}] "
            f"QoS désactivée — trafic retombé au mode normal."
        )

    def _desactiver_si_trafic_faible(self):
        """
        Désactive les missions QoS actives si le trafic est faible.
        """
        missions_qos = self._get_missions_qos()

        for mission_info in missions_qos:
            mission_id = mission_info.get("mission_id")
            if not mission_id:
                continue

            mission = self._registry.get_mission(mission_id)

            if not mission or mission.status != "ACTIVE":
                continue

            ips = _lire_ips(mission.manifeste)

            if len(ips) >= 1:
                debit = self._mesurer_debit_hotes(ips)

                if debit < SEUIL_DESACTIVATION:
                    self._desactiver_mission(mission)
