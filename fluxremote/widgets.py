"""Éléments d'interface (repris de Flux) : boutons, bascules, voyants, notifications, navigation."""

import math
import time

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRectF, QSize,
                            Qt, QTimer, QVariantAnimation, Property)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from .theme import C, T, couleur, dessiner_icone, dessiner_logo, melange, police


def _anim(parent, rappel, courbe=QEasingCurve.Type.OutCubic):
    a = QVariantAnimation(parent)
    a.setEasingCurve(courbe)
    a.valueChanged.connect(rappel)
    return a


def _aller(anim, depuis, vers, duree):
    anim.stop()
    anim.setDuration(T.ms(duree))
    anim.setStartValue(float(depuis))
    anim.setEndValue(float(vers))
    anim.start()


class Bouton(QPushButton):
    """Bouton à survol animé. Styles : primaire (accent), discret, danger, fantome. Icône facultative."""

    def __init__(self, texte="", style="discret", icone=None, parent=None):
        super().__init__(texte, parent)
        self._style, self._icone, self._t = style, icone, 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._a = _anim(self, self._maj)

    def definir_style(self, style):
        self._style = style
        self.update()

    def definir_icone(self, icone):
        self._icone = icone
        self.update()

    def sizeHint(self):
        h = int(36 * max(0.85, T.densite))
        larg = QFontMetrics(police(None, True)).horizontalAdvance(self.text()) + (28 if self.text() else 0)
        if self._icone:
            larg += 22 if self.text() else h
        return QSize(max(larg, h), h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _maj(self, v):
        self._t = float(v)
        self.update()

    def enterEvent(self, e):
        _aller(self._a, self._t, 1.0, 140)
        super().enterEvent(e)

    def leaveEvent(self, e):
        _aller(self._a, self._t, 0.0, 160)
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        t = 0.0 if not self.isEnabled() else (1.0 if self.isDown() else self._t)
        if self._style == "primaire":
            fond = melange("accent", "accent_vif", t)
            bord, texte = fond, QColor(C["accent_texte"])
        elif self._style == "danger":
            fond = melange(couleur("danger", 0), couleur("danger", 40), t)
            bord, texte = couleur("danger", 140 + 80 * t), QColor(C["danger"])
        elif self._style == "fantome":
            fond = melange(couleur("surface2", 0), couleur("surface2", 255), t)
            bord, texte = couleur("trait", 0), QColor(C["texte"])
        else:
            fond = melange("surface", "surface2", t)
            bord, texte = melange("trait", "texte3", t * 0.6), QColor(C["texte"])
        if not self.isEnabled():
            p.setOpacity(0.45)
        p.setPen(QPen(bord, 1))
        p.setBrush(fond)
        p.drawRoundedRect(r, T.rayon, T.rayon)
        if self.hasFocus():
            p.setPen(QPen(couleur("accent", 150), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), max(2, T.rayon - 2), max(2, T.rayon - 2))
        zone = QRectF(r)
        if self._icone:
            fm = QFontMetrics(police(None, True))
            largeur_texte = fm.horizontalAdvance(self.text()) if self.text() else 0
            total = 18 + (8 + largeur_texte if self.text() else 0)
            x0 = r.center().x() - total / 2
            dessiner_icone(p, self._icone, QRectF(x0, r.center().y() - 9, 18, 18), texte)
            zone = QRectF(x0 + 26, r.top(), largeur_texte + 2, r.height())
        if self.text():
            p.setPen(texte)
            p.setFont(police(None, True))
            p.drawText(zone, Qt.AlignmentFlag.AlignCenter if not self._icone else
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class Pastille(QAbstractButton):
    """Bascule en forme de pastille (Visages, Expressions, Plaques)."""

    def __init__(self, texte, teinte, parent=None):
        super().__init__(parent)
        self.setText(texte)
        self._teinte = teinte
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h, self._c = 0.0, 0.0
        self._ah = _anim(self, lambda v: self._set("_h", v))
        self._ac = _anim(self, lambda v: self._set("_c", v))
        self.toggled.connect(lambda e: _aller(self._ac, self._c, 1.0 if e else 0.0, 200))

    def _set(self, nom, v):
        setattr(self, nom, float(v))
        self.update()

    def regler(self, etat):
        self.blockSignals(True)
        self.setChecked(etat)
        self.blockSignals(False)
        self._c = 1.0 if etat else 0.0
        self.update()

    def enterEvent(self, e):
        _aller(self._ah, self._h, 1.0, 140)
        super().enterEvent(e)

    def leaveEvent(self, e):
        _aller(self._ah, self._h, 0.0, 140)
        super().leaveEvent(e)

    def sizeHint(self):
        return QSize(QFontMetrics(police(None, True)).horizontalAdvance(self.text()) + 44, int(32 * max(0.85, T.densite)))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        teinte = C[self._teinte] if self._teinte in C else self._teinte
        fond = melange(couleur("surface", 255), melange("surface", teinte, 0.22), self._c)
        fond = melange(fond, couleur("surface2"), self._h * (1 - self._c) * 0.9)
        p.setPen(QPen(melange("trait", teinte, self._c), 1))
        p.setBrush(fond)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(teinte) if getattr(self, "point_colore", False) else melange("texte3", teinte, self._c))
        p.drawEllipse(QPointF(r.left() + 15, r.center().y()), 3.5 + self._c, 3.5 + self._c)
        p.setPen(melange("texte2", "texte", self._c))
        p.setFont(police(None, True))
        p.drawText(r.adjusted(25, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class Interrupteur(QAbstractButton):
    """Bascule à bouton glissant."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._pos = 0.0
        self._a = QPropertyAnimation(self, b"position", self)
        self._a.setEasingCurve(QEasingCurve.Type.OutBack)
        self.toggled.connect(self._basculer)

    def _get(self):
        return self._pos

    def _setp(self, v):
        self._pos = v
        self.update()

    position = Property(float, _get, _setp)

    def _basculer(self, etat):
        self._a.stop()
        self._a.setDuration(T.ms(220))
        self._a.setStartValue(self._pos)
        self._a.setEndValue(1.0 if etat else 0.0)
        self._a.start()

    def regler(self, etat):
        self.blockSignals(True)
        self.setChecked(etat)
        self.blockSignals(False)
        self._a.stop()
        self._pos = 1.0 if etat else 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = max(0.0, min(1.0, self._pos))
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(melange("trait", "accent", t))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + self._pos * (r.width() - 6 - d)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        if not self.isEnabled():
            p.fillRect(self.rect(), couleur("fond", 120))


class BoutonX(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._t = 0.0
        self._a = _anim(self, lambda v: (setattr(self, "_t", float(v)), self.update()))

    def enterEvent(self, e):
        _aller(self._a, self._t, 1.0, 120)

    def leaveEvent(self, e):
        _aller(self._a, self._t, 0.0, 120)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(couleur("danger", 60 * self._t))
        p.drawEllipse(c, 9, 9)
        p.setPen(QPen(melange("texte3", "danger", self._t), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(c.x() - 3.2, c.y() - 3.2), QPointF(c.x() + 3.2, c.y() + 3.2))
        p.drawLine(QPointF(c.x() - 3.2, c.y() + 3.2), QPointF(c.x() + 3.2, c.y() - 3.2))


class Voyant(QWidget):
    """Témoin d'état : arrêt, direct, chargement, alerte (pulsation)."""

    TEINTES = {"arret": "texte3", "direct": "succes", "alerte": "danger", "chargement": "attention"}

    def __init__(self, diametre=12, parent=None):
        super().__init__(parent)
        self._d = diametre
        self._etat = "arret"
        self.setFixedSize(diametre + 10, diametre + 10)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.update)

    def etat(self):
        return self._etat

    def regler(self, etat):
        if etat == self._etat:
            return
        self._etat = etat
        (self._timer.start if etat in ("alerte", "chargement") and T.animations else self._timer.stop)()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        base = C[self.TEINTES[self._etat]]
        pulse = (0.5 + 0.5 * math.sin(time.time() * (7.0 if self._etat == "alerte" else 4.0))
                 if T.animations and self._etat in ("alerte", "chargement") else 0.6)
        p.setPen(Qt.PenStyle.NoPen)
        if self._etat != "arret":
            p.setBrush(couleur(base, 40 + 70 * pulse))
            r = self._d / 2 + 2 + 2.5 * pulse
            p.drawEllipse(c, r, r)
        p.setBrush(couleur(base))
        p.drawEllipse(c, self._d / 2 - 1, self._d / 2 - 1)


class Repliable(QWidget):
    """Conteneur qui se déplie en douceur."""

    def __init__(self, contenu, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(contenu)
        self._contenu = contenu
        self._ouvert = False
        self.setMaximumHeight(0)
        self._a = QPropertyAnimation(self, b"maximumHeight", self)
        self._a.setEasingCurve(QEasingCurve.Type.OutCubic)

    def ouvrir(self, ouvert, instantane=False):
        if ouvert == self._ouvert:
            return
        self._ouvert = ouvert
        self._a.stop()
        cible = self._contenu.sizeHint().height() + 4 if ouvert else 0
        if instantane or not T.animations:
            self.setMaximumHeight(cible)
            return
        self._a.setDuration(T.ms(240))
        self._a.setStartValue(self.maximumHeight())
        self._a.setEndValue(cible)
        self._a.start()


def separateur():
    f = QFrame()
    f.setObjectName("sep")
    f.setFixedHeight(1)
    return f


def etiquette(texte, nom="aide", mots=True):
    lab = QLabel(texte)
    lab.setObjectName(nom)
    lab.setWordWrap(mots)
    return lab


def ligne_option(texte, controle, aide=None):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(texte)
    lab.setWordWrap(True)
    h.addWidget(lab, 1)
    h.addWidget(controle)
    v.addLayout(h)
    if aide:
        v.addWidget(etiquette(aide))
    return w


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
class Toast(QFrame):
    TEINTES = {"info": "accent", "ok": "succes", "erreur": "danger", "alerte": "danger"}

    def __init__(self, parent, texte, genre):
        super().__init__(parent)
        self.setObjectName("toast")
        self.genre = genre
        self.restyler()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lab = QLabel(texte)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.setFixedWidth(380)
        self.adjustSize()
        self.eff = QGraphicsOpacityEffect(self)
        self.eff.setOpacity(0.0)
        self.setGraphicsEffect(self.eff)
        self.anims = []

    def restyler(self):
        self.setStyleSheet(f"#toast {{ background: {C['surface']}; border: 1px solid {C['trait']}; "
                           f"border-left: 4px solid {C[self.TEINTES.get(self.genre, 'accent')]}; "
                           f"border-radius: {T.rayon}px; }} #toast QLabel {{ color: {C['texte']}; }}")


class Toasts:
    """Empile les notifications en bas à droite d'un widget hôte."""

    def __init__(self, hote):
        self.hote = hote
        self.liste = []

    def montrer(self, texte, genre="info", duree=4200):
        if len(self.liste) >= 5:
            self.retirer(self.liste[0])
        t = Toast(self.hote, texte, genre)
        self.liste.append(t)
        t.show()
        t.raise_()
        self._placer(nouveau=t)
        QTimer.singleShot(duree, lambda: self.retirer(t))

    def _cible(self, rang, hauteurs):
        y = self.hote.height() - 24 - sum(hauteurs[:rang + 1]) - rang * 10
        return QPoint(self.hote.width() - 380 - 24, y)

    def _placer(self, nouveau=None):
        hauteurs = [t.height() for t in reversed(self.liste)]
        for rang, t in enumerate(reversed(self.liste)):
            cible = self._cible(rang, hauteurs)
            if t is nouveau:
                t.move(cible + QPoint(0, 16) if T.animations else cible)
                g = QParallelAnimationGroup(t)
                a1 = QPropertyAnimation(t, b"pos")
                a1.setDuration(T.ms(260))
                a1.setStartValue(t.pos())
                a1.setEndValue(cible)
                a1.setEasingCurve(QEasingCurve.Type.OutCubic)
                a2 = QPropertyAnimation(t.eff, b"opacity")
                a2.setDuration(T.ms(220))
                a2.setStartValue(0.0 if T.animations else 1.0)
                a2.setEndValue(1.0)
                g.addAnimation(a1)
                g.addAnimation(a2)
                g.start()
                t.anims.append(g)
                if not T.animations:
                    t.eff.setOpacity(1.0)
            else:
                a = QPropertyAnimation(t, b"pos")
                a.setDuration(T.ms(200))
                a.setStartValue(t.pos())
                a.setEndValue(cible)
                a.setEasingCurve(QEasingCurve.Type.OutCubic)
                a.start()
                t.anims.append(a)

    def retirer(self, t):
        if t not in self.liste:
            return
        self.liste.remove(t)
        a = QPropertyAnimation(t.eff, b"opacity", t)
        a.setDuration(T.ms(220))
        a.setStartValue(t.eff.opacity())
        a.setEndValue(0.0)
        a.finished.connect(t.deleteLater)
        a.start()
        t.anims.append(a)
        if not T.animations:
            t.deleteLater()
        self._placer()

    def restyler(self):
        for t in self.liste:
            t.restyler()

    def replacer(self):
        hauteurs = [t.height() for t in reversed(self.liste)]
        for rang, t in enumerate(reversed(self.liste)):
            t.move(self._cible(rang, hauteurs))


# ---------------------------------------------------------------------------
# Navigation latérale
# ---------------------------------------------------------------------------
class BoutonNav(QAbstractButton):
    def __init__(self, texte, icone, parent=None):
        super().__init__(parent)
        self.setText(texte)
        self._icone = icone
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h, self._c = 0.0, 0.0
        self._ah = _anim(self, lambda v: (setattr(self, "_h", float(v)), self.update()))
        self._ac = _anim(self, lambda v: (setattr(self, "_c", float(v)), self.update()))
        self.toggled.connect(lambda e: _aller(self._ac, self._c, 1.0 if e else 0.0, 220))
        self.compact = False
        self.compteur = 0
        self.setToolTip(texte)

    def sizeHint(self):
        return QSize(44 if self.compact else 200, int(42 * max(0.85, T.densite)))

    def enterEvent(self, e):
        _aller(self._ah, self._h, 1.0, 120)

    def leaveEvent(self, e):
        _aller(self._ah, self._h, 0.0, 160)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(6, 2, -6, -2)
        fond = melange(couleur("surface2", 0), couleur("surface2"), self._h * (1 - self._c))
        fond = melange(fond, "accent_doux", self._c)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fond)
        p.drawRoundedRect(r, T.rayon, T.rayon)
        if self._c > 0.01:  # barre d'accent qui pousse depuis le centre
            hb = (r.height() - 16) * self._c
            p.setBrush(couleur("accent"))
            p.drawRoundedRect(QRectF(r.left() - 6, r.center().y() - hb / 2, 3, hb), 1.5, 1.5)
        teinte = melange("texte2", "accent_vif", self._c)
        ic = QRectF(r.left() + (r.width() - 20) / 2 if self.compact else r.left() + 12, r.center().y() - 10, 20, 20)
        dessiner_icone(p, self._icone, ic, teinte)
        if not self.compact:
            p.setPen(melange("texte2", "texte", max(self._c, self._h * 0.6)))
            p.setFont(police(None, self._c > 0.5))
            p.drawText(r.adjusted(44, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        if self.compteur:
            t = str(self.compteur) if self.compteur < 100 else "99+"
            p.setFont(police(max(9, T.taille - 3), True))
            w = QFontMetrics(p.font()).horizontalAdvance(t) + 10
            b = QRectF(r.right() - w - 8, r.center().y() - 9, w, 18) if not self.compact else QRectF(
                r.right() - w + 2, r.top() + 1, w, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(couleur("danger"))
            p.drawRoundedRect(b, 9, 9)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(b, Qt.AlignmentFlag.AlignCenter, t)


class Logo(QWidget):
    """Logo animé (les courants ondulent doucement quand une caméra est en direct)."""

    def __init__(self, taille=34, parent=None):
        super().__init__(parent)
        self.setFixedSize(taille, taille)
        self.phase = 0.0
        self.actif = False
        self._t = QTimer(self)
        self._t.setInterval(50)
        self._t.timeout.connect(self._tic)

    def animer(self, actif):
        self.actif = actif
        (self._t.start if actif and T.animations else self._t.stop)()

    def _tic(self):
        self.phase += 0.12
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        dessiner_logo(p, QRectF(1, 1, self.width() - 2, self.height() - 2), self.phase)


# ---------------------------------------------------------------------------
