"""Un PC Flux relié à Flux Remote : son adresse, sa clé, sa session et ce qu'on sait de lui en ce moment.

Flux Remote peut suivre plusieurs PC Flux à la fois (un directeur et tous ses établissements). Chaque serveur garde
sa propre session et ses propres droits ; les caméras sont repérées par « clé du serveur|identifiant ».
"""
from . import api as module_api


class Serveur:
    CHAMPS = ("cle", "nom", "hote", "hotes", "port", "relais", "jeton", "cgu", "affiche")

    def __init__(self, d):
        self.cle = d["cle"]
        self.nom = d.get("nom") or "Flux"
        self.hote = d.get("hote") or ""
        self.hotes = list(d.get("hotes") or [])
        self.port = int(d.get("port") or 47810)
        self.relais = d.get("relais") or ""
        self.jeton = d.get("jeton") or ""
        self.cgu = d.get("cgu") or ""
        self.affiche = d.get("affiche", True) is not False
        # état en cours (pas enregistré)
        self.api, self.ecoute = None, None
        self.info, self.profil, self.etat_pilotage = None, {}, None
        self.cameras = []
        self.pilotage_autorise, self.sans_entreprise, self.detection_globale, self.en_ligne = False, False, True, True

    def vers_dict(self):
        return {k: getattr(self, k) for k in self.CHAMPS}

    @property
    def actif(self):
        return self.api is not None

    def uid(self, cam_id):
        return f"{self.cle}|{cam_id}"

    def nouvelle_api(self, jeton=None):
        return module_api.Api(self.hote, self.port, self.cle, jeton if jeton is not None else self.jeton,
                              relais=self.relais)

    def texte_route(self):
        route = self.api.route if self.api is not None else ""
        if route == "internet":
            return "par Internet (relais Flux)"
        if route == "direct":
            return f"réseau local {self.hote}:{self.port}"
        return (self.hote or "par Internet") + (f":{self.port}" if self.hote else "")
