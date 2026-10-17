"""Connexion chiffrée au serveur Flux (le même que FluxLite) et appels de l'API.

La sécurité repose sur la clé du serveur : l'empreinte de la clé publique du PC Flux, affichée dans sa page FluxLite.
Avant d'envoyer le moindre octet (mot de passe, jeton), on vérifie que le serveur présente exactement cette clé.
Sinon la connexion est coupée : impossible de se faire passer pour le PC Flux, même sur un réseau public.

Deux chemins mènent au PC Flux, choisis tout seuls à chaque connexion :
* direct, sur le même réseau (adresse locale du PC Flux) ;
* par Internet, au travers du relais Flux, quand le réseau local ne répond pas. Le relais colle simplement deux
  connexions bout à bout : la poignée de main TLS et la vérification de la clé se font de bout en bout avec le PC
  Flux, le relais ne voit que des octets chiffrés.
"""

import hashlib
import hmac
import http.client
import json
import platform
import re
import socket
import ssl
import threading
import time
import urllib.parse

from .version import SITE, VERSION

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PORT_DEFAUT = 47810
VERSION_CGU = "2026-10"
PROTOCOLE_RELAIS = "FLUXRELAIS/1"
PORT_RELAIS = 443
URL_RELAIS_SITE = SITE.rstrip("/") + "/relais.json"
DIRECT_ESSAI = 3.0        # secondes laissées au réseau local avant de passer par Internet
DIRECT_OUBLI = 120.0      # après un échec direct, on passe par Internet pendant ce temps sans réessayer


class ErreurApi(Exception):
    def __init__(self, message, code=0, statut=None):
        super().__init__(message)
        self.code, self.statut = code, statut


class ErreurRelais(ErreurApi):
    """Le relais répond, mais ne peut pas joindre ce PC Flux (éteint, hors ligne…)."""


class CleIncorrecte(ErreurApi):
    def __init__(self):
        super().__init__("Attention : ce serveur ne présente pas la bonne clé. Connexion refusée pour votre sécurité. "
                         "Vérifiez la clé dans Flux (page FluxLite).", 495)


# --- clé du serveur -----------------------------------------------------------------------------
def base32(octets):
    sortie, tampon, bits = [], 0, 0
    for o in octets:
        tampon = (tampon << 8) | o
        bits += 8
        while bits >= 5:
            bits -= 5
            sortie.append(ALPHABET[(tampon >> bits) & 31])
        tampon &= (1 << bits) - 1
    if bits:
        sortie.append(ALPHABET[(tampon << (5 - bits)) & 31])
    return "".join(sortie)


def normaliser_cle(texte):
    t = re.sub(r"[\s\-_.]", "", str(texte or "")).upper()
    return t.translate(str.maketrans({"O": "0", "I": "1", "L": "1", "U": "V"}))


def cle_valide(cle):
    return len(cle) == 32 and all(c in ALPHABET for c in cle)


def formater_cle(cle):
    return "-".join(cle[i:i + 4] for i in range(0, len(cle), 4))


