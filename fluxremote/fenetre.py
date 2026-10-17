"""Fenêtre principale de Flux Remote : tableau de bord, caméras, contrôle, journal, compte et réglages."""
import csv
import os
import sys
import tempfile
import time
import wave
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QScrollArea, QStackedWidget,
                               QStatusBar, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import api as module_api
from . import maj, systeme, theme
from .alertes import Ecoute
from .connexion import Accueil, force_mdp, html_cgu, mdp_accepte
from .taches import Tache
from .theme import C, T, couleur, dessiner_logo
from .version import SITE, VERSION
from .video import LecteurFlux, VueImage, Vignettes
from .widgets import Bouton, BoutonNav, Interrupteur, Logo, Toasts, Voyant, etiquette, ligne_option, separateur

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
        self.setWindowTitle(f"{cam['nom']} · Flux Remote")
        self.setWindowIcon(fen.windowIcon())
        self.setObjectName("fond")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1100, 680)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        barre = QHBoxLayout()
        self.voyant = Voyant(12)
        barre.addWidget(self.voyant)
        self.lbl = QLabel(cam["nom"])
        self.lbl.setObjectName("titre")
        barre.addWidget(self.lbl)
        self.lbl_etat = etiquette("", "soustitre", False)
        barre.addWidget(self.lbl_etat, 1)
        self.b_detection = Bouton("Détection", "discret", "controle")
        self.b_detection.setToolTip("Activer ou couper la détection de cette caméra sur le PC Flux")
        self.b_detection.clicked.connect(lambda: fen.piloter("camera.detection", not self.cam.get("detection", True),
                                                              self.cam["id"]))
        self.b_clip = Bouton("Vidéo sur le PC", "discret", "video")
        self.b_clip.setToolTip("Enregistre une courte vidéo sur le PC Flux (avec les secondes précédentes)")
        self.b_clip.clicked.connect(lambda: fen.piloter("camera.clip", True, self.cam["id"]))
        for b in (self.b_detection, self.b_clip):
            b.setVisible(fen.pilotage_autorise)
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
        self.lecteur = LecteurFlux(fen.api, cam["id"], 15, 1600)
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
        self.fen.videos.pop(self.cam["id"], None)
        super().closeEvent(e)


