import os
import requests
import json
import threading
import time
import queue as _queue_module
from typing import Union, List
from langchain_groq import ChatGroq
from langchain.tools import tool
from langchain.agents import create_agent
import sys
from os.path import dirname, join, abspath
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

sys.path.append(abspath(join(dirname(__file__), 'Extracteur')))

from extracteur import Extracteur
from Formalisateur import SuperFormalisateur
from Control.mission_watcheur import ControlLayer
from Control.validateur_politique import get_validateur
from intent_registry import IntentRegistry  

"""

NOTE : Certaines fonctions de ce code ne sont pas utilisées ou ne sont pas optimisées pour une conversation fluide avec 
le chat bot comme avec chat gpt. Mais le LLM est capable d'exécutée les actions définies.


"""


MISSION_DIR        = "ordres_mission"
MAX_MESSAGES       = 100   # mémoire glissante
messages           = []    # historique partagé
_intent_a_rejouer  = []    # intentions à rejouer après suppression de mission

# violation_queue reçoit maintenant des LOGS de correction (pas des demandes IA)
# L'IA les lit et informe l'utilisateur sans prendre d'action supplémentaire
violation_queue = _queue_module.Queue()

input_queue  = _queue_module.Queue()
_quitter     = threading.Event()

# IntentRegistry remplace WatchdogManager
registry = IntentRegistry(
    log_callback=lambda rapport: violation_queue.put(rapport)
)
registry.demarrer_scheduler()  

sf = SuperFormalisateur()
os.makedirs(MISSION_DIR, exist_ok=True)



# OUTILS IA


@tool
def manage_link(dpid: int, port: int, action: str) -> str:
    """Coupe (break) ou restaure (restore) un lien sur un switch.
    - dpid   : identifiant du switch (entier, ex: 3)
    - port   : numéro du port physique (entier)
    - action : 'break' pour couper, 'restore' pour rétablir
    """
    clean_dpid = int(''.join(filter(str.isdigit, str(dpid))))
    url = f"http://localhost:5000/link/{action}"
    try:
        res = requests.post(
            url, json={"dpid": clean_dpid, "port": int(port)}, timeout=5
        )
        return json.dumps(res.json())
    except Exception as e:
        return f"Échec de l'action {action}: {str(e)}"


@tool
def get_ports_status() -> str:
    """Récupère l'état actuel de tous les ports du réseau (UP ou DOWN)."""
    try:
        res = requests.get("http://localhost:5000/api/port_states", timeout=5)
        return json.dumps(res.json())
    except Exception as e:
        return f"Erreur statut ports : {str(e)}"


@tool
def set_network_wide_policy(profile: str) -> str:
    """Applique un profil QoS sur l'ensemble du réseau.
    - profile : nom du profil (STANDARD, MULTIMEDIA, BRONZE, GOLD, SILVER)
    """
    try:
        res = requests.post(
            "http://localhost:5000/qos/network_wide",
            json={"profile": profile.upper()},
            timeout=10
        )
        if res.status_code == 200:
            return f"CONFIRMATION : Profil {profile.upper()} appliqué sur tout le réseau."
        return f"ERREUR : Code {res.status_code}."
    except Exception as e:
        return f"ÉCHEC : {str(e)}"


@tool
def set_access_qos(ip_a: str, ip_b: str, profil: str) -> str:
    """Applique une QoS par hôte sur les switches d'ACCÈS uniquement.
    C'est l'outil QoS principal — scalable et suffisant dans 95% des cas.

    Workflow : installe la règle de queue OVS sur le switch d'accès de
    chaque hôte, puis appelle set_dscp automatiquement.

    - ip_a  : IP de l'hôte source  (ex: '10.0.0.1')
    - ip_b  : IP de l'hôte destination (ex: '10.0.0.10')
    - profil: GOLD, SILVER, MULTIMEDIA, BRONZE ou STANDARD
    """
    from network_config import HOST_IP_TO_ACCESS_SWITCH, DSCP_MAP
    QOS_TABLE    = {"STANDARD": 0, "BRONZE": 2, "GOLD": 3, "SILVER": 4}
    profil_upper = profil.upper().strip()
    if profil_upper not in QOS_TABLE:
        return f"ERREUR : Profil '{profil}' inconnu. Valides : {list(QOS_TABLE.keys())}"

    queue_id = QOS_TABLE[profil_upper]
    url_qos  = "http://localhost:5000/qos/set_qos_profile"
    url_dscp = "http://localhost:5000/dscp/set"
    log      = []

    for ip in [ip_a, ip_b]:
        sw_name = HOST_IP_TO_ACCESS_SWITCH.get(ip)
        if sw_name is None:
            log.append(f"{ip}: switch d'accès introuvable — ignoré")
            continue
        dpid = int(sw_name.replace('s', ''))
        try:
            rq = requests.post(url_qos,
                               json={"dpid": dpid, "ip": ip, "queue": queue_id},
                               timeout=10)
            qos_ok = rq.status_code == 200

            rd = requests.post(url_dscp,
                               json={"ip_src": ip, "profile": profil_upper},
                               timeout=5)
            dscp_ok = rd.json().get("status") == "ok"

            dscp_val = DSCP_MAP.get(profil_upper, 0)
            log.append(
                f"{ip} ({sw_name}): queue={'OK' if qos_ok else 'ERR'} "
                f"DSCP={dscp_val}({'OK' if dscp_ok else 'ERR'})"
            )
        except Exception as e:
            log.append(f"{ip}: Échec ({e})")

    return f"QoS accès {profil_upper} → {' | '.join(log)}"


