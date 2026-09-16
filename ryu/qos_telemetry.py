import json
import time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.lib.ovs import bridge
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from webob import Response

"""
CUSTOM_STANDARD_CONFIG correspond à la capacités des liens que nous avons définis pour la topologie. 
Nous n'avons pas utilisé le module TC Link dans mininet.

"Numéro du Switch" : {"numéro_port" : Capacité_port en mb/s}
"""
CUSTOM_STANDARD_CONFIG = {
    "1": {"1": 70000000, "2": 300000000},
    "7": {"1": 70000000, "2": 45000000, "3": 45000000, "4": 45000000},
    "2": {"1": 30000000, "2": 30000000, "3": 30000000, "4": 45000000},
    "3": {"1": 30000000, "2": 30000000, "3": 30000000, "4": 45000000},
    "4": {"1": 30000000, "2": 30000000},
    "5": {"1": 30000000, "2": 30000000},
    "6": {"1": 30000000, "2": 30000000},
    "9": {"1": 30000000, "2": 30000000, "3": 30000000, "4": 45000000},
    "8": {"1": 45000000, "2": 45000000}
}

class QoSTelemetry(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(QoSTelemetry, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.stats     = {}
        self.bandwidths = {}
        self.setup_queue      = hub.Queue()
        self.bootstrap_thread = hub.spawn(self._bootstrap_worker)
        self.monitor_thread   = hub.spawn(self._monitor)
        kwargs['wsgi'].register(StatsAPIController, {'app': self})
        self.logger.info("=== QoS Telemetry Ready (TX+RX) ===")

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if dp.id not in self.datapaths:
                self.datapaths[dp.id] = dp
                self.setup_queue.put(dp)
        elif ev.state == DEAD_DISPATCHER:
            if dp.id in self.datapaths:
                del self.datapaths[dp.id]

    def _bootstrap_worker(self):
        while True:
            dp = self.setup_queue.get()
            self._setup_switch_queues(dp)
            hub.sleep(1)

    def _setup_switch_queues(self, dp):
        dpid_raw = str(dp.id)
        dpid_str = f"s{dpid_raw}"
        self.logger.info(f"Configuration QoS sur {dpid_str}...")
        ovs_br = bridge.OVSBridge(self.CONF, dp.id, "tcp:127.0.0.1:6640")
        ovs_br.timeout = 20
        try:
            ovs_br.init()
            ports = ovs_br.get_port_name_list()
            for p_name in ports:
                if p_name == dpid_str or p_name == dpid_raw:
                    continue
                if 'eth' not in p_name:
                    continue
                port_no = p_name.split('eth')[-1]
                if not port_no.isdigit():
                    continue

                cap = CUSTOM_STANDARD_CONFIG.get(dpid_raw, {}).get(port_no, 100_000_000)

                # Calcul des valeurs par profil selon la capacité du lien
                std_max  = cap   # STANDARD  
                std_min  = int(cap * 0.10)   # STANDARD 
                bron_max = int(cap * 0.15)   # BRONZE    
                gold_max = cap               # GOLD      
                gold_min = int(cap * 0.40)   # GOLD     
                silv_max = cap               # SILVER   
                silv_min = int(cap * 0.70)   # SILVER   

                queues_config = [
                    # queue 0 — STANDARD : trafic normal
                    {"max-rate": str(std_max),  "min-rate": str(std_min),  "priority": "3"},
                    # queue 2 — BRONZE : basse priorité, invités
                    {"max-rate": str(bron_max),                              "priority": "4"},
                    # queue 3 — GOLD : priorité absolue, latence minimale
                    {"max-rate": str(gold_max), "min-rate": str(gold_min), "priority": "0"},
                    # queue 4 — SILVER : débit maximal garanti
                    {"max-rate": str(silv_max), "min-rate": str(silv_min), "priority": "2"},
                ]

                ovs_br.del_qos(p_name)
                ovs_br.set_qos(
                    p_name,
                    type='linux-htb',
                    max_rate=str(cap),
                    queues=queues_config
                )
                self.logger.info(
                    f"  {p_name} ({cap//1_000_000}Mbps) — "
                    f"GOLD:{gold_min//1_000_000}-{gold_max//1_000_000}Mbps "
                    f"SILVER:{silv_min//1_000_000}-{silv_max//1_000_000}Mbps "
                    f"STD:{std_min//1_000_000}-{std_max//1_000_000}Mbps "
                    f"BRONZE:0-{bron_max//1_000_000}Mbps"
                )

            self.logger.info(f"--- SUCCESS : {dpid_str} configuré.")
        except Exception as e:
            self.logger.error(f"--- ECHEC {dpid_str} : {e}")

    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                req = parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY)
                dp.send_msg(req)
            hub.sleep(3)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        now = time.time()
    
        
  
        if dpid not in self.bandwidths:
            self.bandwidths[dpid] = {}
    
        for stat in ev.msg.body:
            if stat.port_no == ev.msg.datapath.ofproto.OFPP_LOCAL:
                continue
        
            port = stat.port_no
        
            # Récupère les stats précédentes
            prev = self.stats.get(dpid, {}).get(port, {
                'tx': stat.tx_bytes,  
                'rx': stat.rx_bytes, 
                'time': now
            })
        
            delta_time = now - prev['time']
        
            # Premier passage ou délai trop court
            if delta_time <= 0 or delta_time > 10:
                # Met à jour les stats sans calculer de débit
                self.stats.setdefault(dpid, {})[port] = {
                    'tx': stat.tx_bytes,
                    'rx': stat.rx_bytes,
                    'time': now
                }
                self.bandwidths[dpid][port] = {'tx': 0, 'rx': 0, 'total': 0}
                continue
        
            # Calcule les différences (gère les overflows)
            delta_tx = stat.tx_bytes - prev['tx']
            delta_rx = stat.rx_bytes - prev['rx']
        
            if delta_tx < 0:
                delta_tx = stat.tx_bytes
            if delta_rx < 0:
                delta_rx = stat.rx_bytes
        
            # Calcule les débits en Mbps
            mbps_tx = (delta_tx * 8) / (delta_time * 1_000_000)
            mbps_rx = (delta_rx * 8) / (delta_time * 1_000_000)
        
            # Stocke les stats
            self.stats.setdefault(dpid, {})[port] = {
                'tx': stat.tx_bytes,
                'rx': stat.rx_bytes,
                'time': now
            }
        
            self.bandwidths[dpid][port] = {
                'tx': round(mbps_tx, 2),
                'rx': round(mbps_rx, 2),
                'total': round(mbps_tx + mbps_rx, 2)
            }
        
           


class StatsAPIController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(StatsAPIController, self).__init__(req, link, data, **config)
        self.app = data['app']
    
    
    
    #Route pour récupérer les débit
    @route('topology', '/topology/bandwidth', methods=['GET'])
    def get_bandwidth(self, req, **kwargs):
        return Response(
            content_type='application/json',
            body=json.dumps(self.app.bandwidths).encode('utf-8')
        )
        
        
    @route('stats', '/stats/port/all', methods=['GET'])
    def get_port_stats_all(self, req, **kwargs):
        """
        Retourne les statistiques complètes de tous les ports.
        Format attendu par collecteur.py :
        {
            "1": [{"tx_dropped": 0, "rx_dropped": 0, "tx_errors": 0, "rx_errors": 0, ...}],
            "2": [...]
        }
        """
        result = {}
        for dpid, ports in self.app.stats.items():
            dpid_str = str(dpid)
            result[dpid_str] = []
            for port, stats in ports.items():
                result[dpid_str].append({
                    "port_no": port,
                    "tx_dropped": 0, 
                    "rx_dropped": 0,
                    "tx_errors": 0,
                    "rx_errors": 0,
                    "tx_bytes": stats.get('tx', 0),
                    "rx_bytes": stats.get('rx', 0),
                })
        
        return Response(
            content_type='application/json',
            body=json.dumps(result).encode('utf-8')
        )
