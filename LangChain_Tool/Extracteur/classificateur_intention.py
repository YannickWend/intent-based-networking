"""
Extracteur/classificateur_intention.py

Classificateur ML d'intention SDN.
Utilise TF-IDF + SVM pour prédire le type d'action à partir d'une phrase en français.
"""

import os
import pickle
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import cross_val_score

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modele_ibn.pkl")
CONFIDENCE_THRESHOLD = 0.55

DATASET = [
    # BREAK
    ("coupe h1", "BREAK"),
    ("isole le directeur", "BREAK"),
    ("bloque h3", "BREAK"),
    ("débranche h5", "BREAK"),
    ("coupe le lien de Mariem", "BREAK"),
    ("isole les stagiaires", "BREAK"),
    ("neutralise h7", "BREAK"),
    ("éteins h2", "BREAK"),
    ("je veux bloquer le bureau RH", "BREAK"),
    ("interromps la connexion de h4", "BREAK"),
    ("stoppe h6", "BREAK"),
    ("désactive h9", "BREAK"),
    ("coupe la connexion du serveur", "BREAK"),
    ("offline h1", "BREAK"),
    ("down h3", "BREAK"),
    ("ferme le port de h8", "BREAK"),
    ("suspend h2", "BREAK"),
    ("interdit l'accès à h5", "BREAK"),
    ("kill h4", "BREAK"),
    ("je ne veux plus que h1 soit connecté", "BREAK"),
    ("déconnecte Aziz du réseau", "BREAK"),
    ("isole le bureau finance", "BREAK"),
    ("coupe tous les stagiaires", "BREAK"),
    ("bloque h10", "BREAK"),
    ("retire h3 du réseau", "BREAK"),
    ("je veux couper h2", "BREAK"),
    ("mets h1 hors ligne", "BREAK"),
    ("déconnecte le directeur", "BREAK"),
    ("peux-tu isoler h5 du reste", "BREAK"),
    ("bloque la connexion de Ons", "BREAK"),
    ("je veux que h7 soit isolé", "BREAK"),
    ("coupe h4 maintenant", "BREAK"),
    ("interromps le trafic de h6", "BREAK"),
    ("désactive le lien de h9", "BREAK"),
    ("je souhaite isoler h3", "BREAK"),
    ("empêche h2 d'accéder au réseau", "BREAK"),
    ("bloque Aziz", "BREAK"),
    ("débranche le serveur", "BREAK"),
    ("coupe Mariem du réseau", "BREAK"),
    ("isole h8 immédiatement", "BREAK"),
    ("stoppe la connexion de h1", "BREAK"),
    ("je veux mettre h5 offline", "BREAK"),
    ("retire le bureau RH du réseau", "BREAK"),
    ("désactive h10", "BREAK"),
    ("neutralise la connexion de h2", "BREAK"),
    ("coupe le stagiaire h4", "BREAK"),
    ("peux-tu bloquer h7", "BREAK"),
    ("mets Ons hors ligne", "BREAK"),
    ("interromps l'accès de h3", "BREAK"),
    ("je veux désactiver h6", "BREAK"),

    # RESTORE
    ("rétablis h1", "RESTORE"),
    ("reconnecte h3", "RESTORE"),
    ("active h5", "RESTORE"),
    ("remet h7 en ligne", "RESTORE"),
    ("restaure h2", "RESTORE"),
    ("relance la connexion de h4", "RESTORE"),
    ("débloque h6", "RESTORE"),
    ("up h9", "RESTORE"),
    ("online h1", "RESTORE"),
    ("autorise h8 à se reconnecter", "RESTORE"),
    ("remets le directeur sur le réseau", "RESTORE"),
    ("ouvre le port de h3", "RESTORE"),
    ("réactive h5", "RESTORE"),
    ("assure que le serveur soit toujours actif", "RESTORE"),
    ("je veux que h2 soit de nouveau connecté", "RESTORE"),
    ("rétablis la connexion de Mariem", "RESTORE"),
    ("remets Ons en ligne", "RESTORE"),
    ("reconnecte le bureau RH", "RESTORE"),
    ("réouvre la connexion de h10", "RESTORE"),
    ("remets tous les stagiaires en ligne", "RESTORE"),
    ("rebranche h4", "RESTORE"),
    ("réactive le serveur", "RESTORE"),
    ("assure la disponibilité de h1", "RESTORE"),
    ("remets h6 actif", "RESTORE"),
    ("remets en marche h2", "RESTORE"),
    ("assure que Mariem soit connectée", "RESTORE"),
    ("je veux que h5 soit à nouveau disponible", "RESTORE"),
    ("rétablis l'accès de h7", "RESTORE"),
    ("assure la connexion de h9", "RESTORE"),
    ("reconnecte Aziz", "RESTORE"),
    ("je veux remettre h3 en ligne", "RESTORE"),
    ("remet le bureau finance sur le réseau", "RESTORE"),
    ("réactive la connexion de h8", "RESTORE"),
    ("assure que h10 soit actif", "RESTORE"),
    ("je veux que le directeur soit connecté", "RESTORE"),
    ("remets h1 en service", "RESTORE"),
    ("rétablis l'accès à h2", "RESTORE"),
    ("assure que Ons puisse se connecter", "RESTORE"),
    ("relance h5", "RESTORE"),
    ("remets le réseau de h4 en marche", "RESTORE"),
    ("je veux rétablir h6", "RESTORE"),
    ("réactive Mariem", "RESTORE"),
    ("remets h3 sur le réseau", "RESTORE"),
    ("assure la disponibilité du serveur", "RESTORE"),
    ("reconnecte h7 maintenant", "RESTORE"),
    ("je veux que h8 soit de nouveau actif", "RESTORE"),
    ("remets Aziz en ligne", "RESTORE"),
    ("rétablis la connexion du stagiaire h4", "RESTORE"),
    ("assure que h2 reste connecté", "RESTORE"),
    ("rebranche le directeur", "RESTORE"),
    ("restore le lien de",        "RESTORE"),
    ("rétablis le lien",          "RESTORE"),
    ("remets en ligne",           "RESTORE"),
    ("reconnecte",                "RESTORE"),
    ("réactive le port de",       "RESTORE"),
    ("remet en marche",           "RESTORE"),
    # QOS
    ("priorise le trafic entre h1 et h3", "QOS"),
    ("applique GOLD entre h2 et h5", "QOS"),
    ("booste la connexion de h1 vers h10", "QOS"),
    ("optimise le lien entre Mariem et le serveur", "QOS"),
    ("donne la priorité à h7 pour accéder à h10", "QOS"),
    ("applique SILVER entre h3 et h9", "QOS"),
    ("je veux de la haute qualité entre h1 et h2", "QOS"),
    ("fluidifie le chemin entre h4 et h10", "QOS"),
    ("mets MULTIMEDIA entre h6 et h10", "QOS"),
    ("favorise le trafic de h2 vers h5", "QOS"),
    ("applique BRONZE entre h4 et h6", "QOS"),
    ("garantis la latence entre h1 et h3", "QOS"),
    ("priorise h1 pour joindre le serveur", "QOS"),
    ("je veux du GOLD entre le directeur et h10", "QOS"),
    ("améliore la qualité entre h7 et h9", "QOS"),
    ("limite h4 vers h10 en BRONZE", "QOS"),
    ("applique une QoS entre h2 et h3", "QOS"),
    ("queue 3 entre h1 et h10", "QOS"),
    ("donne plus de débit à h1 pour aller vers h10", "QOS"),
    ("streaming entre h6 et le serveur", "QOS"),
    ("visioconférence entre h3 et h5", "QOS"),
    ("zoom entre Mariem et Aziz", "QOS"),
    ("temps réel entre h1 et h2", "QOS"),
    ("maximise le débit entre h7 et h10", "QOS"),
    ("latence minimale entre h2 et h10", "QOS"),
    ("je veux GOLD pour h1 vers h3", "QOS"),
    ("donne la priorité à Mariem pour joindre h10", "QOS"),
    ("applique SILVER de h2 à h9", "QOS"),
    ("mets GOLD sur le chemin entre h1 et h5", "QOS"),
    ("priorise la vidéo entre h3 et h10", "QOS"),
    ("optimise le flux entre Aziz et le serveur", "QOS"),
    ("je veux du MULTIMEDIA entre h6 et h9", "QOS"),
    ("donne BRONZE à h4 pour aller vers h7", "QOS"),
    ("applique une priorité haute entre h1 et h2", "QOS"),
    ("booste le lien de h5 vers h10", "QOS"),
    ("mets SILVER entre h3 et h8", "QOS"),
    ("priorise Ons pour accéder au serveur", "QOS"),
    ("applique GOLD de h2 vers h10", "QOS"),
    ("je veux de la réactivité entre h7 et h3", "QOS"),
    ("mets une QoS haute entre h1 et h9", "QOS"),
    ("donne la priorité au trafic de h6 vers h10", "QOS"),
    ("applique MULTIMEDIA sur le chemin h3 vers h5", "QOS"),
    ("limite la bande passante de h4 vers h6", "QOS"),
    ("je veux BRONZE entre les stagiaires et le serveur", "QOS"),
    ("priorise le flux de Mariem vers h10", "QOS"),
    ("applique GOLD pour la connexion de h1 au serveur", "QOS"),
    ("mets du SILVER entre le directeur et h5", "QOS"),
    ("je veux optimiser le lien h2 vers h3", "QOS"),
    ("donne une haute priorité à h7 vers h10", "QOS"),
    ("applique un profil QoS entre h4 et h9", "QOS"),

    # NETWORK_WIDE
    ("applique GOLD sur tout le réseau", "NETWORK_WIDE"),
    ("mets BRONZE partout", "NETWORK_WIDE"),
    ("priorise tout le réseau en MULTIMEDIA", "NETWORK_WIDE"),
    ("applique STANDARD sur tous les switchs", "NETWORK_WIDE"),
    ("bascule tout en SILVER", "NETWORK_WIDE"),
    ("optimise l'ensemble du réseau", "NETWORK_WIDE"),
    ("applique une politique globale GOLD", "NETWORK_WIDE"),
    ("je veux BRONZE pour tout le monde", "NETWORK_WIDE"),
    ("mets le réseau entier en MULTIMEDIA", "NETWORK_WIDE"),
    ("applique STANDARD sur tous les équipements", "NETWORK_WIDE"),
    ("bascule tous les switchs en GOLD", "NETWORK_WIDE"),
    ("reset le réseau en mode standard", "NETWORK_WIDE"),
    ("applique une QoS globale SILVER", "NETWORK_WIDE"),
    ("tout le monde passe en BRONZE", "NETWORK_WIDE"),
    ("politique MULTIMEDIA sur l'infrastructure", "NETWORK_WIDE"),
    ("applique GOLD à tous les hôtes", "NETWORK_WIDE"),
    ("mets le réseau en mode rapide", "NETWORK_WIDE"),
    ("bascule l'ensemble en priorité haute", "NETWORK_WIDE"),
    ("applique un profil global", "NETWORK_WIDE"),
    ("mode BRONZE pour tout le réseau", "NETWORK_WIDE"),
    ("déploie SILVER partout dans le réseau", "NETWORK_WIDE"),
    ("initialise le réseau en STANDARD", "NETWORK_WIDE"),
    ("applique MULTIMEDIA à tous les utilisateurs", "NETWORK_WIDE"),
    ("je veux optimiser tout le réseau", "NETWORK_WIDE"),
    ("donne la priorité à tout le monde", "NETWORK_WIDE"),
    ("je veux GOLD pour tout le réseau", "NETWORK_WIDE"),
    ("bascule l'infrastructure en BRONZE", "NETWORK_WIDE"),
    ("mets SILVER sur tous les équipements", "NETWORK_WIDE"),
    ("applique MULTIMEDIA globalement", "NETWORK_WIDE"),
    ("je veux une politique STANDARD sur tout", "NETWORK_WIDE"),
    ("déploie GOLD sur l'ensemble des switchs", "NETWORK_WIDE"),
    ("mets tout le monde en MULTIMEDIA", "NETWORK_WIDE"),
    ("applique BRONZE à toute l'infrastructure", "NETWORK_WIDE"),
    ("je veux SILVER partout", "NETWORK_WIDE"),
    ("bascule le réseau entier en STANDARD", "NETWORK_WIDE"),
    ("mets GOLD sur tous les hôtes", "NETWORK_WIDE"),
    ("politique globale BRONZE", "NETWORK_WIDE"),
    ("applique un profil réseau SILVER", "NETWORK_WIDE"),
    ("je veux changer la politique de tout le réseau en GOLD", "NETWORK_WIDE"),
    ("déploie MULTIMEDIA sur l'ensemble", "NETWORK_WIDE"),
    ("mets tous les utilisateurs en BRONZE", "NETWORK_WIDE"),
    ("applique STANDARD globalement sur le réseau", "NETWORK_WIDE"),
    ("je veux une QoS globale haute", "NETWORK_WIDE"),
    ("bascule tous les hôtes en SILVER", "NETWORK_WIDE"),
    ("politique réseau MULTIMEDIA pour tout le monde", "NETWORK_WIDE"),
    ("applique GOLD à l'ensemble des équipements", "NETWORK_WIDE"),
    ("je veux que tout le réseau soit en BRONZE", "NETWORK_WIDE"),
    ("mets une priorité globale sur le réseau", "NETWORK_WIDE"),
    ("déploie un profil GOLD partout", "NETWORK_WIDE"),
        ("applique SILVER sur tout le monde", "NETWORK_WIDE"),


    ("liste les missions actives", "QUERY"),
    ("affiche les missions en cours", "QUERY"),
    ("quelles sont les missions actives", "QUERY"),
    ("montre-moi les missions", "QUERY"),
    ("liste les missions", "QUERY"),
    ("quel est l'état du réseau", "QUERY"),
    ("affiche l'état des ports", "QUERY"),
    ("montre les ports actifs", "QUERY"),
    ("quels ports sont up", "QUERY"),
    ("état du réseau", "QUERY"),
    ("status réseau", "QUERY"),
    ("info réseau", "QUERY"),
    ("donne-moi les informations réseau", "QUERY"),
    ("check les ports", "QUERY"),
    ("vérifie l'état des liens", "QUERY"),
    ("affiche les ports", "QUERY"),
    ("combien de missions actives", "QUERY"),
    ("liste toutes les missions", "QUERY"),
    ("qu'est-ce qui tourne en ce moment", "QUERY"),
    ("quelles intentions sont actives", "QUERY"),
    ("montre les intentions en cours", "QUERY"),
    ("liste les intentions", "QUERY"),
    ("affiche les politiques actives", "QUERY"),
]