def cle_du_certificat(der):
    """Même calcul que Flux et FluxLite : SHA-256 de la clé publique (SubjectPublicKeyInfo), 160 premiers bits."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    cle_publique = x509.load_der_x509_certificate(der).public_key()
    spki = cle_publique.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base32(hashlib.sha256(spki).digest()[:20])


def lire_adresse_relais(texte, port_defaut=PORT_RELAIS):
    """« relais.exemple.be », « relais.exemple.be:8443 », « [2001:db8::1]:443 » -> (hôte, port) ou None."""
    t = str(texte or "").strip()
    for prefixe in ("https://", "http://", "fluxrelais://"):
        if t.lower().startswith(prefixe):
            t = t[len(prefixe):]
    t = t.split("/")[0].strip()
    if not t:
        return None
    if t.startswith("["):
        hote, _, reste = t[1:].partition("]")
        port = reste[1:] if reste.startswith(":") else ""
    elif t.count(":") == 1:
        hote, port = t.split(":")
    else:
        hote, port = t, ""
    try:
        port = int(port) if port else int(port_defaut)
    except ValueError:
        return None
    if not hote or not 0 < port < 65536 or not re.fullmatch(r"[A-Za-z0-9.\-:]+", hote):
        return None
    return hote, port


def texte_relais(adresse):
    if not adresse:
        return ""
    hote, port = adresse
    hote = f"[{hote}]" if ":" in hote else hote
    return hote if port == PORT_RELAIS else f"{hote}:{port}"


# Relais publié sur le site (lu au démarrage, gardé dans les réglages) et chemin utilisé par chaque serveur.
_relais = {"site": None}
_echecs_directs = {}      # (hôte, port) -> heure du dernier échec direct
ROUTES = {}               # clé du serveur -> "direct" ou "internet" (dernière connexion réussie)
_verrou = threading.Lock()


def definir_relais_site(texte):
    _relais["site"] = lire_adresse_relais(texte)


def relais_site():
    return _relais["site"]


def charger_relais_site(delai=12):
    """Lit l'adresse du relais publiée sur le site. Renvoie le texte (vide si aucun relais publié) ou None si le
    site est injoignable."""
    import urllib.request
    try:
        with urllib.request.urlopen(URL_RELAIS_SITE, timeout=delai) as r:
            d = json.loads(r.read(65536).decode("utf-8"))
    except Exception:  # noqa: BLE001 - hors ligne : on garde la dernière adresse connue
        return None
    adresse = lire_adresse_relais(d.get("hote") or "", d.get("port") or PORT_RELAIS) \
        if isinstance(d, dict) and d.get("actif", True) else None
    _relais["site"] = adresse
    return texte_relais(adresse)


def _lire_ligne(sock, maximum=4096):
    octets = bytearray()
    while len(octets) < maximum:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("connexion fermée par le relais")
        if b == b"\n":
            return octets.decode("utf-8", "replace").strip()
        octets += b
    raise ConnectionError("réponse du relais trop longue")


def socket_relais(adresse, cle, delai=12):
    """Connexion au PC Flux au travers du relais : renvoie une socket prête pour la poignée de main TLS."""
    s = socket.create_connection(adresse, timeout=delai)
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.sendall(f"{PROTOCOLE_RELAIS} CLIENT {cle}\n".encode())
        ligne = _lire_ligne(s)
    except BaseException:
        s.close()
        raise
    if ligne == "OK":
        return s
    s.close()
    if ligne.startswith("ERREUR"):
        morceaux = ligne.split(" ", 2)
        raise ErreurRelais(morceaux[2] if len(morceaux) > 2 else "Le relais refuse la connexion.",
                           int(morceaux[1]) if len(morceaux) > 1 and morceaux[1].isdigit() else 502)
    raise ErreurRelais("Le relais a répondu de façon inattendue.", 502)


class _ConnexionTLS(http.client.HTTPSConnection):
    """HTTPS sur une socket déjà ouverte (directe ou relayée)."""

    def __init__(self, ouvrir, contexte, delai):
        super().__init__("flux", context=contexte, timeout=delai)
        self._ouvrir, self._ctx_tls = ouvrir, contexte

    def connect(self):
        sock = self._ouvrir()
        sock.settimeout(self.timeout)
        self.sock = self._ctx_tls.wrap_socket(sock, server_hostname=None)


def lire_lien(texte):
    """Lien d'appairage (contenu du QR code de Flux) -> (adresses, port, clé, nom) ou None."""
    try:
        u = urllib.parse.urlsplit(texte.strip())
        if u.scheme != "fluxlite" or u.netloc != "appairer":
            return None
        q = urllib.parse.parse_qs(u.query)
        cle = normaliser_cle(q.get("k", [""])[0])
        hotes = [h.strip() for h in q.get("h", [""])[0].split(",") if h.strip()]
        if not cle_valide(cle) or not hotes:
            return None
        return hotes, int(q.get("p", [PORT_DEFAUT])[0]), cle, q.get("n", ["Flux"])[0]
    except (ValueError, IndexError):
        return None


def relais_du_lien(texte):
    """Relais indiqué dans le lien d'appairage (seulement quand le PC Flux utilise son propre relais)."""
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(texte.strip()).query)
        return texte_relais(lire_adresse_relais(q.get("r", [""])[0]))
    except ValueError:
        return ""


def id_camera(nom):
    import base64
    return base64.urlsafe_b64encode(nom.encode("utf-8")).decode().rstrip("=")


def appareil():
    systeme = platform.system()
    version = platform.release()
    if systeme == "Windows":
        try:
            build = int(platform.version().split(".")[-1])
            version = "11" if build >= 22000 else version
        except ValueError:
            pass
    return f"Flux Remote · {platform.node() or 'PC'} · {systeme} {version}".strip()


