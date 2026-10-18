"""Fenêtre principale de Flux Remote : tableau de bord, caméras, contrôle, journal, compte et réglages.

Plusieurs PC Flux peuvent être reliés en même temps : leurs caméras, leurs alertes et leur journal sont regroupés
(avec le nom du serveur), et le contrôle et le compte se règlent serveur par serveur.
"""
import csv
import os
import sys
import tempfile
import time
import wave
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QScrollArea, QStackedWidget,
                               QStatusBar, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import api as module_api
from . import maj, systeme, theme
from .alertes import Ecoute
from .connexion import Accueil, force_mdp, html_cgu, mdp_accepte
from .serveurs import Serveur
from .taches import Tache
from .theme import C, T, couleur, dessiner_logo
from .version import SITE, VERSION
from .video import LecteurFlux, VueImage, Vignettes
from .widgets import Bouton, BoutonNav, Interrupteur, Logo, Toasts, Voyant, etiquette, ligne_option, separateur
from .feedback import CREDITS_IA

PAGES = [("tableau", "Tableau de bord", "accueil"), ("cameras", "Caméras", "cameras"),
         ("controle", "Contrôle", "controle"), ("journal", "Journal", "journal"), ("compte", "Compte", "personnes"),
         ("reglages", "Réglages", "reglages")]
SESSION_PERDUE = "\x00401:"  # préfixe interne : la session a expiré pendant un appel
MODES_ALERTES = [("sonores", "Sonores"), ("silencieuses", "Silencieuses"), ("coupees", "Coupées")]


def heure(t, avec_date=None):
    d = datetime.fromtimestamp(t)
    if avec_date is None:
        avec_date = d.date() != datetime.now().date()
    return d.strftime("%d/%m %H:%M:%S" if avec_date else "%H:%M:%S")


def icone_programme(taille=256):
    pix = QPixmap(taille, taille)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    dessiner_logo(p, QRectF(taille * 0.04, taille * 0.04, taille * 0.92, taille * 0.92))
    # petit signal « télécommande » en bas à droite
    r = taille * 0.13
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(couleur("#0A1220"))
    p.drawEllipse(QRectF(taille - 2.5 * r, taille - 2.5 * r, 2.3 * r, 2.3 * r))
    p.setBrush(couleur("o_personne"))
    p.drawEllipse(QRectF(taille - 2.1 * r, taille - 2.1 * r, 1.5 * r, 1.5 * r))
    p.end()
    return QIcon(pix)


def carte(titre=None, aide=None):
    f = QFrame()
    f.setObjectName("carte")
    v = QVBoxLayout(f)
    v.setContentsMargins(18, 16, 18, 16)
    v.setSpacing(8)
    if titre:
        t = QLabel(titre)
        t.setStyleSheet(f"font-size: {T.taille + 3}px; font-weight: 600;")
        v.addWidget(t)
    if aide:
        v.addWidget(etiquette(aide))
    return f, v


def defilant(contenu):
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.Shape.NoFrame)
    s.setWidget(contenu)
    return s


def titre_page(texte, sous=None):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 6)
    v.setSpacing(2)
    t = QLabel(texte)
    t.setObjectName("titre_page")
    v.addWidget(t)
    if sous is not None:
        s = etiquette(sous, "soustitre")
        v.addWidget(s)
        w.sous = s
    return w


