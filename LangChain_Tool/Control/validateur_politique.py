"""
Control/validateur_politique.py

Validateur ML de politique SDN — couche de vérification entre le LLM et l'exécution.

Trois niveaux de validation :
  N1 — Cohérence outil/intention   : BREAK doit utiliser manage_link, etc.
  N2 — Cohérence paramètres/action : action="break" avec intention RESTORE → INVALIDE
  N3 — Existence des cibles réseau : dpid, ip, profil doivent exister dans la config

Le ML (RandomForest) apprend à distinguer VALIDE/INVALIDE sur des triplets
(intention, outil, paramètres). Les règles déterministes servent de filet
de sécurité quand la confiance ML est insuffisante.

Intégration dans sdn_ai_rétroactif.py :
  Avant chaque appel d'outil par le LLM, on passe par valider_decision().
  Si INVALIDE → on renvoie un feedback au LLM pour qu'il réessaie (max 2 fois).
  
NOTE : La base d'entrainement de ce ML est synthétique et pas suffisante. Elle doit etre optimisée pour de meilleur résultat.
"""

import os
import json
import pickle
import random
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score

# Chemin du modèle sauvegardé
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "validateur_model.pkl"
)

# -----------------------------------------------------------------------
# Constantes réseau — source de vérité pour la validation N3
# -----------------------------------------------------------------------
DPIDS_VALIDES   = {1, 2, 3, 4, 5, 6, 7, 8, 9}
IPS_VALIDES     = {
    "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5",
    "10.0.0.6", "10.0.0.7", "10.0.0.8", "10.0.0.9", "10.0.0.10"
}
PROFILS_VALIDES = {"STANDARD", "MULTIMEDIA", "BRONZE", "GOLD", "SILVER"}
OUTILS_VALIDES  = {
    "manage_link", "set_path_qos",
    "set_network_wide_policy", "set_access_qos", "get_ports_status"
}

# Mapping intention → outil attendu (règle déterministe N1)
OUTIL_ATTENDU = {
    "BREAK":        "manage_link",
    "RESTORE":      "manage_link",
    "QOS": ["set_access_qos", "set_path_qos", "set_network_wide_policy"],
    "NETWORK_WIDE": "set_network_wide_policy",
    "QUERY":        "get_ports_status",
}

# Action technique attendue selon l'intention (règle N2)
ACTION_ATTENDUE = {
    "BREAK":   "break",
    "RESTORE": "restore",
}

# -----------------------------------------------------------------------
# Encodage des features pour le ML
# Toutes les valeurs catégorielles sont encodées en entiers
# -----------------------------------------------------------------------
INTENTIONS_IDX = {
    "BREAK": 0, "RESTORE": 1, "QOS": 2,
    "NETWORK_WIDE": 3, "QUERY": 4, "INCONNU": 5
}
OUTILS_IDX = {
    "manage_link": 0, "set_path_qos": 1,
    "set_network_wide_policy": 2, "get_ports_status": 3, "INCONNU": 4
}
ACTIONS_IDX = {"break": 0, "restore": 1, "apply": 2, "global": 3, "AUCUNE": 4}
PROFILS_IDX = {
    "STANDARD": 0, "MULTIMEDIA": 1, "BRONZE": 2,
    "GOLD": 3, "SILVER": 4, "AUCUN": 5
}


