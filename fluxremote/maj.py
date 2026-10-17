"""Mises à jour de Flux Remote depuis le site (fichier remote/version.json), paquets hébergés sur GitHub.

version.json :
{
  "version": "1.1.0", "notes": "…", "obligatoire": false,
  "windows": {"url": "https://github.com/…/FluxRemote-1.1.0-windows.zip", "sha256": "…"},
  "linux":   {"url": "https://github.com/…/FluxRemote-1.1.0-linux.zip",   "sha256": "…"},
  "sources": {"url": "https://github.com/…/FluxRemote-1.1.0-sources.zip", "sha256": "…"}
}
Programme compilé : paquet « windows » ou « linux ». Lancé avec Python (installer.bat / installer.sh) : paquet
« sources » ; l'environnement « venv » est gardé et FluxRemote.bat / FluxRemote.sh installent au besoin les
nouvelles dépendances au redémarrage.
Installation : l'archive est téléchargée en HTTPS, son empreinte SHA-256 vérifiée, puis un petit script remplace les
fichiers du programme une fois Flux Remote fermé, et le relance. Les réglages (dossier de l'utilisateur) ne bougent pas.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from .stockage import dossier_programme
from .version import URL_MAJ, VERSION


class ErreurMaj(Exception):
    pass


def cle_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) + (0,) * 3


def plateforme():
    return "windows" if os.name == "nt" else "linux"


def compile_():
    """Vrai pour le programme compilé (PyInstaller), faux quand il est lancé avec Python (installer.bat / .sh)."""
    return bool(getattr(sys, "frozen", False))


def cle_paquet():
    return plateforme() if compile_() else "sources"


def _get(url, delai=20, progression=None):
    req = urllib.request.Request(url, headers={"User-Agent": f"FluxRemote/{VERSION}", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            total = int(r.headers.get("Content-Length") or 0)
            morceaux, lu = [], 0
            while True:
                bloc = r.read(256 * 1024)
                if not bloc:
                    break
                morceaux.append(bloc)
                lu += len(bloc)
                if progression:
                    progression(lu, total)
            return b"".join(morceaux)
    except OSError as e:
        raise ErreurMaj(f"connexion impossible ({getattr(e, 'reason', e)})") from None


def verifier():
    """Renvoie le dict de la nouvelle version, ou None si Flux Remote est à jour."""
    try:
        v = json.loads(_get(URL_MAJ))
    except ValueError:
        raise ErreurMaj("fichier de version illisible") from None
    if not v.get("version") or cle_version(v["version"]) <= cle_version(VERSION):
        return None
    if not (v.get(cle_paquet()) or {}).get("url"):
        return None
    return v


def installer(v, progression=None):
    """Télécharge, vérifie et prépare la mise à jour, puis lance le script de remplacement. Le programme doit
    ensuite se fermer (il est relancé automatiquement)."""
    paquet = v[cle_paquet()]
    if not paquet["url"].startswith("https://"):
        raise ErreurMaj("le paquet doit être téléchargé en HTTPS")
    octets = _get(paquet["url"], delai=60, progression=progression)
    if hashlib.sha256(octets).hexdigest().lower() != str(paquet.get("sha256", "")).lower():
        raise ErreurMaj("fichier corrompu ou modifié (empreinte SHA-256 différente) : mise à jour annulée")
    temp = tempfile.mkdtemp(prefix="flux-remote-maj-")
    archive = os.path.join(temp, "paquet.zip")
    with open(archive, "wb") as f:
        f.write(octets)
    extrait = os.path.join(temp, "nouveau")
    with zipfile.ZipFile(archive) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in n.split("/") or ":" in n:
                raise ErreurMaj(f"chemin dangereux dans l'archive : {n}")
            if n.split("/")[1:2] == ["venv"] or n.split("/")[:1] == ["venv"]:
                raise ErreurMaj("l'archive contient un environnement Python : paquet refusé")
        z.extractall(extrait)
    racine = extrait
    contenu = os.listdir(extrait)
    if len(contenu) == 1 and os.path.isdir(os.path.join(extrait, contenu[0])):
        racine = os.path.join(extrait, contenu[0])
    if os.name != "nt":  # zipfile ne garde pas les droits d'exécution
        for d, _, fichiers in os.walk(racine):
            for f in fichiers:
                if f in ("FluxRemote", "FluxRemote.sh", "installer.sh") or f.endswith((".so", ".sh")) or ".so." in f:
                    os.chmod(os.path.join(d, f), 0o755)
    destination = dossier_programme()
    if not os.access(destination, os.W_OK):
        raise ErreurMaj(f"impossible d'écrire dans {destination} : déplacez Flux Remote dans un dossier à vous")
    _lancer_remplacement(racine, destination, temp)


def _lancer_remplacement(source, destination, temp):
    pid = os.getpid()
    if os.name == "nt":
        exe = os.path.join(destination, "FluxRemote.exe" if compile_() else "FluxRemote.bat")
        script = os.path.join(temp, "maj.bat")
        with open(script, "w", encoding="utf-8") as f:
            f.write(f'@echo off\r\nchcp 65001 >nul\r\n:attendre\r\n'
                    f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto attendre)\r\n'
                    f'robocopy "{source}" "{destination}" /E /NFL /NDL /NJH /NJS /R:5 /W:1 >nul\r\n'
                    f'start "" "{exe}"\r\nrmdir /s /q "{temp}" 2>nul\r\n')
        # processus détaché : il survit à la fermeture de Flux Remote, sans fenêtre
        subprocess.Popen(["cmd", "/c", script], creationflags=0x00000008 | 0x00000200, close_fds=True)
    else:
        exe = os.path.join(destination, "FluxRemote" if compile_() else "FluxRemote.sh")
        script = os.path.join(temp, "maj.sh")
        with open(script, "w", encoding="utf-8") as f:
            f.write(f'#!/bin/sh\nwhile kill -0 {pid} 2>/dev/null; do sleep 1; done\n'
                    f'cp -rf "{source}/." "{destination}/"\nchmod +x "{exe}"\n'
                    f'nohup "{exe}" >/dev/null 2>&1 &\nrm -rf "{temp}"\n')
        os.chmod(script, 0o755)
        subprocess.Popen(["/bin/sh", script], start_new_session=True, close_fds=True)