def message_erreur(e):
    if isinstance(e, ErreurApi):
        return str(e)
    if isinstance(e, ConnectionError) and "relais" in str(e):
        return "Le relais Flux a coupé la connexion. Réessayez dans un instant."
    if isinstance(e, socket.gaierror):
        return "Adresse introuvable. Vérifiez l'adresse du PC Flux."
    if isinstance(e, ConnectionRefusedError):
        return ("Le PC Flux refuse la connexion. Le serveur FluxLite est-il activé (page FluxLite de Flux) et le port "
                "ouvert dans le pare-feu ?")
    if isinstance(e, (TimeoutError, socket.timeout)):
        return "Le PC Flux ne répond pas (délai dépassé). Est-il allumé et joignable depuis ce réseau ?"
    if isinstance(e, ssl.SSLError):
        return "Connexion sécurisée impossible avec ce serveur."
    if isinstance(e, OSError):
        return f"Problème de réseau : {e.strerror or e}"
    return str(e) or e.__class__.__name__


# --- client --------------------------------------------------------------------------------------
class Api:
    def __init__(self, hote, port, cle, jeton=None, relais=None, mode="auto"):
        """relais : adresse du relais propre à ce PC Flux (vide = celui du site). mode : auto, direct ou internet."""
        self.hote, self.port, self.cle, self.jeton = (hote or "").strip(), int(port), cle, jeton
        self.relais = lire_adresse_relais(relais) if relais else None
        self.mode = mode
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE  # l'identité est vérifiée par la clé, juste après la poignée de main

    @property
    def adresse_relais(self):
        return self.relais or relais_site()

    @property
    def route(self):
        return ROUTES.get(self.cle, "")

    def _ouvrir(self, delai):
        """Socket brute vers le PC Flux : d'abord le réseau local, puis Internet par le relais."""
        relais_connu = self.adresse_relais
        relais = relais_connu if self.mode != "direct" else None
        cle_directe = (self.hote, self.port)
        direct = self.hote and self.mode != "internet"
        if direct and relais:
            with _verrou:
                echec = _echecs_directs.get(cle_directe, 0)
                direct = time.time() - echec > DIRECT_OUBLI  # réseau local raté il y a peu : Internet directement
                if direct and echec:
                    _echecs_directs[cle_directe] = time.time()  # nouvel essai : les autres requêtes passent par Internet
        erreur = None
        if direct:
            try:
                s = socket.create_connection(cle_directe, timeout=min(delai, DIRECT_ESSAI) if relais_connu else delai)
                with _verrou:
                    _echecs_directs.pop(cle_directe, None)
                ROUTES[self.cle] = "direct"
                return s
            except OSError as e:
                erreur = e
                with _verrou:
                    _echecs_directs[cle_directe] = time.time()
        if relais:
            s = socket_relais(relais, self.cle, delai)
            ROUTES[self.cle] = "internet"
            return s
        if erreur is not None:
            raise erreur
        raise ErreurApi("Ce PC Flux n'est pas joignable : aucune adresse locale et aucun relais Internet connu.")

    def connexion(self, delai=12):
        c = _ConnexionTLS(lambda: self._ouvrir(delai), self._ctx, delai)
        try:
            c.connect()
        except ssl.SSLError:
            c.close()
            raise
        der = c.sock.getpeercert(binary_form=True)
        if not der or not hmac.compare_digest(cle_du_certificat(der), self.cle):
            c.close()
            raise CleIncorrecte()
        return c

    def _entetes(self, json_=False):
        e = {"User-Agent": f"FluxRemote/{VERSION}", "Accept": "application/json"}
        if json_:
            e["Content-Type"] = "application/json"
        if self.jeton:
            e["Authorization"] = f"Bearer {self.jeton}"
        return e

    def requete(self, methode, chemin, corps=None, delai=12, brut=False):
        c = self.connexion(delai)
        try:
            donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
            c.request(methode, "/api/v1" + chemin, donnees, self._entetes(corps is not None))
            r = c.getresponse()
            contenu = r.read()
        finally:
            c.close()
        if r.status >= 400:
            try:
                d = json.loads(contenu)
            except ValueError:
                d = {}
            raise ErreurApi(d.get("erreur") or f"Erreur {r.status}", r.status, d.get("statut"))
        if brut:
            return contenu
        return json.loads(contenu) if contenu else {}

    # --- serveur et compte ---------------------------------------------------------------------
    def info(self):
        return self.requete("GET", "/info")

    def connecter(self, mail, mdp):
        return self.requete("POST", "/connexion", {"mail": mail, "mot_de_passe": mdp, "appareil": appareil(),
                                                    "version_app": f"Remote {VERSION}"})

    def inscrire(self, mail, mdp, nom, prenom, societe):
        return self.requete("POST", "/inscription", {"mail": mail, "mot_de_passe": mdp, "nom": nom, "prenom": prenom,
                                                      "societe": societe, "cgu_version": VERSION_CGU,
                                                      "appareil": appareil(), "version_app": f"Remote {VERSION}"})

    def deconnecter(self):
        return self.requete("POST", "/deconnexion", {})

    def profil(self):
        return self.requete("GET", "/compte")

    def modifier_profil(self, **champs):
        return self.requete("PATCH", "/compte", champs)

    def changer_mdp(self, ancien, nouveau):
        return self.requete("POST", "/compte/mot_de_passe", {"ancien": ancien, "nouveau": nouveau})

    def revoquer(self, session_id=None):
        return self.requete("POST", "/compte/sessions/revoquer", {"id": session_id if session_id else "autres"})

    def exporter(self):
        return self.requete("GET", "/compte/export", brut=True)

    def supprimer_compte(self, mdp):
        return self.requete("DELETE", "/compte", {"mot_de_passe": mdp})

    # --- caméras et pilotage --------------------------------------------------------------------------
    def cameras(self):
        return self.requete("GET", "/cameras")

    def image(self, cam_id, largeur=640):
        try:
            return self.requete("GET", f"/cameras/{cam_id}/image?largeur={largeur}", brut=True, delai=10)
        except ErreurApi as e:
            if e.code in (404, 503):
                return None
            raise

    def pilotage(self):
        return self.requete("GET", "/pilotage")

    def piloter(self, cle, valeur, camera=None):
        corps = {"cle": cle, "valeur": valeur}
        if camera:
            corps["camera"] = camera
        return self.requete("POST", "/pilotage", corps)

    # --- journal et alertes ---------------------------------------------------------------------------
    def journal(self, avant=None, camera=None, limite=60):
        q = [f"limite={limite}"] + ([f"avant={avant}"] if avant else []) + ([f"camera={camera}"] if camera else [])
        return self.requete("GET", "/journal?" + "&".join(q))

    def photo(self, jid):
        try:
            return self.requete("GET", f"/journal/{jid}/photo", brut=True)
        except ErreurApi as e:
            if e.code == 404:
                return None
            raise

    def attente(self, depuis=None, delai=40):
        chemin = "/alertes/attente" if depuis is None else f"/alertes/attente?depuis={depuis}&delai={delai}"
        return self.requete("GET", chemin, delai=delai + 25)

    def flux(self, cam_id, fps=12, largeur=1280, arret=None):
        """Générateur d'images JPEG (vidéo MJPEG). S'arrête quand arret() devient vrai ou que la connexion coupe."""
        c = self.connexion(25)
        try:
            c.request("GET", f"/api/v1/cameras/{cam_id}/flux?fps={fps}&largeur={largeur}", headers=self._entetes())
            r = c.getresponse()
            if r.status >= 400:
                try:
                    d = json.loads(r.read())
                except ValueError:
                    d = {}
                raise ErreurApi(d.get("erreur") or f"Erreur {r.status}", r.status)
            while not (arret and arret()):
                ligne = r.fp.readline()
                if not ligne:
                    return
                if not ligne.startswith(b"--fluxlite"):
                    continue
                longueur, personnes = -1, 0
                while True:
                    entete = r.fp.readline().strip()
                    if not entete:
                        break
                    cle, _, valeur = entete.decode("latin-1").partition(":")
                    if cle.lower() == "content-length":
                        longueur = int(valeur)
                    elif cle.lower() == "x-personnes":
                        personnes = int(valeur or 0)
                if not 0 < longueur < 20_000_000:
                    return
                yield r.fp.read(longueur), personnes
        finally:
            c.close()


def appairer(hotes, port, cle, relais=None):
    """Essaie chaque adresse locale, puis Internet (relais). Renvoie (hôte, informations du serveur, route).
    hôte vaut la première adresse indiquée quand seul le relais a répondu (elle resservira sur place)."""
    derniere = ErreurApi("Indiquez l'adresse du PC Flux ou sa clé.")
    for h in hotes:
        try:
            return h, Api(h, port, cle, relais=relais, mode="direct").info(), "direct"
        except CleIncorrecte:
            raise
        except Exception as e:  # noqa: BLE001
            derniere = e
    api = Api(hotes[0] if hotes else "", port, cle, relais=relais, mode="internet")
    if api.adresse_relais is None:
        if not hotes:
            raise ErreurApi("Aucun relais Internet connu pour l'instant : indiquez l'adresse locale du PC Flux.")
        raise derniere
    try:
        return (hotes[0] if hotes else ""), api.info(), "internet"
    except CleIncorrecte:
        raise
    except ErreurRelais:
        raise
    except Exception as e:  # noqa: BLE001
        if hotes:
            raise derniere from e
        raise