@tool
def set_path_qos(path: Union[List, str], ip_a: str, ip_b: str,
                  profil: str) -> str:
    """Applique une QoS sur TOUS les switches du chemin entre deux hôtes.
    Utiliser uniquement si un switch INTERMÉDIAIRE est le point de congestion.

    - path  : liste de DPIDs du chemin complet (ex: [6, 9, 8, 7, 1])
    - ip_a  : IP de l'hôte source
    - ip_b  : IP de l'hôte destination
    - profil: GOLD, SILVER, MULTIMEDIA, BRONZE ou STANDARD
    """
    QOS_TABLE    = {"STANDARD": 0, "MULTIMEDIA": 1, "BRONZE": 2, "GOLD": 3, "SILVER": 4}
    profil_upper = profil.upper().strip()
    if profil_upper not in QOS_TABLE:
        return f"ERREUR : Profil '{profil}' inconnu."

    clean_queue = QOS_TABLE[profil_upper]
    url         = "http://localhost:5000/qos/set_qos_profile"
    log         = []

    path_list = (
        [p.strip() for p in path.replace('[','').replace(']','').split(',') if p.strip()]
        if isinstance(path, str) else path
    )

    for dpid in path_list:
        try:
            clean_dpid = int(str(dpid).lower().replace('switch','').replace('s','').strip())
            ra = requests.post(url, json={"dpid": clean_dpid, "ip": ip_a, "queue": clean_queue}, timeout=10)
            rb = requests.post(url, json={"dpid": clean_dpid, "ip": ip_b, "queue": clean_queue}, timeout=10)
            log.append(f"s{clean_dpid}: {'OK' if ra.status_code==200 and rb.status_code==200 else 'Erreur'}")
        except Exception as e:
            log.append(f"s{dpid}: Échec ({e})")

    return f"QoS chemin complet {profil_upper} → {', '.join(log)}"


@tool
def set_dscp(ip_src: str, profile: str) -> str:
    """Marque les paquets d'un hôte avec le DSCP correspondant à son profil QoS.
    Installé UNIQUEMENT sur le switch d'accès de l'hôte.

    - ip_src  : adresse IP de l'hôte source (ex: '10.0.0.1')
    - profile : GOLD, SILVER, MULTIMEDIA, BRONZE ou STANDARD
    """
    try:
        res = requests.post(
            "http://localhost:5000/dscp/set",
            json={"ip_src": ip_src, "profile": profile.upper()},
            timeout=5
        )
        data = res.json()
        if data.get("status") == "ok":
            return (
                f"DSCP OK : {ip_src} → DSCP {data.get('dscp_value')} "
                f"({data.get('profile')}) sur s{data.get('dpid')}."
            )
        return f"DSCP ERREUR : {data.get('message', 'inconnu')}"
    except Exception as e:
        return f"ÉCHEC set_dscp : {str(e)}"


@tool
def remove_dscp(ip_src: str) -> str:
    """Supprime le marquage DSCP d'un hôte (retour à STANDARD/Best Effort).
    - ip_src : adresse IP de l'hôte
    """
    try:
        res  = requests.post(
            "http://localhost:5000/dscp/remove",
            json={"ip_src": ip_src},
            timeout=5
        )
        data = res.json()
        return (f"DSCP supprimé pour {ip_src}."
                if data.get("status") == "ok"
                else f"Erreur : {data.get('message')}")
    except Exception as e:
        return f"ÉCHEC remove_dscp : {str(e)}"


