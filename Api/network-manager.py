#!/usr/bin/env python3
from flask import Flask, jsonify, request, render_template
import requests
import json
import time
import sys
from os.path import dirname, join, abspath
from network_config import (
    ROLES, ROUTES, QOS_PROFILES, UPLINK_PORTS, LINKS,
    SWITCHES, PORT_MAP, DSCP_MAP, ACCESS_SWITCHES, HOST_IP_TO_ACCESS_SWITCH
)



RYU_URL = "http://localhost:8080"
sys.path.append(abspath(join(dirname(__file__), '..', 'LangChain_Tool')))



try:
    from sdn_ai_retroactif import agent_graph, registry
except ImportError as e:
    print(f"Impossible d'importer l'IA. ")
    agent_graph = None
    registry = None



app = Flask(__name__)



class NetworkManager:
    def __init__(self):
        self.ryu_url = RYU_URL

    def format_dpid(self, dpid):
        if isinstance(dpid, str):
            import re
            dpid = re.sub(r'\D', '', dpid)
        try:
            return "{:016x}".format(int(dpid))
        except (ValueError, TypeError):
            print(f"Impossible de convertir le DPID '{dpid}'")
            return "{:016x}".format(0)


    def break_link(self, dpid, port):
        url = f"{self.ryu_url}/link/break"
        try:
            res = requests.post(url, json={"dpid": int(dpid), "port": int(port)}, timeout=5)
            return res.json()
        except Exception as e:
            return {"status": "error", "message": f"Erreur Ryu: {str(e)}"}



    def restore_link(self, dpid, port):
        url = f"{self.ryu_url}/link/restore"
        try:
            res = requests.post(url, json={"dpid": int(dpid), "port": int(port)}, timeout=5)
            return res.json()
        except Exception as e:
            return {"status": "error", "message": f"Erreur Ryu: {str(e)}"}
            
            
            
    def set_qos_profile(self, dpid, ip_src, queue_id):
        """Aiguille le flux d'un hôte vers une queue OVS existante."""
        dpid_str = self.format_dpid(dpid)
        try:
            rule_data = {
                "priority": 100,
                "match": {"nw_src": ip_src, "dl_type": "IPv4"},
                "actions": {"queue": str(queue_id)}
            }
            res = requests.post(f"{self.ryu_url}/qos/rules/{dpid_str}",
                                json=rule_data, timeout=5)
            return res.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}



    def set_global_switch_qos(self, dpid, queue_id):
        """Applique un profil à TOUT le trafic d'un switch (priorité basse)."""
        dpid_str = self.format_dpid(dpid)
        clean_id = queue_id.get('id', 0) if isinstance(queue_id, dict) else queue_id
        rule_data = {
            "priority": 1,
            "match": {"dl_type": "IPv4"},
            "actions": {"queue": str(clean_id)}
        }
        res = requests.post(f"{self.ryu_url}/qos/rules/{dpid_str}", json=rule_data)
        try:
            return res.json()
        except Exception:
            return {"status": "success" if res.status_code == 200 else "error"}




    def set_network_wide_policy(self, profile_name):
        """Applique un profil de débit à tout le réseau."""
        p_upper = profile_name.upper()
        if p_upper not in QOS_PROFILES:
            return {
                "status": "error",
                "message": (f"Le profil '{profile_name}' n'existe pas. "
                            f"Profils valides : {list(QOS_PROFILES.keys())}")
            }
        q_id = QOS_PROFILES[p_upper]
        try:
            results = []
            for s_name in SWITCHES:
                dpid = int(s_name.replace('s', ''))
                res  = self.set_global_switch_qos(dpid, q_id)
                results.append({s_name: res})
            summary = f"Profil {profile_name} appliqué avec succès sur {len(results)} switchs."
            return {"status": "success", "message": summary, "response": summary}
        except Exception as e:
            return {"status": "error",
                    "message": f"Erreur lors de l'application globale : {str(e)}"}


    
    def set_backbone_dscp_queues(self, profile: str) -> dict:
        """
        Installe sur les switches BACKBONE (s7, s8, s9) une règle OpenFlow
        qui aiguille les paquets portant le DSCP du profil vers la queue
        correspondante.
        """
        p_upper = profile.upper()
        dscp_val = DSCP_MAP.get(p_upper)
        if dscp_val is None:
            return {"status": "error", "message": f"Profil '{profile}' inconnu"}

        queue_map = {
            "STANDARD": 0, 
            "BRONZE": 2,
            "GOLD": 3, 
            "SILVER": 4
        }
        queue_id = queue_map.get(p_upper, 0)

        if dscp_val == 0:
            return {"status": "ok", "message": "STANDARD — pas de règle backbone"}

        backbone_dpids = [7, 8, 9]
        results = {}

        for dpid in backbone_dpids:
            dpid_hex = self.format_dpid(dpid)
            rule_data = {
                "priority": 150,
                "match": {
                    "dl_type": "IPv4",
                    "ip_dscp": dscp_val
                },
                "actions": {
                    "queue": str(queue_id)
                }
            }
            try:
                res = requests.post(
                    f"{self.ryu_url}/qos/rules/{dpid_hex}",
                    json=rule_data, 
                    timeout=5
                )
                results[f"s{dpid}"] = res.json()
            except Exception as e:
                results[f"s{dpid}"] = {"error": str(e)}

        return {"status": "ok", "backbone_results": results}




    def set_dscp(self, ip_src: str, profile: str, dpid: int = None) -> dict:
        """
        Demande à Ryu d'installer une règle DSCP sur le switch d'accès
        de l'hôte ip_src.
        """
        p_upper = profile.upper()
        if p_upper not in DSCP_MAP:
            return {
                "status": "error",
                "message": (f"Profil DSCP '{profile}' inconnu. "
                            f"Valides : {list(DSCP_MAP.keys())}")
            }

        payload = {"ip_src": ip_src, "profile": p_upper}
        if dpid is not None:
            payload["dpid"] = int(dpid)

        try:
            res = requests.post(
                f"{self.ryu_url}/dscp/set",
                json=payload, 
                timeout=5
            )
            result = res.json()
            
            # Si la règle DSCP a bien été posée sur le switch d'accès,
            # on configure les queues correspondantes sur le backbone (s7, s8, s9).
            if result.get("status") == "ok":
                self.set_backbone_dscp_queues(p_upper)
            
            return result
        except Exception as e:
            return {"status": "error", "message": f"Erreur Ryu DSCP: {str(e)}"}




    def remove_dscp(self, ip_src: str, dpid: int = None) -> dict:
        """Supprime la règle DSCP d'un hôte (retour à STANDARD/BE)."""
        payload = {"ip_src": ip_src}
        if dpid is not None:
            payload["dpid"] = int(dpid)
        try:
            res = requests.post(f"{self.ryu_url}/dscp/remove",
                                json=payload, timeout=5)
            return res.json()
        except Exception as e:
            return {"status": "error", "message": f"Erreur Ryu DSCP remove: {str(e)}"}




    def get_dscp_status(self) -> dict:
        """Retourne toutes les règles DSCP actives sur les switches"""
        try:
            res = requests.get(f"{self.ryu_url}/dscp/status", timeout=3)
            return res.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}



    def get_total_network_throughput(self):
        try:
            res = requests.get(f"{self.ryu_url}/topology/bandwidth", timeout=1)
            all_bandwidths = res.json()
            total_sum = 0
            for dpid, ports in UPLINK_PORTS.items():
                for p_no in ports:
                    speed_data = all_bandwidths.get(dpid, {}).get(str(p_no), {})
                    total_sum += speed_data.get('total', 0)
            return {"total_mbps": round(total_sum, 2)}
        except Exception:
            return {"total_mbps": 0}




    def get_links_telemetry(self):
        """Renvoie le débit max tx ou rx pour chaque lien"""
        try:
            res = requests.get(f"{self.ryu_url}/topology/bandwidth", timeout=3).json()
            results = {}
            for l in LINKS:
                link_id    = f"{l['node1']}-{l['node2']}"
                candidates = []
                if l['node1'].startswith('s'):
                    dpid1     = str(int(l['node1'][1:]))
                    port_data = res.get(dpid1, {}).get(str(l['port1']), {})
                    if isinstance(port_data, dict):
                        candidates += [port_data.get('tx', 0), port_data.get('rx', 0)]
                if l['node2'].startswith('s'):
                    dpid2     = str(int(l['node2'][1:]))
                    port_data = res.get(dpid2, {}).get(str(l['port2']), {})
                    if isinstance(port_data, dict):
                        candidates += [port_data.get('tx', 0), port_data.get('rx', 0)]
                results[link_id] = max(candidates) if candidates else 0
            return results
        except Exception as e:
            print(f"Erreur télémétrie : {e}")
            return {}




    def get_links_telemetry_detail(self):
        """Renvoie tx et rx séparément pour chaque lien"""
        try:
            res = requests.get(f"{self.ryu_url}/topology/bandwidth", timeout=3).json()
            results = {}
            for l in LINKS:
                link_id = f"{l['node1']}-{l['node2']}"
                tx, rx  = 0, 0
                if l['node1'].startswith('s'):
                    dpid1     = str(int(l['node1'][1:]))
                    port_data = res.get(dpid1, {}).get(str(l['port1']), {})
                    if isinstance(port_data, dict):
                        tx = port_data.get('tx', 0)
                        rx = port_data.get('rx', 0)
                if l['node2'].startswith('s') and tx == 0 and rx == 0:
                    dpid2     = str(int(l['node2'][1:]))
                    port_data = res.get(dpid2, {}).get(str(l['port2']), {})
                    if isinstance(port_data, dict):
                        tx = port_data.get('rx', 0)
                        rx = port_data.get('tx', 0)
                results[link_id] = {"tx": tx, "rx": rx}
            return results
        except Exception as e:
            print(f"Erreur télémétrie détail : {e}")
            return {}


