"""
correcteur.py — Correction autonome sans IA
============================================
Quand le watchdog détecte une violation, ce module corrige
directement via Flask sans passer par le LLM.
L'IA reçoit seulement un log de confirmation après coup.
"""

import requests
import json
import time
from datetime import datetime

FLASK_BASE = "http://localhost:5000"



# FONCTIONS DE CORRECTION PAR TYPE D'ACTION


def _corriger_break(manifeste: dict) -> dict:
    """Réinstalle un lien coupé (BREAK) s'il est remonté sans notre accord."""
    try:
        # Méthode 1 : chercher dans technical_targets.nodes (structure réelle)
        dpid = None
        port = None
        
        technical_targets = manifeste.get("technical_targets", {})
        nodes = technical_targets.get("nodes", [])
        
        if nodes:
            dpid = nodes[0].get("dpid")
            port = nodes[0].get("port")
        
        # Méthode 2 : fallback sur l'ancienne structure (topology.target_switch)
        if dpid is None or port is None:
            topology = manifeste.get("topology", {})
            target   = topology.get("target_switch", {})
            dpid     = target.get("dpid")
            port     = target.get("port")
        
        # Méthode 3 : résoudre l'ID hôte vers dpid/port depuis LINKS
        if dpid is None or port is None:
            from Extracteur.network_config import LINKS
            host_id = nodes[0].get("id") if nodes else None
            if host_id:
                for link in LINKS:
                    if link.get("node1") == host_id:
                        dpid = int(link["node2"].replace("s", ""))
                        port = link["port2"]
                        break
                    elif link.get("node2") == host_id:
                        dpid = int(link["node1"].replace("s", ""))
                        port = link["port1"]
                        break

        if dpid is None or port is None:
            return {"succes": False, "raison": "dpid ou port manquant dans le manifeste"}

        res = requests.post(
            f"{FLASK_BASE}/link/break",
            json={"dpid": int(dpid), "port": int(port)},
            timeout=5
        )
        if res.status_code == 200:
            return {
                "succes": True,
                "action": "break",
                "dpid": dpid,
                "port": port,
                "message": f"Lien s{dpid}:port{port} recoupé automatiquement."
            }
        return {"succes": False, "raison": f"Flask retourne {res.status_code}"}
    except Exception as e:
        return {"succes": False, "raison": str(e)}


def _corriger_restore(manifeste: dict) -> dict:
    """Restaure un lien qui a disparu (RESTORE) s'il est retombé."""
    try:
        # Méthode 1 : chercher dans technical_targets.nodes (structure réelle)
        dpid = None
        port = None
        
        technical_targets = manifeste.get("technical_targets", {})
        nodes = technical_targets.get("nodes", [])
        
        if nodes:
            dpid = nodes[0].get("dpid")
            port = nodes[0].get("port")
        
        # Méthode 2 : fallback sur l'ancienne structure (topology.target_switch)
        if dpid is None or port is None:
            topology = manifeste.get("topology", {})
            target   = topology.get("target_switch", {})
            dpid     = target.get("dpid")
            port     = target.get("port")
        
        # Méthode 3 : résoudre l'ID hôte vers dpid/port depuis LINKS
        if dpid is None or port is None:
            from Extracteur.network_config import LINKS
            host_id = nodes[0].get("id") if nodes else None
            if host_id:
                for link in LINKS:
                    if link.get("node1") == host_id:
                        dpid = int(link["node2"].replace("s", ""))
                        port = link["port2"]
                        break
                    elif link.get("node2") == host_id:
                        dpid = int(link["node1"].replace("s", ""))
                        port = link["port1"]
                        break

        if dpid is None or port is None:
            return {"succes": False, "raison": "dpid ou port manquant dans le manifeste"}

        res = requests.post(
            f"{FLASK_BASE}/link/restore",
            json={"dpid": int(dpid), "port": int(port)},
            timeout=5
        )
        if res.status_code == 200:
            return {
                "succes": True,
                "action": "restore",
                "dpid": dpid,
                "port": port,
                "message": f"Lien s{dpid}:port{port} restauré automatiquement."
            }
        return {"succes": False, "raison": f"Flask retourne {res.status_code}"}
    except Exception as e:
        return {"succes": False, "raison": str(e)}