def _encoder(intention: str, outil: str, params: dict) -> list:
    """
    Encode un triplet (intention, outil, params) en vecteur numérique.

    Features :
      [0] intention_idx
      [1] outil_idx
      [2] action_idx          (depuis params["action"] si présent)
      [3] profil_idx          (depuis params["profil"] si présent)
      [4] a_dpid              (1 si params contient dpid, 0 sinon)
      [5] dpid_valide         (1 si dpid dans DPIDS_VALIDES)
      [6] a_ip                (1 si params contient ip_a ou ip)
      [7] ip_valide           (1 si ip dans IPS_VALIDES)
      [8] a_path              (1 si params contient path non vide)
      [9] outil_match_intention (1 si outil correspond à l'intention attendue)
     [10] action_match_intention (1 si action correspond à l'intention)
    """
    intention = intention.upper() if intention else "INCONNU"
    outil     = outil.lower()     if outil     else "INCONNU"

    action = str(params.get("action", "AUCUNE")).lower()
    profil = str(params.get("profil", params.get("profile", "AUCUN"))).upper()
    dpid   = params.get("dpid")
    ip_a   = params.get("ip_a", params.get("ip"))
    ip_b   = params.get("ip_b")
    path   = params.get("path", [])

    # Feature 9 : l'outil correspond-il à l'intention ?
    # OUTIL_ATTENDU peut être une str ou une liste (ex: QOS accepte plusieurs outils)
    outil_attendu = OUTIL_ATTENDU.get(intention, "")
    if isinstance(outil_attendu, list):
        outil_match = 1 if outil in outil_attendu else 0
    else:
        outil_match = 1 if outil == outil_attendu else 0

    # Feature 10 : l'action correspond-elle à l'intention ?
    action_attendue   = ACTION_ATTENDUE.get(intention, "")
    action_match      = 1 if (not action_attendue or action == action_attendue) else 0

    # Feature dpid
    a_dpid     = 1 if dpid is not None else 0
    dpid_valid = 0
    if dpid is not None:
        try:
            dpid_valid = 1 if int(str(dpid).replace("s","")) in DPIDS_VALIDES else 0
        except (ValueError, TypeError):
            dpid_valid = 0

    # Feature ip
    a_ip     = 1 if (ip_a or ip_b) else 0
    ip_valid = 0
    if ip_a:
        ip_valid = 1 if str(ip_a) in IPS_VALIDES else 0
    elif ip_b:
        ip_valid = 1 if str(ip_b) in IPS_VALIDES else 0

    # Feature path
    a_path = 1 if (isinstance(path, list) and len(path) > 0) else 0

    return [
        INTENTIONS_IDX.get(intention, 5),
        OUTILS_IDX.get(outil, 4),
        ACTIONS_IDX.get(action, 4),
        PROFILS_IDX.get(profil, 5),
        a_dpid,
        dpid_valid,
        a_ip,
        ip_valid,
        a_path,
        outil_match,
        action_match,
    ]


# -----------------------------------------------------------------------
# Dataset d'entraînement
# Format : (intention, outil, params, label)
# label : 1 = VALIDE, 0 = INVALIDE
# -----------------------------------------------------------------------

