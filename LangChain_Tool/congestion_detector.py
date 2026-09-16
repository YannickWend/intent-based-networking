"""
congestion_detector.py — Dataset recalibré aux vraies capacités Mininet
Fix : s1 bridé à ~100 Mbps effectif (pas 900), seuils ajustés
On abandonne aussi tx_dropped (toujours 0 dans Ryu de base)
→ features réduites à 3 par switch : tx_mbps, rx_mbps, utilisation
→ 9 switches × 3 = 27 features
"""

import numpy as np
import pickle
import os
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

MODEL_PATH = os.path.join(os.path.dirname(__file__), "congestion_model.pkl")

NORMAL        = 0
CHARGE_ELEVEE = 1
CONGESTION    = 2
LABEL_NOMS    = {0: "NORMAL", 1: "CHARGE_ELEVEE", 2: "CONGESTION"}

# Capacités EFFECTIVES observées en pratique sur le réseau Mininet
# (pas les limites théoriques OVS, mais ce qu'on mesure vraiment)
CAP_EFFECTIVE = {
    "s1": 70,
    "s2": 45,
    "s3": 45,
    "s4": 30,
    "s5": 30,
    "s6": 30,
    "s7": 70,
    "s8": 45,
    "s9": 45,
}
SWITCHES = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"]


def _generer_dataset(n_samples: int = 900) -> tuple:
    rng = np.random.default_rng(42)
    X, y = [], []
    n_par_classe = n_samples // 3

    # NORMAL : tous les switches sous 30% de leur capacité
    for _ in range(n_par_classe):
        features = []
        for sw in SWITCHES:
            c  = CAP_EFFECTIVE[sw]
            tx = rng.uniform(0, c * 0.30)
            features += [round(tx, 2), round(tx * 0.9, 2), round(tx / c, 3)]
        X.append(features); y.append(NORMAL)

    # CHARGE_ELEVEE : backbone entre 40-75%, accès entre 20-60%
    for _ in range(n_par_classe):
        features = []
        for sw in SWITCHES:
            c  = CAP_EFFECTIVE[sw]
            is_bb = sw in ("s7", "s8", "s9")
            if is_bb:
                tx = rng.uniform(c * 0.40, c * 0.75)
            else:
                tx = rng.uniform(c * 0.20, c * 0.60)
            features += [round(tx, 2), round(tx * 0.85, 2), round(tx / c, 3)]
        X.append(features); y.append(CHARGE_ELEVEE)

    # CONGESTION : backbone > 75%, accès > 60%
    for _ in range(n_par_classe):
        features = []
        for sw in SWITCHES:
            c  = CAP_EFFECTIVE[sw]
            is_bb = sw in ("s7", "s8", "s9")
            if is_bb:
                tx = rng.uniform(c * 0.75, c * 1.0)
            else:
                tx = rng.uniform(c * 0.60, c * 1.0)
            features += [round(tx, 2), round(tx * 0.9, 2), round(min(tx / c, 1.0), 3)]
        X.append(features); y.append(CONGESTION)

    return np.array(X), np.array(y)


class CongestionDetector:
    def __init__(self):
        self.model    = None
        self.entrainé = False

    def entrainer(self, verbose=True) -> dict:
        if verbose:
            print("🔧 [ML] Génération dataset recalibré...")
        X, y = _generer_dataset(900)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y)

        self.model = RandomForestClassifier(
            n_estimators=150, max_depth=10,
            min_samples_leaf=2, random_state=42, n_jobs=-1)
        self.model.fit(X_train, y_train)
        self.entrainé = True

        y_pred   = self.model.predict(X_test)
        accuracy = (y_pred == y_test).mean()
        rapport  = classification_report(
            y_test, y_pred,
            target_names=["NORMAL", "CHARGE_ELEVEE", "CONGESTION"])

        with open(MODEL_PATH, "wb") as f:
            pickle.dump(self.model, f)

        if verbose:
            print(f" [ML] Accuracy : {accuracy:.1%}")
            print(rapport)
            print(f" Modèle sauvegardé : {MODEL_PATH}")
        return {"accuracy": accuracy, "rapport": rapport}

    def charger(self) -> bool:
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                self.model = pickle.load(f)
            self.entrainé = True
            return True
        return False

    def predire(self, snapshot: dict) -> dict:
        if not self.entrainé:
            if not self.charger():
                return {
                    "label": "NORMAL",
                    "code": 0,
                    "confiance": 0.0,
                    "zone": "normal",
                    "details": {}
                }

        features = self._snapshot_vers_features(snapshot)
        if features is None:
            return {
                "label": "NORMAL",
                "code": 0,
                "confiance": 0.0,
                "zone": "normal",
                "details": {}
            }

        X = np.array(features).reshape(1, -1)

        code = int(self.model.predict(X)[0])
        label = LABEL_NOMS[code]

        probas = self.model.predict_proba(X)[0]
        confiance = float(probas[code])

        zone = self._detecter_zone(snapshot)

        details = {
            f"s{k}": round(v.get("utilisation", 0.0), 2)
            for k, v in snapshot.get("switches", {}).items()
        }

        if details:
            max_switch = max(details, key=details.get)
            max_util = details[max_switch]

            if max_util >= 0.90 and label == "NORMAL":
                label = "CONGESTION"
                code = 2
                confiance = max(confiance, 0.90)
                zone = "backbone" if max_switch in ["s7", "s8", "s9"] else "access"

            elif max_util >= 0.75 and label == "NORMAL":
                label = "CHARGE_ELEVEE"
                code = 1
                confiance = max(confiance, 0.80)
                zone = "backbone" if max_switch in ["s7", "s8", "s9"] else "access"

        return {
            "label": label,
            "code": code,
            "confiance": round(confiance, 3),
            "zone": zone,
            "details": details,
        }

    def _snapshot_vers_features(self, snapshot: dict):
        try:
            sw_data = snapshot.get("switches", {})
            features = []
            for sw_num in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
                sw = sw_data.get(sw_num, {})
                features += [
                    float(sw.get("tx_mbps",    0)),
                    float(sw.get("rx_mbps",    0)),
                    float(sw.get("utilisation", 0)),
                ]
            return features
        except Exception as e:
            print(f"[CongestionDetector] Erreur features : {e}")
            return None

    def _detecter_zone(self, snapshot: dict) -> str:
        sw = snapshot.get("switches", {})
        bb_sat = any(sw.get(s, {}).get("utilisation", 0) > 0.70
                     for s in ["7", "8", "9"])
        ac_sat = any(sw.get(s, {}).get("utilisation", 0) > 0.75
                     for s in ["1", "2", "3", "4", "5", "6"])
        if bb_sat and ac_sat: return "global"
        if bb_sat:            return "backbone"
        if ac_sat:            return "access"
        return "normal"