network_manager = NetworkManager()



@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/topology_config')
def get_topo():
    return jsonify({
        "switches": SWITCHES,
        "links": LINKS,
        "roles": ROLES
    })

@app.route('/link/<action>', methods=['POST'])
def control_link(action):
    data = request.json
    if action == 'break':
        return jsonify(network_manager.break_link(data['dpid'], data['port']))
    return jsonify(network_manager.restore_link(data['dpid'], data['port']))




@app.route('/qos/network_wide', methods=['POST'])
def api_network_wide_qos():
    data   = request.json
    result = network_manager.set_network_wide_policy(data['profile'])
    return jsonify(result)



@app.route('/qos/set_qos_profile', methods=['POST'])
def api_set_profile():
    data   = request.json
    result = network_manager.set_qos_profile(
        data['dpid'], data['ip'], data['queue']
    )
    return jsonify(result)



@app.route('/api/port_states')
def api_port_states():
    try:
        return jsonify(requests.get(f"{RYU_URL}/topology/port_states", timeout=2).json())
    except Exception:
        return jsonify({})




@app.route('/api/global_stats')
def api_global_stats():
    return jsonify(network_manager.get_total_network_throughput())




@app.route('/api/links_bandwidth')
def api_links_bandwidth():
    return jsonify(network_manager.get_links_telemetry())