def _corriger_qos(manifeste: dict) -> dict:
    try:
        from network_config import HOST_IP_TO_ACCESS_SWITCH, DSCP_MAP
        import requests

        QOS_TABLE = {
            "STANDARD": 0,
            "MULTIMEDIA": 1,
            "BRONZE": 2,
            "GOLD": 3,
            "SILVER": 4
        }

        profil = (
            manifeste.get("qos_specs", {}).get("profile_name")
            or "STANDARD"
        ).upper()

        ips = manifeste.get("technical_targets", {}).get("ips", [])

        if not ips:
            return {
                "succes": False,
                "raison": "Aucune IP trouvée dans le manifeste"
            }

        queue_id = QOS_TABLE.get(profil, 0)
        dscp_val = DSCP_MAP.get(profil, 0)

        log = []
        erreurs = 0

        for ip in ips:
            sw_name = HOST_IP_TO_ACCESS_SWITCH.get(ip)

            if not sw_name:
                log.append(f"{ip}: switch introuvable")
                erreurs += 1
                continue

            dpid = int(sw_name.replace("s", ""))

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

            if not qos_ok or not dscp_ok:
                erreurs += 1

            log.append(
                f"{ip}({sw_name}): "
                f"queue={queue_id} {'OK' if qos_ok else 'ERR'}, "
                f"DSCP={dscp_val} {'OK' if dscp_ok else 'ERR'}"
            )

        return {
            "succes": erreurs == 0,
            "action": "qos",
            "profil": profil,
            "queue": queue_id,
            "details": log,
            "message": f"QoS {profil} réinstallée sur {len(ips)} IP(s)."
        }

    except Exception as e:
        return {
            "succes": False,
            "raison": str(e)
        }


def _corriger_network_wide(manifeste: dict) -> dict:
    """Réapplique la politique réseau globale."""
    try:
        profil = manifeste.get("qos_parameters", {}).get("profile", "STANDARD").upper()
        res = requests.post(
            f"{FLASK_BASE}/qos/network_wide",
            json={"profile": profil},
            timeout=10
        )
        if res.status_code == 200:
            return {
                "succes": True,
                "action": "network_wide",
                "profil": profil,
                "message": f"Politique réseau {profil} réappliquée automatiquement."
            }
        return {"succes": False, "raison": f"Flask retourne {res.status_code}"}
    except Exception as e:
        return {"succes": False, "raison": str(e)}



# POINT D'ENTRÉE PRINCIPAL


CORRECTEURS = {
    "BREAK":        _corriger_break,
    "RESTORE":      _corriger_restore,
    "QOS":          _corriger_qos,
    "NETWORK_WIDE": _corriger_network_wide,
}


def corriger_autonomement(manifeste: dict, rapport_violation: str) -> str:
    """
    Point d'entrée principal appelé par le watchdog.
    Corrige sans IA et retourne un rapport formaté pour le log.

    Args:
        manifeste        : le manifeste JSON de la mission active
        rapport_violation: le texte du rapport de violation du watchdog

    Returns:
        str: rapport de correction formaté (envoyé à l'IA comme log seulement)
    """
    action = manifeste.get("decision_engine", {}).get("detected_action", "").upper()
    horodatage = datetime.now().strftime("%H:%M:%S")

    correcteur_fn = CORRECTEURS.get(action)
    if correcteur_fn is None:
        return (
            f"[{horodatage}]  CORRECTEUR : action '{action}' non reconnue. "
            f"Correction manuelle requise."
        )

    print(f"🔧 [CORRECTEUR] Correction autonome en cours pour action={action}...")
    resultat = correcteur_fn(manifeste)

    if resultat["succes"]:
        rapport = (
            f"[{horodatage}]  CORRECTION AUTONOME RÉUSSIE\n"
            f"  Action    : {action}\n"
            f"  Détails   : {resultat.get('message', '')}\n"
            f"  Violation : {str(rapport_violation)[:200]}\n"

        )
        print(f" [CORRECTEUR] {resultat.get('message', 'Succès')}")
    else:
        rapport = (
            f"[{horodatage}] CORRECTION AUTONOME ÉCHOUÉE\n"
            f"  Action  : {action}\n"
            f"  Raison  : {resultat.get('raison', 'inconnue')}\n"
            f"  Violation : {str(rapport_violation)[:200]}\n"
            f"  Intervention manuelle ou IA requise."
        )
        print(f"[CORRECTEUR] Échec : {resultat.get('raison', 'inconnue')}")

    return rapport
