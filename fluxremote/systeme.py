"""Intégration au système : démarrage avec la session, raccourci sur le bureau, dossier des captures."""
import os
import subprocess
import sys

from .stockage import dossier_programme


def commande_lancement(reduit=False):
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        python = sys.executable
        if os.name == "nt" and python.lower().endswith("python.exe"):
            python = python[:-10] + "pythonw.exe"
        cmd = [python, os.path.join(dossier_programme(), "flux_remote.py")]
    return cmd + (["--reduit"] if reduit else [])


def demarrage_session(actif, reduit=False):
    """Lance Flux Remote à l'ouverture de la session (Windows : registre utilisateur ; Linux : autostart XDG)."""
    if os.name == "nt":
        import winreg
        cle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        with cle:
            if actif:
                valeur = subprocess.list2cmdline(commande_lancement(reduit))
                winreg.SetValueEx(cle, "Flux Remote", 0, winreg.REG_SZ, valeur)
            else:
                try:
                    winreg.DeleteValue(cle, "Flux Remote")
                except FileNotFoundError:
                    pass
        return
    dossier = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart")
    chemin = os.path.join(dossier, "flux-remote.desktop")
    if actif:
        os.makedirs(dossier, exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(_desktop(reduit))
    elif os.path.exists(chemin):
        os.remove(chemin)


def _desktop(reduit=False):
    icone = os.path.join(dossier_programme(), "ressources", "flux-remote.png")
    if not os.path.exists(icone):
        icone = os.path.join(dossier_programme(), "_internal", "ressources", "flux-remote.png")
    return ("[Desktop Entry]\nType=Application\nName=Flux Remote\nComment=Télécommande de Flux\n"
            f"Exec={subprocess.list2cmdline(commande_lancement(reduit))}\nIcon={icone}\nTerminal=false\n"
            "Categories=Utility;Security;\n")


def creer_raccourci_bureau():
    """Raccourci « Flux Remote » sur le bureau. Renvoie le chemin créé."""
    bureau = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.name != "nt":
        try:
            sortie = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
            bureau = sortie or bureau
        except (OSError, subprocess.SubprocessError):
            pass
        os.makedirs(bureau, exist_ok=True)
        chemin = os.path.join(bureau, "flux-remote.desktop")
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(_desktop())
        os.chmod(chemin, 0o755)
        return chemin
    cmd = commande_lancement()
    cible, args = cmd[0], subprocess.list2cmdline(cmd[1:])
    chemin = os.path.join(bureau, "Flux Remote.lnk")
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);$s.TargetPath=$env:CIBLE;"
              "$s.Arguments=$env:ARGS;$s.WorkingDirectory=$env:DOSSIER;$s.IconLocation=$env:CIBLE;$s.Save()")
    env = dict(os.environ, LNK=chemin, CIBLE=cible, ARGS=args, DOSSIER=dossier_programme())
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, timeout=30,
                   creationflags=0x08000000, check=True)
    return chemin


def dossier_captures(reglage=""):
    if reglage and os.path.isdir(reglage):
        return reglage
    images = os.path.join(os.path.expanduser("~"), "Pictures")
    if os.name != "nt":
        try:
            images = subprocess.run(["xdg-user-dir", "PICTURES"], capture_output=True, text=True,
                                    timeout=5).stdout.strip() or images
        except (OSError, subprocess.SubprocessError):
            pass
    d = os.path.join(images, "Flux Remote")
    os.makedirs(d, exist_ok=True)
    return d


def ouvrir_dossier(chemin):
    if os.name == "nt":
        os.startfile(chemin)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", chemin])