class IntentClassifier:
    """
    Classificateur ML d'intention SDN.
    Usage :
        clf = IntentClassifier()
        action = clf.predire("coupe h1")  # -> "BREAK" ou None
    """

    # Version du dataset — incrémenter à chaque ajout d'exemples
    # pour forcer le réentraînement automatique
    DATASET_VERSION = 2

    def __init__(self):
        self.pipeline = None
        self.classes  = None
        self._version = None

        if os.path.exists(MODEL_PATH):
            self._charger()
            # Si la version sauvegardée est différente → réentraîner
            if self._version != self.DATASET_VERSION:
                print(f"[ML] Dataset mis à jour (v{self._version}→v{self.DATASET_VERSION}) — réentraînement...")
                self.entrainer()
        else:
            print("[ML] Premier lancement — entraînement du classificateur...")
            self.entrainer()
            print("[ML] Classificateur prêt et sauvegardé.")

    def entrainer(self, verbose=True):
        textes = [t for t, _ in DATASET]
        labels = [l for _, l in DATASET]
        svm = LinearSVC(max_iter=2000, C=1.0)
        self.pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(
                ngram_range=(1, 3),
                analyzer="word",
                sublinear_tf=True,
                min_df=1
            )),
            ("clf", CalibratedClassifierCV(svm, cv=5))
        ])
        self.pipeline.fit(textes, labels)
        self.classes = list(self.pipeline.classes_)
        if verbose:
            scores = cross_val_score(self.pipeline, textes, labels, cv=5, scoring="accuracy")
            print(f"[ML] Accuracy cross-validation : {scores.mean():.2%} +/- {scores.std():.2%}")
        self._sauvegarder()

    # Mots-clés QUERY prioritaires — détectés avant le ML pour éviter
    # que "liste les missions" soit classifié NETWORK_WIDE
    QUERY_KEYWORDS = [
        "liste", "lister", "affiche", "afficher", "montre", "montrer",
        "quelles sont", "quel est l'état", "status", "état des",
        "quels ports", "check", "info réseau", "combien de missions",
        "missions actives", "intentions actives", "politiques actives",
    ]

    def predire(self, text: str):
        if self.pipeline is None:
            return None
        text_lower = text.lower()

        # Pré-filtre QUERY : si la phrase contient des mots-clés de requête
        # on court-circuite le ML pour éviter les faux NETWORK_WIDE
        for kw in self.QUERY_KEYWORDS:
            if kw in text_lower:
                # Vérifier qu'il ne s'agit pas d'une confusion avec QOS/NETWORK_WIDE
                # (ex: "affiche GOLD sur tout le réseau" → NETWORK_WIDE, pas QUERY)
                qos_signals = ["gold", "silver", "bronze", "multimedia", "standard",
                               "profil", "priorité", "qos", "partout", "tout le réseau"]
                has_qos = any(sig in text_lower for sig in qos_signals)
                if not has_qos:
                    return "QUERY"

        probas    = self.pipeline.predict_proba([text_lower])[0]
        max_proba = float(np.max(probas))
        predicted = self.classes[int(np.argmax(probas))]
        if max_proba >= CONFIDENCE_THRESHOLD:
            return predicted
        return None

    def _sauvegarder(self):
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({
                "pipeline": self.pipeline,
                "classes":  self.classes,
                "version":  self.DATASET_VERSION,
            }, f)

    def _charger(self):
        try:
            with open(MODEL_PATH, "rb") as f:
                data = pickle.load(f)
            self.pipeline = data["pipeline"]
            self.classes  = data["classes"]
            self._version = data.get("version", 1)   # 1 = ancienne version sans versionnage
        except Exception as e:
            print(f"[ML] Erreur chargement : {e} — réentraînement...")
            self.entrainer()

    def reinitialiser(self):
        """Force un réentraînement si on ajoute des exemples au dataset."""
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
        self.entrainer()


"""if __name__ == "__main__":
    clf = IntentClassifier()

    tests = [
        "coupe h1",
        "rétablis le serveur",
        "applique GOLD entre h1 et h3",
        "mets BRONZE sur tout le réseau",
        "isole le directeur",
        "assure que Mariem soit connectée",
        "priorise la vidéo entre h2 et h10",
        "bascule tout en MULTIMEDIA",
        "je veux que h5 soit hors ligne",
        "assure que h9 reste actif",
        "donne SILVER à h1 vers h3",
        "politique globale GOLD",
    ]
    for phrase in tests:
        result = clf.predire(phrase)
        print(f"  '{phrase}'\n   -> {result}\n")"""
