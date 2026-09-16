"""
collecteur.py — Fix clé "total" dans /topology/bandwidth
"""
import requests

BACKBONE_SWITCHES = ["7", "8", "9"]
CAPACITE_SWITCH = {
    "1": 70,    # 70 Mbps 
    "2": 45,    # 45 Mbps 
    "3": 45,    # 45 Mbps 
    "4": 30,    # 30 Mbps
    "5": 30,    # 30 Mbps
    "6": 30,    # 30 Mbps
    "7": 70,    # 70 Mbps 
    "8": 45,    # 45 Mbps
    "9": 45,    # 45 Mbps 
}


class NetworkCollector:
    def __init__(self, api_base_url="http://localhost:5000",
                 ryu_base_url="http://localhost:8080"):
        self.api_url = api_base_url
        self.ryu_url = ryu_base_url

    def get_all_metrics(self) -> dict:
        metrics = {"port_states": {}, "bandwidth": {}, "status": "OFFLINE"}
        try:
            r1 = requests.get(f"{self.api_url}/api/port_states", timeout=2)
            if r1.status_code == 200:
                metrics["port_states"] = r1.json()
            r2 = requests.get(f"{self.api_url}/api/links_bandwidth", timeout=2)
            if r2.status_code == 200:
                metrics["bandwidth"] = r2.json()
            metrics["status"] = "ONLINE"
        except Exception as e:
            print(f"[Collector] inaccessible : {e}")
        return metrics

    def get_network_snapshot(self) -> dict:
        """
        Format /topology/bandwidth produit par qos_telemetry :
          { dpid_int_as_str : { port_no_int_as_str : {"total": mbps} } }
        On prend le max de "total" sur tous les ports.
        """
        snapshot = {"status": "OFFLINE", "switches": {}}
        try:
            res = requests.get(f"{self.ryu_url}/topology/bandwidth", timeout=3)
            raw = res.json() if res.status_code == 200 else {}

            for sw_str in [str(i) for i in range(1, 10)]:
                tx_mbps = 0.0
                # Les clés du JSON peuvent être int ou str selon sérialisation
                ports = raw.get(sw_str) or raw.get(int(sw_str), {})
                for port_data in ports.values():
                    if isinstance(port_data, dict):
                        # qos_telemetry stocke {"total": mbps}
                        val = port_data.get("total",
                              port_data.get("tx",
                              port_data.get("rx", 0)))
                    else:
                        val = float(port_data)
                    tx_mbps = max(tx_mbps, float(val or 0))

                cap  = CAPACITE_SWITCH.get(sw_str, 100)
                util = min(tx_mbps / cap, 1.0) if cap > 0 else 0.0

                snapshot["switches"][sw_str] = {
                    "tx_mbps":     round(tx_mbps, 2),
                    "rx_mbps":     round(tx_mbps, 2),
                    "tx_dropped":  0,
                    "rx_dropped":  0,
                    "tx_errors":   0,
                    "rx_errors":   0,
                    "utilisation": round(util, 3),
                    "type": "backbone" if sw_str in BACKBONE_SWITCHES else "access",
                }
            snapshot["status"] = "ONLINE"
        except Exception as e:
            print(f"[Collector] Erreur snapshot : {e}")
        return snapshot

    def get_debit_intention(self, ip_a: str, ip_b: str) -> float:
        try:
            from network_config import HOST_IP_TO_ACCESS_SWITCH
            snap = self.get_network_snapshot()
            if snap["status"] == "OFFLINE":
                return 0.0
            max_d = 0.0
            for ip in [ip_a, ip_b]:
                sw = HOST_IP_TO_ACCESS_SWITCH.get(ip, "")
                num = sw.replace("s", "")
                d = snap["switches"].get(num, {}).get("tx_mbps", 0.0)
                max_d = max(max_d, d)
            return max_d
        except Exception:
            return 0.0
            
