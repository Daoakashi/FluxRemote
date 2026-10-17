"""Réglages de Flux Remote, rangés dans le dossier de l'utilisateur (jamais à côté du programme).

Le jeton de session est protégé : sous Windows par DPAPI (lié au compte Windows, illisible depuis un autre compte ou
un autre PC), sous Linux par un fichier lisible seulement par l'utilisateur.
"""
import base64
import json
import os
import sys
import threading

if os.name == "nt":
    DOSSIER = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Flux Remote")
else:
    DOSSIER = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "flux-remote")
FICHIER = os.path.join(DOSSIER, "reglages.json")

DEFAUTS = {
    # serveur et session
    "hote": "", "hotes": [], "port": 47810, "cle": "", "nom_serveur": "", "jeton": "", "cgu": "",
    # accès par Internet : relais propre à ce PC Flux (vide = celui du site), adresse du site gardée en mémoire
    "relais": "", "relais.site": "",
    # apparence (mêmes clés que Flux : le thème est partagé)
    "apparence.theme": "sombre", "apparence.accent": "#2F7BFF", "apparence.police": "systeme",
    "apparence.taille_police": 13, "apparence.arrondi": 10, "apparence.densite": "normale",
    "apparence.animations": True, "apparence.vitesse_animations": 1.0,
    # alertes sur ce PC
    "alertes.mode": "sonores", "alertes.delai": 0, "alertes.pause_jusqua": 0.0, "alertes.muettes": [],
    "alertes.ouvrir_camera": True,
    # comportement
    "systeme.zone_notification": True, "systeme.demarrage": False, "systeme.demarrer_reduit": False,
    "systeme.premier_plan_video": False, "systeme.dossier_captures": "",
    "cameras.colonnes": 0, "cameras.masquees": [], "cameras.qualite": "normale",
    "maj.auto": True, "maj.ignoree": "",
    "fenetre": {},
}


def _proteger(texte):
    if not texte:
        return ""
    if os.name == "nt":
        try:
            return "dpapi:" + base64.b64encode(_dpapi(texte.encode("utf-8"), True)).decode()
        except OSError:
            pass
    return "brut:" + texte


def _lire_protege(valeur):
    if not valeur:
        return ""
    if valeur.startswith("dpapi:") and os.name == "nt":
        try:
            return _dpapi(base64.b64decode(valeur[6:]), False).decode("utf-8")
        except (OSError, ValueError):
            return ""
    return valeur[5:] if valeur.startswith("brut:") else ""


def _dpapi(octets, chiffrer):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    tampon = ctypes.create_string_buffer(octets, len(octets))
    entree, sortie = BLOB(len(octets), tampon), BLOB()
    crypt32 = ctypes.windll.crypt32
    f = crypt32.CryptProtectData if chiffrer else crypt32.CryptUnprotectData
    if not f(ctypes.byref(entree), None, None, None, None, 0x01, ctypes.byref(sortie)):  # 0x01 : pas d'interface
        raise OSError("DPAPI")
    try:
        return ctypes.string_at(sortie.pbData, sortie.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(sortie.pbData)


class Reglages:
    """Accès type dictionnaire, sûr entre fils, sauvegarde atomique, abonnés prévenus des changements."""

    def __init__(self, chemin=FICHIER):
        self.chemin = chemin
        self._v = json.loads(json.dumps(DEFAUTS))
        self._lock = threading.RLock()
        self._abonnes = []
        try:
            with open(chemin, encoding="utf-8") as f:
                lu = json.load(f)
            if isinstance(lu, dict):
                for k, v in lu.items():
                    if k in DEFAUTS:
                        self._v[k] = v
                self._v["jeton"] = _lire_protege(lu.get("jeton", ""))
        except (OSError, ValueError):
            pass

    def get(self, cle, defaut=None):
        with self._lock:
            return self._v.get(cle, DEFAUTS.get(cle, defaut))

    __getitem__ = get

    def set(self, cle, valeur, sauver=True):
        with self._lock:
            if self._v.get(cle) == valeur:
                return
            self._v[cle] = valeur
        if sauver:
            self.sauver()
        for f in list(self._abonnes):
            try:
                f(cle, valeur)
            except Exception:  # noqa: BLE001
                pass

    def maj(self, **valeurs):
        for k, v in valeurs.items():
            self.set(k, v, sauver=False)
        self.sauver()

    def abonner(self, f):
        self._abonnes.append(f)

    def sauver(self):
        with self._lock:
            d = dict(self._v)
        d["jeton"] = _proteger(d.get("jeton", ""))
        os.makedirs(DOSSIER, exist_ok=True)
        tmp = self.chemin + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.chemin)

    def oublier_serveur(self):
        self.maj(hote="", hotes=[], cle="", nom_serveur="", jeton="", relais="", **{"cameras.masquees": [], "alertes.muettes": []})


def dossier_programme():
    """Dossier où se trouve le programme (exécutable compilé ou sources)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