@tool
def lister_missions() -> str:
    """Liste toutes les missions IBN actives avec leur statut.
    Utile pour voir ce qui tourne et détecter des conflits potentiels.
    """
    missions = registry.liste_missions()
    if not missions:
        return "Aucune mission active en ce moment."
    lignes = [f"{registry.nb_missions()} mission(s) active(s) :"]
    for m in missions:
        lignes.append(
            f"  [{m['mission_id']}] {m['action']} | "
            f"hôtes={m['hotes']} | status={m['status']} | "
            f"corrections={m['corrections']} | depuis {m['cree_a']}"
        )
    return "\n".join(lignes)


@tool
def supprimer_mission(mission_id: str) -> str:
    """Arrête et supprime une mission active par son ID.
    Utile pour résoudre un conflit ou arrêter une surveillance.
    - mission_id : l'identifiant de la mission (ex: 'MA3F2B')
    """
    mid = mission_id.upper()

    # Récupérer l'intention originale AVANT la suppression
    mission_obj = registry.get_mission(mid)
    intent_original = None
    if mission_obj:
        intent_original = mission_obj.manifeste.get("intent", None)

    ok = registry.supprimer(mid)
    if not ok:
        return f"Mission {mid} introuvable."

    # Si l'intention originale existe, on la remet en attente de rejeu
    # Le pipeline IBN sera relancé automatiquement après cet appel
    if intent_original:
        _intent_a_rejouer.append(intent_original)
        return (
            f"Mission {mid} supprimée. "
            f"L'intention originale sera réappliquée automatiquement."
        )
    return f"Mission {mid} supprimée. Surveillance arrêtée."



# AGENT IA


llm = ChatGroq(
    model_name="llama-3.3-70b-versatile",
    temperature=0,
    max_tokens=1024
)

SDN_PROMPT = """
# RÔLE
Tu es l'Exécuteur Technique autonome du réseau SDN avec capacité d'auto-réparation.
Le système gère maintenant PLUSIEURS intentions simultanées (multi-missions).

# FONCTIONNEMENT NORMAL (mission utilisateur)
Tu reçois un MANIFESTE JSON. Le champ 'ai_guidance.instructions' est intentionnellement
vide — tu dois TOUJOURS choisir toi-même l'outil approprié selon le contexte.

## Règles de sélection d'outil

detected_action = BREAK
  → manage_link(action='break', dpid=..., port=...)

detected_action = RESTORE
  → manage_link(action='restore', dpid=..., port=...)

detected_action = QUERY
  → get_ports_status()

detected_action = QOS  ← CAS PRINCIPAL
  → set_access_qos(ip_a=..., ip_b=..., profil=...)
  Cet outil fait TOUT en un seul appel :
    • installe la queue OVS sur le switch d'accès de chaque hôte
    • marque automatiquement le DSCP sur ces mêmes switches
  Les switches cœur (s7, s8, s9) ne sont PAS modifiés — c'est voulu.

  Exception — utiliser set_path_qos EN PLUS de set_access_qos UNIQUEMENT si :
    • le rapport de violation indique une congestion sur un switch intermédiaire

detected_action = NETWORK_WIDE
  → set_network_wide_policy(profile=...)

## Hiérarchie des outils QoS
  1. set_access_qos  → cas nominal (hôtes spécifiques)
  2. set_path_qos    → congestion chemin confirmée
  3. set_network_wide_policy → politique réseau globale

## Outils de gestion des missions
  → lister_missions()      : voir toutes les missions actives et leur statut
  → supprimer_mission(id)  : arrêter une mission (pour résoudre un conflit)

Tous les paramètres sont dans le manifeste — ne les invente jamais.
Si execution_ready = FALSE, explique ce qui manque sans appeler d'outil.

# FONCTIONNEMENT MULTI-MISSIONS
Le système gère PLUSIEURS missions simultanément.
Chaque mission a son propre watchdog indépendant.
Si un conflit est détecté par le registry, explique-le clairement à l'utilisateur
et propose soit de supprimer la mission existante, soit d'ajuster l'intention.

# FONCTIONNEMENT LOGS DE CORRECTION AUTONOME
Tu reçois des [LOG CORRECTION AUTONOME]. Ces logs t'informent qu'une correction
a déjà été effectuée SANS ton intervention par le système autonome.
→ Informe l'utilisateur brièvement de ce qui s'est passé.
→ N'appelle AUCUN outil — la correction est déjà faite.

# RÈGLE D'OR
Ne devine jamais une donnée technique. Si une valeur est null, elle n'existe pas.
Sois concis. Pour le Small Talk, réponds normalement sans outil.

RÈGLE ABSOLUE — supprimer_mission :
Ne jamais appeler supprimer_mission automatiquement.
Toujours demander confirmation explicite à l'utilisateur avant.
Exemple correct : "La mission MXXXXX est en conflit.
Voulez-vous la supprimer ? Tapez 'oui supprimer MXXXXX'."

REGLE ABSOLUE — apres suppression de mission :
Apres avoir appele supprimer_mission(), NE JAMAIS enchainer une autre
action reseau dans la meme reponse. Tu dois demander a l'utilisateur
de reformuler son intention pour qu'elle soit enregistree correctement.
Exemple correct apres suppression :
  'Mission MXXXXX supprimee. Reformule maintenant ton intention
   pour que je l'applique et l'enregistre correctement.'
Exemple INTERDIT : appeler supprimer_mission() puis set_access_qos()
dans la meme reponse.

"""

