"""Flux Remote — télécommande pour PC du logiciel de vidéosurveillance Flux.

Lancement : python flux_remote.py   (option --reduit : démarre dans la zone de notification)
"""
import os
import sys
import traceback


def main():
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from fluxremote import theme
    from fluxremote.fenetre import Fenetre, icone_programme
    from fluxremote.stockage import Reglages

    if os.name == "nt":  # icône correcte dans la barre des tâches
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Flux.Remote.1")
        except Exception:  # noqa: BLE001
            pass
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("Flux Remote")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    # Une seule instance : un deuxième lancement montre simplement la fenêtre existante.
    nom = f"flux-remote-{os.environ.get('USERNAME') or os.environ.get('USER') or 'session'}"
    sonde = QLocalSocket()
    sonde.connectToServer(nom)
    if sonde.waitForConnected(300):
        sonde.write(b"montrer")
        sonde.flush()
        sonde.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(nom)
    serveur = QLocalServer()
    serveur.listen(nom)

    reg = Reglages()
    app.setWindowIcon(icone_programme())
    theme.appliquer(reg, app)
    fen = Fenetre(reg, reduit="--reduit" in sys.argv)
    serveur.newConnection.connect(lambda: (serveur.nextPendingConnection(), fen.montrer()))
    app.garde = (serveur, fen)
    return app.exec()


def erreur_fatale():
    texte = traceback.format_exc()
    from fluxremote.stockage import DOSSIER
    try:
        os.makedirs(DOSSIER, exist_ok=True)
        with open(os.path.join(DOSSIER, "erreur.log"), "w", encoding="utf-8") as f:
            f.write(texte)
    except OSError:
        pass
    message = f"Flux Remote n'a pas pu démarrer.\n\n{texte.strip().splitlines()[-1]}\n\nDétails : {DOSSIER}/erreur.log"
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Flux Remote", 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    print(message, file=sys.stderr)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        erreur_fatale()
        sys.exit(1)
