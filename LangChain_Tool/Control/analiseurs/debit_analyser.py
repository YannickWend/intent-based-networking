"""
Control/analiseurs/debit_analyser.py

Analyseur de conformité QoS — version simplifiée et corrigée.

Logique unifiée basée sur le constat suivant :
  - Les queues OVS sont des contraintes physiques — on ne peut pas dépasser
    le plafond d'une queue active. Surveiller le débit est donc inutile.
  - Ce qui peut disparaître : la RÈGLE QoS dans Ryu (idle_timeout, reboot,
    intervention manuelle, bug OVS). C'est ça qu'on surveille.

Pour tous les profils à surveiller (BRONZE, MULTIMEDIA, GOLD) :
  → Vérifier que la règle QoS (ip_src → queue_id) existe encore dans Ryu
  → Si absente : violation → recommended_call pour réappliquer

Profils sans surveillance :
  SILVER   : illimité, pas de règle spécifique à vérifier
  STANDARD : état par défaut, pas de règle QoS installée
"""

import requests
from datetime import datetime

# -----------------------------------------------------------------------
# Profils qui nécessitent une règle QoS active dans Ryu
# -----------------------------------------------------------------------
PROFILS_A_SURVEILLER     = {"BRONZE", "MULTIMEDIA", "GOLD"}
PROFILS_SANS_SURVEILLANCE = {"SILVER", "STANDARD"}

# URL de l'API Ryu pour lire les règles QoS actives sur un switch
RYU_QOS_RULES_URL = "http://localhost:8080/qos/rules/{dpid_hex}"


def _dpid_to_hex(dpid) -> str:
    """Convertit un DPID entier en format hexadécimal Ryu (16 caractères)."""
    try:
        return "{:016x}".format(int(str(dpid).replace("s", "")))
    except (ValueError, TypeError):
        return "{:016x}".format(0)


def _regle_qos_active(dpid, ip: str, queue_id: int) -> bool:
    """
    Vérifie via l'API Ryu que la règle QoS pour cette IP
    est encore active sur ce switch.

    Retourne True si active, True aussi si l'API est injoignable
    (on évite les fausses violations sur coupure réseau temporaire).
    """
    try:
        url = RYU_QOS_RULES_URL.format(dpid_hex=_dpid_to_hex(dpid))
        res = requests.get(url, timeout=2)
        if res.status_code != 200:
            return True  # API KO → on ne génère pas de fausse violation
        rules = res.json()
        for rule in rules:
            match   = rule.get("match", {})
            actions = rule.get("actions", {})
            ip_match    = match.get("nw_src") == ip
            queue_match = str(actions.get("queue", "")) == str(queue_id)
            if ip_match and queue_match:
                return True
        return False
    except Exception:
        return True  # Timeout ou erreur réseau → pas de fausse violation


def _get_switch_path_ports(dpid: str, switches_path: list, links: list) -> list:
    """
    Retourne les ports d'un switch qui sont sur le chemin entre deux hôtes.
    Inclut les ports hôtes si le switch est en bout de chemin.
    """
    try:
        dpid_int  = int(str(dpid).replace("s", ""))
        path_ints = [int(str(s).replace("s", "")) for s in switches_path]
    except ValueError:
        return []

    if dpid_int not in path_ints:
        return []

    idx        = path_ints.index(dpid_int)
    neighbours = set()
    if idx > 0:
        neighbours.add(path_ints[idx - 1])
    if idx < len(path_ints) - 1:
        neighbours.add(path_ints[idx + 1])

    sw_str = f"s{dpid_int}"
    ports  = []

    for link in links:
        n1, n2 = link["node1"], link["node2"]
        if n1 == sw_str and n2.startswith("s"):
            try:
                if int(n2[1:]) in neighbours:
                    ports.append(link["port1"])
            except ValueError:
                pass
        elif n2 == sw_str and n1.startswith("s"):
            try:
                if int(n1[1:]) in neighbours:
                    ports.append(link["port2"])
            except ValueError:
                pass
        elif n1 == sw_str and n2.startswith("h"):
            ports.append(link["port1"])
        elif n2 == sw_str and n1.startswith("h"):
            ports.append(link["port2"])

    return list(set(ports))