agent_graph = create_agent(
    model=llm,
    tools=[
        manage_link,
        get_ports_status,
        set_network_wide_policy,
        set_access_qos,
        set_path_qos,
        set_dscp,
        remove_dscp,
        lister_missions,
        supprimer_mission,
    ],
    system_prompt=SDN_PROMPT
)



# LOGIQUE PRINCIPALE


def _execution_ready(manifeste: dict) -> bool:
    return manifeste.get("ai_guidance", {}).get("execution_ready", False)


def _extraire_decision_ia(msgs: list) -> tuple:
    for msg in reversed(msgs):
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            last = msg.tool_calls[-1]
            return last.get("name", ""), last.get("args", {})
        if hasattr(msg, 'additional_kwargs'):
            tc = msg.additional_kwargs.get("tool_calls", [])
            if tc:
                last  = tc[-1]
                outil = last.get("function", {}).get("name", "")
                try:
                    params = json.loads(last.get("function", {}).get("arguments", "{}"))
                except Exception:
                    params = {}
                return outil, params
    return None, {}


def _valider_et_corriger(manifeste: dict, reponse_ia: str,
                          tentative: int) -> str:
    global messages
    intention  = manifeste["decision_engine"]["detected_action"]
    validateur = get_validateur()
    outil, params = _extraire_decision_ia(messages)

    if outil is None:
        return reponse_ia

    verdict = validateur.valider(intention, outil, params)

    if verdict["valide"]:
        print(f"[VALIDATEUR] {outil} validé (confiance {verdict['confiance']:.0%})")
        return reponse_ia

    print(
        f"🚫 [VALIDATEUR] Bloqué — niveau {verdict['niveau_echec']} : "
        f"{verdict['raison']}"
    )

    if tentative >= 2:
        print("[VALIDATEUR] Max tentatives atteint — exécution forcée.")
        return reponse_ia

    feedback = f"""
[VALIDATEUR DE POLITIQUE — CORRECTION REQUISE]
Ta décision a été BLOQUÉE :

Niveau      : {verdict['niveau_echec']}
Raison      : {verdict['raison']}
Correction  : {verdict['suggestion']}

Reprends le manifeste et réessaie avec les paramètres corrects.
"""
    messages.append({"role": "user", "content": feedback})
    result   = agent_graph.invoke({"messages": messages})
    messages = result["messages"][-20:]
    nouvelle_reponse = messages[-1].content
    return _valider_et_corriger(manifeste, nouvelle_reponse, tentative + 1)


# ── Mots-clés réseau pour détection conversation ──────────────────────────
_MOTS_RESEAU = [
    "coupe", "isole", "bloque", "déconnecte", "stoppe", "ferme",
    "reconnecte", "rétablis", "remets", "réactive", "rallume", "rebranche",
    "priorise", "priorité", "latence", "débit", "bande passante", "qos",
    "gold", "silver", "bronze", "multimedia", "standard",
    "limite", "ralentis", "réduis", "restreins",
    "visio", "zoom", "teams", "streaming", "réunion", "conférence",
    "backup", "téléchargement", "transfert", "maximise",
    "h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h10",
    "directeur", "stagiaire", "mariem", "aziz", "ons", "serveur",
    "finance", "rh", "bureau",
    "switch", "port", "réseau", "watchdog",
]


