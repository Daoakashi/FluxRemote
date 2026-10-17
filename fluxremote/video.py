"""Images des caméras : vidéo en direct (MJPEG) pour les grandes vues, images régulières pour la grille."""
import threading
import time

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

from .api import ErreurApi, message_erreur
from .theme import T, couleur, police


class LecteurFlux(QObject):
    """Lit la vidéo d'une caméra dans un fil à part ; se reconnecte tout seul si la connexion coupe."""
    image = Signal(QImage, int)
    etat = Signal(str)

    def __init__(self, api, cam_id, fps=12, largeur=1280):
        super().__init__()
        self.api, self.cam_id, self.fps, self.largeur = api, cam_id, fps, largeur
        self._stop = threading.Event()
        self.ips = 0.0
        self._fil = threading.Thread(target=self._boucle, daemon=True, name=f"flux-video-{cam_id}")

    def demarrer(self):
        self._fil.start()
        return self

    def arreter(self):
        self._stop.set()

    def _boucle(self):
        try:
            self._boucle_video()
        except RuntimeError:
            pass  # fenêtre fermée pendant la réception d'une image : rien à afficher

    def _boucle_video(self):
        while not self._stop.is_set():
            try:
                self.etat.emit("Connexion…")
                n, t0 = 0, time.time()
                for jpeg, personnes in self.api.flux(self.cam_id, self.fps, self.largeur, self._stop.is_set):
                    img = QImage.fromData(jpeg, "JPG")
                    if not img.isNull():
                        self.image.emit(img, personnes)
                    n += 1
                    if time.time() - t0 >= 2:
                        self.ips, n, t0 = n / (time.time() - t0), 0, time.time()
                if not self._stop.is_set():
                    self.etat.emit("Vidéo interrompue, reconnexion…")
            except ErreurApi as e:
                self.etat.emit(str(e))
                if e.code in (401, 404):
                    return
            except Exception as e:  # noqa: BLE001
                self.etat.emit(message_erreur(e))
            self._stop.wait(3)


class Vignettes(QObject):
    """Une seule connexion à la fois : les images des caméras de la grille sont demandées l'une après l'autre."""
    image = Signal(str, QImage)

    def __init__(self, api, largeur=560, pause=1.2):
        super().__init__()
        self.api, self.largeur, self.pause = api, largeur, pause
        self.ids = []
        self._stop = threading.Event()
        threading.Thread(target=self._boucle, daemon=True, name="flux-vignettes").start()

    def arreter(self):
        self._stop.set()

    def _boucle(self):
        try:
            self._boucle_video()
        except RuntimeError:
            pass  # fenêtre fermée pendant la réception d'une image : rien à afficher

    def _boucle_video(self):
        while not self._stop.is_set():
            ids = list(self.ids)
            if not ids:
                self._stop.wait(0.5)
                continue
            for i in ids:
                if self._stop.is_set():
                    return
                try:
                    jpeg = self.api.image(i, self.largeur)
                    if jpeg:
                        img = QImage.fromData(jpeg, "JPG")
                        if not img.isNull():
                            self.image.emit(i, img)
                except Exception:  # noqa: BLE001
                    self._stop.wait(2)
            self._stop.wait(self.pause)


class VueImage(QWidget):
    """Affiche une image de caméra (proportions gardées) avec un bandeau d'état."""
    clic = Signal()
    double_clic = Signal()

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.img = None
        self.titre, self.etat, self.texte_vide = "", "arret", "Caméra arrêtée"
        self.personnes, self.detection, self.compact = 0, True, compact
        self.badges = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 130)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def definir(self, img):
        self.img = img
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clic.emit()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.double_clic.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rayon = T.rayon + 2
        alerte = self.etat == "alerte"
        p.setPen(couleur("o_personne") if alerte else couleur("trait"))
        p.setBrush(couleur("video"))
        p.drawRoundedRect(r, rayon, rayon)
        if self.img is not None:
            w, h = self.img.width(), self.img.height()
            k = min(r.width() / w, r.height() / h)
            cible = QRectF(0, 0, w * k, h * k)
            cible.moveCenter(r.center())
            chemin = QPainterPath()
            chemin.addRoundedRect(r.adjusted(1, 1, -1, -1), rayon - 1, rayon - 1)
            p.save()
            p.setClipPath(chemin)
            if self.etat == "arret":
                p.setOpacity(0.35)
            p.drawImage(cible, self.img)
            p.restore()
        else:
            p.setPen(couleur("texte3"))
            p.setFont(police())
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.texte_vide)
        if alerte:
            p.setPen(couleur("o_personne"))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rayon, rayon)
        # pastilles d'état en haut à gauche
        x = r.left() + 10
        pastilles = []
        if self.titre and self.compact:
            pastilles.append((self.titre, None))
        libelle = {"alerte": f"{self.personnes} personne{'s' if self.personnes > 1 else ''}", "direct": "En direct",
                   "chargement": "Connexion…", "arret": "Arrêtée"}.get(self.etat, self.etat)
        pastilles.append((libelle, {"alerte": "o_personne", "direct": "succes", "chargement": "attention"}.get(self.etat, "texte3")))
        if not self.detection:
            pastilles.append(("Détection coupée", "attention"))
        pastilles += [(b, None) for b in self.badges]
        p.setFont(police(max(10, T.taille - 2), True))
        for texte, teinte in pastilles:
            larg = p.fontMetrics().horizontalAdvance(texte) + (26 if teinte else 16)
            pr = QRectF(x, r.top() + 10, larg, 24)
            p.setPen(Qt.PenStyle.NoPen)
            fond = couleur("#050B15", 200)
            p.setBrush(fond)
            p.drawRoundedRect(pr, 12, 12)
            tx = pr.left() + 8
            if teinte:
                p.setBrush(couleur(teinte))
                p.drawEllipse(pr.left() + 8, pr.center().y() - 3.5, 7, 7)
                tx += 12
            p.setPen(couleur("#FFFFFF"))
            p.drawText(QRectF(tx, pr.top(), larg, pr.height()), Qt.AlignmentFlag.AlignVCenter, texte)
            x += larg + 6
