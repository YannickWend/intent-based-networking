"""
Control/seuil_agent.py

Agent Q-Learning DOUBLE rôle :

  RÔLE 1 — Ajustement dynamique des seuils d'alerte débit
    État   : (profil_qos, niveau_débit_relatif)
    Action : monter / garder / baisser le seuil de 10%
    Reward : +0.5 si stable, -1.0 si violations répétées (faux positifs)

  RÔLE 2 — Choix automatique du profil QoS selon la charge réseau
    État   : niveau de charge global du réseau (BAS / MOYEN / ELEVE)
    Action : choisir un profil (GOLD / STANDARD / BRONZE / MULTIMEDIA)
    Reward : +1 si la charge baisse après application,
             -1 si la charge monte ou reste critique

Les deux rôles partagent le même fichier de persistance (qtable_seuils.json)
mais utilisent des espaces d'état/action séparés dans la Q-table.

Intégration :
  - debit_analyser.py  → get_seuil(profile) pour les seuils dynamiques
  - mission_watcheur.py → get_profil_auto(debit_global, scope) pour le choix auto
"""

import os
import json
import random
from datetime import datetime, time as dtime

QTABLE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "qtable_seuils.json"
)

# -----------------------------------------------------------------------
# Hyperparamètres Q-Learning (communs aux deux rôles)
# -----------------------------------------------------------------------
ALPHA   = 0.1    # Taux d'apprentissage
GAMMA   = 0.9    # Discount des récompenses futures
EPSILON = 0.15   # Taux d'exploration (15% d'actions aléatoires)

# -----------------------------------------------------------------------
# RÔLE 1 — Seuils dynamiques
# -----------------------------------------------------------------------
ACTIONS_SEUIL  = [0, 1, 2]           # 0=baisser, 1=garder, 2=monter
DELTA_SEUIL    = {0: -0.10, 1: 0.0, 2: +0.10}

SEUILS_INITIAUX = {
    "MULTIMEDIA": 4.25,   # 85% de 5 Mbps
    "BRONZE":     1.80,   # 90% de 2 Mbps
}
SEUILS_MIN = {"MULTIMEDIA": 1.0, "BRONZE": 0.5}
SEUILS_MAX = {"MULTIMEDIA": 5.0, "BRONZE": 2.0}

# -----------------------------------------------------------------------
# RÔLE 2 — Choix automatique de profil
# -----------------------------------------------------------------------
# Profils que l'agent peut choisir automatiquement
PROFILS_AUTO = ["GOLD", "STANDARD", "BRONZE", "MULTIMEDIA"]

# Seuils de charge réseau pour discrétiser l'état (en Mbps moyen)
# Ces valeurs correspondent à ton réseau : liens access à 30 Mbps
CHARGE_BAS    = 5.0    # < 5 Mbps  → réseau peu chargé
CHARGE_MOYEN  = 15.0   # < 15 Mbps → charge normale
                        # >= 15 Mbps → réseau congestionné

# Mapping intuitif charge → profil recommandé (point de départ de l'agent)
# L'agent peut dévier de ça s'il apprend que c'est sous-optimal
PROFIL_PAR_DEFAUT_CHARGE = {
    "BAS":   "GOLD",       # Peu de trafic → profite de la disponibilité
    "MOYEN": "STANDARD",   # Charge normale → mode équilibré
    "ELEVE": "BRONZE",     # Congestion → limiter pour protéger
}


def _discretiser_debit_relatif(debit: float, plafond: float) -> str:
    """Discrétise un débit en BAS/MOYEN/HAUT par rapport à un plafond."""
    ratio = debit / plafond if plafond > 0 else 0
    if ratio < 0.5:   return "BAS"
    if ratio < 0.85:  return "MOYEN"
    return "HAUT"


def _discretiser_charge_globale(debit_moyen_mbps: float) -> str:
    """Discrétise la charge globale du réseau en BAS/MOYEN/ELEVE."""
    if debit_moyen_mbps < CHARGE_BAS:    return "BAS"
    if debit_moyen_mbps < CHARGE_MOYEN:  return "MOYEN"
    return "ELEVE"


