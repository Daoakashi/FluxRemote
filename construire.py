"""Compile Flux Remote en programme autonome (dossier FluxRemote/ + archive zip), avec PyInstaller.

    python construire.py            -> dist/FluxRemote/  et  dist/FluxRemote-<version>-<windows|linux>.zip

Mode « dossier » (pas un seul .exe) : les bibliothèques Qt restent des fichiers séparés et remplaçables, comme
le demande la licence LGPL de Qt, et le programme démarre plus vite.
"""
import os
import shutil
import sys
import zipfile

import PyInstaller.__main__

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
from fluxremote.version import VERSION  # noqa: E402

plateforme = "windows" if os.name == "nt" else "linux"
sep = os.pathsep
PyInstaller.__main__.run([
    os.path.join(ICI, "flux_remote.py"),
    "--name", "FluxRemote",
    "--noconfirm", "--clean", "--windowed",
    "--icon", os.path.join(ICI, "ressources", "flux-remote.ico"),
    "--add-data", f"{os.path.join(ICI, 'ressources')}{sep}ressources",
    "--distpath", os.path.join(ICI, "dist"), "--workpath", os.path.join(ICI, "build"),
    "--specpath", os.path.join(ICI, "build"),
    # modules Qt inutiles : programme plus léger
    "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.Qt3DCore",
    "--exclude-module", "tkinter",
])
dossier = os.path.join(ICI, "dist", "FluxRemote")
for source, nom in (("juridique/LICENCES-TIERCES.md", "LICENCES-TIERCES.md"), ("README.md", "LISEZMOI.md"), ("LICENSE", "LICENSE.txt"),
                     ("juridique/CONDITIONS-UTILISATION.md", "CONDITIONS-UTILISATION.md")):
    shutil.copy(os.path.join(ICI, source), os.path.join(dossier, nom))
archive = os.path.join(ICI, "dist", f"FluxRemote-{VERSION}-{plateforme}.zip")
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for d, _, fichiers in os.walk(dossier):
        for f in fichiers:
            chemin = os.path.join(d, f)
            z.write(chemin, os.path.join("FluxRemote", os.path.relpath(chemin, dossier)))
print("Archive :", archive)