@app.route('/api/links_bandwidth_detail')
def api_links_bandwidth_detail():
    return jsonify(network_manager.get_links_telemetry_detail())



@app.route('/dscp/set', methods=['POST'])
def api_dscp_set():
    """
    Marque les paquets de l'hôte avec le DSCP correspondant au profil,
    uniquement sur son switch d'accès. Les switches cœur propagent intact.
    """
    data    = request.json
    ip_src  = data.get('ip_src')
    profile = data.get('profile', 'STANDARD')
    dpid    = data.get('dpid')

    result = network_manager.set_dscp(ip_src, profile, dpid)
    status_code = 200 if result.get('status') == 'ok' else 400
    return jsonify(result), status_code




@app.route('/dscp/remove', methods=['POST'])
def api_dscp_remove():
    """
    Supprime le marquage DSCP (retour à STANDARD / Best Effort).
    """
    data   = request.json
    ip_src = data.get('ip_src')
    dpid   = data.get('dpid')

    result = network_manager.remove_dscp(ip_src, dpid)
    return jsonify(result)
 
 
 
   
@app.route('/dscp/backbone/set', methods=['POST'])
def api_dscp_backbone_set():
    """Installe manuellement les règles DSCP sur les switches backbone."""
    data = request.json
    profile = data.get("profile", "STANDARD")
    result = network_manager.set_backbone_dscp_queues(profile)
    return jsonify(result)




@app.route('/dscp/backbone/remove', methods=['POST'])
def api_dscp_backbone_remove():
    """Supprime les règles DSCP des switches backbone pour un profil."""
    data = request.json
    profile = data.get("profile", "STANDARD")
    result = network_manager.remove_backbone_dscp_queues(profile)
    return jsonify(result)



    
@app.route('/dscp/status', methods=['GET'])
def api_dscp_status():
    """
    GET /dscp/status
    Retourne toutes les règles DSCP actives sur les switches d'accès.
    """
    return jsonify(network_manager.get_dscp_status())
    
    
    
@app.route('/api/ai/chat', methods=['POST'])
def api_ai_chat():
    """Point d'entrée pour le chat IA depuis le dashboard."""
    try:
        data = request.json
        user_message = data.get('prompt', '')

        import sys
        langchain_path = abspath(join(dirname(__file__), '..', 'LangChain_Tool'))
        if langchain_path not in sys.path:
            sys.path.insert(0, langchain_path)

        import sdn_ai_retroactif as ai_module
        
        reponse = ai_module.traiter_message_utilisateur(user_message)

        return jsonify({"status": "success", "response": reponse})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "response": f"Erreur: {str(e)}"}), 500


 
@app.route('/api/missions', methods=['GET'])
def api_missions():
    """Retourne la liste des missions actives depuis sdn_ai_retroactif."""
    try:
        from sdn_ai_retroactif import registry
        return jsonify({
            "status": "success",
            "missions": registry.liste_missions(),
            "total": registry.nb_missions()
        })
    except Exception as e:
        return jsonify({"status": "error", "missions": [], "total": 0})



@app.route('/api/missions/<mission_id>', methods=['DELETE'])
def api_supprimer_mission(mission_id):
    """Supprime une mission depuis le dashboard."""
    try:
        from sdn_ai_retroactif import registry
        ok = registry.supprimer(mission_id.upper())
        if ok:
            return jsonify({"status": "success", "message": f"Mission {mission_id} supprimée."})
        return jsonify({"status": "error", "message": "Mission introuvable."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route('/api/logs', methods=['GET'])
def api_logs():
    try:
        from sdn_ai_retroactif import dashboard_logs
        return jsonify({"logs": list(dashboard_logs)})
    except Exception as e:
        return jsonify({"logs": []})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