"""
if __name__ == "__main__":
    print("=" * 60)
    print("🔧 DEBUG - CongestionDetector")
    print("=" * 60)
    
    detector = CongestionDetector()
    
    # Test 1: Entraînement ou chargement
    print("\n Test 1: Chargement/Entraînement du modèle")
    if detector.charger():
        print(" Modèle chargé depuis disque")
    else:
        print(" Modèle non trouvé, entraînement...")
        detector.entrainer(verbose=True)
    
    # Test 2: Prédiction sur snapshot simulé (NORMAL)
    print("\n Test 2: Prédiction sur snapshot simulé NORMAL")
    snapshot_normal = {
        "status": "ONLINE",
        "switches": {
            "1": {"tx_mbps": 10, "rx_mbps": 9, "utilisation": 0.10},
            "2": {"tx_mbps": 10, "rx_mbps": 9, "utilisation": 0.10},
            "3": {"tx_mbps": 10, "rx_mbps": 9, "utilisation": 0.10},
            "4": {"tx_mbps": 5, "rx_mbps": 4, "utilisation": 0.15},
            "5": {"tx_mbps": 5, "rx_mbps": 4, "utilisation": 0.15},
            "6": {"tx_mbps": 5, "rx_mbps": 4, "utilisation": 0.15},
            "7": {"tx_mbps": 30, "rx_mbps": 27, "utilisation": 0.17},
            "8": {"tx_mbps": 30, "rx_mbps": 27, "utilisation": 0.17},
            "9": {"tx_mbps": 30, "rx_mbps": 27, "utilisation": 0.17},
        }
    }
    pred = detector.predire(snapshot_normal)
    print(f"Résultat: {pred}")
    
    # Test 3: Prédiction sur snapshot simulé CONGESTION
    print("\n Test 3: Prédiction sur snapshot simulé CONGESTION")
    snapshot_congestion = {
        "status": "ONLINE",
        "switches": {
            "1": {"tx_mbps": 80, "rx_mbps": 70, "utilisation": 0.80},
            "2": {"tx_mbps": 80, "rx_mbps": 70, "utilisation": 0.80},
            "3": {"tx_mbps": 80, "rx_mbps": 70, "utilisation": 0.80},
            "4": {"tx_mbps": 25, "rx_mbps": 22, "utilisation": 0.83},
            "5": {"tx_mbps": 25, "rx_mbps": 22, "utilisation": 0.83},
            "6": {"tx_mbps": 25, "rx_mbps": 22, "utilisation": 0.83},
            "7": {"tx_mbps": 150, "rx_mbps": 140, "utilisation": 0.83},
            "8": {"tx_mbps": 150, "rx_mbps": 140, "utilisation": 0.83},
            "9": {"tx_mbps": 150, "rx_mbps": 140, "utilisation": 0.83},
        }
    }
    pred = detector.predire(snapshot_congestion)
    print(f"Résultat: {pred}")
    
    # Test 4: Conversion features
    print("\n Test 4: _snapshot_vers_features()")
    features = detector._snapshot_vers_features(snapshot_congestion)
    print(f"Nombre de features: {len(features)} (devrait être 27)")
    print(f"Premières features: {features[:9]}")"""
