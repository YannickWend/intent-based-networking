#!/usr/bin/env python3
import json
from webob import Response
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from network_config import ACCESS_SWITCHES, DSCP_MAP, HOST_IP_TO_ACCESS_SWITCH


class SimpleSwitch13Custom(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13Custom, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.switches    = {}
        self.port_states = {}
        self.dscp_rules  = {}

        wsgi = kwargs['wsgi']
        wsgi.register(APIController, {'app': self})
        self.logger.info("=== Contrôleur SDN ===")



    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.switches[dp.id] = dp
        self.install_table_miss(dp)
        self._replay_dscp_rules(dp)


    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _port_status_handler(self, ev):
        msg     = ev.msg
        dp      = msg.datapath
        port_no = msg.desc.port_no
        self.port_states.setdefault(dp.id, {})
        if msg.reason in [dp.ofproto.OFPPR_ADD, dp.ofproto.OFPPR_MODIFY]:
            state = 'DOWN' if msg.desc.config & dp.ofproto.OFPPC_PORT_DOWN else 'FORWARD'
            self.port_states[dp.id][port_no] = state
        elif msg.reason == dp.ofproto.OFPPR_DELETE:
            self.port_states[dp.id][port_no] = 'DOWN'



    def install_table_miss(self, dp):
        parser  = dp.ofproto_parser
        ofp     = dp.ofproto
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        inst    = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod     = parser.OFPFlowMod(datapath=dp, priority=0, table_id=1,
                                    match=match, instructions=inst)
        dp.send_msg(mod)

 

    def add_flow(self, dp, priority, match, actions):
        parser = dp.ofproto_parser
        inst   = [parser.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod    = parser.OFPFlowMod(datapath=dp, priority=priority, table_id=1,
                                   match=match, instructions=inst, idle_timeout=15)
        dp.send_msg(mod)

    

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg     = ev.msg
        dp      = msg.datapath
        ofp     = dp.ofproto
        parser  = dp.ofproto_parser
        in_port = msg.match['in_port']
        pkt     = packet.Packet(msg.data)
        eth     = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        self.mac_to_port.setdefault(dp.id, {})
        self.mac_to_port[dp.id][eth.src] = in_port

        out_port = (self.mac_to_port[dp.id][eth.dst]
                    if eth.dst in self.mac_to_port[dp.id]
                    else ofp.OFPP_FLOOD)

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst)
            self.add_flow(dp, 1, match, actions)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        out  = parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                   in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)


    # DSCP — installation d'une règle de marquage aux switch d'accès uniquement
	
    def install_dscp_rule(self, dpid: int, ip_src: str, dscp_value: int) -> bool:
        """
        Installe une flow rule priorité 200 sur le switch d'accès dpid :
          match  : paquet IPv4 avec ip_src donné
          action : set_field(ip_dscp) + output NORMAL

        Les switches cœur (s7, s8, s9) propagent le champ DSCP intact.
        OVS/linux-htb les envoie dans la bonne queue selon la conf QoS.

        Retourne True si succès, False si switch inconnu ou non-accès.
        """
        if dpid not in self.switches:
            self.logger.warning(f"[DSCP] Switch s{dpid} inconnu — règle non installée.")
            return False

        dpid_name = f"s{dpid}"
        if dpid_name not in ACCESS_SWITCHES:
            self.logger.warning(
                f"[DSCP] {dpid_name} n'est pas un switch d'accès — marquage refusé."
            )
            return False

        dp     = self.switches[dpid]
        parser = dp.ofproto_parser

        match = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=ip_src
        )
        actions = [
            parser.OFPActionSetField(ip_dscp=dscp_value),
            parser.OFPActionOutput(dp.ofproto.OFPP_NORMAL)
        ]

        # idle_timeout=0 → règle permanente jusqu'au prochain flush explicite
        inst = [parser.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod  = parser.OFPFlowMod(
            datapath=dp,
            priority=200,
            table_id=1,
            match=match,
            instructions=inst,
            idle_timeout=0,
            hard_timeout=0
        )
        dp.send_msg(mod)


        self.dscp_rules.setdefault(dpid, {})[ip_src] = dscp_value
        self.logger.info(
            f"[DSCP] OK s{dpid} | {ip_src} → DSCP {dscp_value} "
            f"({self._dscp_name(dscp_value)})"
        )
        return True

    def remove_dscp_rule(self, dpid: int, ip_src: str) -> bool:
        """Supprime la règle DSCP pour un hôte (retour DSCP=0, profil STANDARD)."""
        if dpid not in self.switches:
            return False

        dp     = self.switches[dpid]
        parser = dp.ofproto_parser
        ofp    = dp.ofproto

        match = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=ip_src
        )
        mod = parser.OFPFlowMod(
            datapath=dp,
            command=ofp.OFPFC_DELETE,
            priority=200,
            table_id=1,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
            match=match
        )
        dp.send_msg(mod)

        self.dscp_rules.get(dpid, {}).pop(ip_src, None)
        self.logger.info(f"[DSCP] Supprimé s{dpid} | {ip_src}")
        return True

    def _replay_dscp_rules(self, dp):
        """Rejoue toutes les règles DSCP lors de la reconnexion d'un switch."""
        for ip_src, dscp_value in self.dscp_rules.get(dp.id, {}).items():
            self.install_dscp_rule(dp.id, ip_src, dscp_value)

    @staticmethod
    def _dscp_name(value: int) -> str:
        reverse = {v: k for k, v in DSCP_MAP.items()}
        return reverse.get(value, f"custom({value})")


    def surgical_flush(self):
        """
        Supprime uniquement les flows L2 appris (priorité 1).
        Les règles DSCP (priorité 200) sont intentionnellement conservées.
        """
        for dp in self.switches.values():
            parser = dp.ofproto_parser
            ofp    = dp.ofproto

            mod = parser.OFPFlowMod(
                datapath=dp,
                command=ofp.OFPFC_DELETE_STRICT,
                priority=1,
                table_id=1,
                out_port=ofp.OFPP_ANY,
                out_group=ofp.OFPG_ANY,
                match=parser.OFPMatch()
            )
            dp.send_msg(mod)
        self.mac_to_port = {}
        self.logger.info("Flows L2 supprimés — règles DSCP conservées.")


    def break_link(self, dpid, port_no):
        if dpid not in self.switches: return False
        dp   = self.switches[dpid]
        port = dp.ports.get(port_no)
        if not port: return False
        dp.send_msg(dp.ofproto_parser.OFPPortMod(
            datapath=dp, port_no=port_no, hw_addr=port.hw_addr,
            config=dp.ofproto.OFPPC_PORT_DOWN,
            mask=dp.ofproto.OFPPC_PORT_DOWN, advertise=0
        ))
        self.port_states.setdefault(dpid, {})[port_no] = 'DOWN'
        return True

    def restore_link(self, dpid, port_no):
        if dpid not in self.switches: return False
        dp   = self.switches[dpid]
        port = dp.ports.get(port_no)
        if not port: return False
        dp.send_msg(dp.ofproto_parser.OFPPortMod(
            datapath=dp, port_no=port_no, hw_addr=port.hw_addr,
            config=0, mask=dp.ofproto.OFPPC_PORT_DOWN, advertise=0
        ))
        self.port_states.setdefault(dpid, {})[port_no] = 'FORWARD'
        return True