def _est_conversation(text: str) -> bool:
    """True = conversation générale, False = intention réseau IBN."""
    import re as _re
    text_lower = text.lower().strip()

    # Small talk — exact match ou phrase courte sans mot réseau
    small_talk = [
        "bonjour", "salut", "hello", "hi", "bonsoir", "coucou",
        "merci", "ok", "bien", "super", "parfait", "compris",
        "comment tu vas", "comment ça va", "quoi de neuf",
        "au revoir", "bye", "à bientôt", "ciao",
    ]
    if any(text_lower == kw for kw in small_talk):
        return True
    if len(text_lower.split()) <= 3 and any(kw in text_lower for kw in small_talk):
        return True

    # Questions explicites
    questions = [
        "c'est quoi", "qu'est-ce que", "qu'est ce que", "kesako",
        "explique", "comment fonctionne", "comment ça marche",
        "quelle est la différence", "différence entre",
        "qu'as-tu fait", "pourquoi", "tu peux m'expliquer", "dis-moi",
    ]
    if any(p in text_lower for p in questions):
        return True

    # Gestion de missions par commande ou ID
    mission_kw = [
        "supprime la mission", "supprimer la mission",
        "liste les missions", "liste missions",
        "montre les missions", "oui supprimer", "oui supprime",
    ]
    if any(kw in text_lower for kw in mission_kw):
        return True
    if _re.search(r"\b[Mm][A-Z0-9]{4,}\b", text):
        return True

    # Aucun mot réseau → conversation
    if not any(mot in text_lower for mot in _MOTS_RESEAU):
        return True

    return False


def _repondre_directement(user_input: str) -> str:
    """Envoie directement à l'IA sans pipeline IBN. Met à jour l'historique."""
    global messages, _intent_a_rejouer
    messages.append({"role": "user", "content": user_input})
    if len(messages) > MAX_MESSAGES:
        messages = messages[-MAX_MESSAGES:]
    result   = agent_graph.invoke({"messages": messages})
    messages = result["messages"][-MAX_MESSAGES:]
    reponse  = messages[-1].content

    # Après la réponse, rejouer les intentions en attente
    if _intent_a_rejouer:
        intent = _intent_a_rejouer.pop(0)
        print(f"\n[REGISTRY] Rejeu automatique : {intent}")
        reponse_rejeu = traiter_message_utilisateur(intent)
        reponse += f"\n\nIntention réappliquée : {reponse_rejeu}"

    return reponse


def traiter_message_utilisateur(user_input: str) -> str:
    """
    Traite une intention utilisateur et l'ajoute au registry
    si execution_ready=True. Détecte les conflits avant d'ajouter.
    """
    global messages
    import uuid as _uuid

    # Détection conversation vs intention réseau
    if _est_conversation(user_input):
        return _repondre_directement(user_input)

    mission_seq = int(_uuid.uuid4().hex[:4], 16) % 1000
    manifeste = sf.generer_ordre_mission(user_input, test_id=mission_seq)
    if manifeste is None:
        return _repondre_directement(user_input)

    manifeste_ia = dict(manifeste)
    manifeste_ia["ai_guidance"] = {
        "execution_ready": manifeste["ai_guidance"]["execution_ready"],
        "instructions":    None
    }

    # Indiquer à l'IA combien de missions sont déjà actives
    nb_actives = registry.nb_missions()
    info_missions = ""
    if nb_actives > 0:
        missions_resumees = registry.liste_missions()
        info_missions = (
            f"\n\n[INFO SYSTÈME] {nb_actives} mission(s) déjà active(s) :\n"
            + "\n".join(
                f"  [{m['mission_id']}] {m['action']} hôtes={m['hotes']}"
                for m in missions_resumees
            )
        )

    prompt = f"""
MANIFESTE DE MISSION SDN REÇU :
--------------------------------
{json.dumps(manifeste_ia, indent=2, ensure_ascii=False)}
--------------------------------{info_missions}
Analyse le manifeste et choisis l'outil approprié selon les règles de ton rôle.
Pour les missions QoS, utilise set_access_qos (queue + DSCP en un seul appel).
"""
    messages.append({"role": "user", "content": prompt})
    # Après avoir construit le prompt, avant agent_graph.invoke()
    action = manifeste.get("decision_engine", {}).get("detected_action", "")

    # QoS / NETWORK_WIDE : mode demand-driven — enregistrement immédiat
    if action in ("QOS", "NETWORK_WIDE"):
        mission_id, conflit, msg_conflit = registry.ajouter(manifeste)
        if conflit:
            return f"Conflit détecté : {msg_conflit}"
        return (f"Mission {mission_id} enregistrée en attente. "
                f"La QoS sera activée automatiquement selon la charge réseau.")

    # BREAK / RESTORE : vérification des données avant envoi à l'IA
    if action in ("BREAK", "RESTORE"):
        nodes = manifeste.get("technical_targets", {}).get("nodes", [])
        if not nodes or nodes[0] is None:
            return (
                "Impossible d'identifier le switch cible. "
                "Précise le nom de l'hôte (ex: 'h3') ou du switch dans ta demande."
            )
        # Vérifier que les clés dpid et port sont présentes
        node0 = nodes[0]
        if not node0.get("dpid") or not node0.get("port"):
            return (
                f"Informations incomplètes pour {action} : "
                f"dpid={node0.get('dpid')}, port={node0.get('port')}. "
                "Précise l'hôte ou le switch visé."
            )

    result   = agent_graph.invoke({"messages": messages})
    messages = result["messages"][-20:]
    reponse  = messages[-1].content

    if _execution_ready(manifeste):
        reponse = _valider_et_corriger(manifeste, reponse, tentative=1)

    if _execution_ready(manifeste):
        mission_id, conflit, msg_conflit = registry.ajouter(manifeste)

        if conflit:
            # Informer l'IA du conflit pour qu'elle l'explique à l'utilisateur
            messages.append({
                "role": "user",
                "content": (
                    f"[CONFLIT DÉTECTÉ PAR LE REGISTRY]\n{msg_conflit}\n"
                    f"Explique ce conflit à l'utilisateur et propose une solution."
                )
            })
            result   = agent_graph.invoke({"messages": messages})
            messages = result["messages"][-20:]
            reponse  = messages[-1].content
        else:
            print(f"[REGISTRY] Mission {mission_id} enregistrée et surveillée.")
    else:
        print("[REGISTRY] Mission incomplète — non enregistrée.")

    return reponse