def _generer_dataset():
    """Génère ~300 exemples couvrant tous les cas valides et invalides."""
    data = []

    # Valeurs de test
    dpids_ok    = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    dpids_ko    = [0, 10, 99, -1]
    ips_ok      = ["10.0.0.1","10.0.0.2","10.0.0.3","10.0.0.4","10.0.0.5",
                   "10.0.0.6","10.0.0.7","10.0.0.8","10.0.0.9","10.0.0.10"]
    ips_ko      = ["192.168.1.1","172.16.0.1","10.0.1.1","8.8.8.8"]
    profils_ok  = ["GOLD","SILVER","BRONZE","MULTIMEDIA","STANDARD"]
    profils_ko  = ["ULTRA","VIP","PREMIUM","NONE",""]
    paths_ok    = [[1,7,2],[1,7,8,9,4],[4,9,5],[2,7,3]]
    paths_ko    = [[],[99,100],[None]]

    # -------------------------------------------------------------------
    # VALIDES — BREAK correct
    # -------------------------------------------------------------------
    for dpid in dpids_ok:
        for port in [1, 2, 3, 4]:
            data.append(("BREAK", "manage_link",
                {"action": "break", "dpid": dpid, "port": port}, 1))

    # VALIDES — RESTORE correct
    for dpid in dpids_ok:
        for port in [1, 2]:
            data.append(("RESTORE", "manage_link",
                {"action": "restore", "dpid": dpid, "port": port}, 1))

    # VALIDES — QOS correct (set_path_qos)
    for profil in profils_ok:
        for path in paths_ok:
            for i in range(len(ips_ok) - 1):
                data.append(("QOS", "set_path_qos",
                    {"path": path, "ip_a": ips_ok[i],
                     "ip_b": ips_ok[i+1], "profil": profil}, 1))

    # VALIDES — QOS correct (set_access_qos — outil principal)
    for profil in profils_ok:
        for i in range(len(ips_ok) - 1):
            data.append(("QOS", "set_access_qos",
                {"ip_a": ips_ok[i], "ip_b": ips_ok[i+1], "profil": profil}, 1))

    # VALIDES — QOS correct (set_network_wide_policy depuis QOS)
    for profil in profils_ok:
        data.append(("QOS", "set_network_wide_policy", {"profile": profil}, 1))

    # VALIDES — NETWORK_WIDE correct
    for profil in profils_ok:
        data.append(("NETWORK_WIDE", "set_network_wide_policy",
            {"profile": profil}, 1))
        data.append(("NETWORK_WIDE", "set_network_wide_policy",
            {"profil": profil}, 1))

    # VALIDES — QUERY correct
    for _ in range(8):
        data.append(("QUERY", "get_ports_status", {}, 1))

    # -------------------------------------------------------------------
    # INVALIDES — mauvais outil pour l'intention
    # -------------------------------------------------------------------
    for outil_ko in ["set_path_qos", "set_network_wide_policy", "get_ports_status"]:
        for dpid in random.sample(dpids_ok, 3):
            data.append(("BREAK", outil_ko,
                {"dpid": dpid, "port": 1}, 0))
            data.append(("RESTORE", outil_ko,
                {"dpid": dpid, "port": 1}, 0))

    # Outils invalides pour QOS (manage_link, get_ports_status)
    # Note: set_network_wide_policy EST valide pour QOS selon OUTIL_ATTENDU
    for outil_ko in ["manage_link", "get_ports_status"]:
        for profil in random.sample(profils_ok, 2):
            data.append(("QOS", outil_ko,
                {"path": [1,7], "ip_a": "10.0.0.1",
                 "ip_b": "10.0.0.2", "profil": profil}, 0))

    for outil_ko in ["manage_link", "set_path_qos", "get_ports_status"]:
        for profil in random.sample(profils_ok, 2):
            data.append(("NETWORK_WIDE", outil_ko,
                {"profile": profil}, 0))

    # -------------------------------------------------------------------
    # INVALIDES — mauvaise action technique
    # -------------------------------------------------------------------
    for dpid in random.sample(dpids_ok, 5):
        # BREAK avec action restore
        data.append(("BREAK", "manage_link",
            {"action": "restore", "dpid": dpid, "port": 1}, 0))
        # RESTORE avec action break
        data.append(("RESTORE", "manage_link",
            {"action": "break", "dpid": dpid, "port": 1}, 0))
        # BREAK sans action
        data.append(("BREAK", "manage_link",
            {"dpid": dpid, "port": 1}, 0))

    # -------------------------------------------------------------------
    # INVALIDES — dpid hors réseau
    # -------------------------------------------------------------------
    for dpid in dpids_ko:
        data.append(("BREAK", "manage_link",
            {"action": "break", "dpid": dpid, "port": 1}, 0))
        data.append(("RESTORE", "manage_link",
            {"action": "restore", "dpid": dpid, "port": 1}, 0))

    # -------------------------------------------------------------------
    # INVALIDES — IP hors réseau pour QOS
    # -------------------------------------------------------------------
    for ip_ko in ips_ko:
        for profil in random.sample(profils_ok, 2):
            data.append(("QOS", "set_path_qos",
                {"path": [1,7,2], "ip_a": ip_ko,
                 "ip_b": "10.0.0.1", "profil": profil}, 0))
            data.append(("QOS", "set_path_qos",
                {"path": [1,7,2], "ip_a": "10.0.0.1",
                 "ip_b": ip_ko, "profil": profil}, 0))

    # -------------------------------------------------------------------
    # INVALIDES — profil inconnu
    # -------------------------------------------------------------------
    for profil_ko in profils_ko:
        data.append(("QOS", "set_path_qos",
            {"path": [1,7], "ip_a": "10.0.0.1",
             "ip_b": "10.0.0.2", "profil": profil_ko}, 0))
        data.append(("NETWORK_WIDE", "set_network_wide_policy",
            {"profile": profil_ko}, 0))

    # -------------------------------------------------------------------
    # INVALIDES — path vide ou absurde pour QOS
    # -------------------------------------------------------------------
    for path_ko in paths_ko:
        for profil in random.sample(profils_ok, 2):
            data.append(("QOS", "set_path_qos",
                {"path": path_ko, "ip_a": "10.0.0.1",
                 "ip_b": "10.0.0.2", "profil": profil}, 0))

    # -------------------------------------------------------------------
    # INVALIDES — paramètres manquants critiques
    # -------------------------------------------------------------------
    # manage_link sans dpid
    for _ in range(6):
        data.append(("BREAK", "manage_link",
            {"action": "break", "port": 1}, 0))
    # set_path_qos sans ip
    for profil in profils_ok:
        data.append(("QOS", "set_path_qos",
            {"path": [1,7,2], "profil": profil}, 0))
    # set_path_qos sans path
    for profil in profils_ok:
        data.append(("QOS", "set_path_qos",
            {"ip_a": "10.0.0.1", "ip_b": "10.0.0.2", "profil": profil}, 0))
    # set_network_wide_policy sans profil
    for _ in range(5):
        data.append(("NETWORK_WIDE", "set_network_wide_policy", {}, 0))

    random.shuffle(data)
    return data