class SeuilAgent:
    """
    Agent Q-Learning double rôle pour l'optimisation QoS autonome.

    Usage :
        agent = SeuilAgent()

        # Rôle 1 : seuil dynamique
        seuil = agent.get_seuil("BRONZE")
        agent.apprendre_seuil("BRONZE", debit_obs, violation_repetee)

        # Rôle 2 : choix auto de profil
        profil = agent.get_profil_auto(debit_moyen, scope="global")
        agent.apprendre_profil(debit_avant, debit_apres, profil_applique, scope)
    """

    def __init__(self):
        self.seuils    = dict(SEUILS_INITIAUX)
        self.q_table   = {}
        self.historique_violations = {}
        # Mémorise le dernier état/action par scope pour l'apprentissage différé
        self._last_profil_state = {}
        self._charger()

    # ===================================================================
    # RÔLE 1 — Seuils dynamiques
    # ===================================================================

    def get_seuil(self, profile: str):
        """
        Retourne le seuil d'alerte courant pour un profil à plafond.
        Retourne None pour GOLD, SILVER, STANDARD (pas de plafond débit).
        """
        return self.seuils.get(profile.upper(), None)

    def apprendre_seuil(self, profile: str, debit_observe: float,
                        violation_repetee: bool):
        """
        Met à jour la Q-table des seuils et ajuste le seuil si nécessaire.

        Args:
            profile          : "BRONZE" ou "MULTIMEDIA"
            debit_observe    : débit mesuré en Mbps
            violation_repetee: True si cette violation a déjà été signalée
                               dans les 2+ derniers cycles (faux positif)
        """
        profile = profile.upper()
        if profile not in self.seuils:
            return

        seuil_actuel = self.seuils[profile]
        etat         = _discretiser_debit_relatif(debit_observe, seuil_actuel)
        namespace    = f"SEUIL_{profile}"

        action     = self._choisir_action(namespace, etat, ACTIONS_SEUIL)
        recompense = self._recompense_seuil(profile, violation_repetee)
        self._update_q(namespace, etat, action, recompense, ACTIONS_SEUIL)

        # Application du delta
        nouveau = seuil_actuel * (1 + DELTA_SEUIL[action])
        nouveau = round(
            max(SEUILS_MIN[profile], min(SEUILS_MAX[profile], nouveau)), 3
        )

        if nouveau != seuil_actuel:
            symbole = "↓" if action == 0 else ("↑" if action == 2 else "=")
            print(
                f"[Q-AGENT SEUIL] {profile} : "
                f"{seuil_actuel:.2f} → {nouveau:.2f} Mbps "
                f"(action={symbole}, reward={recompense:+.1f})"
            )
            self.seuils[profile] = nouveau

        self.historique_violations.setdefault(profile, 0)
        if violation_repetee:
            self.historique_violations[profile] += 1
        else:
            self.historique_violations[profile] = max(
                0, self.historique_violations[profile] - 1
            )

        self._sauvegarder()

    # ===================================================================
    # RÔLE 2 — Choix automatique de profil QoS
    # ===================================================================

    def get_profil_auto(self, debit_moyen_mbps: float,
                        scope: str = "global") -> str:
        """
        Choisit automatiquement le profil QoS le plus adapté
        selon la charge réseau observée.

        Args:
            debit_moyen_mbps : débit moyen observé sur le scope concerné
            scope            : "global" (NETWORK_WIDE) ou "path" (QOS ciblé)

        Returns:
            Nom du profil recommandé (str)
        """
        etat      = _discretiser_charge_globale(debit_moyen_mbps)
        namespace = f"PROFIL_{scope.upper()}"

        # Indices des actions = indices dans PROFILS_AUTO
        action_idx = self._choisir_action(
            namespace, etat, list(range(len(PROFILS_AUTO)))
        )
        profil_choisi = PROFILS_AUTO[action_idx]

        # Mémoriser pour l'apprentissage différé
        self._last_profil_state[scope] = {
            "namespace":   namespace,
            "etat":        etat,
            "action":      action_idx,
            "debit_avant": debit_moyen_mbps,
            "profil":      profil_choisi
        }

        print(
            f"[Q-AGENT PROFIL] Charge {etat} ({debit_moyen_mbps:.1f} Mbps) "
            f"→ profil recommandé : {profil_choisi} (scope={scope})"
        )
        return profil_choisi

    def apprendre_profil(self, debit_apres_mbps: float, scope: str = "global"):
        """
        Apprentissage différé : appelé après avoir appliqué le profil
        et observé l'effet sur le réseau (cycle suivant).

        Args:
            debit_apres_mbps : débit observé APRÈS application du profil
            scope            : même scope que lors du get_profil_auto()
        """
        ctx = self._last_profil_state.get(scope)
        if not ctx:
            return  # Pas de décision précédente à évaluer

        debit_avant = ctx["debit_avant"]
        namespace   = ctx["namespace"]
        etat        = ctx["etat"]
        action      = ctx["action"]

        # Récompense : est-ce que la charge a baissé ?
        delta = debit_avant - debit_apres_mbps
        if delta > 2.0:
            recompense = +1.0   # Nette amélioration
        elif delta > 0:
            recompense = +0.3   # Légère amélioration
        elif delta > -2.0:
            recompense = -0.3   # Légère dégradation
        else:
            recompense = -1.0   # La situation a empiré

        self._update_q(namespace, etat, action, recompense,
                       list(range(len(PROFILS_AUTO))))

        print(
            f"[Q-AGENT PROFIL] Apprentissage scope={scope} : "
            f"débit {debit_avant:.1f}→{debit_apres_mbps:.1f} Mbps "
            f"| reward={recompense:+.1f}"
        )

        # Effacer le contexte pour éviter un double apprentissage
        del self._last_profil_state[scope]
        self._sauvegarder()

    # ===================================================================
    # Helpers Q-Learning communs
    # ===================================================================

    def _choisir_action(self, namespace: str, etat: str,
                        actions: list) -> int:
        """Epsilon-greedy sur n'importe quel espace d'actions."""
        if random.random() < EPSILON:
            return random.choice(actions)
        q_vals = [
            self.q_table.get((namespace, etat, a), 0.0) for a in actions
        ]
        return actions[q_vals.index(max(q_vals))]

    def _update_q(self, namespace: str, etat: str, action: int,
                  recompense: float, actions: list):
        """Mise à jour Q(s,a) — équation de Bellman."""
        key      = (namespace, etat, action)
        q_actuel = self.q_table.get(key, 0.0)
        q_next   = max(
            self.q_table.get((namespace, etat, a), 0.0) for a in actions
        )
        self.q_table[key] = round(
            q_actuel + ALPHA * (recompense + GAMMA * q_next - q_actuel), 4
        )

    def _recompense_seuil(self, profile: str, violation_repetee: bool) -> float:
        nb_rep = self.historique_violations.get(profile, 0)
        if violation_repetee and nb_rep >= 2:
            return -1.0
        elif not violation_repetee:
            return +0.5
        return 0.0

    def rapport(self) -> dict:
        """Résumé lisible de l'état de l'agent."""
        return {
            "timestamp":      datetime.now().isoformat(),
            "seuils_actifs":  dict(self.seuils),
            "seuils_defaut":  dict(SEUILS_INITIAUX),
            "derives_seuils": {
                p: round(self.seuils[p] - SEUILS_INITIAUX[p], 3)
                for p in self.seuils
            },
            "q_table_size":   len(self.q_table),
        }

    # ===================================================================
    # Persistance
    # ===================================================================

    def _sauvegarder(self):
        try:
            data = {
                "seuils":     self.seuils,
                "q_table":    {str(k): v for k, v in self.q_table.items()},
                "historique": self.historique_violations
            }
            with open(QTABLE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Q-AGENT] Erreur sauvegarde : {e}")

    def _charger(self):
        if not os.path.exists(QTABLE_PATH):
            return
        try:
            with open(QTABLE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.seuils    = data.get("seuils", dict(SEUILS_INITIAUX))
            self.historique_violations = data.get("historique", {})
            for k_str, v in data.get("q_table", {}).items():
                try:
                    self.q_table[eval(k_str)] = v
                except Exception:
                    pass
            print(f"[Q-AGENT] Chargé ({len(self.q_table)} entrées Q-table).")
        except Exception as e:
            print(f"[Q-AGENT] Erreur chargement : {e} — démarrage à zéro.")

    def reinitialiser(self):
        """Repart de zéro — utile pour les tests."""
        if os.path.exists(QTABLE_PATH):
            os.remove(QTABLE_PATH)
        self.__init__()


# -----------------------------------------------------------------------
# Singleton global
# -----------------------------------------------------------------------
_agent_instance = None

def get_agent() -> SeuilAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SeuilAgent()
    return _agent_instance

def get_seuil(profile: str):
    """Raccourci Rôle 1 — seuil dynamique."""
    return get_agent().get_seuil(profile)

def get_profil_auto(debit_moyen_mbps: float, scope: str = "global") -> str:
    """Raccourci Rôle 2 — choix automatique de profil."""
    return get_agent().get_profil_auto(debit_moyen_mbps, scope)