def traiter_log_correction(rapport: str) -> str:
    """
    Reçoit un LOG de correction autonome.
    L'IA informe l'utilisateur sans intervenir.
    """
    global messages
    messages.append({"role": "user", "content": rapport})
    result   = agent_graph.invoke({"messages": messages})
    messages = result["messages"][-20:]
    return messages[-1].content



# THREAD INPUT


def _thread_lecture_input():
    print("\nVous : ", end="", flush=True)
    while not _quitter.is_set():
        try:
            saisie = input()
            input_queue.put(saisie.strip())
            if saisie.strip().lower() not in ["exit", "quit"]:
                print("\nVous : ", end="", flush=True)
        except EOFError:
            input_queue.put("quit")
            break



if __name__ == "__main__":
    print("\nIA SDN ORCHESTRATOR READY")
    print("   IBN + MULTI-MISSIONS + AUTO-HEALING + DSCP + VALIDATION ML")
    print("   Tapez 'exit' ou 'quit' pour quitter proprement.\n")

    t_input = threading.Thread(target=_thread_lecture_input, daemon=True)
    t_input.start()

    try:
        while not _quitter.is_set():

            # Traitement des logs de correction autonome (priorité)
            try:
                rapport = violation_queue.get_nowait()
                print("\n\n[CORRECTION AUTONOME] Log reçu — l'IA informe l'utilisateur...")
                try:
                    reponse = traiter_log_correction(rapport)
                    print(f"\nIA : {reponse}")
                    print("\nVous : ", end="", flush=True)
                except Exception as e:
                    print(f"Erreur log correction : {e}")
                continue
            except _queue_module.Empty:
                pass

            # Traitement des messages utilisateur
            try:
                user_input = input_queue.get(timeout=0.3)
            except _queue_module.Empty:
                continue

            if not user_input:
                print("\nVous : ", end="", flush=True)
                continue

            if user_input.lower() in ["exit", "quit"]:
                break

            try:
                reponse = traiter_message_utilisateur(user_input)
                print(f"\nIA : {reponse}")
            except AttributeError as e:
                # Souvent NoneType lors d'un manifeste incomplet
                print(f"Erreur système (données manquantes) : {e}")
                print("   Conseil : reformule l'intention en précisant l'hôte ou switch cible.")
            except Exception as e:
                print(f"Erreur système : {e}")

    finally:
        _quitter.set()
        print("\nArrêt en cours...")
        registry.arreter_tout()
        print("Arrêt propre. Au revoir.")