# ---------------------------------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------------------------------
class PageTableau(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
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
        # détection
        f, v = carte("Détection sur le PC Flux")
        h = QHBoxLayout()
        self.voyant_det = Voyant(16)
        h.addWidget(self.voyant_det)
        self.lbl_det = QLabel("…")
        self.lbl_det.setStyleSheet(f"font-size: {T.taille + 4}px; font-weight: 600;")
        h.addWidget(self.lbl_det, 1)
        self.inter_det = Interrupteur()
        self.inter_det.toggled.connect(lambda e: fen.piloter("detection.actif", bool(e)))
        h.addWidget(self.inter_det)
        v.addLayout(h)
        self.lbl_niveau = etiquette("")
        v.addWidget(self.lbl_niveau)
        self.lbl_pilotage = etiquette("")
        v.addWidget(self.lbl_pilotage)
        g.addWidget(f, 1, 0, 1, 2)
        # actions rapides
        f, v = carte("Actions rapides")
        self.b_pause = Bouton("Pause des alertes sur ce PC (1 h)", "discret", "cloche_barree")
        self.b_pause.clicked.connect(lambda: fen.pause_alertes(1))
        self.b_tout = Bouton("Couper détection et notifications", "danger", "pause")
        self.b_tout.setToolTip("Mode discret : coupe la détection et toutes les notifications de Flux")
        self.b_tout.clicked.connect(self._tout_couper)
        self.b_reprendre = Bouton("Tout réactiver", "primaire", "lecture")
        self.b_reprendre.clicked.connect(self._tout_reprendre)
        b_mur = Bouton("Ouvrir les caméras", "discret", "cameras")
        b_mur.clicked.connect(lambda: fen.aller("cameras"))
        for b in (b_mur, self.b_pause, self.b_tout, self.b_reprendre):
            v.addWidget(b)
        v.addStretch(1)
        g.addWidget(f, 1, 2, 1, 2)
        # serveur
        f, v = carte("Serveur")
        self.lbl_serveur = etiquette("", "aide")
        v.addWidget(self.lbl_serveur)
        v.addStretch(1)
        g.addWidget(f, 2, 0, 1, 2)
        # dernières alertes
        f, v = carte("Dernières alertes")
        self.liste = QTableWidget(0, 3)
        self.liste.setHorizontalHeaderLabels(["Heure", "Caméra", "Alerte"])
        self.liste.verticalHeader().setVisible(False)
        self.liste.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.liste.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.liste.setShowGrid(False)
        self.liste.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.liste.setMinimumHeight(220)
        self.liste.cellDoubleClicked.connect(lambda *_: fen.aller("journal"))
        v.addWidget(self.liste)
        g.addWidget(f, 2, 2, 1, 2)
        for c in range(4):
            g.setColumnStretch(c, 1)
        g.setRowStretch(3, 1)
        racine.addWidget(defilant(contenu), 1)

    def _tout_couper(self):
        if QMessageBox.question(self, "Mode discret", "Couper la détection de toutes les caméras et toutes les "
                                "notifications du PC Flux ?") != QMessageBox.StandardButton.Yes:
            return
        self.fen.piloter("detection.actif", False)
        self.fen.piloter("notif.actif", False)
        if any(c["cle"] == "mail.actif" and c["actif"] for c in (self.fen.etat_pilotage or {}).get("canaux", [])):
            self.fen.piloter("mail.actif", False)

    def _tout_reprendre(self):
        self.fen.piloter("detection.actif", True)
        self.fen.piloter("notif.actif", True)

    def rafraichir(self):
        fen = self.fen
        cams = fen.cameras
        self.tete.sous.setText(f"{fen.reg['nom_serveur'] or 'Flux'} · {fen.profil.get('prenom', '')} "
                               f"{fen.profil.get('nom', '')}".strip())
        self.chiffres["direct"].setText(f"{sum(1 for c in cams if c['etat'] in ('direct', 'alerte'))} / {len(cams)}")
        self.chiffres["presences"].setText(str(sum(c.get("personnes", 0) for c in cams)))
        aujourd = [e for e in fen.dernieres_alertes if datetime.fromtimestamp(e["heure"]).date() == datetime.now().date()]
        self.chiffres["alertes"].setText(str(len(aujourd)) if fen.journal_charge else "—")
        e = fen.etat_pilotage
        self.chiffres["connus"].setText(str(e["statistiques"]["personnes"]) if e and e.get("statistiques") else "—")
        det = fen.detection_globale
        self.voyant_det.regler("direct" if det else "chargement")
        self.lbl_det.setText("Active sur le PC Flux" if det else "En pause : images visibles, aucune alerte")
        self.inter_det.regler(det)
        self.inter_det.setEnabled(fen.pilotage_autorise)
        if e and e.get("niveau"):
            n = next((x for x in e.get("niveaux", []) if x["cle"] == e["niveau"]), None)
            self.lbl_niveau.setText(f"Niveau de scan : {n['nom'] if n else e['niveau']}"
                                    + (f" · calcul : {e['calcul']}" if e.get("calcul") else ""))
        self.lbl_pilotage.setText("" if fen.pilotage_autorise else
                                  "Votre compte peut voir mais pas piloter. Le responsable du PC Flux peut vous accorder "
                                  "le droit « pilotage à distance ».")
        for b in (self.b_tout, self.b_reprendre):
            b.setVisible(fen.pilotage_autorise)
        i = fen.info or {}
        self.lbl_serveur.setText(
            f"Nom : {i.get('nom') or fen.reg['nom_serveur']}\nChemin : {fen.texte_route()}\n"
            f"Version de Flux : {i.get('version_flux') or '—'}\n"
            f"Clé : {module_api.formater_cle(fen.reg['cle'])}\n"
            f"Connexion : {'chiffrée, clé vérifiée' if fen.en_ligne else 'perdue, nouvelle tentative…'}")
        self.liste.setRowCount(0)
        for ev in fen.dernieres_alertes[:12]:
            r = self.liste.rowCount()
            self.liste.insertRow(r)
            for j, val in enumerate((heure(ev["heure"]), ev["camera"], ev["texte"])):
                it = QTableWidgetItem(val)
                if ev.get("prioritaire"):
                    it.setForeground(couleur("liste_noire"))
                self.liste.setItem(r, j, it)
        self.liste.resizeColumnToContents(0)
        self.liste.resizeColumnToContents(1)


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
        self.lbl = QLabel(cam["nom"])
        self.lbl.setStyleSheet("font-weight: 600;")
        h.addWidget(self.lbl, 1)
        self.b_cloche = Bouton("", "fantome", "cloche")
        self.b_cloche.clicked.connect(lambda: self.fen.basculer_muette(self.cam["id"]))
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
        self.vue.etat, self.vue.personnes = cam["etat"], cam.get("personnes", 0)
        self.vue.detection = cam.get("detection", True) and self.fen.detection_globale
        self.vue.badges = [cam["resolution"]] if cam.get("resolution") and self.page.colonnes_effectives() <= 2 else []
        self.voyant.regler(cam["etat"])
        muette = cam["id"] in self.fen.reg["alertes.muettes"]
        self.b_cloche.definir_icone("cloche_barree" if muette else "cloche")
        self.b_cloche.setToolTip("Alertes de cette caméra coupées sur ce PC" if muette else
                                 "Couper les alertes de cette caméra sur ce PC")
        self.vue.update()

    def _menu(self):
        m = QMenu(self)
        m.addAction("Ouvrir en grand", lambda: self.fen.ouvrir_video(self.cam))
        if self.fen.pilotage_autorise:
            m.addSeparator()
            en_marche = self.cam["etat"] != "arret"
            m.addAction("Arrêter la caméra sur le PC" if en_marche else "Démarrer la caméra sur le PC",
                        lambda: self.fen.piloter("camera.marche", not en_marche, self.cam["id"]))
            m.addAction("Couper la détection" if self.cam.get("detection", True) else "Activer la détection",
                        lambda: self.fen.piloter("camera.detection", not self.cam.get("detection", True), self.cam["id"]))
            a = m.addAction("Enregistrer une vidéo sur le PC", lambda: self.fen.piloter("camera.clip", True, self.cam["id"]))
            a.setEnabled(en_marche)
        m.addSeparator()
        m.addAction("Voir son journal", lambda: self.fen.journal_camera(self.cam))
        m.addAction("Masquer de la grille", lambda: self.page.masquer(self.cam["id"], True))
        m.exec(self.b_menu.mapToGlobal(self.b_menu.rect().bottomLeft()))


class PageCameras(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self.tuiles = {}
        self.vignettes = None
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        haut = QHBoxLayout()
        haut.addWidget(titre_page("Caméras"), 1)
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
        return [c for c in self.fen.cameras if c["id"] not in masquees]

    def _colonnes(self):
        self.fen.reg.set("cameras.colonnes", self.combo_col.currentData())
        self.reconstruire()

    def masquer(self, cam_id, masquee):
        s = set(self.fen.reg["cameras.masquees"])
        s.add(cam_id) if masquee else s.discard(cam_id)
        self.fen.reg.set("cameras.masquees", sorted(s))
        self.reconstruire()

    def _menu_masquees(self):
        masquees = [c for c in self.fen.cameras if c["id"] in set(self.fen.reg["cameras.masquees"])]
        m = QMenu(self)
        if not masquees:
            a = m.addAction("Aucune caméra masquée")
            a.setEnabled(False)
        for c in masquees:
            m.addAction(f"Afficher « {c['nom']} »", lambda i=c["id"]: self.masquer(i, False))
        m.exec(self.b_masquees.mapToGlobal(self.b_masquees.rect().bottomLeft()))

    def reconstruire(self):
        for t in self.tuiles.values():
            t.setParent(None)
            t.deleteLater()
        self.tuiles = {}
        cams = self.visibles()
        n = self.colonnes_effectives()
        for i, c in enumerate(cams):
            t = Tuile(self, c)
            self.tuiles[c["id"]] = t
            self.grille.addWidget(t, i // n, i % n)
        for c in range(5):
            self.grille.setColumnStretch(c, 1 if c < n else 0)
        if self.vignettes is not None:
            self.vignettes.ids = [c["id"] for c in cams if c["etat"] != "arret"]
            self.vignettes.largeur = 960 if n <= 1 else 720 if n == 2 else 520
        self._message()

    def _message(self):
        if self.fen.sans_entreprise:
            self.message.setText("Votre compte n'est rattaché à aucune entreprise : le responsable du PC Flux doit vous "
                                 "attribuer des caméras.")
        elif not self.fen.cameras:
            self.message.setText("Aucune caméra disponible pour votre entreprise.")
        else:
            m = len(self.fen.cameras) - len(self.visibles())
            self.message.setText(("Double-clic sur une caméra pour l'ouvrir en grand. "
                                  + (f"{m} caméra(s) masquée(s)." if m else "")).strip())

    def rafraichir(self):
        ids = [c["id"] for c in self.visibles()]
        if ids != list(self.tuiles):
            self.reconstruire()
        for c in self.visibles():
            self.tuiles[c["id"]].maj(c)
        if self.vignettes is not None:
            self.vignettes.ids = [c["id"] for c in self.visibles() if c["etat"] != "arret"] if self.isVisible() else []
        self._message()

    def demarrer(self, api):
        self.arreter()
        self.vignettes = Vignettes(api)
        self.vignettes.image.connect(self._image)

    def arreter(self):
        if self.vignettes is not None:
            self.vignettes.arreter()
            self.vignettes = None

    def _image(self, cam_id, img):
        t = self.tuiles.get(cam_id)
        if t is not None:
            t.vue.definir(img)

    def showEvent(self, e):
        super().showEvent(e)
        self.rafraichir()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self.vignettes is not None:
            self.vignettes.ids = []


class PageControle(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self.lignes_cam, self.lignes_canal = {}, {}
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.addWidget(titre_page("Contrôle", "Les commandes s'appliquent au PC Flux et sont notées dans son journal "
                                                "avec votre nom."))
        self.pile = QStackedWidget()
        # sans droit
        sans = QWidget()
        sv = QVBoxLayout(sans)
        f, v = carte("Pilotage non autorisé", "Votre compte peut voir les caméras et les alertes, mais pas piloter Flux. "
                                             "Le responsable du PC Flux peut vous accorder ce droit : page FluxLite, clic "
                                             "droit sur votre compte › Autoriser le pilotage à distance. Le PC Flux doit "
                                             "être en version 0.9 ou plus récente.")
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
        self.inter_det.toggled.connect(lambda e: fen.piloter("detection.actif", bool(e)))
        v.addWidget(ligne_option("Toutes les caméras du PC", self.inter_det,
                                 "Coupée : les images restent visibles, sans analyse ni alerte."))
        v.addWidget(separateur())
        self.combo_niveau = QComboBox()
        self.combo_niveau.activated.connect(lambda _i: fen.piloter("detection.niveau", self.combo_niveau.currentData()))
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

    def _delai(self, cle, w):
        e = self.fen.etat_pilotage or {}
        if abs((e.get("delais") or {}).get(cle, -1) - w.value()) > 1e-6:
            self.fen.piloter(cle, w.value())

    def rafraichir(self):
        fen = self.fen
        e = fen.etat_pilotage
        self.pile.setCurrentIndex(1 if fen.pilotage_autorise and e else 0)
        if not e:
            return
        self.inter_det.regler(e["detection"])
        if self.combo_niveau.count() != len(e.get("niveaux", [])):
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
                s.setValue(float((e.get("delais") or {}).get(cle, 0)))
                s.blockSignals(False)
        # caméras
        ids = [c["id"] for c in e["cameras"]]
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
                im.toggled.connect(lambda v, i=c["id"]: fen.piloter("camera.marche", bool(v), i))
                h.addWidget(im)
                h.addSpacing(12)
                h.addWidget(etiquette("Détection", "aide", False))
                idt = Interrupteur()
                idt.toggled.connect(lambda v, i=c["id"]: fen.piloter("camera.detection", bool(v), i))
                h.addWidget(idt)
                h.addSpacing(12)
                bc = Bouton("Vidéo sur le PC", "discret", "video")
                bc.clicked.connect(lambda _=False, i=c["id"]: fen.piloter("camera.clip", True, i))
                h.addWidget(bc)
                self.v_cams.addWidget(w)
                self.lignes_cam[c["id"]] = {"widget": w, "marche": im, "detection": idt, "clip": bc}
        for c in e["cameras"]:
            ligne = self.lignes_cam[c["id"]]
            ligne["marche"].regler(c.get("en_marche", False))
            ligne["detection"].regler(c.get("detection", True))
            ligne["clip"].setEnabled(c.get("en_marche", False))
        # canaux
        cles = [c["cle"] for c in e["canaux"]]
        if cles != list(self.lignes_canal):
            for w in self.lignes_canal.values():
                w["widget"].setParent(None)
            self.lignes_canal = {}
            for c in e["canaux"]:
                inter = Interrupteur()
                inter.toggled.connect(lambda v, k=c["cle"]: fen.piloter(k, bool(v)))
                w = ligne_option(c["nom"], inter, " ")
                self.v_canaux.addWidget(w)
                self.lignes_canal[c["cle"]] = {"widget": w, "inter": inter, "aide": w.findChildren(QLabel)[-1]}
        general = next((c for c in e["canaux"] if c["cle"] == "notif.actif"), None)
        for c in e["canaux"]:
            ligne = self.lignes_canal[c["cle"]]
            ligne["inter"].regler(c["actif"])
            ligne["inter"].setEnabled(c["configure"] or c["actif"])
            dependant = c["cle"] not in ("notif.actif", "mail.actif") and general is not None and not general["actif"]
            ligne["aide"].setText("Pas configuré sur le PC Flux" if not c["configure"] else
                                  "Activé, mais les notifications sont coupées" if dependant and c["actif"] else
                                  "Activé" if c["actif"] else "Désactivé")


class PageJournal(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self.evenements, self.fin = [], False
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.addWidget(titre_page("Journal", "Les alertes de vos caméras, les plus récentes en haut."))
        filtres = QHBoxLayout()
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
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Caméra", "Alerte", "Photo"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
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

    def maj_cameras(self):
        actuel = self.combo_cam.currentData()
        noms = [(c["id"], c["nom"]) for c in self.fen.cameras]
        if [self.combo_cam.itemData(i) for i in range(1, self.combo_cam.count())] == [i for i, _ in noms]:
            return
        self.combo_cam.blockSignals(True)
        self.combo_cam.clear()
        self.combo_cam.addItem("Toutes les caméras", None)
        for i, n in noms:
            self.combo_cam.addItem(n, i)
        self.combo_cam.setCurrentIndex(max(0, self.combo_cam.findData(actuel)))
        self.combo_cam.blockSignals(False)

    def charger(self, suite=False):
        if self.fen.api is None:
            return
        avant = self.evenements[-1]["id"] if suite and self.evenements else None
        cam = self.combo_cam.currentData()

        def fini(r):
            lignes = r.get("journal", [])
            self.evenements = (self.evenements if suite else []) + lignes
            self.fin = len(lignes) < 60
            if not suite and cam is None:
                self.fen.dernieres_alertes = [e for e in self.evenements if e["niveau"] == "alerte"][:50]
                self.fen.journal_charge = True
            self._remplir()
        self.fen.appeler(lambda: self.fen.api.journal(avant, cam), fini)

    def _remplir(self):
        filtre = self.recherche.text().strip().lower()
        lignes = [e for e in self.evenements if not filtre or filtre in (e["texte"] + " " + e["camera"]).lower()]
        self.table.setRowCount(len(lignes))
        for i, e in enumerate(lignes):
            for j, val in enumerate((heure(e["heure"], True), e["camera"], e["texte"], "oui" if e.get("photo") else "")):
                it = QTableWidgetItem(val)
                it.setData(Qt.ItemDataRole.UserRole, e)
                if e.get("prioritaire"):
                    it.setForeground(couleur("liste_noire"))
                self.table.setItem(i, j, it)
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)
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
        self.lbl_detail.setText(f"{e['texte']}\n{e['camera']} · {heure(e['heure'], True)}")
        if not e.get("photo"):
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
        self.fen.appeler(lambda: self.fen.api.photo(e["id"]), fini)

    def _enregistrer_photo(self):
        e = self._courant()
        if e and self._pix is not None:
            self.fen.enregistrer_capture(f"alerte {e['camera']}", self._pix.toImage(), e["heure"])

    def _ouvrir_camera(self):
        e = self._courant()
        cam = next((c for c in self.fen.cameras if c["id"] == (e or {}).get("camera_id")), None)
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
            w.writerow(["Date", "Caméra", "Alerte", "Niveau", "Liste noire"])
            for e in self.evenements:
                w.writerow([heure(e["heure"], True), e["camera"], e["texte"], e["niveau"],
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
        racine.addWidget(titre_page("Compte"))
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
        f, v = carte("Mot de passe", "Vos autres appareils seront déconnectés.")
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
        f, v = carte("Appareils connectés")
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
        b.clicked.connect(lambda: self.fen.appeler(lambda: self.fen.api.revoquer(None), self._profil_recu,
                                                   "Vos autres appareils sont déconnectés."))
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g.addWidget(f, 1, 0, 1, 2)
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
        g.addWidget(f, 2, 0, 1, 2)
        b = Bouton("Se déconnecter", "danger", "sortie")
        b.clicked.connect(self._deconnexion)
        g.addWidget(b, 3, 0, Qt.AlignmentFlag.AlignLeft)
        g.setRowStretch(4, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        racine.addWidget(defilant(contenu), 1)

    def showEvent(self, e):
        super().showEvent(e)
        self.fen.appeler(self.fen.api.profil, self._profil_recu)

    def _profil_recu(self, p):
        self.fen.profil = p
        self.fen.pilotage_autorise = bool(p.get("pilotage"))
        self.lbl_ident.setText(f"{p['prenom']} {p['nom']}")
        self.lbl_infos.setText(f"{p['mail']}\nEntreprise : {p.get('entreprise') or 'aucune'}"
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
        p, n = self.c_prenom.text().strip(), self.c_nom.text().strip()
        if not p or not n:
            return self.fen.toast("Le prénom et le nom ne peuvent pas être vides.", "erreur")
        self.fen.appeler(lambda: self.fen.api.modifier_profil(prenom=p, nom=n), self._profil_recu, "Profil enregistré.")

    def _changer_mdp(self):
        a, n, c = self.c_ancien.text(), self.c_nouveau.text(), self.c_confirm.text()
        if not mdp_accepte(n):
            return self.fen.toast("Nouveau mot de passe trop faible : 10 caractères, lettres et chiffres.", "erreur")
        if n != c:
            return self.fen.toast("Les deux mots de passe diffèrent.", "erreur")

        def fini(r):
            for w in (self.c_ancien, self.c_nouveau, self.c_confirm):
                w.clear()
            self.fen.toast(r.get("message") or "Mot de passe changé.", "ok")
        self.fen.appeler(lambda: self.fen.api.changer_mdp(a, n), fini)

    def _revoquer(self):
        it = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        s = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not s:
            return self.fen.toast("Choisissez un appareil dans la liste.")
        if s.get("courante"):
            return self._deconnexion()
        self.fen.appeler(lambda: self.fen.api.revoquer(s["id"]), self._profil_recu, "Appareil déconnecté.")

    def _exporter(self):
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter mes données",
                                                os.path.join(os.path.expanduser("~"), "flux-mes-donnees.json"),
                                                "JSON (*.json)")
        if chemin:
            def fini(octets):
                with open(chemin, "wb") as f:
                    f.write(octets)
                self.fen.toast("Vos données ont été exportées.", "ok")
            self.fen.appeler(self.fen.api.exporter, fini)

    def _cgu(self):
        d = QDialog(self)
        d.setWindowTitle("Conditions d'utilisation")
        d.resize(700, 600)
        v = QVBoxLayout(d)
        from PySide6.QtWidgets import QTextBrowser
        t = QTextBrowser()
        t.setHtml(html_cgu(self.fen.info))
        v.addWidget(t)
        b = Bouton("Fermer", "discret")
        b.clicked.connect(d.accept)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
        d.exec()

    def _supprimer(self):
        mdp, ok = QInputDialog.getText(self, "Supprimer mon compte",
                                       "Votre compte et vos informations seront effacés du PC Flux. C'est définitif.\n\n"
                                       "Mot de passe pour confirmer :", QLineEdit.EchoMode.Password)
        if ok and mdp:
            def fini(r):
                self.fen.toast(r.get("message") or "Compte supprimé.", "ok")
                self.fen.fin_session()
            self.fen.appeler(lambda: self.fen.api.supprimer_compte(mdp), fini)

    def _deconnexion(self):
        if QMessageBox.question(self, "Se déconnecter", "Se déconnecter de ce PC Flux ? Vous ne recevrez plus d'alertes "
                                "sur cet ordinateur.") == QMessageBox.StandardButton.Yes:
            api = self.fen.api
            Tache(api.deconnecter).lancer()
            self.fen.fin_session()


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
        b = Bouton("Tester une alerte", "discret", "cloche")
        b.clicked.connect(fen.alerte_test)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(f, 0, 0)

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
        g.addWidget(f, 0, 1)

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
        g.addWidget(f, 1, 0)

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
        g.addWidget(f, 1, 1)

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
        g.addWidget(f, 2, 0)

        f, v = carte("Serveur Flux")
        self.lbl_serveur = etiquette("")
        v.addWidget(self.lbl_serveur)
        h = QHBoxLayout()
        b = Bouton("Relais Internet…", "discret", "lien")
        b.setToolTip("Adresse du relais Flux utilisé hors du réseau du PC Flux. Vide = celui publié sur le site.")
        b.clicked.connect(self._choisir_relais)
        h.addWidget(b)
        b = Bouton("Changer de serveur", "danger", "reseau")
        b.clicked.connect(self._changer_serveur)
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        g.addWidget(f, 2, 1)

        f, v = carte("À propos")
        v.addWidget(etiquette(f"Flux Remote {VERSION} · la télécommande de Flux pour Windows et Linux.\n"
                              "Construit avec Python, Qt pour Python (PySide6, licence LGPL v3) et cryptography (Apache 2.0). "
                              "Détail des licences dans le fichier LICENCES-TIERCES.md à côté du programme."))
        g.addWidget(f, 3, 0, 1, 2)
        g.setRowStretch(4, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        racine.addWidget(defilant(contenu), 1)

    def showEvent(self, e):
        if e is not None:
            super().showEvent(e)
        reg = self.fen.reg
        self.lbl_dossier.setText(systeme.dossier_captures(reg["systeme.dossier_captures"]))
        relais = reg["relais"] or module_api.texte_relais(module_api.relais_site())
        self.lbl_serveur.setText(f"{reg['nom_serveur'] or 'Flux'}\nRéseau local : "
                                 f"{(reg['hote'] + ':' + str(reg['port'])) if reg['hote'] else '—'}\n"
                                 f"Par Internet : {('relais ' + relais) if relais else 'aucun relais connu'}"
                                 f"{' (propre à ce PC Flux)' if reg['relais'] else ''}\nClé : "
                                 f"{module_api.formater_cle(reg['cle'])}")
        self.maj_pause()

    def _choisir_relais(self):
        reg = self.fen.reg
        texte, ok = QInputDialog.getText(
            self, "Relais Internet", "Adresse du relais (ex. relais.monentreprise.be ou 203.0.113.5:8443).\n"
            "Laissez vide pour utiliser le relais publié sur le site de Flux.", text=reg["relais"])
        if not ok:
            return
        texte = texte.strip()
        if texte and not module_api.lire_adresse_relais(texte):
            self.fen.toast("Adresse de relais invalide.", "erreur")
            return
        reg.set("relais", module_api.texte_relais(module_api.lire_adresse_relais(texte)) if texte else "")
        if self.fen.api is not None:
            self.fen.api.relais = module_api.lire_adresse_relais(reg["relais"]) if reg["relais"] else None
        self.fen.toast("Relais enregistré." if texte else "Relais du site utilisé.", "ok")
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

    def _changer_serveur(self):
        if QMessageBox.question(self, "Changer de serveur", "Flux Remote oubliera ce PC Flux, sa clé et votre session. "
                                "Continuer ?") == QMessageBox.StandardButton.Yes:
            api = self.fen.api
            if api is not None:
                Tache(api.deconnecter).lancer()
            self.fen.fin_session(oublier=True)


# ---------------------------------------------------------------------------------------------------
# Fenêtre principale
# ---------------------------------------------------------------------------------------------------
class Fenetre(QMainWindow):
    def __init__(self, reg, reduit=False):
        super().__init__()
        self.reg = reg
        self.api, self.ecoute = None, None
        self.info, self.profil, self.etat_pilotage = None, {}, None
        self.cameras, self.dernieres_alertes = [], []
        self.journal_charge, self.sans_entreprise, self.detection_globale = False, False, True
        self.pilotage_autorise, self.en_ligne = False, True
        self.videos, self.derniers_envois, self.retenues = {}, {}, {}
        self._derniere_alerte_cam = None
        self._non_vues = 0
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
        if reg["jeton"] and reg["cle"]:
            self.debut_session()
        else:
            self.pile.setCurrentWidget(self.accueil)
            self.accueil.montrer()
        if not reduit or not QSystemTrayIcon.isSystemTrayAvailable():
            self.show()
        if reg["maj.auto"]:
            QTimer.singleShot(5000, lambda: self.verifier_maj(manuel=False))

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
        self.a_detection = m.addAction("Couper la détection sur le PC Flux",
                                       lambda: self.piloter("detection.actif", not self.detection_globale))
        m.addSeparator()
        m.addAction("Quitter", self.quitter)
        self.zone.setContextMenu(m)
        self.zone.activated.connect(lambda r: r == QSystemTrayIcon.ActivationReason.Trigger and self.montrer())
        self.zone.messageClicked.connect(self._message_clique)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.zone.show()
        self.maj_zone()

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
        self.a_detection.setVisible(self.pilotage_autorise)
        self.a_detection.setText("Couper la détection sur le PC Flux" if self.detection_globale
                                 else "Réactiver la détection sur le PC Flux")
        self.zone.setToolTip(f"Flux Remote · {self.reg['nom_serveur'] or 'non connecté'}")
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

    # --- session ------------------------------------------------------------------------------------
    def debut_session(self):
        reg = self.reg
        self.api = module_api.Api(reg["hote"], reg["port"], reg["cle"], reg["jeton"], relais=reg["relais"])
        self.pile.setCurrentWidget(self.principal)
        self.statusBar().show()
        self.lbl_serveur.setText(reg["nom_serveur"] or "Flux")
        self.p_cameras.demarrer(self.api)
        self.ecoute = Ecoute(self.api)
        self.ecoute.evenements.connect(self._alertes)
        self.ecoute.session_perdue.connect(self._session_perdue)
        self.ecoute.connecte.connect(self._connexion_etat)
        self.appeler(self.api.info, self._info_recue)
        self.appeler(self.api.profil, self._profil_recu)
        self.aller("tableau")
        self._timer.start()
        self.actualiser()
        self.p_journal.charger()

    def fin_session(self, oublier=False):
        self._timer.stop()
        if self.ecoute is not None:
            self.ecoute.arreter()
            self.ecoute = None
        self.p_cameras.arreter()
        for v in list(self.videos.values()):
            v.close()
        self.api = None
        self.reg.set("jeton", "")
        if oublier:
            self.reg.oublier_serveur()
            self.reg.set("cgu", "")
        self.cameras, self.dernieres_alertes, self.etat_pilotage = [], [], None
        self.statusBar().hide()
        self.pile.setCurrentWidget(self.accueil)
        self.accueil.montrer()

    def _session_perdue(self, msg):
        self.toast(msg or "Session expirée : reconnectez-vous.", "erreur")
        self.fin_session()

    def _info_recue(self, info):
        self.info = info
        self.accueil.info = info
        if info.get("nom"):
            self.reg.set("nom_serveur", info["nom"])
            self.lbl_serveur.setText(info["nom"])

    def _profil_recu(self, p):
        self.profil = p
        self.pilotage_autorise = bool(p.get("pilotage"))
        self.maj_zone()
        self.nav["controle"].setVisible(True)

    def _connexion_etat(self, ok):
        if ok != self.en_ligne:
            self.en_ligne = ok
            if not ok:
                self.toast("Connexion au PC Flux perdue, nouvelle tentative…", "erreur")
        self._maj_barre()

    def texte_route(self):
        route = self.api.route if self.api is not None else ""
        if route == "internet":
            return "par Internet (relais Flux)"
        if route == "direct":
            return f"réseau local {self.reg['hote']}:{self.reg['port']}"
        return f"{self.reg['hote'] or 'par Internet'}" + (f":{self.reg['port']}" if self.reg["hote"] else "")

    def _maj_barre(self):
        teinte = C["succes"] if self.en_ligne else C["danger"]
        self.st_connexion.setText(f"● {'Connecté à' if self.en_ligne else 'Connexion perdue avec'} "
                                  f"{self.reg['nom_serveur'] or 'Flux'} · {self.texte_route()} · chiffré, clé vérifiée")
        self.st_connexion.setStyleSheet(f"color: {teinte}; padding: 0 6px;")
        pause = self.reg["alertes.pause_jusqua"] > time.time()
        self.st_alertes.setText("Alertes en pause" if pause else f"Alertes {dict(MODES_ALERTES)[self.reg['alertes.mode']].lower()}")

    # --- données ----------------------------------------------------------------------------------------
    def appeler(self, f, rappel=None, message_ok=None):
        """Appel au serveur hors de l'interface ; les erreurs s'affichent en bas à droite."""
        def ok(r):
            if rappel:
                rappel(r)
            if message_ok:
                self.toast(message_ok, "ok")

        def echec(msg):
            if msg.startswith(SESSION_PERDUE):
                return self._session_perdue(msg[len(SESSION_PERDUE):])
            self.toast(msg, "erreur")

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

    def actualiser(self):
        if self.api is None:
            return
        api = self.api

        def cameras_recues(r):
            if api is not self.api:
                return
            self.cameras = r.get("cameras", [])
            self.sans_entreprise = not r.get("entreprise", True)
            self.detection_globale = bool(r.get("detection", True))
            if r.get("pilotage") != self.pilotage_autorise:
                self.pilotage_autorise = bool(r.get("pilotage"))
            self.en_ligne = True
            for cam in self.cameras:
                v = self.videos.get(cam["id"])
                if v is not None:
                    v.maj_camera(cam)
            self._rafraichir_pages()
            self.logo.animer(any(c["etat"] == "alerte" for c in self.cameras))

        def echec(_msg):
            self.en_ligne = False
            self._maj_barre()
        t = Tache(api.cameras)
        t.fini.connect(cameras_recues)
        t.echec.connect(echec)
        t.lancer()
        if self.pilotage_autorise:
            def etat_recu(e):
                if api is self.api:
                    self.etat_pilotage = e
                    self.detection_globale = e.get("detection", True)
                    self._rafraichir_pages()
            t2 = Tache(api.pilotage)
            t2.fini.connect(etat_recu)
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

    def piloter(self, cle, valeur, camera=None):
        if not self.pilotage_autorise or self.api is None:
            return self.toast("Votre compte n'est pas autorisé à piloter Flux.", "erreur")

        def fini(e):
            self.etat_pilotage = e
            self.detection_globale = e.get("detection", True)
            if cle == "camera.clip":
                self.toast("Vidéo demandée : elle est enregistrée sur le PC Flux.", "ok")
            self.actualiser()
        self.appeler(lambda: self.api.piloter(cle, valeur, camera), fini)
        if cle != "camera.clip":
            self.actualiser()

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
        i = self.p_journal.combo_cam.findData(cam["id"])
        if i >= 0:
            self.p_journal.combo_cam.setCurrentIndex(i)

    def ouvrir_video(self, cam):
        v = self.videos.get(cam["id"])
        if v is None:
            if cam["etat"] == "arret":
                return self.toast(f"« {cam['nom']} » est arrêtée sur le PC Flux.")
            v = FenetreVideo(self, cam)
            self.videos[cam["id"]] = v
        v.show()
        v.raise_()
        v.activateWindow()

    def montrer(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toast(self, texte, genre="info"):
        self.toasts.montrer(texte, genre)

    # --- alertes sur ce PC ------------------------------------------------------------------------------------
    def _alertes(self, evenements):
        reg = self.reg
        nouvelles = [e for e in evenements if e.get("niveau") == "alerte" or e.get("prioritaire")]
        if not nouvelles:
            return
        self.dernieres_alertes = (list(reversed(nouvelles)) + self.dernieres_alertes)[:50]
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
            cid = e.get("camera_id")
            if cid in muettes and not e.get("prioritaire"):
                continue
            delai = reg["alertes.delai"] * 60
            if delai and not e.get("prioritaire") and maintenant - self.derniers_envois.get(cid, 0) < delai:
                self.retenues[cid] = self.retenues.get(cid, 0) + 1
                continue
            self.derniers_envois[cid] = maintenant
            n = self.retenues.pop(cid, 0)
            titre = f"{'⚠ LISTE NOIRE · ' if e.get('prioritaire') else ''}{e['camera']}"
            texte = e["texte"] + (f"  (+{n} pendant le délai)" if n else "")
            self._derniere_alerte_cam = cid
            self.zone.showMessage(titre, texte, QSystemTrayIcon.MessageIcon.Warning if e.get("prioritaire")
                                  else QSystemTrayIcon.MessageIcon.Information, 8000)
            if mode == "sonores" or e.get("prioritaire"):
                jouer_son()

    def _message_clique(self):
        self.montrer()
        cam = next((c for c in self.cameras if c["id"] == self._derniere_alerte_cam), None)
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

    def basculer_muette(self, cam_id):
        s = set(self.reg["alertes.muettes"])
        s.symmetric_difference_update({cam_id})
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
        if self.ecoute is not None:
            self.ecoute.arreter()
        self.zone.hide()
        QApplication.quit()
        if redemarrage:
            sys.exit(0)