def vider(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            vider(it.layout())


# ---------------------------------------------------------------------------------------------------
# Son d'alerte : deux notes courtes, générées une fois (aucun fichier à fournir)
# ---------------------------------------------------------------------------------------------------
def fichier_son():
    chemin = os.path.join(tempfile.gettempdir(), "flux-remote-alerte.wav")
    if not os.path.exists(chemin):
        import math
        import struct
        taux = 22050
        echantillons = []
        for freq, duree in ((880, 0.12), (0, 0.05), (1175, 0.18)):
            n = int(taux * duree)
            for i in range(n):
                env = min(1.0, i / 200, (n - i) / 400) if freq else 0
                echantillons.append(int(9000 * env * math.sin(2 * math.pi * freq * i / taux)))
        with wave.open(chemin, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(taux)
            w.writeframes(b"".join(struct.pack("<h", e) for e in echantillons))
    return chemin


def jouer_son():
    try:
        if os.name == "nt":
            import winsound
            winsound.PlaySound(fichier_son(), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        import shutil
        import subprocess
        for lecteur in ("paplay", "pw-play", "aplay"):
            if shutil.which(lecteur):
                subprocess.Popen([lecteur, fichier_son()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    except Exception:  # noqa: BLE001
        pass
    QApplication.beep()


# ---------------------------------------------------------------------------------------------------
# Vidéo d'une caméra dans sa propre fenêtre
# ---------------------------------------------------------------------------------------------------
class FenetreVideo(QWidget):
    def __init__(self, fen, cam):
        super().__init__(None, Qt.WindowType.Window)
        self.fen, self.cam = fen, cam
        self.srv = fen.serveur_de(cam)
        nom = cam["nom"] + (f" · {self.srv.nom}" if fen.plusieurs() else "")
        self.setWindowTitle(f"{nom} · Flux Remote")
        self.setWindowIcon(fen.windowIcon())
        self.setObjectName("fond")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1100, 680)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        barre = QHBoxLayout()
        self.voyant = Voyant(12)
        barre.addWidget(self.voyant)
        self.lbl = QLabel(nom)
        self.lbl.setObjectName("titre")
        barre.addWidget(self.lbl)
        self.lbl_etat = etiquette("", "soustitre", False)
        barre.addWidget(self.lbl_etat, 1)
        self.b_detection = Bouton("Détection", "discret", "controle")
        self.b_detection.setToolTip("Activer ou couper la détection de cette caméra sur le PC Flux")
        self.b_detection.clicked.connect(lambda: fen.piloter("camera.detection", not self.cam.get("detection", True),
                                                              self.cam["id"], self.srv))
        self.b_clip = Bouton("Vidéo sur le PC", "discret", "video")
        self.b_clip.setToolTip("Enregistre une courte vidéo sur le PC Flux (avec les secondes précédentes)")
        self.b_clip.clicked.connect(lambda: fen.piloter("camera.clip", True, self.cam["id"], self.srv))
        for b in (self.b_detection, self.b_clip):
            b.setVisible(self.srv.pilotage_autorise)
            barre.addWidget(b)
        b_cap = Bouton("Capture", "discret", "capture")
        b_cap.clicked.connect(self.capture)
        barre.addWidget(b_cap)
        self.b_epingle = Bouton("", "discret", "epingle")
        self.b_epingle.setToolTip("Toujours au premier plan")
        self.b_epingle.setCheckable(True)
        self.b_epingle.toggled.connect(self._epingler)
        barre.addWidget(self.b_epingle)
        b_plein = Bouton("", "discret", "plein_ecran")
        b_plein.setToolTip("Plein écran (F11, Échap pour revenir)")
        b_plein.clicked.connect(self.basculer_plein_ecran)
        barre.addWidget(b_plein)
        v.addLayout(barre)
        self.vue = VueImage()
        self.vue.texte_vide = "Connexion à la vidéo…"
        self.vue.double_clic.connect(self.basculer_plein_ecran)
        v.addWidget(self.vue, 1)
        QShortcut(QKeySequence("F11"), self, activated=self.basculer_plein_ecran)
        QShortcut(QKeySequence("Escape"), self, activated=lambda: self.isFullScreen() and self.showNormal())
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.capture)
        self.derniere = None
        self.lecteur = LecteurFlux(self.srv.api, cam["id"], 15, 1600)
        self.lecteur.image.connect(self._image)
        self.lecteur.etat.connect(lambda t: self.lbl_etat.setText(t))
        self.lecteur.demarrer()
        if fen.reg["systeme.premier_plan_video"]:
            self.b_epingle.setChecked(True)
        self.maj_camera(cam)

    def _image(self, img, personnes):
        self.derniere = img
        self.vue.definir(img)
        self.vue.personnes = personnes
        self.vue.etat = "alerte" if personnes else "direct"
        self.voyant.regler(self.vue.etat)
        self.lbl_etat.setText(f"{img.width()}×{img.height()} · {self.lecteur.ips:.0f} images/s"
                              + (f" · {personnes} personne(s)" if personnes else ""))

    def maj_camera(self, cam):
        self.cam = cam
        self.vue.detection = cam.get("detection", True)
        self.b_detection.setText("Couper la détection" if cam.get("detection", True) else "Activer la détection")

    def _epingler(self, actif):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, actif)
        self.show()

    def basculer_plein_ecran(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def capture(self):
        if self.derniere is None:
            return self.fen.toast("Pas encore d'image à enregistrer.")
        self.fen.enregistrer_capture(self.cam["nom"], self.derniere)

    def closeEvent(self, e):
        self.lecteur.arreter()
        self.fen.videos.pop(self.cam["uid"], None)
        super().closeEvent(e)


def menu_serveurs(fen, bouton, apres):
    """Menu « Serveurs affichés » : tous, un ou plusieurs."""
    m = QMenu(bouton)
    actifs = fen.serveurs_actifs()
    tous = all(s.affiche for s in actifs)
    a = m.addAction("Tous les serveurs")
    a.setCheckable(True)
    a.setChecked(tous)
    a.triggered.connect(lambda: (fen.afficher_serveurs([s.cle for s in actifs]), apres()))
    m.addSeparator()
    for s in actifs:
        a = m.addAction(s.nom)
        a.setCheckable(True)
        a.setChecked(s.affiche)
        a.triggered.connect(lambda _=False, s=s: (fen.basculer_affichage(s), apres()))
    m.addSeparator()
    m.addAction("Seulement…").setEnabled(False)
    for s in actifs:
        m.addAction(f"  {s.nom} seul", lambda s=s: (fen.afficher_serveurs([s.cle]), apres()))
    m.exec(bouton.mapToGlobal(bouton.rect().bottomLeft()))


# ---------------------------------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------------------------------
class PageTableau(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self.lignes_srv = {}
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        self.tete = titre_page("Tableau de bord", "")
        racine.addWidget(self.tete)
        contenu = QWidget()
        g = QGridLayout(contenu)
        g.setContentsMargins(0, 6, 4, 4)
        g.setSpacing(14)
        self.chiffres = {}
        for i, (cle, lib) in enumerate((("direct", "Caméras en direct"), ("presences", "Personnes à l'image"),
                                        ("alertes", "Alertes aujourd'hui"), ("connus", "Personnes connues"))):
            f, v = carte()
            n = QLabel("—")
            n.setStyleSheet(f"font-size: {T.taille + 18}px; font-weight: 650;")
            v.addWidget(n)
            v.addWidget(etiquette(lib, "soustitre"))
            self.chiffres[cle] = n
            g.addWidget(f, 0, i)
        # serveurs et détection
        f, v = carte("Serveurs Flux")
        self.v_srv = QVBoxLayout()
        self.v_srv.setSpacing(4)
        v.addLayout(self.v_srv)
        self.lbl_pilotage = etiquette("")
        v.addWidget(self.lbl_pilotage)
        h = QHBoxLayout()
        b = Bouton("Ajouter un serveur", "fantome", "plus")
        b.clicked.connect(fen.ajouter_serveur)
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        v.addStretch(1)
        g.addWidget(f, 1, 0, 1, 2)
        # actions rapides
        f, v = carte("Actions rapides")
        self.b_pause = Bouton("Pause des alertes sur ce PC (1 h)", "discret", "cloche_barree")
        self.b_pause.clicked.connect(lambda: fen.pause_alertes(1))
        self.b_tout = Bouton("Couper détection et notifications", "danger", "pause")
        self.b_tout.setToolTip("Mode discret : coupe la détection et toutes les notifications des PC Flux affichés")
        self.b_tout.clicked.connect(self._tout_couper)
        self.b_reprendre = Bouton("Tout réactiver", "primaire", "lecture")
        self.b_reprendre.clicked.connect(self._tout_reprendre)
        b_mur = Bouton("Ouvrir les caméras", "discret", "cameras")
        b_mur.clicked.connect(lambda: fen.aller("cameras"))
        for b in (b_mur, self.b_pause, self.b_tout, self.b_reprendre):
            v.addWidget(b)
        v.addStretch(1)
        g.addWidget(f, 1, 2, 1, 2)
        # dernières alertes
        f, v = carte("Dernières alertes")
        self.liste = QTableWidget(0, 4)
        self.liste.setHorizontalHeaderLabels(["Heure", "Caméra", "Serveur", "Alerte"])
        self.liste.verticalHeader().setVisible(False)
        self.liste.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.liste.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.liste.setShowGrid(False)
        self.liste.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.liste.setMinimumHeight(220)
        self.liste.cellDoubleClicked.connect(lambda *_: fen.aller("journal"))
        v.addWidget(self.liste)
        g.addWidget(f, 2, 0, 1, 4)
        for c in range(4):
            g.setColumnStretch(c, 1)
        g.setRowStretch(3, 1)
        racine.addWidget(defilant(contenu), 1)

    def _tout_couper(self):
        cibles = [s for s in self.fen.affiches() if s.pilotage_autorise]
        if not cibles or QMessageBox.question(
                self, "Mode discret", "Couper la détection de toutes les caméras et toutes les notifications sur "
                f"{'les ' + str(len(cibles)) + ' PC Flux affichés' if len(cibles) > 1 else 'le PC Flux'} ?") \
                != QMessageBox.StandardButton.Yes:
            return
        for s in cibles:
            self.fen.piloter("detection.actif", False, srv=s)
            self.fen.piloter("notif.actif", False, srv=s)
            if any(c["cle"] == "mail.actif" and c["actif"] for c in (s.etat_pilotage or {}).get("canaux", [])):
                self.fen.piloter("mail.actif", False, srv=s)

    def _tout_reprendre(self):
        for s in self.fen.affiches():
            if s.pilotage_autorise:
                self.fen.piloter("detection.actif", True, srv=s)
                self.fen.piloter("notif.actif", True, srv=s)

    def _lignes_serveurs(self):
        fen = self.fen
        actifs = fen.serveurs_actifs()
        if [s.cle for s in actifs] != list(self.lignes_srv):
            vider(self.v_srv)
            self.lignes_srv = {}
            for s in actifs:
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(0, 4, 0, 4)
                voy = Voyant(12)
                h.addWidget(voy)
                lab = QLabel(s.nom)
                lab.setStyleSheet("font-weight: 600;")
                h.addWidget(lab)
                info = etiquette("", "aide", False)
                h.addWidget(info, 1)
                h.addWidget(etiquette("Détection", "aide", False))
                inter = Interrupteur()
                inter.toggled.connect(lambda e, s=s: fen.piloter("detection.actif", bool(e), srv=s))
                h.addWidget(inter)
                self.v_srv.addWidget(w)
                self.lignes_srv[s.cle] = {"voyant": voy, "nom": lab, "info": info, "inter": inter, "widget": w}
        for s in actifs:
            l_ = self.lignes_srv[s.cle]
            cams = s.cameras
            l_["voyant"].regler(("direct" if s.detection_globale else "chargement") if s.en_ligne else "arret")
            l_["nom"].setText(s.nom)
            l_["info"].setText(
                (f"{sum(1 for c in cams if c['etat'] in ('direct', 'alerte'))}/{len(cams)} caméras · {s.texte_route()}"
                 if s.en_ligne else "connexion perdue, nouvelle tentative…")
                + ("" if s.affiche else " · masqué"))
            l_["inter"].blockSignals(True)
            l_["inter"].regler(s.detection_globale)
            l_["inter"].blockSignals(False)
            l_["inter"].setEnabled(s.pilotage_autorise)
            l_["inter"].setToolTip("" if s.pilotage_autorise else "Votre compte peut voir mais pas piloter ce PC Flux.")

    def rafraichir(self):
        fen = self.fen
        cams = fen.cameras
        p = fen.profil_connu()
        n = len(fen.affiches())
        self.tete.sous.setText(" · ".join(x for x in (
            f"{n} serveurs" if n > 1 else (fen.affiches()[0].nom if n else "Flux"),
            f"{p.get('prenom', '')} {p.get('nom', '')}".strip()) if x))
        self.chiffres["direct"].setText(f"{sum(1 for c in cams if c['etat'] in ('direct', 'alerte'))} / {len(cams)}")
        self.chiffres["presences"].setText(str(sum(c.get("personnes", 0) for c in cams)))
        aujourd = [e for e in fen.dernieres_alertes if datetime.fromtimestamp(e["heure"]).date() == datetime.now().date()]
        self.chiffres["alertes"].setText(str(len(aujourd)) if fen.journal_charge else "—")
        stats = [s.etat_pilotage["statistiques"]["personnes"] for s in fen.affiches()
                 if s.etat_pilotage and s.etat_pilotage.get("statistiques")]
        self.chiffres["connus"].setText(str(sum(stats)) if stats else "—")
        self._lignes_serveurs()
        pilotables = any(s.pilotage_autorise for s in fen.affiches())
        self.lbl_pilotage.setText("" if all(s.pilotage_autorise for s in fen.serveurs_actifs()) else
                                  "Sur certains serveurs, votre compte peut voir mais pas piloter. Leur responsable "
                                  "peut vous accorder le droit « pilotage à distance ».")
        for b in (self.b_tout, self.b_reprendre):
            b.setVisible(pilotables)
        alertes = fen.dernieres_alertes[:12]
        self.liste.setColumnHidden(2, not fen.plusieurs())
        self.liste.setRowCount(0)
        for ev in alertes:
            r = self.liste.rowCount()
            self.liste.insertRow(r)
            for j, val in enumerate((heure(ev["heure"]), ev["camera"], ev.get("serveur", ""), ev["texte"])):
                it = QTableWidgetItem(val)
                if ev.get("prioritaire"):
                    it.setForeground(couleur("liste_noire"))
                self.liste.setItem(r, j, it)
        for c in (0, 1, 2):
            self.liste.resizeColumnToContents(c)


class Tuile(QFrame):
    """Une caméra dans la grille : image, nom, boutons."""

    def __init__(self, page, cam):
        super().__init__()
        self.page, self.fen, self.cam = page, page.fen, cam
        self.setObjectName("carte")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.vue = VueImage(compact=False)
        self.vue.setMinimumHeight(180)
        self.vue.double_clic.connect(lambda: self.fen.ouvrir_video(self.cam))
        self.vue.setToolTip("Double-clic : ouvrir en grand")
        v.addWidget(self.vue, 1)
        h = QHBoxLayout()
        h.setContentsMargins(4, 0, 0, 0)
        self.voyant = Voyant(10)
        h.addWidget(self.voyant)
        noms = QVBoxLayout()
        noms.setSpacing(0)
        self.lbl = QLabel(cam["nom"])
        self.lbl.setStyleSheet("font-weight: 600;")
        noms.addWidget(self.lbl)
        self.lbl_srv = etiquette("", "aide", False)
        noms.addWidget(self.lbl_srv)
        h.addLayout(noms, 1)
        self.b_cloche = Bouton("", "fantome", "cloche")
        self.b_cloche.clicked.connect(lambda: self.fen.basculer_muette(self.cam["uid"]))
        b_grand = Bouton("", "fantome", "plein_ecran")
        b_grand.setToolTip("Ouvrir en grand")
        b_grand.clicked.connect(lambda: self.fen.ouvrir_video(self.cam))
        b_cap = Bouton("", "fantome", "capture")
        b_cap.setToolTip("Enregistrer une capture sur ce PC")
        b_cap.clicked.connect(lambda: self.vue.img is not None and self.fen.enregistrer_capture(self.cam["nom"], self.vue.img))
        self.b_menu = Bouton("", "fantome", "reglages")
        self.b_menu.setToolTip("Commandes de la caméra")
        self.b_menu.clicked.connect(self._menu)
        for b in (self.b_cloche, b_cap, b_grand, self.b_menu):
            h.addWidget(b)
        v.addLayout(h)
        self.maj(cam)

    def maj(self, cam):
        self.cam = cam
        srv = self.fen.serveur_de(cam)
        self.vue.etat, self.vue.personnes = cam["etat"], cam.get("personnes", 0)
        self.vue.detection = cam.get("detection", True) and (srv.detection_globale if srv else True)
        self.vue.badges = [cam["resolution"]] if cam.get("resolution") and self.page.colonnes_effectives() <= 2 else []
        self.voyant.regler(cam["etat"])
        self.lbl_srv.setText(cam.get("serveur", "") if self.fen.plusieurs() else "")
        self.lbl_srv.setVisible(self.fen.plusieurs())
        muette = cam["uid"] in self.fen.reg["alertes.muettes"]
        self.b_cloche.definir_icone("cloche_barree" if muette else "cloche")
        self.b_cloche.setToolTip("Alertes de cette caméra coupées sur ce PC" if muette else
                                 "Couper les alertes de cette caméra sur ce PC")
        self.vue.update()

    def _menu(self):
        srv = self.fen.serveur_de(self.cam)
        m = QMenu(self)
        m.addAction("Ouvrir en grand", lambda: self.fen.ouvrir_video(self.cam))
        if srv is not None and srv.pilotage_autorise:
            m.addSeparator()
            en_marche = self.cam["etat"] != "arret"
            m.addAction("Arrêter la caméra sur le PC" if en_marche else "Démarrer la caméra sur le PC",
                        lambda: self.fen.piloter("camera.marche", not en_marche, self.cam["id"], srv))
            m.addAction("Couper la détection" if self.cam.get("detection", True) else "Activer la détection",
                        lambda: self.fen.piloter("camera.detection", not self.cam.get("detection", True),
                                                 self.cam["id"], srv))
            a = m.addAction("Enregistrer une vidéo sur le PC",
                            lambda: self.fen.piloter("camera.clip", True, self.cam["id"], srv))
            a.setEnabled(en_marche)
        m.addSeparator()
        m.addAction("Voir son journal", lambda: self.fen.journal_camera(self.cam))
        m.addAction("Masquer de la grille", lambda: self.page.masquer(self.cam["uid"], True))
        m.exec(self.b_menu.mapToGlobal(self.b_menu.rect().bottomLeft()))


class PageCameras(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self.tuiles = {}
        self.vignettes = {}  # clé du serveur -> Vignettes (une connexion à la fois par serveur)
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        haut = QHBoxLayout()
        haut.addWidget(titre_page("Caméras"), 1)
        self.b_serveurs = Bouton("Tous les serveurs", "discret", "reseau")
        self.b_serveurs.setToolTip("Choisir les PC Flux dont les caméras s'affichent")
        self.b_serveurs.clicked.connect(lambda: menu_serveurs(fen, self.b_serveurs, fen.serveurs_changes))
        haut.addWidget(self.b_serveurs)
        self.combo_col = QComboBox()
        for n, lib in ((0, "Disposition automatique"), (1, "1 colonne"), (2, "2 colonnes"), (3, "3 colonnes"),
                       (4, "4 colonnes")):
            self.combo_col.addItem(lib, n)
        self.combo_col.setCurrentIndex(max(0, self.combo_col.findData(fen.reg["cameras.colonnes"])))
        self.combo_col.currentIndexChanged.connect(self._colonnes)
        haut.addWidget(self.combo_col)
        self.b_masquees = Bouton("Caméras masquées", "discret", "grille")
        self.b_masquees.clicked.connect(self._menu_masquees)
        haut.addWidget(self.b_masquees)
        racine.addLayout(haut)
        self.message = etiquette("", "soustitre")
        racine.addWidget(self.message)
        self.conteneur = QWidget()
        self.grille = QGridLayout(self.conteneur)
        self.grille.setContentsMargins(0, 4, 4, 4)
        self.grille.setSpacing(12)
        racine.addWidget(defilant(self.conteneur), 1)

    def colonnes_effectives(self):
        n = self.fen.reg["cameras.colonnes"]
        if n:
            return n
        k = len(self.visibles())
        return 1 if k <= 1 else 2 if k <= 4 else 3 if k <= 9 else 4

    def visibles(self):
        masquees = set(self.fen.reg["cameras.masquees"])
        return [c for c in self.fen.cameras if c["uid"] not in masquees]

    def _colonnes(self):
        self.fen.reg.set("cameras.colonnes", self.combo_col.currentData())
        self.reconstruire()

    def masquer(self, uid, masquee):
        s = set(self.fen.reg["cameras.masquees"])
        s.add(uid) if masquee else s.discard(uid)
        self.fen.reg.set("cameras.masquees", sorted(s))
        self.reconstruire()

    def _menu_masquees(self):
        masquees = [c for c in self.fen.cameras if c["uid"] in set(self.fen.reg["cameras.masquees"])]
        m = QMenu(self)
        if not masquees:
            a = m.addAction("Aucune caméra masquée")
            a.setEnabled(False)
        for c in masquees:
            nom = c["nom"] + (f" · {c['serveur']}" if self.fen.plusieurs() else "")
            m.addAction(f"Afficher « {nom} »", lambda i=c["uid"]: self.masquer(i, False))
        m.exec(self.b_masquees.mapToGlobal(self.b_masquees.rect().bottomLeft()))

    def _maj_vignettes(self, cams):
        n = self.colonnes_effectives()
        for cle, v in self.vignettes.items():
            v.ids = [c["id"] for c in cams if c["srv"] == cle and c["etat"] != "arret"] if self.isVisible() else []
            v.largeur = 960 if n <= 1 else 720 if n == 2 else 520

    def reconstruire(self):
        for t in self.tuiles.values():
            t.setParent(None)
            t.deleteLater()
        self.tuiles = {}
        cams = self.visibles()
        n = self.colonnes_effectives()
        for i, c in enumerate(cams):
            t = Tuile(self, c)
            self.tuiles[c["uid"]] = t
            self.grille.addWidget(t, i // n, i % n)
        for c in range(5):
            self.grille.setColumnStretch(c, 1 if c < n else 0)
        self._maj_vignettes(cams)
        self._message()

    def _message(self):
        fen = self.fen
        actifs = fen.serveurs_actifs()
        tous = all(s.affiche for s in actifs)
        self.b_serveurs.setVisible(len(actifs) > 1)
        self.b_serveurs.setText("Tous les serveurs" if tous else
                                ", ".join(s.nom for s in fen.affiches())[:40] or "Aucun serveur")
        if fen.affiches() and all(s.sans_entreprise for s in fen.affiches()):
            self.message.setText("Votre compte n'est rattaché à aucune entreprise : le responsable du PC Flux doit vous "
                                 "attribuer des caméras.")
        elif not fen.cameras:
            self.message.setText("Aucune caméra disponible pour votre entreprise.")
        else:
            m = len(fen.cameras) - len(self.visibles())
            hors = [s.nom for s in fen.affiches() if not s.en_ligne]
            self.message.setText(" ".join(x for x in (
                "Double-clic sur une caméra pour l'ouvrir en grand.",
                f"{m} caméra(s) masquée(s)." if m else "",
                f"Injoignable : {', '.join(hors)}." if hors else "") if x))

    def rafraichir(self):
        uids = [c["uid"] for c in self.visibles()]
        if uids != list(self.tuiles):
            self.reconstruire()
        for c in self.visibles():
            self.tuiles[c["uid"]].maj(c)
        self._maj_vignettes(self.visibles())
        self._message()

    def sync_serveurs(self):
        """Une source d'images par serveur relié."""
        actifs = {s.cle: s for s in self.fen.serveurs_actifs()}
        for cle in list(self.vignettes):
            if cle not in actifs or self.vignettes[cle].api is not actifs[cle].api:
                self.vignettes.pop(cle).arreter()
        for cle, s in actifs.items():
            if cle not in self.vignettes:
                v = Vignettes(s.api)
                v.image.connect(lambda i, img, c=cle: self._image(f"{c}|{i}", img))
                self.vignettes[cle] = v
        self._maj_vignettes(self.visibles())

    def arreter(self):
        for v in self.vignettes.values():
            v.arreter()
        self.vignettes = {}

    def _image(self, uid, img):
        t = self.tuiles.get(uid)
        if t is not None:
            t.vue.definir(img)

    def showEvent(self, e):
        super().showEvent(e)
        self.rafraichir()

    def hideEvent(self, e):
        super().hideEvent(e)
        for v in self.vignettes.values():
            v.ids = []


class PageControle(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self.lignes_cam, self.lignes_canal = {}, {}
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.addWidget(titre_page("Contrôle", "Les commandes s'appliquent au PC Flux choisi et sont notées dans son "
                                                "journal avec votre nom."))
        self.barre_srv = QWidget()
        hb = QHBoxLayout(self.barre_srv)
        hb.setContentsMargins(0, 0, 0, 6)
        hb.addWidget(QLabel("Serveur"))
        self.combo_srv = QComboBox()
        self.combo_srv.setMinimumWidth(240)
        self.combo_srv.activated.connect(lambda _i: (fen.choisir_controle(self.combo_srv.currentData()), self.rafraichir()))
        hb.addWidget(self.combo_srv)
        self.chk_tous = QCheckBox("Appliquer aussi aux autres serveurs")
        self.chk_tous.setToolTip("Détection, niveau de scan, délais et notifications : le même réglage est envoyé à "
                                 "tous les PC Flux affichés que vous pouvez piloter. Les commandes de caméra restent "
                                 "propres à chaque serveur.")
        hb.addWidget(self.chk_tous)
        hb.addStretch(1)
        racine.addWidget(self.barre_srv)
        self.pile = QStackedWidget()
        # sans droit
        sans = QWidget()
        sv = QVBoxLayout(sans)
        f, v = carte("Pilotage non autorisé", "Votre compte peut voir les caméras et les alertes de ce PC Flux, mais pas "
                                             "le piloter. Son responsable peut vous accorder ce droit : page FluxLite, "
                                             "clic droit sur votre compte › Autoriser le pilotage à distance. Le PC Flux "
                                             "doit être en version 0.9 ou plus récente.")
        sv.addWidget(f)
        sv.addStretch(1)
        self.pile.addWidget(sans)
        # avec droit
        contenu = QWidget()
        g = QGridLayout(contenu)
        g.setContentsMargins(0, 4, 4, 4)
        g.setSpacing(14)
        f, v = carte("Détection")
        self.inter_det = Interrupteur()
        self.inter_det.toggled.connect(lambda e: self._global("detection.actif", bool(e)))
        v.addWidget(ligne_option("Toutes les caméras du PC", self.inter_det,
                                 "Coupée : les images restent visibles, sans analyse ni alerte."))
        v.addWidget(separateur())
        self.combo_niveau = QComboBox()
        self.combo_niveau.activated.connect(lambda _i: self._global("detection.niveau", self.combo_niveau.currentData()))
        v.addWidget(ligne_option("Niveau de scan", self.combo_niveau))
        self.lbl_niveau = etiquette("")
        v.addWidget(self.lbl_niveau)
        v.addStretch(1)
        g.addWidget(f, 0, 0)
        f, v = carte("Délais", "Pour éviter d'être submergé : par caméra, les alertes pendant le délai sont regroupées.")
        self.delais = {}
        for cle, lib in (("notif.delai", "Entre deux notifications"), ("mail.delai", "Entre deux mails")):
            s = QDoubleSpinBox()
            s.setRange(0, 1440)
            s.setDecimals(1)
            s.setSingleStep(0.5)
            s.setSuffix(" min")
            s.editingFinished.connect(lambda c=cle, w=s: self._delai(c, w))
            self.delais[cle] = s
            v.addWidget(ligne_option(lib, s))
        v.addStretch(1)
        g.addWidget(f, 0, 1)
        f, self.v_cams = carte("Caméras", "Démarrer ou arrêter une caméra sur le PC, couper sa détection, enregistrer "
                                          "une vidéo des dernières secondes.")
        g.addWidget(f, 1, 0, 1, 2)
        f, self.v_canaux = carte("Notifications envoyées par Flux", "Réglages du PC Flux : ils valent pour toutes les "
                                                                   "personnes qui reçoivent ses mails et messages.")
        g.addWidget(f, 2, 0, 1, 2)
        g.setRowStretch(3, 1)
        self.pile.addWidget(defilant(contenu))
        racine.addWidget(self.pile, 1)

    def _global(self, cle, valeur):
        self.fen.piloter(cle, valeur, srv=self.fen.srv_controle(), tous=self.chk_tous.isChecked())

    def _delai(self, cle, w):
        e = (self.fen.srv_controle() or Serveur({"cle": ""})).etat_pilotage or {}
        if abs((e.get("delais") or {}).get(cle, -1) - w.value()) > 1e-6:
            self._global(cle, w.value())

    def _combo(self):
        fen = self.fen
        srvs = [s for s in fen.affiches() if s.pilotage_autorise] or fen.affiches()
        if [self.combo_srv.itemData(i) for i in range(self.combo_srv.count())] != [s.cle for s in srvs]:
            self.combo_srv.clear()
            for s in srvs:
                self.combo_srv.addItem(s.nom, s.cle)
        courant = fen.srv_controle()
        i = self.combo_srv.findData(courant.cle if courant else None)
        if i >= 0:
            self.combo_srv.setCurrentIndex(i)
        self.barre_srv.setVisible(len(srvs) > 1)
        self.chk_tous.setVisible(sum(1 for s in srvs if s.pilotage_autorise) > 1)

    def rafraichir(self):
        fen = self.fen
        self._combo()
        srv = fen.srv_controle()
        e = srv.etat_pilotage if srv else None
        self.pile.setCurrentIndex(1 if srv and srv.pilotage_autorise and e else 0)
        if not e:
            return
        self.inter_det.blockSignals(True)
        self.inter_det.regler(e["detection"])
        self.inter_det.blockSignals(False)
        if [self.combo_niveau.itemData(i) for i in range(self.combo_niveau.count())] != \
                [n["cle"] for n in e.get("niveaux", [])]:
            self.combo_niveau.clear()
            for n in e.get("niveaux", []):
                self.combo_niveau.addItem(n["nom"], n["cle"])
        i = self.combo_niveau.findData(e.get("niveau"))
        if i >= 0 and not self.combo_niveau.view().isVisible():
            self.combo_niveau.setCurrentIndex(i)
            self.lbl_niveau.setText(e["niveaux"][i]["texte"])
        for cle, s in self.delais.items():
            if not s.hasFocus():
                s.blockSignals(True)
                s.setValue(float((e.get("delais") or {}).get(cle) or 0))
                s.blockSignals(False)
        # caméras
        ids = [srv.uid(c["id"]) for c in e["cameras"]]
        if ids != list(self.lignes_cam):
            for w in self.lignes_cam.values():
                w["widget"].setParent(None)
            self.lignes_cam = {}
            for c in e["cameras"]:
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(0, 4, 0, 4)
                lab = QLabel(c["nom"])
                lab.setStyleSheet("font-weight: 600;")
                h.addWidget(lab, 1)
                h.addWidget(etiquette("En marche", "aide", False))
                im = Interrupteur()
                im.toggled.connect(lambda v, i=c["id"], s=srv: fen.piloter("camera.marche", bool(v), i, s))
                h.addWidget(im)
                h.addSpacing(12)
                h.addWidget(etiquette("Détection", "aide", False))
                idt = Interrupteur()
                idt.toggled.connect(lambda v, i=c["id"], s=srv: fen.piloter("camera.detection", bool(v), i, s))
                h.addWidget(idt)
                h.addSpacing(12)
                bc = Bouton("Vidéo sur le PC", "discret", "video")
                bc.clicked.connect(lambda _=False, i=c["id"], s=srv: fen.piloter("camera.clip", True, i, s))
                h.addWidget(bc)
                self.v_cams.addWidget(w)
                self.lignes_cam[srv.uid(c["id"])] = {"widget": w, "marche": im, "detection": idt, "clip": bc}
        for c in e["cameras"]:
            ligne = self.lignes_cam[srv.uid(c["id"])]
            for k, val in (("marche", c.get("en_marche", False)), ("detection", c.get("detection", True))):
                ligne[k].blockSignals(True)
                ligne[k].regler(val)
                ligne[k].blockSignals(False)
            ligne["clip"].setEnabled(c.get("en_marche", False))
        # canaux
        cles = [c["cle"] for c in e["canaux"]]
        if cles != list(self.lignes_canal):
            for w in self.lignes_canal.values():
                w["widget"].setParent(None)
            self.lignes_canal = {}
            for c in e["canaux"]:
                inter = Interrupteur()
                inter.toggled.connect(lambda v, k=c["cle"]: self._global(k, bool(v)))
                w = ligne_option(c["nom"], inter, " ")
                self.v_canaux.addWidget(w)
                self.lignes_canal[c["cle"]] = {"widget": w, "inter": inter, "aide": w.findChildren(QLabel)[-1]}
        general = next((c for c in e["canaux"] if c["cle"] == "notif.actif"), None)
        for c in e["canaux"]:
            ligne = self.lignes_canal[c["cle"]]
            ligne["inter"].blockSignals(True)
            ligne["inter"].regler(c["actif"])
            ligne["inter"].blockSignals(False)
            ligne["inter"].setEnabled(c["configure"] or c["actif"])
            dependant = c["cle"] not in ("notif.actif", "mail.actif") and general is not None and not general["actif"]
            ligne["aide"].setText("Pas configuré sur le PC Flux" if not c["configure"] else
                                  "Activé, mais les notifications sont coupées" if dependant and c["actif"] else
                                  "Activé" if c["actif"] else "Désactivé")


class PageJournal(QWidget):
    TAILLE = 60

    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self.evenements, self.fin = [], False
        self.plus_anciens = {}  # serveur -> identifiant le plus ancien chargé (None : tout est chargé)
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.addWidget(titre_page("Journal", "Les alertes de vos caméras, les plus récentes en haut."))
        filtres = QHBoxLayout()
        self.combo_srv = QComboBox()
        self.combo_srv.addItem("Tous les serveurs", None)
        self.combo_srv.currentIndexChanged.connect(lambda _i: (self.maj_cameras(forcer=True), self.charger()))
        filtres.addWidget(self.combo_srv)
        self.combo_cam = QComboBox()
        self.combo_cam.addItem("Toutes les caméras", None)
        self.combo_cam.currentIndexChanged.connect(lambda _i: self.charger())
        filtres.addWidget(self.combo_cam)
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText("Rechercher dans les alertes…")
        self.recherche.textChanged.connect(self._remplir)
        filtres.addWidget(self.recherche, 1)
        b = Bouton("Actualiser", "discret", "recherche")
        b.clicked.connect(lambda: self.charger())
        filtres.addWidget(b)
        b = Bouton("Exporter en CSV", "discret", "telecharger")
        b.clicked.connect(self._exporter)
        filtres.addWidget(b)
        racine.addLayout(filtres)
        corps = QHBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date", "Caméra", "Serveur", "Alerte", "Photo"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._apercu)
        self.table.verticalScrollBar().valueChanged.connect(self._defile)
        corps.addWidget(self.table, 1)
        droite = QVBoxLayout()
        self.photo = QLabel("Choisissez une alerte pour voir sa photo")
        self.photo.setObjectName("soustitre")
        self.photo.setWordWrap(True)
        self.photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo.setFixedSize(340, 255)
        self.photo.setStyleSheet(f"background: {C['video']}; border-radius: {T.rayon}px;")
        droite.addWidget(self.photo)
        self.lbl_detail = etiquette("")
        droite.addWidget(self.lbl_detail)
        self.b_photo = Bouton("Enregistrer la photo", "discret", "capture")
        self.b_photo.clicked.connect(self._enregistrer_photo)
        self.b_photo.setEnabled(False)
        droite.addWidget(self.b_photo)
        self.b_cam = Bouton("Ouvrir la caméra", "discret", "cameras")
        self.b_cam.clicked.connect(self._ouvrir_camera)
        self.b_cam.setEnabled(False)
        droite.addWidget(self.b_cam)
        droite.addStretch(1)
        self.lbl_compte = etiquette("")
        droite.addWidget(self.lbl_compte)
        corps.addLayout(droite)
        racine.addLayout(corps, 1)
        self._pix = None

    def _serveurs(self):
        cle = self.combo_srv.currentData()
        return [s for s in self.fen.affiches() if cle is None or s.cle == cle]

    def maj_cameras(self, forcer=False):
        fen = self.fen
        srvs = [(s.cle, s.nom) for s in fen.affiches()]
        if [self.combo_srv.itemData(i) for i in range(1, self.combo_srv.count())] != [c for c, _ in srvs]:
            actuel = self.combo_srv.currentData()
            self.combo_srv.blockSignals(True)
            self.combo_srv.clear()
            self.combo_srv.addItem("Tous les serveurs", None)
            for c, n in srvs:
                self.combo_srv.addItem(n, c)
            self.combo_srv.setCurrentIndex(max(0, self.combo_srv.findData(actuel)))
            self.combo_srv.blockSignals(False)
        self.combo_srv.setVisible(len(srvs) > 1)
        cles = {s.cle for s in self._serveurs()}
        noms = [(c["uid"], c["nom"] + (f" · {c['serveur']}" if fen.plusieurs() and self.combo_srv.currentData() is None
                                       else "")) for c in fen.cameras if c["srv"] in cles]
        if not forcer and [self.combo_cam.itemData(i) for i in range(1, self.combo_cam.count())] == [i for i, _ in noms]:
            return
        actuel = self.combo_cam.currentData()
        self.combo_cam.blockSignals(True)
        self.combo_cam.clear()
        self.combo_cam.addItem("Toutes les caméras", None)
        for i, n in noms:
            self.combo_cam.addItem(n, i)
        self.combo_cam.setCurrentIndex(max(0, self.combo_cam.findData(actuel)))
        self.combo_cam.blockSignals(False)

    def charger(self, suite=False):
        fen = self.fen
        uid = self.combo_cam.currentData()
        srv_cam, cam_id = uid.split("|", 1) if uid else (None, None)
        cibles = [s for s in self._serveurs() if s.actif and (srv_cam is None or s.cle == srv_cam)]
        if suite:
            cibles = [s for s in cibles if self.plus_anciens.get(s.cle)]
        else:
            self.plus_anciens = {}
        if not cibles:
            if not suite:
                self.evenements = []
                self._remplir()
            return
        taille = self.TAILLE

        def tout_charger():
            resultats = []
            for s in cibles:
                try:
                    lignes = s.api.journal(self.plus_anciens.get(s.cle) if suite else None, cam_id, taille)\
                        .get("journal", [])
                except module_api.ErreurApi as e:
                    if e.code == 401:
                        raise
                    lignes = []
                except Exception:  # noqa: BLE001
                    lignes = []
                resultats.append((s, lignes))
            return resultats

        def fini(resultats):
            nouveaux = []
            for s, lignes in resultats:
                self.plus_anciens[s.cle] = lignes[-1]["id"] if len(lignes) >= taille else None
                nouveaux += [fen.enrichir(e, s) for e in lignes]
            nouveaux.sort(key=lambda e: e["heure"], reverse=True)
            self.evenements = (self.evenements if suite else []) + nouveaux
            self.fin = not any(self.plus_anciens.values())
            if not suite and uid is None and self.combo_srv.currentData() is None:
                fen.dernieres_alertes = [e for e in self.evenements if e["niveau"] == "alerte"][:50]
                fen.journal_charge = True
            self._remplir()
        fen.appeler(tout_charger, fini)

    def _remplir(self):
        filtre = self.recherche.text().strip().lower()
        lignes = [e for e in self.evenements
                  if not filtre or filtre in (e["texte"] + " " + e["camera"] + " " + e.get("serveur", "")).lower()]
        self.table.setColumnHidden(2, not self.fen.plusieurs())
        self.table.setRowCount(len(lignes))
        for i, e in enumerate(lignes):
            for j, val in enumerate((heure(e["heure"], True), e["camera"], e.get("serveur", ""), e["texte"],
                                     "oui" if e.get("photo") else "")):
                it = QTableWidgetItem(val)
                it.setData(Qt.ItemDataRole.UserRole, e)
                if e.get("prioritaire"):
                    it.setForeground(couleur("liste_noire"))
                self.table.setItem(i, j, it)
        for c in (0, 1, 2):
            self.table.resizeColumnToContents(c)
        self.lbl_compte.setText(f"{len(lignes)} alerte(s) affichée(s)" + ("" if self.fin else " · faites défiler pour la suite"))

    def _defile(self, v):
        if not self.fin and v >= self.table.verticalScrollBar().maximum() - 2 and self.evenements:
            self.fin = True  # évite les doubles chargements
            self.charger(suite=True)

    def _courant(self):
        it = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _apercu(self):
        e = self._courant()
        self.b_cam.setEnabled(e is not None)
        self.b_photo.setEnabled(False)
        self._pix = None
        if e is None:
            return
        self.lbl_detail.setText(f"{e['texte']}\n{e['camera']}" + (f" · {e.get('serveur')}" if self.fen.plusieurs() else "")
                                + f" · {heure(e['heure'], True)}")
        srv = self.fen.serveurs.get(e.get("srv"))
        if not e.get("photo") or srv is None or not srv.actif:
            self.photo.setText("Pas de photo pour cette alerte")
            return
        self.photo.setText("Chargement…")

        def fini(octets):
            if self._courant() is not e:
                return
            pix = QPixmap()
            if octets and pix.loadFromData(octets):
                self._pix = pix
                self.photo.setPixmap(pix.scaled(self.photo.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
                self.b_photo.setEnabled(True)
            else:
                self.photo.setText("Photo indisponible (effacée après la durée de conservation)")
        self.fen.appeler(lambda: srv.api.photo(e["id"]), fini, srv=srv)

    def _enregistrer_photo(self):
        e = self._courant()
        if e and self._pix is not None:
            self.fen.enregistrer_capture(f"alerte {e['camera']}", self._pix.toImage(), e["heure"])

    def _ouvrir_camera(self):
        e = self._courant()
        cam = next((c for c in self.fen.cameras if c["uid"] == (e or {}).get("uid")), None)
        if cam:
            self.fen.ouvrir_video(cam)
        elif e:
            self.fen.toast("Cette caméra n'est plus disponible.")

    def _exporter(self):
        if not self.evenements:
            return self.fen.toast("Rien à exporter.")
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter le journal",
                                                os.path.join(os.path.expanduser("~"),
                                                             f"journal-flux-{datetime.now():%Y%m%d-%H%M}.csv"),
                                                "Tableur CSV (*.csv)")
        if not chemin:
            return
        with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Date", "Serveur", "Caméra", "Alerte", "Niveau", "Liste noire"])
            for e in self.evenements:
                w.writerow([heure(e["heure"], True), e.get("serveur", ""), e["camera"], e["texte"], e["niveau"],
                            "oui" if e.get("prioritaire") else ""])
        self.fen.toast(f"Journal exporté ({len(self.evenements)} lignes).", "ok")

    def showEvent(self, e):
        super().showEvent(e)
        self.maj_cameras()
        self.charger()


class PageCompte(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.addWidget(titre_page("Compte", "Chaque PC Flux a ses propres comptes : choisissez le serveur."))
        self.barre_srv = QWidget()
        hb = QHBoxLayout(self.barre_srv)
        hb.setContentsMargins(0, 0, 0, 6)
        hb.addWidget(QLabel("Compte sur le serveur"))
        self.combo_srv = QComboBox()
        self.combo_srv.setMinimumWidth(240)
        self.combo_srv.activated.connect(lambda _i: (fen.choisir_courant(self.combo_srv.currentData()), self.showEvent(None)))
        hb.addWidget(self.combo_srv)
        hb.addStretch(1)
        racine.addWidget(self.barre_srv)
        contenu = QWidget()
        g = QGridLayout(contenu)
        g.setContentsMargins(0, 4, 4, 4)
        g.setSpacing(14)
        f, v = carte("Profil")
        self.lbl_ident = QLabel("")
        self.lbl_ident.setStyleSheet(f"font-size: {T.taille + 6}px; font-weight: 600;")
        v.addWidget(self.lbl_ident)
        self.lbl_infos = etiquette("")
        v.addWidget(self.lbl_infos)
        h = QHBoxLayout()
        self.c_prenom, self.c_nom = QLineEdit(), QLineEdit()
        self.c_prenom.setPlaceholderText("Prénom")
        self.c_nom.setPlaceholderText("Nom")
        h.addWidget(self.c_prenom)
        h.addWidget(self.c_nom)
        v.addLayout(h)
        b = Bouton("Enregistrer mon nom", "discret")
        b.clicked.connect(self._enregistrer_nom)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)
        g.addWidget(f, 0, 0)
        f, v = carte("Mot de passe", "Sur ce serveur seulement. Vos autres appareils seront déconnectés.")
        self.c_ancien = QLineEdit()
        self.c_nouveau = QLineEdit()
        self.c_confirm = QLineEdit()
        for c, t in ((self.c_ancien, "Mot de passe actuel"), (self.c_nouveau, "Nouveau mot de passe"),
                     (self.c_confirm, "Confirmer")):
            c.setEchoMode(QLineEdit.EchoMode.Password)
            c.setPlaceholderText(t)
            v.addWidget(c)
        self.lbl_force = etiquette("Au moins 10 caractères, avec des lettres et des chiffres.")
        self.c_nouveau.textChanged.connect(lambda m: self.lbl_force.setText(force_mdp(m)[1] if m else
                                                                            "Au moins 10 caractères, avec des lettres et des chiffres."))
        v.addWidget(self.lbl_force)
        b = Bouton("Changer de mot de passe", "discret", "reglages")
        b.clicked.connect(self._changer_mdp)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(f, 0, 1)
        f, v = carte("Appareils connectés à ce serveur")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Appareil", "Adresse", "Dernière activité"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(170)
        v.addWidget(self.table)
        h = QHBoxLayout()
        b = Bouton("Déconnecter l'appareil choisi", "discret")
        b.clicked.connect(self._revoquer)
        h.addWidget(b)
        b = Bouton("Déconnecter tous mes autres appareils", "discret")
        b.clicked.connect(lambda: self._srv() and self.fen.appeler(lambda: self._srv().api.revoquer(None), self._profil_recu,
                                                                   "Vos autres appareils sont déconnectés.", srv=self._srv()))
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g.addWidget(f, 1, 0, 1, 2)
        f, v = carte("Mon compte sur d'autres PC Flux", "Suivez plusieurs établissements depuis Flux Remote. Si votre "
                                                          "responsable a transféré votre compte, connectez-vous avec le "
                                                          "même mail et le même mot de passe ; sinon, vos informations "
                                                          "sont reprises pour créer le compte en un clic.")
        b = Bouton("Utiliser mon compte sur un autre serveur", "discret", "plus")
        b.clicked.connect(fen.ajouter_serveur)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(f, 2, 0, 1, 2)
        f, v = carte("Mes données (RGPD)")
        h = QHBoxLayout()
        b = Bouton("Exporter mes données", "discret", "telecharger")
        b.clicked.connect(self._exporter)
        h.addWidget(b)
        b = Bouton("Lire les conditions d'utilisation", "discret", "info")
        b.clicked.connect(self._cgu)
        h.addWidget(b)
        b = Bouton("Supprimer mon compte", "danger")
        b.clicked.connect(self._supprimer)
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g.addWidget(f, 3, 0, 1, 2)
        self.b_deconnexion = Bouton("Se déconnecter de ce serveur", "danger", "sortie")
        self.b_deconnexion.clicked.connect(self._deconnexion)
        g.addWidget(self.b_deconnexion, 4, 0, Qt.AlignmentFlag.AlignLeft)
        g.setRowStretch(5, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        racine.addWidget(defilant(contenu), 1)

    def _srv(self):
        return self.fen.courant()

    def showEvent(self, e):
        if e is not None:
            super().showEvent(e)
        fen = self.fen
        actifs = fen.serveurs_actifs()
        self.combo_srv.clear()
        for s in actifs:
            self.combo_srv.addItem(s.nom, s.cle)
        srv = self._srv()
        if srv is not None:
            self.combo_srv.setCurrentIndex(max(0, self.combo_srv.findData(srv.cle)))
            fen.appeler(srv.api.profil, lambda p, s=srv: self._profil_recu(p, s), srv=srv)
        self.barre_srv.setVisible(len(actifs) > 1)

    def _profil_recu(self, p, srv=None):
        srv = srv or self._srv()
        if srv is None:
            return
        srv.profil = p
        srv.pilotage_autorise = bool(p.get("pilotage"))
        if srv is not self._srv():
            return
        self.lbl_ident.setText(f"{p['prenom']} {p['nom']}")
        self.lbl_infos.setText(f"{p['mail']}\nServeur : {srv.nom}\nEntreprise : {p.get('entreprise') or 'aucune'}"
                               f"\nPilotage à distance : {'autorisé' if p.get('pilotage') else 'non autorisé'}"
                               f"\nCompte créé le {datetime.fromtimestamp(p['cree_le']):%d/%m/%Y}")
        if not self.c_prenom.hasFocus() and not self.c_nom.hasFocus():
            self.c_prenom.setText(p["prenom"])
            self.c_nom.setText(p["nom"])
        sessions = p.get("sessions", [])
        self.table.setRowCount(len(sessions))
        for i, s in enumerate(sessions):
            for j, val in enumerate(((s.get("appareil") or "Appareil") + (" · cet ordinateur" if s.get("courante") else ""),
                                     s.get("ip") or "", heure(s["activite"], True))):
                it = QTableWidgetItem(val)
                it.setData(Qt.ItemDataRole.UserRole, s)
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def _enregistrer_nom(self):
        srv = self._srv()
        p, n = self.c_prenom.text().strip(), self.c_nom.text().strip()
        if not p or not n:
            return self.fen.toast("Le prénom et le nom ne peuvent pas être vides.", "erreur")
        if srv:
            self.fen.appeler(lambda: srv.api.modifier_profil(prenom=p, nom=n), self._profil_recu, "Profil enregistré.",
                             srv=srv)

    def _changer_mdp(self):
        srv = self._srv()
        a, n, c = self.c_ancien.text(), self.c_nouveau.text(), self.c_confirm.text()
        if not mdp_accepte(n):
            return self.fen.toast("Nouveau mot de passe trop faible : 10 caractères, lettres et chiffres.", "erreur")
        if n != c:
            return self.fen.toast("Les deux mots de passe diffèrent.", "erreur")

        def fini(r):
            for w in (self.c_ancien, self.c_nouveau, self.c_confirm):
                w.clear()
            self.fen.toast(r.get("message") or "Mot de passe changé.", "ok")
        if srv:
            self.fen.appeler(lambda: srv.api.changer_mdp(a, n), fini, srv=srv)

    def _revoquer(self):
        srv = self._srv()
        it = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        s = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not s or srv is None:
            return self.fen.toast("Choisissez un appareil dans la liste.")
        if s.get("courante"):
            return self._deconnexion()
        self.fen.appeler(lambda: srv.api.revoquer(s["id"]), self._profil_recu, "Appareil déconnecté.", srv=srv)

    def _exporter(self):
        srv = self._srv()
        if srv is None:
            return
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter mes données",
                                                os.path.join(os.path.expanduser("~"), "flux-mes-donnees.json"),
                                                "JSON (*.json)")
        if chemin:
            def fini(octets):
                with open(chemin, "wb") as f:
                    f.write(octets)
                self.fen.toast("Vos données ont été exportées.", "ok")
            self.fen.appeler(srv.api.exporter, fini, srv=srv)

    def _cgu(self):
        srv = self._srv()
        d = QDialog(self)
        d.setWindowTitle("Conditions d'utilisation")
        d.resize(700, 600)
        v = QVBoxLayout(d)
        from PySide6.QtWidgets import QTextBrowser
        t = QTextBrowser()
        t.setHtml(html_cgu(srv.info if srv else None))
        v.addWidget(t)
        b = Bouton("Fermer", "discret")
        b.clicked.connect(d.accept)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
        d.exec()

    def _supprimer(self):
        srv = self._srv()
        if srv is None:
            return
        mdp, ok = QInputDialog.getText(self, "Supprimer mon compte",
                                       f"Votre compte et vos informations seront effacés du PC Flux « {srv.nom} ». "
                                       "C'est définitif.\n\nMot de passe pour confirmer :", QLineEdit.EchoMode.Password)
        if ok and mdp:
            def fini(r):
                self.fen.toast(r.get("message") or "Compte supprimé.", "ok")
                self.fen.deconnecter_serveur(srv, oublier=True, appel=False)
            self.fen.appeler(lambda: srv.api.supprimer_compte(mdp), fini, srv=srv)

    def _deconnexion(self):
        srv = self._srv()
        if srv and QMessageBox.question(self, "Se déconnecter", f"Se déconnecter du PC Flux « {srv.nom} » ? Vous ne "
                                        "recevrez plus ses alertes sur cet ordinateur.") == QMessageBox.StandardButton.Yes:
            self.fen.deconnecter_serveur(srv)


class PageReglages(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        reg = fen.reg
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.addWidget(titre_page("Réglages", "Réglages de Flux Remote sur cet ordinateur."))
        contenu = QWidget()
        g = QGridLayout(contenu)
        g.setContentsMargins(0, 4, 4, 4)
        g.setSpacing(14)

        f, v = carte("Serveurs Flux", "Les PC Flux suivis par Flux Remote. Chacun garde sa clé, sa session et ses droits.")
        self.v_serveurs = QVBoxLayout()
        self.v_serveurs.setSpacing(2)
        v.addLayout(self.v_serveurs)
        h = QHBoxLayout()
        b = Bouton("Ajouter un serveur", "discret", "plus")
        b.clicked.connect(fen.ajouter_serveur)
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g.addWidget(f, 0, 0, 1, 2)

        f, v = carte("Alertes sur cet ordinateur")
        self.combo_mode = QComboBox()
        for k, lib in MODES_ALERTES:
            self.combo_mode.addItem(lib, k)
        self.combo_mode.setCurrentIndex(max(0, self.combo_mode.findData(reg["alertes.mode"])))
        self.combo_mode.currentIndexChanged.connect(lambda _i: (reg.set("alertes.mode", self.combo_mode.currentData()),
                                                                fen.maj_zone()))
        v.addWidget(ligne_option("Notifications", self.combo_mode, "Sonores : notification et son. Silencieuses : "
                                                                  "notification sans son. Coupées : rien."))
        self.combo_delai = QComboBox()
        for m, lib in ((0, "Aucun"), (1, "1 min"), (5, "5 min"), (15, "15 min"), (30, "30 min")):
            self.combo_delai.addItem(lib, m)
        self.combo_delai.setCurrentIndex(max(0, self.combo_delai.findData(reg["alertes.delai"])))
        self.combo_delai.currentIndexChanged.connect(lambda _i: reg.set("alertes.delai", self.combo_delai.currentData()))
        v.addWidget(ligne_option("Délai entre deux alertes d'une caméra", self.combo_delai))
        self.combo_pause = QComboBox()
        for hh, lib in ((0, "Pas de pause"), (1, "1 heure"), (2, "2 heures"), (4, "4 heures"), (8, "8 heures"),
                        (24, "24 heures")):
            self.combo_pause.addItem(lib, hh)
        self.combo_pause.activated.connect(lambda _i: fen.pause_alertes(self.combo_pause.currentData()))
        self.lbl_pause = etiquette("")
        v.addWidget(ligne_option("Mettre en pause", self.combo_pause))
        v.addWidget(self.lbl_pause)
        i_ouvrir = Interrupteur()
        i_ouvrir.regler(bool(reg["alertes.ouvrir_camera"]))
        i_ouvrir.toggled.connect(lambda e: reg.set("alertes.ouvrir_camera", bool(e)))
        v.addWidget(ligne_option("Ouvrir la caméra quand je clique sur une alerte", i_ouvrir))
        v.addWidget(etiquette("Seuls les serveurs affichés envoient des alertes sur cet ordinateur."))
        b = Bouton("Tester une alerte", "discret", "cloche")
        b.clicked.connect(fen.alerte_test)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(f, 1, 0)

        f, v = carte("Démarrage et fenêtre")
        for cle, lib, aide, rappel in (
                ("systeme.demarrage", "Démarrer avec l'ordinateur", "Flux Remote se lance à l'ouverture de la session.",
                 self._demarrage),
                ("systeme.demarrer_reduit", "Démarrer dans la zone de notification", "Sans ouvrir la fenêtre.",
                 self._demarrage),
                ("systeme.zone_notification", "Fermer = réduire dans la zone de notification",
                 "Les alertes continuent d'arriver. Quitter : clic droit sur l'icône.", None),
                ("systeme.premier_plan_video", "Vidéos toujours au premier plan", "Les fenêtres vidéo restent "
                                                                                    "au-dessus des autres.", None)):
            inter = Interrupteur()
            inter.regler(bool(reg[cle]))
            inter.toggled.connect(lambda e, c=cle, r=rappel: (reg.set(c, bool(e)), r and r()))
            v.addWidget(ligne_option(lib, inter, aide))
        b = Bouton("Créer un raccourci sur le bureau", "discret", "plus")
        b.clicked.connect(self._raccourci)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(f, 1, 1)

        f, v = carte("Apparence")
        self.combo_theme = QComboBox()
        self.combo_theme.addItem("Sombre", "sombre")
        self.combo_theme.addItem("Clair", "clair")
        self.combo_theme.setCurrentIndex(max(0, self.combo_theme.findData(reg["apparence.theme"])))
        self.combo_theme.currentIndexChanged.connect(lambda _i: fen.changer_theme(self.combo_theme.currentData()))
        v.addWidget(ligne_option("Thème", self.combo_theme))
        self.combo_taille = QComboBox()
        for t, lib in ((12, "Petit"), (13, "Normal"), (15, "Grand"), (17, "Très grand")):
            self.combo_taille.addItem(lib, t)
        self.combo_taille.setCurrentIndex(max(0, self.combo_taille.findData(reg["apparence.taille_police"])))
        self.combo_taille.currentIndexChanged.connect(lambda _i: fen.changer_taille(self.combo_taille.currentData()))
        v.addWidget(ligne_option("Taille du texte", self.combo_taille))
        i_anim = Interrupteur()
        i_anim.regler(bool(reg["apparence.animations"]))
        i_anim.toggled.connect(lambda e: (reg.set("apparence.animations", bool(e)), theme.appliquer(reg)))
        v.addWidget(ligne_option("Animations", i_anim))
        g.addWidget(f, 2, 0)

        f, v = carte("Captures")
        self.lbl_dossier = etiquette("")
        v.addWidget(self.lbl_dossier)
        h = QHBoxLayout()
        b = Bouton("Choisir le dossier…", "discret", "dossier")
        b.clicked.connect(self._choisir_dossier)
        h.addWidget(b)
        b = Bouton("Ouvrir", "discret")
        b.clicked.connect(lambda: systeme.ouvrir_dossier(systeme.dossier_captures(reg["systeme.dossier_captures"])))
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g.addWidget(f, 2, 1)

        f, v = carte("Mises à jour")
        i_maj = Interrupteur()
        i_maj.regler(bool(reg["maj.auto"]))
        i_maj.toggled.connect(lambda e: reg.set("maj.auto", bool(e)))
        v.addWidget(ligne_option("Vérifier au démarrage", i_maj, "Un petit fichier sur le site de Flux, aucune donnée "
                                                                 "envoyée."))
        self.lbl_maj = etiquette(f"Version installée : {VERSION}")
        v.addWidget(self.lbl_maj)
        self.barre_maj = QProgressBar()
        self.barre_maj.setRange(0, 100)
        self.barre_maj.setTextVisible(False)
        self.barre_maj.setFixedHeight(6)
        self.barre_maj.hide()
        v.addWidget(self.barre_maj)
        h = QHBoxLayout()
        b = Bouton("Rechercher une mise à jour", "discret", "telecharger")
        b.clicked.connect(lambda: fen.verifier_maj(manuel=True))
        h.addWidget(b)
        b = Bouton("Site de Flux", "fantome", "lien")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SITE)))
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g.addWidget(f, 3, 0)

        f, v = carte("À propos")
        v.addWidget(etiquette(f"Flux Remote {VERSION} · la télécommande de Flux pour Windows et Linux.\n"
                              "© 2026 DMS Security · logiciel libre sous licence GNU AGPL-3.0, sans garantie. Code "
                              "source : github.com/Daoakashi/FluxRemote. Construit avec Python, Qt pour Python (PySide6, "
                              "LGPL v3) et cryptography (Apache 2.0) : détail dans LICENCES-TIERCES.md, à côté du "
                              "programme.\nFlux Remote a été conçu et développé avec l'aide d'outils d'intelligence "
                              "artificielle, sous la direction et la vérification de son auteur. Aucune image n'est "
                              "envoyée à un service d'IA.\n" + CREDITS_IA))
        h = QHBoxLayout()
        b = Bouton("Feedback", "discret", "message")
        b.setToolTip("Envoyer une idée, un problème ou une question à l'éditeur de Flux")
        b.clicked.connect(fen.feedback)
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g.addWidget(f, 3, 1)
        g.setRowStretch(4, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        racine.addWidget(defilant(contenu), 1)

    def _lignes_serveurs(self):
        fen = self.fen
        vider(self.v_serveurs)
        relais_site = module_api.texte_relais(module_api.relais_site())
        for s in fen.serveurs.values():
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 6, 0, 6)
            voy = Voyant(12)
            voy.regler(("direct" if s.en_ligne else "arret") if s.actif else "chargement")
            h.addWidget(voy)
            txt = QVBoxLayout()
            txt.setSpacing(0)
            lab = QLabel(s.nom)
            lab.setStyleSheet("font-weight: 600;")
            txt.addWidget(lab)
            relais = s.relais or relais_site
            txt.addWidget(etiquette(
                (f"{s.texte_route()} · " if s.actif else "Déconnecté · ")
                + f"clé {module_api.formater_cle(s.cle)[:14]}… · "
                + (f"Internet : relais {relais}" + (" (propre à ce PC)" if s.relais else "") if relais
                   else "aucun relais Internet connu"), "aide"))
            h.addLayout(txt, 1)
            if s.actif:
                h.addWidget(etiquette("Affiché", "aide", False))
                inter = Interrupteur()
                inter.regler(s.affiche)
                inter.toggled.connect(lambda e, s=s: fen.basculer_affichage(s, bool(e)))
                h.addWidget(inter)
            b = Bouton("Relais…", "fantome", "lien")
            b.setToolTip("Adresse du relais Flux utilisé hors du réseau de ce PC Flux. Vide = celui publié sur le site.")
            b.clicked.connect(lambda _=False, s=s: self._choisir_relais(s))
            h.addWidget(b)
            if s.actif:
                b = Bouton("Se déconnecter", "fantome")
                b.clicked.connect(lambda _=False, s=s: fen.deconnecter_serveur(s))
            else:
                b = Bouton("Se reconnecter", "discret", "reseau")
                b.clicked.connect(lambda _=False, s=s: fen.reconnecter(s))
            h.addWidget(b)
            b = Bouton("Retirer", "danger")
            b.clicked.connect(lambda _=False, s=s: self._retirer(s))
            h.addWidget(b)
            self.v_serveurs.addWidget(w)

    def showEvent(self, e):
        if e is not None:
            super().showEvent(e)
        self.lbl_dossier.setText(systeme.dossier_captures(self.fen.reg["systeme.dossier_captures"]))
        self._lignes_serveurs()
        self.maj_pause()

    def _choisir_relais(self, s):
        texte, ok = QInputDialog.getText(
            self, f"Relais Internet · {s.nom}", "Adresse du relais (ex. relais.monentreprise.be ou 203.0.113.5:8443).\n"
            "Laissez vide pour utiliser le relais publié sur le site de Flux.", text=s.relais)
        if not ok:
            return
        texte = texte.strip()
        if texte and not module_api.lire_adresse_relais(texte):
            self.fen.toast("Adresse de relais invalide.", "erreur")
            return
        s.relais = module_api.texte_relais(module_api.lire_adresse_relais(texte)) if texte else ""
        if s.api is not None:
            s.api.relais = module_api.lire_adresse_relais(s.relais) if s.relais else None
        self.fen.sauver_serveurs()
        self.fen.toast("Relais enregistré." if texte else "Relais du site utilisé.", "ok")
        self.showEvent(None)

    def _retirer(self, s):
        if QMessageBox.question(self, "Retirer le serveur", f"Flux Remote oubliera « {s.nom} », sa clé et votre session "
                                "sur ce serveur. Votre compte là-bas n'est pas supprimé. Continuer ?") \
                == QMessageBox.StandardButton.Yes:
            self.fen.deconnecter_serveur(s, oublier=True)
            self.showEvent(None)

    def maj_pause(self):
        jusqua = self.fen.reg["alertes.pause_jusqua"]
        self.lbl_pause.setText(f"En pause jusqu'à {datetime.fromtimestamp(jusqua):%H:%M}." if jusqua > time.time() else "")

    def _demarrage(self):
        try:
            systeme.demarrage_session(bool(self.fen.reg["systeme.demarrage"]), bool(self.fen.reg["systeme.demarrer_reduit"]))
        except OSError as e:
            self.fen.toast(f"Démarrage automatique impossible : {e}", "erreur")

    def _raccourci(self):
        try:
            self.fen.toast(f"Raccourci créé : {systeme.creer_raccourci_bureau()}", "ok")
        except Exception as e:  # noqa: BLE001
            self.fen.toast(f"Raccourci impossible : {e}", "erreur")

    def _choisir_dossier(self):
        d = QFileDialog.getExistingDirectory(self, "Dossier des captures",
                                             systeme.dossier_captures(self.fen.reg["systeme.dossier_captures"]))
        if d:
            self.fen.reg.set("systeme.dossier_captures", d)
            self.lbl_dossier.setText(d)


# ---------------------------------------------------------------------------------------------------
# Fenêtre principale
# ---------------------------------------------------------------------------------------------------
class Fenetre(QMainWindow):
    def __init__(self, reg, reduit=False):
        super().__init__()
        self.reg = reg
        self.serveurs = {}  # clé -> Serveur, dans l'ordre d'ajout
        for d in reg["serveurs"] or []:
            if d.get("cle") and d["cle"] not in self.serveurs:
                self.serveurs[d["cle"]] = Serveur(d)
        self.dernieres_alertes = []
        self.journal_charge = False
        self.videos, self.derniers_envois, self.retenues = {}, {}, {}
        self._derniere_alerte_uid = None
        self._non_vues = 0
        self._srv_controle = None
        self.setWindowTitle("Flux Remote")
        self.setWindowIcon(icone_programme())
        self.setMinimumSize(1060, 680)
        g = reg["fenetre"] or {}
        self.resize(g.get("largeur", 1320), g.get("hauteur", 860))
        if "x" in g:
            self.move(g["x"], g["y"])
        self.pile = QStackedWidget()
        self.setCentralWidget(self.pile)
        self.accueil = Accueil(self)
        self.accueil.connecte.connect(self.debut_session)
        self.accueil.annule.connect(self.retour_principal)
        self.pile.addWidget(self.accueil)
        self.principal = self._principal()
        self.pile.addWidget(self.principal)
        self.toasts = Toasts(self.pile)
        self._zone()
        # relais Internet publié sur le site : dernière adresse connue tout de suite, puis relue en arrière-plan
        module_api.definir_relais_site(reg["relais.site"])
        t = Tache(module_api.charger_relais_site)
        t.fini.connect(lambda texte: texte is not None and texte != reg["relais.site"] and reg.set("relais.site", texte))
        t.lancer()
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._cycle)
        avec_session = [s for s in self.serveurs.values() if s.jeton]
        for s in avec_session:
            self.demarrer_serveur(s)
        if avec_session:
            self._ouvrir_principal()
        elif self.serveurs:
            self.reconnecter(next(iter(self.serveurs.values())))
        else:
            self.pile.setCurrentWidget(self.accueil)
            self.accueil.montrer()
        if not reduit or not QSystemTrayIcon.isSystemTrayAvailable():
            self.show()
        if reg["maj.auto"]:
            QTimer.singleShot(5000, lambda: self.verifier_maj(manuel=False))

    # --- serveurs ---------------------------------------------------------------------------------
    def serveurs_actifs(self):
        return [s for s in self.serveurs.values() if s.actif]

    def affiches(self):
        actifs = self.serveurs_actifs()
        return [s for s in actifs if s.affiche] or actifs

    def plusieurs(self):
        return len(self.affiches()) > 1

    def courant(self):
        """Serveur choisi pour le compte (et par défaut pour le contrôle)."""
        actifs = self.serveurs_actifs()
        return next((s for s in actifs if s.cle == self.reg["serveur.courant"]), actifs[0] if actifs else None)

    def choisir_courant(self, cle):
        self.reg.set("serveur.courant", cle or "")

    def srv_controle(self):
        candidats = [s for s in self.affiches() if s.pilotage_autorise] or self.affiches()
        return next((s for s in candidats if s.cle == self._srv_controle), None) or \
            next((s for s in candidats if s is self.courant()), None) or (candidats[0] if candidats else None)

    def choisir_controle(self, cle):
        self._srv_controle = cle
        s = self.serveurs.get(cle)
        if s is not None and s.actif and s.pilotage_autorise:
            self.appeler(s.api.pilotage, lambda e, s=s: self._etat_recu(s, e), srv=s)

    def serveur_de(self, cam):
        return self.serveurs.get(cam.get("srv"))

    def profil_connu(self):
        s = self.courant()
        if s is not None and s.profil:
            return s.profil
        return next((x.profil for x in self.serveurs_actifs() if x.profil), {})

    def mail_connu(self):
        return self.profil_connu().get("mail", "")

    @property
    def cameras(self):
        cams = []
        for s in self.affiches():
            for c in s.cameras:
                cams.append(dict(c, uid=s.uid(c["id"]), srv=s.cle, serveur=s.nom))
        return cams

    def enrichir(self, e, s):
        return dict(e, srv=s.cle, uid=s.uid(e.get("camera_id", "")), serveur=s.nom)

    def sauver_serveurs(self):
        self.reg.set("serveurs", [s.vers_dict() for s in self.serveurs.values()])

    def afficher_serveurs(self, cles):
        for s in self.serveurs_actifs():
            s.affiche = s.cle in cles
        self.sauver_serveurs()

    def basculer_affichage(self, s, valeur=None):
        s.affiche = (not s.affiche) if valeur is None else valeur
        if not any(x.affiche for x in self.serveurs_actifs()):
            s.affiche = True
        self.sauver_serveurs()
        self.serveurs_changes()

    def serveurs_changes(self):
        self.p_cameras.reconstruire()
        self._rafraichir_pages()
        if self.pages_pile.currentWidget() is self.p_journal:
            self.p_journal.maj_cameras(forcer=True)
            self.p_journal.charger()

    def demarrer_serveur(self, s):
        self.arreter_serveur(s)
        s.api = s.nouvelle_api()
        s.en_ligne = True
        s.ecoute = Ecoute(s.api)
        s.ecoute.evenements.connect(lambda ev, s=s: self._alertes(ev, s))
        s.ecoute.session_perdue.connect(lambda msg, s=s: self._session_perdue(s, msg))
        s.ecoute.connecte.connect(lambda ok, s=s: self._connexion_etat(s, ok))
        self.appeler(s.api.info, lambda i, s=s: self._info_recue(s, i), srv=s)
        self.appeler(s.api.profil, lambda p, s=s: self._profil_recu(s, p), srv=s)
        if hasattr(self, "p_cameras"):
            self.p_cameras.sync_serveurs()

    def arreter_serveur(self, s):
        if s.ecoute is not None:
            s.ecoute.arreter()
            s.ecoute = None
        s.api = None
        s.cameras, s.etat_pilotage = [], None
        for uid, v in list(self.videos.items()):
            if uid.startswith(s.cle + "|"):
                v.close()
        if hasattr(self, "p_cameras"):
            self.p_cameras.sync_serveurs()

    def _ouvrir_principal(self):
        self.pile.setCurrentWidget(self.principal)
        self.statusBar().show()
        self._maj_marque()
        if self.pages_pile.currentWidget() is None or self.pages_pile.currentWidget() is self.p_tableau:
            self.aller("tableau")
        self._timer.start()
        self.actualiser()
        self.p_journal.charger()

    def debut_session(self):
        """Fin de l'appairage ou de la connexion d'un serveur (champs provisoires de reg) : il rejoint la liste."""
        reg = self.reg
        cle = reg["cle"]
        s = self.serveurs.get(cle)
        donnees = {"cle": cle, "nom": reg["nom_serveur"] or "Flux", "hote": reg["hote"], "hotes": reg["hotes"],
                   "port": reg["port"], "relais": reg["relais"], "jeton": reg["jeton"], "cgu": reg["cgu"]}
        if s is None:
            s = Serveur(dict(donnees, affiche=True))
            self.serveurs[cle] = s
        else:
            for k, val in donnees.items():
                setattr(s, k, val)
        reg.oublier_serveur()
        self.sauver_serveurs()
        if not reg["serveur.courant"] or reg["serveur.courant"] not in self.serveurs:
            self.choisir_courant(cle)
        self.demarrer_serveur(s)
        if len(self.serveurs_actifs()) > 1:
            self.toast(f"« {s.nom} » ajouté : ses caméras et ses alertes s'affichent avec les autres.", "ok")
        self._ouvrir_principal()

    def ajouter_serveur(self):
        self.reg.oublier_serveur()
        self.pile.setCurrentWidget(self.accueil)
        self.accueil.montrer()

    def reconnecter(self, s):
        self.reg.maj(hote=s.hote, hotes=s.hotes, port=s.port, cle=s.cle, nom_serveur=s.nom, relais=s.relais,
                     cgu=s.cgu, jeton="")
        self.pile.setCurrentWidget(self.accueil)
        self.accueil.montrer()

    def retour_principal(self):
        self.reg.oublier_serveur()
        if self.serveurs_actifs():
            self.pile.setCurrentWidget(self.principal)
        else:
            self.accueil.montrer()

    def deconnecter_serveur(self, s, oublier=False, appel=True):
        if appel and s.api is not None:
            Tache(s.api.deconnecter).lancer()
        self.arreter_serveur(s)
        s.jeton = ""
        if oublier:
            self.serveurs.pop(s.cle, None)
            for k in ("cameras.masquees", "alertes.muettes"):
                self.reg.set(k, [u for u in self.reg[k] if not u.startswith(s.cle + "|")])
        self.sauver_serveurs()
        self.dernieres_alertes = [e for e in self.dernieres_alertes if e.get("srv") != s.cle]
        self._apres_changement()

    def _apres_changement(self):
        if self.serveurs_actifs():
            self._maj_marque()
            self.serveurs_changes()
            return
        self._timer.stop()
        self.statusBar().hide()
        if self.serveurs:
            self.reconnecter(next(iter(self.serveurs.values())))
        else:
            self.pile.setCurrentWidget(self.accueil)
            self.accueil.montrer()

    def _session_perdue(self, s, msg):
        self.toast(f"{s.nom} : {msg or 'session expirée'}. Reconnectez-vous (Réglages › Serveurs Flux).", "erreur")
        self.arreter_serveur(s)
        s.jeton = ""
        self.sauver_serveurs()
        if self.serveurs_actifs():
            self._apres_changement()
        else:
            self.reconnecter(s)

    def _info_recue(self, s, info):
        s.info = info
        self.accueil.info = info
        if info.get("nom") and info["nom"] != s.nom:
            s.nom = info["nom"]
            self.sauver_serveurs()
        self._maj_marque()

    def _profil_recu(self, s, p):
        s.profil = p
        s.pilotage_autorise = bool(p.get("pilotage"))
        self.maj_zone()

    def _connexion_etat(self, s, ok):
        if ok != s.en_ligne:
            s.en_ligne = ok
            if not ok:
                self.toast(f"Connexion à « {s.nom} » perdue, nouvelle tentative…", "erreur")
        self._maj_barre()

    def _maj_marque(self):
        actifs = self.serveurs_actifs()
        self.lbl_serveur.setText(f"{len(actifs)} serveurs Flux" if len(actifs) > 1 else
                                 (actifs[0].nom if actifs else "Flux"))

    def _maj_barre(self):
        actifs = self.serveurs_actifs()
        en_ligne = [s for s in actifs if s.en_ligne]
        teinte = C["succes"] if len(en_ligne) == len(actifs) else C["danger"]
        if len(actifs) == 1:
            s = actifs[0]
            texte = (f"● {'Connecté à' if s.en_ligne else 'Connexion perdue avec'} {s.nom} · {s.texte_route()} · "
                     "chiffré, clé vérifiée")
        else:
            hors = [s.nom for s in actifs if not s.en_ligne]
            texte = (f"● Connecté à {len(en_ligne)}/{len(actifs)} serveurs Flux · chiffré, clés vérifiées"
                     + (f" · injoignable : {', '.join(hors)}" if hors else ""))
        self.st_connexion.setText(texte)
        self.st_connexion.setStyleSheet(f"color: {teinte}; padding: 0 6px;")
        pause = self.reg["alertes.pause_jusqua"] > time.time()
        self.st_alertes.setText("Alertes en pause" if pause else f"Alertes {dict(MODES_ALERTES)[self.reg['alertes.mode']].lower()}")

    # --- construction -----------------------------------------------------------------------------
    def _principal(self):
        w = QWidget()
        w.setObjectName("fond")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        barre = QWidget()
        barre.setObjectName("panneau")
        barre.setFixedWidth(232)
        bv = QVBoxLayout(barre)
        bv.setContentsMargins(10, 16, 10, 14)
        bv.setSpacing(4)
        marque = QHBoxLayout()
        marque.setContentsMargins(8, 0, 0, 0)
        self.logo = Logo(34)
        marque.addWidget(self.logo)
        lab = QLabel("Flux Remote")
        lab.setStyleSheet(f"font-size: {T.taille + 7}px; font-weight: 700;")
        marque.addWidget(lab)
        marque.addStretch(1)
        bv.addLayout(marque)
        self.lbl_serveur = etiquette("", "aide", False)
        self.lbl_serveur.setContentsMargins(10, 4, 0, 0)
        bv.addWidget(self.lbl_serveur)
        bv.addSpacing(14)
        self.nav = {}
        for cle, lib, ic in PAGES:
            b = BoutonNav(lib, ic)
            b.clicked.connect(lambda _=False, k=cle: self.aller(k))
            bv.addWidget(b)
            self.nav[cle] = b
        bv.addStretch(1)
        b_fb = BoutonNav("Feedback", "message")
        b_fb.setCheckable(False)
        b_fb.setToolTip("Envoyer une idée, un problème ou une question à l'éditeur de Flux")
        b_fb.clicked.connect(self.feedback)
        bv.addWidget(b_fb)
        self.b_cloche = BoutonNav("Alertes sonores", "cloche")
        self.b_cloche.setCheckable(False)
        self.b_cloche.clicked.connect(self._menu_alertes)
        bv.addWidget(self.b_cloche)
        h.addWidget(barre)
        zone = QWidget()
        zv = QVBoxLayout(zone)
        zv.setContentsMargins(26, 18, 26, 14)
        self.pages_pile = QStackedWidget()
        self.p_tableau, self.p_cameras = PageTableau(self), PageCameras(self)
        self.p_controle, self.p_journal = PageControle(self), PageJournal(self)
        self.p_compte, self.p_reglages = PageCompte(self), PageReglages(self)
        self.pages = {"tableau": self.p_tableau, "cameras": self.p_cameras, "controle": self.p_controle,
                      "journal": self.p_journal, "compte": self.p_compte, "reglages": self.p_reglages}
        for p in self.pages.values():
            self.pages_pile.addWidget(p)
        zv.addWidget(self.pages_pile)
        h.addWidget(zone, 1)
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.st_connexion = QLabel("")
        self.st_alertes = QLabel("")
        sb.addWidget(self.st_connexion)
        sb.addPermanentWidget(self.st_alertes)
        sb.addPermanentWidget(QLabel(f"Flux Remote {VERSION}"))
        sb.hide()
        for i, (cle, _, _) in enumerate(PAGES):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda k=cle: self.aller(k))
        QShortcut(QKeySequence("F5"), self, activated=self.actualiser)
        self.p_cameras.sync_serveurs()
        return w

    def _zone(self):
        """Icône dans la zone de notification (près de l'horloge)."""
        self.zone = QSystemTrayIcon(self.windowIcon(), self)
        self.zone.setToolTip("Flux Remote")
        m = QMenu()
        m.addAction("Ouvrir Flux Remote", self.montrer)
        m.addSeparator()
        self.menu_modes = {}
        for k, lib in MODES_ALERTES:
            a = QAction(f"Alertes {lib.lower()}", m, checkable=True)
            a.triggered.connect(lambda _=False, k=k: (self.reg.set("alertes.mode", k), self.maj_zone()))
            m.addAction(a)
            self.menu_modes[k] = a
        sous = m.addMenu("Pause des alertes")
        for hh in (1, 2, 4, 8):
            sous.addAction(f"{hh} heure{'s' if hh > 1 else ''}", lambda h_=hh: self.pause_alertes(h_))
        sous.addAction("Reprendre maintenant", lambda: self.pause_alertes(0))
        m.addSeparator()
        self.a_detection = m.addAction("Couper la détection sur les PC Flux", self._basculer_detection)
        m.addSeparator()
        m.addAction("Quitter", self.quitter)
        self.zone.setContextMenu(m)
        self.zone.activated.connect(lambda r: r == QSystemTrayIcon.ActivationReason.Trigger and self.montrer())
        self.zone.messageClicked.connect(self._message_clique)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.zone.show()
        self.maj_zone()

    def _pilotables(self):
        return [s for s in self.affiches() if s.pilotage_autorise]

    def _basculer_detection(self):
        cibles = self._pilotables()
        active = any(s.detection_globale for s in cibles)
        for s in cibles:
            self.piloter("detection.actif", not active, srv=s)

    def maj_zone(self):
        mode = self.reg["alertes.mode"]
        for k, a in self.menu_modes.items():
            a.setChecked(k == mode)
        pause = self.reg["alertes.pause_jusqua"] > time.time()
        lib = dict(MODES_ALERTES)[mode]
        self.b_cloche.setText(f"Alertes en pause ({datetime.fromtimestamp(self.reg['alertes.pause_jusqua']):%H:%M})"
                              if pause else f"Alertes {lib.lower()}")
        self.b_cloche._icone = "cloche_barree" if pause or mode == "coupees" else "cloche"
        self.b_cloche.update()
        cibles = self._pilotables()
        self.a_detection.setVisible(bool(cibles))
        active = any(s.detection_globale for s in cibles)
        lieu = "les PC Flux" if len(cibles) > 1 else "le PC Flux"
        self.a_detection.setText(f"Couper la détection sur {lieu}" if active else f"Réactiver la détection sur {lieu}")
        actifs = self.serveurs_actifs()
        self.zone.setToolTip("Flux Remote · " + (f"{len(actifs)} serveurs" if len(actifs) > 1 else
                                                 actifs[0].nom if actifs else "non connecté"))
        if hasattr(self, "p_reglages"):
            self.p_reglages.maj_pause()

    def _menu_alertes(self):
        m = QMenu(self)
        for k, lib in MODES_ALERTES:
            a = m.addAction(f"Alertes {lib.lower()}", lambda k=k: (self.reg.set("alertes.mode", k), self.maj_zone()))
            a.setCheckable(True)
            a.setChecked(self.reg["alertes.mode"] == k)
        m.addSeparator()
        for hh in (1, 2, 4, 8):
            m.addAction(f"Pause de {hh} heure{'s' if hh > 1 else ''}", lambda h_=hh: self.pause_alertes(h_))
        if self.reg["alertes.pause_jusqua"] > time.time():
            m.addAction("Reprendre maintenant", lambda: self.pause_alertes(0))
        m.exec(self.b_cloche.mapToGlobal(self.b_cloche.rect().topLeft()))

    # --- données ----------------------------------------------------------------------------------------
    def appeler(self, f, rappel=None, message_ok=None, srv=None):
        """Appel au serveur hors de l'interface ; les erreurs s'affichent en bas à droite."""
        def ok(r):
            if rappel:
                rappel(r)
            if message_ok:
                self.toast(message_ok, "ok")

        def echec(msg):
            if msg.startswith(SESSION_PERDUE):
                cible = srv or self.courant()
                if cible is not None and cible.actif:
                    return self._session_perdue(cible, msg[len(SESSION_PERDUE):])
                return
            self.toast((f"{srv.nom} : " if srv is not None and self.plusieurs() else "") + msg, "erreur")

        def envelopper():
            try:
                return f()
            except module_api.ErreurApi as e:
                raise RuntimeError((SESSION_PERDUE if e.code == 401 else "") + str(e)) from None
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(module_api.message_erreur(e)) from None
        t = Tache(envelopper)
        t.fini.connect(ok)
        t.echec.connect(echec)
        return t.lancer()

    def _etat_recu(self, s, e):
        if s.actif:
            s.etat_pilotage = e
            s.detection_globale = e.get("detection", True)
            self._rafraichir_pages()

    def actualiser(self):
        for s in self.serveurs_actifs():
            self._actualiser_serveur(s)

    def _actualiser_serveur(self, s):
        api = s.api

        def cameras_recues(r):
            if api is not s.api:
                return
            s.cameras = r.get("cameras", [])
            s.sans_entreprise = not r.get("entreprise", True)
            s.detection_globale = bool(r.get("detection", True))
            s.pilotage_autorise = bool(r.get("pilotage", s.pilotage_autorise))
            s.en_ligne = True
            for cam in s.cameras:
                v = self.videos.get(s.uid(cam["id"]))
                if v is not None:
                    v.maj_camera(cam)
            self._rafraichir_pages()
            self.logo.animer(any(c["etat"] == "alerte" for c in self.cameras))

        def echec(_msg):
            s.en_ligne = False
            self._maj_barre()
        t = Tache(api.cameras)
        t.fini.connect(cameras_recues)
        t.echec.connect(echec)
        t.lancer()
        if s.pilotage_autorise:
            t2 = Tache(api.pilotage)
            t2.fini.connect(lambda e: api is s.api and self._etat_recu(s, e))
            t2.lancer()

    def _cycle(self):
        self.actualiser()
        self._maj_barre()
        if self.reg["alertes.pause_jusqua"] and self.reg["alertes.pause_jusqua"] < time.time():
            self.reg.set("alertes.pause_jusqua", 0.0)
            self.maj_zone()

    def _rafraichir_pages(self):
        courant = self.pages_pile.currentWidget()
        if courant in (self.p_tableau, self.p_cameras, self.p_controle):
            courant.rafraichir()
        self.p_journal.maj_cameras()
        self.maj_zone()
        self._maj_barre()

    def piloter(self, cle, valeur, camera=None, srv=None, tous=False):
        """Commande sur un PC Flux (`srv`, par défaut celui du contrôle) ; `tous` : sur tous les serveurs affichés que
        le compte peut piloter (réglages généraux seulement)."""
        srv = srv or self.srv_controle()
        cibles = [srv] if srv is not None else []
        if tous and camera is None:
            cibles += [s for s in self._pilotables() if s is not srv]
        cibles = [s for s in cibles if s.actif and s.pilotage_autorise]
        if not cibles:
            return self.toast("Votre compte n'est pas autorisé à piloter ce PC Flux.", "erreur")
        for s in cibles:
            def fini(e, s=s):
                self._etat_recu(s, e)
                if cle == "camera.clip":
                    self.toast("Vidéo demandée : elle est enregistrée sur le PC Flux.", "ok")
                self._actualiser_serveur(s)
            self.appeler(lambda s=s: s.api.piloter(cle, valeur, camera), fini, srv=s)
        if tous and len(cibles) > 1:
            self.toast(f"Réglage envoyé à {len(cibles)} serveurs.", "ok")

    # --- navigation ------------------------------------------------------------------------------------
    def aller(self, cle):
        for k, b in self.nav.items():
            b.setChecked(k == cle)
        page = self.pages[cle]
        self.pages_pile.setCurrentWidget(page)
        if cle == "journal":
            self._non_vues = 0
            self.nav["journal"].compteur = 0
            self.nav["journal"].update()
        if hasattr(page, "rafraichir"):
            page.rafraichir()

    def journal_camera(self, cam):
        self.aller("journal")
        j = self.p_journal
        if self.plusieurs():
            j.combo_srv.setCurrentIndex(0)
        j.maj_cameras(forcer=True)
        i = j.combo_cam.findData(cam["uid"])
        if i >= 0:
            j.combo_cam.setCurrentIndex(i)

    def ouvrir_video(self, cam):
        v = self.videos.get(cam["uid"])
        if v is None:
            if cam["etat"] == "arret":
                return self.toast(f"« {cam['nom']} » est arrêtée sur le PC Flux.")
            if self.serveur_de(cam) is None or not self.serveur_de(cam).actif:
                return self.toast("Ce PC Flux n'est plus connecté.")
            v = FenetreVideo(self, cam)
            self.videos[cam["uid"]] = v
        v.show()
        v.raise_()
        v.activateWindow()

    def montrer(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toast(self, texte, genre="info"):
        self.toasts.montrer(texte, genre)

    def feedback(self):
        from .feedback import DialogueFeedback
        DialogueFeedback(self, VERSION).exec()

    # --- alertes sur ce PC ------------------------------------------------------------------------------------
    def _alertes(self, evenements, s):
        reg = self.reg
        if s not in self.affiches():
            return  # serveur masqué : pas d'alerte sur cet ordinateur
        nouvelles = [self.enrichir(e, s) for e in evenements if e.get("niveau") == "alerte" or e.get("prioritaire")]
        if not nouvelles:
            return
        self.dernieres_alertes = sorted(nouvelles + self.dernieres_alertes, key=lambda e: e["heure"], reverse=True)[:50]
        if self.pages_pile.currentWidget() is not self.p_journal:
            self._non_vues += len(nouvelles)
            self.nav["journal"].compteur = self._non_vues
            self.nav["journal"].update()
        else:
            self.p_journal.charger()
        if self.pages_pile.currentWidget() is self.p_tableau:
            self.p_tableau.rafraichir()
        mode = reg["alertes.mode"]
        if mode == "coupees" or reg["alertes.pause_jusqua"] > time.time():
            return
        muettes = set(reg["alertes.muettes"])
        maintenant = time.time()
        for e in nouvelles[-5:]:
            uid = e["uid"]
            if uid in muettes and not e.get("prioritaire"):
                continue
            delai = reg["alertes.delai"] * 60
            if delai and not e.get("prioritaire") and maintenant - self.derniers_envois.get(uid, 0) < delai:
                self.retenues[uid] = self.retenues.get(uid, 0) + 1
                continue
            self.derniers_envois[uid] = maintenant
            n = self.retenues.pop(uid, 0)
            titre = (f"{'⚠ LISTE NOIRE · ' if e.get('prioritaire') else ''}{e['camera']}"
                     + (f" · {s.nom}" if self.plusieurs() else ""))
            texte = e["texte"] + (f"  (+{n} pendant le délai)" if n else "")
            self._derniere_alerte_uid = uid
            self.zone.showMessage(titre, texte, QSystemTrayIcon.MessageIcon.Warning if e.get("prioritaire")
                                  else QSystemTrayIcon.MessageIcon.Information, 8000)
            if mode == "sonores" or e.get("prioritaire"):
                jouer_son()

    def _message_clique(self):
        self.montrer()
        cam = next((c for c in self.cameras if c["uid"] == self._derniere_alerte_uid), None)
        if cam and self.reg["alertes.ouvrir_camera"]:
            self.ouvrir_video(cam)

    def alerte_test(self):
        self.zone.showMessage("Flux Remote", "Ceci est une alerte de test : les notifications fonctionnent.",
                              QSystemTrayIcon.MessageIcon.Information, 6000)
        if self.reg["alertes.mode"] == "sonores":
            jouer_son()

    def pause_alertes(self, heures):
        self.reg.set("alertes.pause_jusqua", time.time() + heures * 3600 if heures else 0.0)
        self.maj_zone()
        self._maj_barre()
        self.toast(f"Alertes de cet ordinateur en pause pendant {heures} h." if heures else "Alertes réactivées.", "ok")

    def basculer_muette(self, uid):
        s = set(self.reg["alertes.muettes"])
        s.symmetric_difference_update({uid})
        self.reg.set("alertes.muettes", sorted(s))
        self.p_cameras.rafraichir()

    # --- captures ------------------------------------------------------------------------------------------
    def enregistrer_capture(self, nom, image, t=None):
        dossier = systeme.dossier_captures(self.reg["systeme.dossier_captures"])
        propre = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in nom).strip() or "camera"
        chemin = os.path.join(dossier, f"{propre} {datetime.fromtimestamp(t or time.time()):%Y-%m-%d %H-%M-%S}.jpg")
        if image.save(chemin, "JPG", 92):
            self.toast(f"Capture enregistrée : {os.path.basename(chemin)}", "ok")
        else:
            self.toast("Capture impossible à enregistrer.", "erreur")

    # --- apparence ---------------------------------------------------------------------------------------
    def changer_theme(self, nom):
        self.reg.set("apparence.theme", nom)
        theme.appliquer(self.reg)
        self.toasts.restyler()

    def changer_taille(self, taille):
        self.reg.set("apparence.taille_police", taille)
        theme.appliquer(self.reg)

    # --- mises à jour ------------------------------------------------------------------------------------
    def verifier_maj(self, manuel=False):
        lbl = self.p_reglages.lbl_maj
        if manuel:
            lbl.setText("Recherche…")

        def fini(v):
            if v is None:
                lbl.setText(f"Version installée : {VERSION} · à jour.")
                if manuel:
                    self.toast("Flux Remote est à jour.", "ok")
                return
            lbl.setText(f"Version {v['version']} disponible.")
            if not manuel and v["version"] == self.reg["maj.ignoree"] and not v.get("obligatoire"):
                return
            self._proposer_maj(v)

        def echec(msg):
            lbl.setText(f"Vérification impossible : {msg}")
            if manuel:
                self.toast(f"Mises à jour : {msg}", "erreur")
        t = Tache(maj.verifier)
        t.fini.connect(fini)
        t.echec.connect(echec)
        t.lancer()

    def _proposer_maj(self, v):
        boite = QMessageBox(self)
        boite.setWindowTitle("Mise à jour de Flux Remote")
        boite.setText(f"Flux Remote {v['version']} est disponible (vous avez la {VERSION}).")
        boite.setInformativeText(v.get("notes") or "")
        b_inst = boite.addButton("Installer maintenant", QMessageBox.ButtonRole.AcceptRole)
        b_plus_tard = boite.addButton("Plus tard", QMessageBox.ButtonRole.RejectRole)
        b_ignorer = None if v.get("obligatoire") else boite.addButton("Ignorer cette version",
                                                                      QMessageBox.ButtonRole.DestructiveRole)
        boite.exec()
        if boite.clickedButton() is b_ignorer:
            self.reg.set("maj.ignoree", v["version"])
        elif boite.clickedButton() is b_inst:
            barre = self.p_reglages.barre_maj
            barre.show()
            self.toast("Téléchargement de la mise à jour…")
            t = Tache(maj.installer, v, lambda lu, total: None)
            t.fini.connect(lambda _r: self.quitter(redemarrage=True))
            t.echec.connect(lambda msg: (barre.hide(), self.toast(f"Mise à jour impossible : {msg}", "erreur")))
            t.lancer()
        del b_plus_tard

    # --- fermeture ------------------------------------------------------------------------------------------
    def closeEvent(self, e):
        if self.reg["systeme.zone_notification"] and QSystemTrayIcon.isSystemTrayAvailable() and \
                not getattr(self, "_quitter", False):
            e.ignore()
            self.hide()
            if not getattr(self, "_astuce_vue", False):
                self.zone.showMessage("Flux Remote reste ouvert", "Les alertes continuent d'arriver. Clic droit sur "
                                      "l'icône pour quitter.", QSystemTrayIcon.MessageIcon.Information, 5000)
                self._astuce_vue = True
            return
        self._sauver_fenetre()
        e.accept()
        QApplication.quit()

    def _sauver_fenetre(self):
        if not self.isMaximized() and not self.isFullScreen():
            self.reg.set("fenetre", {"largeur": self.width(), "hauteur": self.height(), "x": self.x(), "y": self.y()})

    def quitter(self, redemarrage=False):
        self._quitter = True
        self._sauver_fenetre()
        for v in list(self.videos.values()):
            v.close()
        for s in self.serveurs_actifs():
            if s.ecoute is not None:
                s.ecoute.arreter()
        self.zone.hide()
        QApplication.quit()
        if redemarrage:
            sys.exit(0)