class DebitAnalyser:

    @staticmethod
    def check_path_compliance(mission: dict, metrics: dict) -> dict:
        """
        Mode QOS CIBLÉ : vérifie que les règles QoS sont encore actives
        sur tous les switchs du chemin entre les deux hôtes.

        Ne surveille PAS le débit — les queues OVS sont des contraintes
        physiques qui empêchent tout dépassement par construction.
        """
        rapport = {
            "analyseur":          "DEBIT_ANALYSER_CIBLE",
            "violation_detected": False,
            "affected_nodes":     [],
            "timestamp":          datetime.now().isoformat()
        }

        profile   = (mission["qos_specs"].get("profile_name") or "STANDARD").upper()
        queue_id  = mission["qos_specs"].get("queue_id")
        switches_path = mission["routing"].get("path", [])
        nodes    = mission["technical_targets"].get("nodes", [])
        ips      = mission["technical_targets"].get("ips", [])

        # Profils sans surveillance
        if profile in PROFILS_SANS_SURVEILLANCE:
            rapport["info"] = (
                f"Profil {profile} — aucune règle QoS spécifique "
                f"à surveiller."
            )
            return rapport

        if not switches_path:
            rapport["warning"] = "Aucun chemin défini — surveillance impossible."
            return rapport

        if queue_id is None:
            rapport["warning"] = "queue_id manquant dans la mission."
            return rapport

        if len(ips) < 2:
            rapport["warning"] = "IPs des hôtes manquantes — surveillance impossible."
            return rapport

        ip_a     = ips[0]
        ip_b     = ips[1]
        host_src = nodes[0]["id"] if len(nodes) > 0 else "?"
        host_dst = nodes[1]["id"] if len(nodes) > 1 else "?"

        recommended = (
            f"set_path_qos(path={switches_path}, "
            f"ip_a='{ip_a}', ip_b='{ip_b}', profil='{profile}')"
        )

        # Vérification switch par switch sur le chemin
        for sw_raw in switches_path:
            dpid_int = int(str(sw_raw).replace("s", ""))

            for ip in [ip_a, ip_b]:
                if not _regle_qos_active(dpid_int, ip, queue_id):
                    rapport["violation_detected"] = True
                    rapport["affected_nodes"].append({
                        "dpid":             str(dpid_int),
                        "ip_cible":         ip,
                        "context":          (
                            f"Switch s{dpid_int} — règle {profile} "
                            f"absente pour {ip} "
                            f"(chemin {host_src}→{host_dst})"
                        ),
                        "severity":         "CRITICAL",
                        "recommended_call": recommended
                    })

        return rapport

    @staticmethod
    def check_global_compliance(mission: dict, metrics: dict) -> dict:
        """
        Mode NETWORK_WIDE : vérifie que les règles QoS globales sont encore
        actives sur tous les switchs du réseau.

        Même logique : on surveille la présence des règles, pas le débit.
        """
        rapport = {
            "analyseur":          "DEBIT_ANALYSER_GLOBAL",
            "violation_detected": False,
            "affected_nodes":     [],
            "timestamp":          datetime.now().isoformat()
        }

        profile  = (mission["qos_specs"].get("profile_name") or "STANDARD").upper()
        queue_id = mission["qos_specs"].get("queue_id")

        if profile in PROFILS_SANS_SURVEILLANCE:
            rapport["info"] = (
                f"Profil {profile} — aucune règle QoS spécifique "
                f"à surveiller."
            )
            return rapport

        if queue_id is None:
            rapport["warning"] = "queue_id manquant dans la mission."
            return rapport

        recommended = f"set_network_wide_policy(profile='{profile}')"

        # On vérifie un échantillon représentatif d'IPs sur chaque switch
        # (pas toutes — évite de surcharger l'API Ryu)
        try:
            from network_config import ROLES, SWITCHES
        except ModuleNotFoundError:
            from Extracteur.network_config import ROLES, SWITCHES

        # On prend 3 IPs représentatives — si elles sont KO,
        # c'est que la règle globale n'est plus appliquée
        ips_test = [info["ip"] for info in list(ROLES.values())[:3]]

        for sw_name in SWITCHES:
            dpid_int   = int(sw_name.replace("s", ""))
            sw_viole   = False

            for ip in ips_test:
                if not _regle_qos_active(dpid_int, ip, queue_id):
                    sw_viole = True
                    break  # Un seul manquant suffit pour alerter ce switch

            if sw_viole:
                rapport["violation_detected"] = True
                rapport["affected_nodes"].append({
                    "dpid":             str(dpid_int),
                    "context":          (
                        f"Switch s{dpid_int} — règle globale "
                        f"{profile} absente"
                    ),
                    "severity":         "CRITICAL",
                    "recommended_call": recommended
                })

        return rapport
