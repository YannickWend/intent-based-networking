from extracteur_qos import extract_qos
from extracteur_switchs import extract_switches
from extracteur_hotes import extract_hosts
from extracteur_connection_hotes import get_locations
from extracteur_routes import get_path_between
from extracteur_switch_details import get_switch_details
from extracteur_ip import get_ip_from_hosts
from extracteur_intention import extract_intent_profile
class Extracteur:
    """
    Classe utilitaire pour extraire sélectivement les entités SDN 
    depuis un texte en langage naturel.
    """

    @staticmethod
    def get_hosts(text):
        """Retourne uniquement la liste des IDs d'hôtes (ex: ['h1', 'h7'])."""
        return extract_hosts(text)

    @staticmethod
    def get_qos_profile(text):
        """Retourne uniquement le profil QoS détecté (ex: 'GOLD')."""
        return extract_qos(text)

    @staticmethod
    def get_switches(text):
        """Retourne uniquement la liste des DPID de switchs (ex: [1, 7])."""
        return extract_switches(text)
        
    @staticmethod
    def get_connections(text):
        """Retourne uniquement la les connections des hôtes """
        return get_locations(text)
    
    @staticmethod
    def get_paths(text):
        """Retourne uniquement le chemin entre deux hotes """
        return get_path_between(text)
        
    @staticmethod
    def get_sw_details(sw_list):
        """Retourne les ports et les connections d'un switch """
        return get_switch_details(sw_list)
        
    @staticmethod
    def get_ips(hotes_list):
        """Traduit une liste d'IDs d'hôtes en adresses IP."""
        return get_ip_from_hosts(hotes_list)
    @staticmethod
    def get_intent_profile(text):
        return extract_intent_profile(text)