# -----------------------------------------------------------------------
# Modèle ML
# -----------------------------------------------------------------------

class ValidateurPolitique:
    """
    Validateur ML de politique SDN.

    Usage :
        val = ValidateurPolitique()
        result = val.valider(intention, outil, params)
        # result = {
        #   "valide": True/False,
        #   "confiance": 0.92,
        #   "raison": "...",        # si invalide
        #   "niveau_echec": "N1/N2/N3"
        # }
    """

    CONFIANCE_MIN = 0.60   # En dessous → on bascule sur les règles déterministes

    def __init__(self):
        self.modele  = None
        self.classes = None
        if os.path.exists(MODEL_PATH):
            self._charger()
        else:
            print("[VALIDATEUR] Premier lancement — entraînement...")
            self.entrainer()
            print("[VALIDATEUR] Modèle prêt.")

    # -------------------------------------------------------------------
    # API principale
    # -------------------------------------------------------------------

    def valider(self, intention: str, outil: str, params: dict) -> dict:
        """
        Valide une décision du LLM avant exécution.

        Returns:
            dict avec les clés :
              - valide      : bool
              - confiance   : float (0-1)
              - raison      : str (explication si invalide)
              - niveau_echec: "N1", "N2", "N3" ou None
              - suggestion  : str (correction proposée si invalide)
        """
        # Règles déterministes — toujours prioritaires (N1, N2, N3)
        regle = self._verifier_regles(intention, outil, params)
        if regle is not None:
            return regle   # Violation certaine détectée par règle

        # Prédiction ML pour les cas ambigus
        features   = _encoder(intention, outil, params)
        probas     = self.modele.predict_proba([features])[0]
        idx_valide = list(self.classes).index(1)
        confiance  = float(probas[idx_valide])

        if confiance >= self.CONFIANCE_MIN:
            return {
                "valide":       True,
                "confiance":    round(confiance, 3),
                "raison":       None,
                "niveau_echec": None,
                "suggestion":   None
            }
        else:
            return {
                "valide":       False,
                "confiance":    round(confiance, 3),
                "raison":       (
                    f"Le modèle ML n'est pas confiant ({confiance:.0%}) "
                    f"que '{outil}' est le bon outil pour l'intention '{intention}'."
                ),
                "niveau_echec": "ML",
                "suggestion":   self._suggerer_correction(intention, params)
            }

    # -------------------------------------------------------------------
    # Règles déterministes (N1, N2, N3)
    # -------------------------------------------------------------------

    def _verifier_regles(self, intention: str, outil: str,
                          params: dict) -> dict | None:
        """
        Vérifie les trois niveaux de règles.
        Retourne un dict d'erreur si violation, None si tout est OK.
        """
        intention = (intention or "").upper()
        outil     = (outil     or "").lower()

        # --- N1 : Outil correct pour l'intention ---
        # OUTIL_ATTENDU peut être une str ou une liste (ex: QOS a plusieurs outils valides)
        outil_attendu = OUTIL_ATTENDU.get(intention)
        if outil_attendu:
            outils_ok = outil_attendu if isinstance(outil_attendu, list) else [outil_attendu]
            if outil not in outils_ok:
                outils_ok_str = ", ".join(f"'{o}'" for o in outils_ok)
                return {
                    "valide":       False,
                    "confiance":    1.0,
                    "raison":       (
                        f"N1 — Outil incorrect : intention '{intention}' "
                        f"requiert {outils_ok_str}, "
                        f"reçu '{outil}'."
                    ),
                    "niveau_echec": "N1",
                    "suggestion":   self._suggerer_correction(intention, params)
                }

        # --- N2 : Paramètres cohérents avec l'intention ---
        if intention in ["BREAK", "RESTORE"]:
            action_recue = str(params.get("action", "")).lower()
            action_att   = ACTION_ATTENDUE.get(intention, "")
            if not action_recue:
                return {
                    "valide":       False,
                    "confiance":    1.0,
                    "raison":       (
                        f"N2 — Paramètre manquant : 'action' est requis "
                        f"pour manage_link (attendu : '{action_att}')."
                    ),
                    "niveau_echec": "N2",
                    "suggestion":   (
                        f"Appelle manage_link avec action='{action_att}', "
                        f"dpid=<dpid>, port=<port>."
                    )
                }
            if action_recue != action_att:
                return {
                    "valide":       False,
                    "confiance":    1.0,
                    "raison":       (
                        f"N2 — Action incohérente : intention '{intention}' "
                        f"requiert action='{action_att}', "
                        f"reçu action='{action_recue}'."
                    ),
                    "niveau_echec": "N2",
                    "suggestion":   (
                        f"Corrige action='{action_att}' dans manage_link."
                    )
                }

        if intention == "QOS":
            if not params.get("ip_a") or not params.get("ip_b"):
                return {
                    "valide":       False,
                    "confiance":    1.0,
                    "raison":       (
                        "N2 — Paramètres manquants : "
                        "set_path_qos requiert ip_a ET ip_b."
                    ),
                    "niveau_echec": "N2",
                    "suggestion":   (
                        "Récupère les IPs des hôtes depuis le manifeste "
                        "technical_targets.ips avant d'appeler set_path_qos."
                    )
                }
            path = params.get("path", [])
            if not isinstance(path, list) or len(path) == 0:
                return {
                    "valide":       False,
                    "confiance":    1.0,
                    "raison":       (
                        "N2 — Paramètre manquant : "
                        "set_path_qos requiert un path non vide."
                    ),
                    "niveau_echec": "N2",
                    "suggestion":   (
                        "Récupère le chemin depuis manifeste.routing.path."
                    )
                }

        if intention == "NETWORK_WIDE":
            profil = params.get("profile", params.get("profil", ""))
            if not profil:
                return {
                    "valide":       False,
                    "confiance":    1.0,
                    "raison":       (
                        "N2 — Paramètre manquant : "
                        "set_network_wide_policy requiert un profil."
                    ),
                    "niveau_echec": "N2",
                    "suggestion":   (
                        "Récupère le profil depuis manifeste.qos_specs.profile_name."
                    )
                }

        # --- N3 : Existence des cibles dans le réseau ---
        dpid = params.get("dpid")
        if dpid is not None:
            try:
                dpid_int = int(str(dpid).replace("s", ""))
                if dpid_int not in DPIDS_VALIDES:
                    return {
                        "valide":       False,
                        "confiance":    1.0,
                        "raison":       (
                            f"N3 — DPID '{dpid}' inexistant dans le réseau. "
                            f"DPIDs valides : {sorted(DPIDS_VALIDES)}."
                        ),
                        "niveau_echec": "N3",
                        "suggestion":   (
                            "Récupère le dpid depuis manifeste."
                            "technical_targets.nodes[0].dpid."
                        )
                    }
            except (ValueError, TypeError):
                return {
                    "valide":       False,
                    "confiance":    1.0,
                    "raison":       f"N3 — DPID '{dpid}' n'est pas un entier valide.",
                    "niveau_echec": "N3",
                    "suggestion":   "Le dpid doit être un entier (ex: 1, 2, 3...)."
                }

        for ip_key in ["ip_a", "ip_b", "ip"]:
            ip = params.get(ip_key)
            if ip and str(ip) not in IPS_VALIDES:
                return {
                    "valide":       False,
                    "confiance":    1.0,
                    "raison":       (
                        f"N3 — IP '{ip}' inconnue dans le réseau. "
                        f"Vérifie technical_targets.ips."
                    ),
                    "niveau_echec": "N3",
                    "suggestion":   (
                        "Utilise uniquement les IPs du manifeste "
                        "technical_targets.ips."
                    )
                }

        profil = params.get("profil", params.get("profile", ""))
        if profil and str(profil).upper() not in PROFILS_VALIDES and \
                str(profil).upper() != "AUCUN":
            return {
                "valide":       False,
                "confiance":    1.0,
                "raison":       (
                    f"N3 — Profil '{profil}' inconnu. "
                    f"Profils valides : {PROFILS_VALIDES}."
                ),
                "niveau_echec": "N3",
                "suggestion":   (
                    "Récupère le profil depuis manifeste.qos_specs.profile_name."
                )
            }

        return None   # Toutes les règles passées → pas de violation certaine

    def _suggerer_correction(self, intention: str, params: dict) -> str:
        """Génère un message de correction adapté à l'intention."""
        outil = OUTIL_ATTENDU.get(intention.upper(), "l'outil approprié")
        suggestions = {
            "BREAK":        (
                f"Appelle manage_link(dpid=<dpid>, port=<port>, action='break'). "
                f"Récupère dpid et port depuis manifeste.technical_targets.nodes."
            ),
            "RESTORE":      (
                f"Appelle manage_link(dpid=<dpid>, port=<port>, action='restore'). "
                f"Récupère dpid et port depuis manifeste.technical_targets.nodes."
            ),
            "QOS":          (
                f"Appelle set_path_qos(path=<path>, ip_a=<ip_a>, ip_b=<ip_b>, "
                f"profil=<profil>). "
                f"Récupère toutes ces valeurs depuis le manifeste."
            ),
            "NETWORK_WIDE": (
                f"Appelle set_network_wide_policy(profile=<profil>). "
                f"Récupère le profil depuis manifeste.qos_specs.profile_name."
            ),
        }
        return suggestions.get(
            intention.upper(),
            f"Utilise {outil} avec les paramètres du manifeste."
        )

    # -------------------------------------------------------------------
    # Entraînement ML
    # -------------------------------------------------------------------

    def entrainer(self, verbose=True):
        dataset = _generer_dataset()
        X = [_encoder(d[0], d[1], d[2]) for d in dataset]
        y = [d[3] for d in dataset]

        self.modele = RandomForestClassifier(
            n_estimators=100,
            max_depth=8,
            random_state=42,
            class_weight="balanced"
        )
        self.modele.fit(X, y)
        self.classes = self.modele.classes_

        if verbose:
            scores = cross_val_score(
                self.modele, X, y, cv=5, scoring="accuracy"
            )
            valides   = sum(1 for d in dataset if d[3] == 1)
            invalides = sum(1 for d in dataset if d[3] == 0)
            print(
                f"[VALIDATEUR] Dataset : {len(dataset)} exemples "
                f"({valides} valides, {invalides} invalides)"
            )
            print(
                f"[VALIDATEUR] Accuracy : "
                f"{scores.mean():.2%} ± {scores.std():.2%}"
            )
        self._sauvegarder()

    # -------------------------------------------------------------------
    # Persistance
    # -------------------------------------------------------------------

    def _sauvegarder(self):
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(
                {"modele": self.modele, "classes": self.classes}, f
            )

    def _charger(self):
        try:
            with open(MODEL_PATH, "rb") as f:
                data = pickle.load(f)
            self.modele  = data["modele"]
            self.classes = data["classes"]
        except Exception as e:
            print(f"[VALIDATEUR] Erreur chargement : {e} — réentraînement...")
            self.entrainer()

    def reinitialiser(self):
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
        self.entrainer()


# Singleton
_instance = None

def get_validateur() -> ValidateurPolitique:
    global _instance
    if _instance is None:
        _instance = ValidateurPolitique()
    return _instance


