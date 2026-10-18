"""Bouton Feedback de Flux Remote : une idée, un problème ou une question pour l'éditeur (DMS Security).

Par mail (messagerie de l'ordinateur) ou sur GitHub (page « nouveau ticket »), toujours relu avant l'envoi. Seules
les versions du programme et du système sont ajoutées, jamais d'image, de réglage ni de donnée des caméras.
"""
import platform
import urllib.parse

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from .widgets import Bouton, etiquette

MAIL = "dms.security.list@gmail.com"
GITHUB = "https://github.com/Daoakashi/FluxRemote/issues/new"
SUJETS = ["Idée ou suggestion", "Problème (bug)", "Question", "Autre"]


def contexte(version):
    return (f"Programme : Flux Remote {version}\n"
            f"Système : {platform.system()} {platform.release()} ({platform.machine()})")


class DialogueFeedback(QDialog):
    def __init__(self, parent, version):
        super().__init__(parent)
        self.version = version
        self.setWindowTitle("Feedback")
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(8)
        t = QLabel("Feedback")
        t.setObjectName("titre_page")
        v.addWidget(t)
        v.addWidget(etiquette("Une idée, un problème, une question ? Votre message aide à améliorer Flux. N'y mettez ni "
                              "mot de passe ni image des caméras : seules les versions du programme et du système sont "
                              "ajoutées."))
        v.addWidget(QLabel("Sujet"))
        self.sujet = QComboBox()
        self.sujet.addItems(SUJETS)
        v.addWidget(self.sujet)
        v.addWidget(QLabel("Message"))
        self.texte = QPlainTextEdit()
        self.texte.setPlaceholderText("Décrivez votre idée ou le problème rencontré…")
        self.texte.setMinimumHeight(150)
        v.addWidget(self.texte, 1)
        v.addWidget(etiquette(contexte(version), "soustitre"))
        h = QHBoxLayout()
        b0 = Bouton("Annuler", "fantome")
        b0.clicked.connect(self.reject)
        h.addWidget(b0)
        h.addStretch(1)
        bc = Bouton("Copier le message", "discret")
        bc.clicked.connect(lambda: QGuiApplication.clipboard().setText(
            f"À : {MAIL}\nSujet : Flux Remote · {self.sujet.currentText()}\n\n{self._corps()}"))
        h.addWidget(bc)
        bg = Bouton("Signaler sur GitHub", "discret", "lien")
        bg.setToolTip("Ouvre un ticket public sur GitHub (compte GitHub nécessaire).")
        bg.clicked.connect(self._github)
        h.addWidget(bg)
        bm = Bouton("Envoyer par mail", "primaire", "message")
        bm.setToolTip(f"Ouvre votre messagerie avec un message pour {MAIL}.")
        bm.clicked.connect(self._mail)
        h.addWidget(bm)
        v.addLayout(h)
        self.texte.setFocus()

    def _corps(self):
        return f"{self.texte.toPlainText().strip()}\n\n---\n{contexte(self.version)}"

    def _mail(self):
        sujet = urllib.parse.quote(f"Flux Remote · {self.sujet.currentText()}")
        QDesktopServices.openUrl(QUrl(f"mailto:{MAIL}?subject={sujet}&body={urllib.parse.quote(self._corps())}"))
        self.accept()

    def _github(self):
        titre = urllib.parse.quote(f"[{self.sujet.currentText()}] ")
        QDesktopServices.openUrl(QUrl(f"{GITHUB}?title={titre}&body={urllib.parse.quote(self._corps())}"))
        self.accept()

# Crédits affichés dans « À propos ».
CREDITS_IA = ("Crédits : conception, choix des fonctions, tests et validation par DMS Security. Code et textes écrits en partie avec l'assistant d'IA Claude (Anthropic), qui cède à l'utilisateur ses droits éventuels sur ce qu'il produit. La licence AGPL-3.0 couvre l'apport humain ; les parties produites uniquement par l'IA peuvent ne pas être protégées par le droit d'auteur.")