# API REST — exposée à network-manager.py via Ryu WSGI (port 8080)


class APIController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(APIController, self).__init__(req, link, data, **config)
        self.app = data['app']



    @route('topology', '/topology/port_states', methods=['GET'])
    def get_port_states(self, req, **kwargs):
        return Response(
            content_type='application/json',
            body=json.dumps(self.app.port_states).encode('utf-8')
        )



    @route('link_break', '/link/break', methods=['POST'])
    def break_link_api(self, req, **kwargs):
        data    = json.loads(req.body.decode('utf-8'))
        success = self.app.break_link(int(data['dpid']), int(data['port']))
        return Response(
            content_type='application/json',
            body=json.dumps({'status': 'ok' if success else 'failed'}).encode('utf-8')
        )

    @route('link_restore', '/link/restore', methods=['POST'])
    def restore_link_api(self, req, **kwargs):
        data    = json.loads(req.body.decode('utf-8'))
        success = self.app.restore_link(int(data['dpid']), int(data['port']))
        return Response(
            content_type='application/json',
            body=json.dumps({'status': 'ok' if success else 'failed'}).encode('utf-8')
        )

    # ----------------------------------------------------------------
    # POST /dscp/set
    # Body: { "ip_src": "10.0.0.1", "profile": "GOLD" }
    #    ou { "ip_src": "10.0.0.1", "dscp_value": 46 }
    #    ou { "ip_src": "10.0.0.1", "profile": "GOLD", "dpid": 1 }
    #
    # Si dpid absent → déduit automatiquement via HOST_IP_TO_ACCESS_SWITCH
    # ----------------------------------------------------------------

    @route('dscp_set', '/dscp/set', methods=['POST'])
    def dscp_set_api(self, req, **kwargs):
        try:
            data   = json.loads(req.body.decode('utf-8'))
            ip_src = data.get('ip_src')
            if not ip_src:
                return self._json_resp(400, {'status': 'error',
                                             'message': "Champ 'ip_src' requis."})

            # Résolution DSCP
            if 'profile' in data:
                profile = data['profile'].upper()
                if profile not in DSCP_MAP:
                    return self._json_resp(400, {
                        'status': 'error',
                        'message': f"Profil '{profile}' inconnu. Valides : {list(DSCP_MAP.keys())}"
                    })
                dscp_value = DSCP_MAP[profile]
            elif 'dscp_value' in data:
                dscp_value = int(data['dscp_value'])
            else:
                return self._json_resp(400, {'status': 'error',
                                             'message': "Fournir 'profile' ou 'dscp_value'."})

            # Résolution DPID
            if 'dpid' in data:
                dpid = int(data['dpid'])
            else:
                sw_name = HOST_IP_TO_ACCESS_SWITCH.get(ip_src)
                if sw_name is None:
                    return self._json_resp(404, {
                        'status': 'error',
                        'message': f"Aucun switch d'accès connu pour {ip_src}."
                    })
                dpid = int(sw_name.replace('s', ''))

            success = self.app.install_dscp_rule(dpid, ip_src, dscp_value)
            return self._json_resp(200 if success else 404, {
                'status':     'ok' if success else 'error',
                'ip_src':     ip_src,
                'dpid':       dpid,
                'dscp_value': dscp_value,
                'profile':    self.app._dscp_name(dscp_value)
            })

        except Exception as e:
            return self._json_resp(500, {'status': 'error', 'message': str(e)})



    @route('dscp_remove', '/dscp/remove', methods=['POST'])
    def dscp_remove_api(self, req, **kwargs):
        try:
            data   = json.loads(req.body.decode('utf-8'))
            ip_src = data.get('ip_src')
            if not ip_src:
                return self._json_resp(400, {'status': 'error',
                                             'message': "Champ 'ip_src' requis."})

            if 'dpid' in data:
                dpid = int(data['dpid'])
            else:
                sw_name = HOST_IP_TO_ACCESS_SWITCH.get(ip_src)
                dpid    = int(sw_name.replace('s', '')) if sw_name else None

            if dpid is None:
                return self._json_resp(404, {
                    'status': 'error',
                    'message': f"Switch introuvable pour {ip_src}."
                })

            success = self.app.remove_dscp_rule(dpid, ip_src)
            return self._json_resp(200, {
                'status': 'ok' if success else 'error',
                'ip_src': ip_src,
                'dpid':   dpid
            })
        except Exception as e:
            return self._json_resp(500, {'status': 'error', 'message': str(e)})



    @route('dscp_status', '/dscp/status', methods=['GET'])
    def dscp_status_api(self, req, **kwargs):
        result = {}
        for dpid, rules in self.app.dscp_rules.items():
            result[f"s{dpid}"] = {
                ip: {'dscp': v, 'profile': self.app._dscp_name(v)}
                for ip, v in rules.items()
            }
        return Response(
            content_type='application/json',
            body=json.dumps(result).encode('utf-8')
        )

  

    @staticmethod
    def _json_resp(status_code, body_dict):
        return Response(
            status=status_code,
            content_type='application/json',
            body=json.dumps(body_dict).encode('utf-8')
        )
