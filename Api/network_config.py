
ROLES = {
    "h1":  {"role": "Directeur",      "ip": "10.0.0.1"},
    "h2":  {"role": "Bureau Finance",  "ip": "10.0.0.2"},
    "h3":  {"role": "Bureau RH",       "ip": "10.0.0.3"},
    "h4":  {"role": "Stagiaire",       "ip": "10.0.0.4"},
    "h5":  {"role": "Stagiaire",       "ip": "10.0.0.5"},
    "h6":  {"role": "Stagiaire",       "ip": "10.0.0.6"},
    "h7":  {"role": "Mariem",          "ip": "10.0.0.7"},
    "h8":  {"role": "Aziz",            "ip": "10.0.0.8"},
    "h9":  {"role": "Ons",             "ip": "10.0.0.9"},
    "h10": {"role": "Serveur",         "ip": "10.0.0.10"}
}

# -----------------------------------------------------------------------
# QoS — queues OVS (linux-htb, 5 queues par port)
# -----------------------------------------------------------------------

QOS_PROFILES = {
    "STANDARD":   {"id": 0},
    "MULTIMEDIA": {"id": 1},
    "BRONZE":     {"id": 2},
    "GOLD":       {"id": 3},
    "SILVER":     {"id": 4},
}

# -----------------------------------------------------------------------
# DSCP — marquage sur les switches d'accès uniquement
#
# Valeurs DSCP standard (6 bits, champ ToS/DS) :
#   GOLD      → EF  (Expedited Forwarding)  = 46  (101110)
#   SILVER    → AF31 (Assured Forwarding)   = 26  (011010)
#   MULTIMEDIA→ AF41                        = 34  (100010)
#   BRONZE    → AF11                        = 10  (001010)
#   STANDARD  → BE  (Best Effort)           =  0  (000000)
#
# Ces valeurs correspondent aux PHB (Per-Hop Behavior) RFC 2597/3246.
# Les switches cœur (s7, s8, s9) lisent et transmettent le champ DSCP
# sans le modifier. OVS/linux-htb peut ensuite s'appuyer dessus pour
# du traffic shaping matériel si configuré en mode DSCP-aware.
# -----------------------------------------------------------------------

DSCP_MAP = {
    "GOLD":       46,   # EF  — latence minimale, priorité absolue
    "SILVER":     26,   # AF31 — priorité haute
    "MULTIMEDIA": 34,   # AF41 — trafic temps-réel (vidéo/audio)
    "BRONZE":     10,   # AF11 — meilleur effort amélioré
    "STANDARD":    0,   # BE   — best effort par défaut
}

# Switches d'accès (edge) : connectés directement aux hôtes.
# Le marquage DSCP est appliqué UNIQUEMENT sur ces switches.
# s7, s8, s9 = distribution/cœur → jamais de marquage.
ACCESS_SWITCHES = ["s1", "s2", "s3", "s4", "s5", "s6"]

# Mapping IP hôte → switch d'accès (déduit depuis LINKS).
# Utilisé par l'API /dscp/set pour trouver automatiquement le bon dpid.
HOST_IP_TO_ACCESS_SWITCH = {
    "10.0.0.10": "s1",   # h10
    "10.0.0.9":  "s2",   # h9
    "10.0.0.8":  "s2",   # h8
    "10.0.0.7":  "s2",   # h7
    "10.0.0.6":  "s3",   # h6
    "10.0.0.5":  "s3",   # h5
    "10.0.0.4":  "s3",   # h4
    "10.0.0.3":  "s4",   # h3
    "10.0.0.2":  "s5",   # h2
    "10.0.0.1":  "s6",   # h1
}

# -----------------------------------------------------------------------
# Topologie
# -----------------------------------------------------------------------

PORT_MAP = {
    (1, 7): 2, (7, 1): 1,
    (2, 7): 4, (7, 2): 2,
    (3, 7): 4, (7, 3): 3,
    (7, 8): 4, (8, 7): 1,
    (8, 9): 2, (9, 8): 4,
    (9, 6): 3, (6, 9): 2,
    (9, 5): 2, (5, 9): 2,
    (9, 4): 1, (4, 9): 2,
}

ROUTES = {
    "s1-s2": [1, 7, 2],
    "s1-s3": [1, 7, 3],
    "s2-s3": [2, 7, 3],
    "s2-s1": [2, 7, 1],
    "s3-s1": [3, 7, 1],
    "s3-s2": [3, 7, 2],

    "s1-s4": [1, 7, 8, 9, 4],
    "s1-s5": [1, 7, 8, 9, 5],
    "s1-s6": [1, 7, 8, 9, 6],
    "s2-s4": [2, 7, 8, 9, 4],
    "s2-s5": [2, 7, 8, 9, 5],
    "s2-s6": [2, 7, 8, 9, 6],
    "s3-s4": [3, 7, 8, 9, 4],
    "s3-s5": [3, 7, 8, 9, 5],
    "s3-s6": [3, 7, 8, 9, 6],

    "s4-s1": [4, 9, 8, 7, 1],
    "s5-s1": [5, 9, 8, 7, 1],
    "s6-s1": [6, 9, 8, 7, 1],
    "s4-s2": [4, 9, 8, 7, 2],
    "s5-s2": [5, 9, 8, 7, 2],
    "s6-s2": [6, 9, 8, 7, 2],

    "s4-s5": [4, 9, 5],
    "s4-s6": [4, 9, 6],
    "s5-s6": [5, 9, 6],
    "s5-s4": [5, 9, 4],
    "s6-s4": [6, 9, 4],
    "s6-s5": [6, 9, 5],
}

UPLINK_PORTS = {
    "1": [1],
    "2": [1, 2, 3],
    "3": [1, 2, 3],
    "5": [1],
    "4": [1],
    "6": [1]
}

SWITCHES = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"]

LINKS = [
    {"node1": "h10", "port1": 1, "node2": "s1", "port2": 1},
    {"node1": "h9",  "port1": 1, "node2": "s2", "port2": 1},
    {"node1": "h8",  "port1": 1, "node2": "s2", "port2": 2},
    {"node1": "h7",  "port1": 1, "node2": "s2", "port2": 3},
    {"node1": "h6",  "port1": 1, "node2": "s3", "port2": 1},
    {"node1": "h5",  "port1": 1, "node2": "s3", "port2": 2},
    {"node1": "h4",  "port1": 1, "node2": "s3", "port2": 3},
    {"node1": "h3",  "port1": 1, "node2": "s4", "port2": 1},
    {"node1": "h2",  "port1": 1, "node2": "s5", "port2": 1},
    {"node1": "h1",  "port1": 1, "node2": "s6", "port2": 1},
    {"node1": "s1",  "port1": 2, "node2": "s7", "port2": 1},
    {"node1": "s2",  "port1": 4, "node2": "s7", "port2": 2},
    {"node1": "s3",  "port1": 4, "node2": "s7", "port2": 3},
    {"node1": "s4",  "port1": 2, "node2": "s9", "port2": 1},
    {"node1": "s5",  "port1": 2, "node2": "s9", "port2": 2},
    {"node1": "s6",  "port1": 2, "node2": "s9", "port2": 3},
    {"node1": "s7",  "port1": 4, "node2": "s8", "port2": 1},
    {"node1": "s9",  "port1": 4, "node2": "s8", "port2": 2}
]
