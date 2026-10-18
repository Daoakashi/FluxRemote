"""Écrans d'accueil de Flux Remote : relier le PC Flux (clé), conditions d'utilisation, connexion et inscription."""
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QScrollArea,
                               QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from . import api as module_api
from .taches import Tache
from .theme import C, T
from .widgets import Bouton, Logo, etiquette

RE_MAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def champ(texte_aide="", mdp=False):
    c = QLineEdit()
    c.setPlaceholderText(texte_aide)
    c.setMinimumHeight(38)
    if mdp:
        c.setEchoMode(QLineEdit.EchoMode.Password)
    return c


def force_mdp(m):
    if len(m) < 10:
        return 0.15 + len(m) * 0.03, f"Encore {10 - len(m)} caractère(s) au minimum."
    if not (re.search(r"[A-Za-zÀ-ÿ]", m) and re.search(r"\d", m)):
        return 0.4, "Ajoutez des lettres et des chiffres."
    score = 0.6 + (0.15 if len(m) >= 14 else 0) + (0.15 if re.search(r"[^\w]", m) else 0) + \
        (0.1 if re.search(r"[a-z]", m) and re.search(r"[A-Z]", m) else 0)
    return min(1.0, score), "Excellent mot de passe." if score >= 0.85 else "Correct. Plus long ou avec un symbole, c'est mieux."


def mdp_accepte(m):
    return len(m) >= 10 and bool(re.search(r"[A-Za-zÀ-ÿ]", m)) and bool(re.search(r"\d", m))


def articles_cgu(info):
    info = info or {}
    responsable = info.get("responsable") or "l'entreprise qui exploite le serveur Flux auquel vous vous connectez"
    contact = f" à l'adresse {info['contact']}" if info.get("contact") else " auprès de ce responsable"
    duree = info.get("conservation_journal", 7)
    return [
        ("1. Objet", "Flux Remote permet aux personnes autorisées de consulter et de piloter depuis un ordinateur un "
                     "système de vidéosurveillance Flux. Il ne fonctionne qu'avec un serveur Flux privé."),
        ("2. Accès et compte", "Votre compte est personnel. Il est validé par le responsable du serveur, qui décide des "
                               "caméras et des commandes auxquelles vous avez accès. Gardez votre mot de passe secret et "
                               "signalez toute utilisation suspecte. Le responsable peut suspendre ou supprimer un compte."),
        ("3. Bon usage des images", "Les images montrent des personnes : ce sont des données personnelles. Vous les "
                                    "consultez uniquement pour la mission de sécurité qui vous est confiée. Il est interdit "
                                    "de les diffuser ou de les utiliser à d'autres fins. Les captures que vous enregistrez "
                                    "sur cet ordinateur restent sous votre responsabilité."),
        ("4. Responsable du traitement", f"Le responsable du traitement est {responsable}. Les données sont stockées sur "
                                         "son propre serveur Flux, pas chez l'éditeur du logiciel ni chez un hébergeur tiers."),
        ("5. Données vous concernant", "Nom, prénom, adresse mail, société indiquée, empreinte chiffrée du mot de passe, "
                                       "date d'acceptation des conditions, et des informations techniques de connexion "
                                       "(nom et système de l'ordinateur, version de Flux Remote, adresse IP, dates). Elles "
                                       "servent à sécuriser l'accès et sont conservées tant que le compte existe."),
        ("6. Alertes", f"Les alertes et leurs photos sont conservées {duree} jour(s) sur le serveur puis effacées."),
        ("7. Sécurité", "Les échanges sont chiffrés (TLS) et liés à la clé unique du serveur : Flux Remote refuse tout "
                        "serveur qui ne présente pas cette clé. Les commandes à distance sont notées dans le journal de "
                        "Flux avec votre nom."),
        ("8. Vos droits (RGPD)", "Vous pouvez accéder à vos données, les rectifier, les exporter, demander leur effacement, "
                                 "vous opposer à leur traitement ou en demander la limitation. L'onglet Compte permet "
                                 f"d'exporter vos données et de supprimer votre compte. Pour le reste, adressez-vous au "
                                 f"responsable{contact}. Vous pouvez aussi saisir l'APD (Belgique) ou la CNIL (France)."),
        ("9. Feedback", "Le bouton Feedback ouvre votre messagerie ou GitHub avec un message que vous relisez avant "
                        "de l'envoyer ; rien n'est envoyé automatiquement. Il est adressé à l'éditeur (DMS Security), "
                        "pas au responsable du serveur."),
        ("10. Logiciel libre", "Flux Remote est un logiciel libre (GNU AGPL-3.0) fourni sans garantie, développé avec "
                               "l'aide d'outils d'intelligence artificielle. Code source : github.com/Daoakashi."),
        ("11. Évolution", f"Ces conditions peuvent évoluer ; la nouvelle version devra être acceptée. Version "
                          f"{module_api.VERSION_CGU}."),
    ]


def html_cgu(info):
    return "".join(f"<h3 style='margin:14px 0 4px'>{t}</h3><p style='margin:0;color:{C['texte2']}'>{x}</p>"
                   for t, x in articles_cgu(info))


class Carte(QFrame):
    """Panneau centré des écrans d'accueil."""

    def __init__(self, largeur=520):
        super().__init__()
        self.setObjectName("carte")
        self.setMaximumWidth(largeur)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(34, 30, 34, 30)
        self.v.setSpacing(10)


def centre(widget):
    w = QWidget()
    h = QHBoxLayout(w)
    h.addStretch(1)
    h.addWidget(widget, 10)
    h.addStretch(1)
    defil = QScrollArea()
    defil.setWidgetResizable(True)
    defil.setFrameShape(QFrame.Shape.NoFrame)
    conteneur = QWidget()
    v = QVBoxLayout(conteneur)
    v.addStretch(1)
    v.addWidget(w)
    v.addStretch(2)
    defil.setWidget(conteneur)
    return defil


def entete(titre, sous_titre):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 8)
    h = QHBoxLayout()
    logo = Logo(42)
    h.addWidget(logo)
    h.addSpacing(6)
    t = QLabel(titre)
    t.setObjectName("titre_page")
    h.addWidget(t)
    h.addStretch(1)
    v.addLayout(h)
    v.addWidget(etiquette(sous_titre, "soustitre"))
    return w


class Accueil(QStackedWidget):
    """Appairage › conditions › connexion d'un PC Flux. Émet `connecte` quand la session est ouverte, `annule`
    quand la personne revient aux serveurs déjà reliés sans en ajouter."""
    connecte = Signal()
    annule = Signal()

    def __init__(self, fen):
        super().__init__()
        self.fen, self.reg = fen, fen.reg
        self.info = None
        self._annuler = []
        self.p_appairage = self._appairage()
        self.p_cgu = self._cgu()
        self.p_connexion = self._connexion()
        for p in (self.p_appairage, self.p_cgu, self.p_connexion):
            self.addWidget(p)

    def _bouton_annuler(self, carte):
        b = Bouton("Retour aux serveurs reliés", "fantome", "retour")
        b.clicked.connect(self.annule.emit)
        carte.v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self._annuler.append(b)

    def montrer(self):
        for b in self._annuler:
            b.setVisible(bool(self.fen.serveurs_actifs()))
        self.b_reutiliser.hide()
        if not self.c_mail.text().strip():
            self.c_mail.setText(self.fen.mail_connu())
        if not self.reg["cle"]:
            self.setCurrentWidget(self.p_appairage)
        elif self.reg["cgu"] != module_api.VERSION_CGU:
            self._charger_info(lambda: self.setCurrentWidget(self.p_cgu))
            self.setCurrentWidget(self.p_cgu)
        else:
            self._charger_info()
            self.setCurrentWidget(self.p_connexion)
            self._maj_connexion()

    def api(self, jeton=None):
        return module_api.Api(self.reg["hote"], self.reg["port"], self.reg["cle"], jeton, relais=self.reg["relais"])

    def _charger_info(self, ensuite=None):
        def fini(info):
            self.info = info
            self.cgu_texte.setHtml(html_cgu(info))
            self._maj_connexion()
            if info.get("nom") and info["nom"] != self.reg["nom_serveur"]:
                self.reg.set("nom_serveur", info["nom"])
            if "relais" in info and (info.get("relais") or "") != self.reg["relais"]:
                self.reg.set("relais", info.get("relais") or "")
            if ensuite:
                ensuite()
        t = Tache(self.api().info)
        t.fini.connect(fini)
        t.lancer()

    # --- appairage -------------------------------------------------------------------------------
    def _appairage(self):
        carte = Carte(560)
        carte.v.addWidget(entete("Flux Remote", "La télécommande de Flux sur votre ordinateur. Reliez-la au PC qui fait "
                                                "tourner Flux : son adresse et sa clé sont affichées dans Flux, page "
                                                "FluxLite."))
        carte.v.addSpacing(6)
        carte.v.addWidget(QLabel("Lien d'appairage (facultatif)"))
        self.c_lien = champ("Dans Flux, page FluxLite › « Copier le lien pour Flux Remote », puis collez ici")
        self.c_lien.textChanged.connect(self._lien_colle)
        carte.v.addWidget(self.c_lien)
        carte.v.addSpacing(6)
        h = QHBoxLayout()
        g = QVBoxLayout()
        g.addWidget(QLabel("Adresse du PC Flux sur son réseau"))
        self.c_hote = champ("192.168.1.20 (facultatif hors de ce réseau)")
        g.addWidget(self.c_hote)
        h.addLayout(g, 3)
        d = QVBoxLayout()
        d.addWidget(QLabel("Port"))
        self.c_port = champ("47810")
        self.c_port.setText(str(self.reg["port"] or 47810))
        d.addWidget(self.c_port)
        h.addLayout(d, 1)
        carte.v.addLayout(h)
        carte.v.addWidget(QLabel("Clé du serveur"))
        self.c_cle = champ("32 caractères, ex. 7X51-S5WV-SGBE-…")
        carte.v.addWidget(self.c_cle)
        self.relais_lien = ""
        self.l_appairage = etiquette("")
        carte.v.addWidget(self.l_appairage)
        self.b_appairer = Bouton("Se connecter au serveur", "primaire", "reseau")
        self.b_appairer.clicked.connect(self._appairer)
        carte.v.addWidget(self.b_appairer)
        carte.v.addSpacing(10)
        carte.v.addWidget(etiquette("Pourquoi une clé ? Flux Remote vérifie à chaque connexion que l'ordinateur en face est "
                                    "bien votre PC Flux. Sur le même réseau, la connexion est directe ; ailleurs (autre "
                                    "site, partage de connexion), elle passe par Internet grâce au relais Flux, sans rien "
                                    "ouvrir dans la box. Dans les deux cas, images, alertes et commandes restent chiffrées "
                                    "de bout en bout entre ce PC et le PC Flux."))
        self._bouton_annuler(carte)
        return centre(carte)

    def _lien_colle(self, texte):
        r = module_api.lire_lien(texte)
        if r:
            hotes, port, cle, _nom = r
            self.relais_lien = module_api.relais_du_lien(texte)
            self.c_hote.setText(", ".join(hotes))
            self.c_port.setText(str(port))
            self.c_cle.setText(module_api.formater_cle(cle))
        elif module_api.cle_valide(module_api.normaliser_cle(texte)):
            self.c_cle.setText(module_api.formater_cle(module_api.normaliser_cle(texte)))

    def _appairer(self):
        cle = module_api.normaliser_cle(self.c_cle.text())
        hotes = [h.strip() for h in re.split(r"[,\s]+", self.c_hote.text()) if h.strip()]
        try:
            port = int(self.c_port.text() or 47810)
        except ValueError:
            port = 0
        if not hotes and not (self.relais_lien or module_api.relais_site()):
            return self._msg(self.l_appairage, "Indiquez l'adresse du PC Flux (aucun relais Internet connu pour "
                                               "l'instant).", True)
        if not 1 <= port <= 65535:
            return self._msg(self.l_appairage, "Port invalide.", True)
        if not module_api.cle_valide(cle):
            return self._msg(self.l_appairage, "Clé invalide : 32 caractères, comme affiché dans Flux.", True)
        self.b_appairer.setEnabled(False)
        self._msg(self.l_appairage, "Vérification de la clé…")
        relais = self.relais_lien

        def fini(r):
            hote, info, route = r
            self.b_appairer.setEnabled(True)
            self.info = info
            self.reg.maj(hote=hote, hotes=hotes, port=port, cle=cle, nom_serveur=info.get("nom", "Flux"),
                         relais=info.get("relais") or relais or "")
            self.cgu_texte.setHtml(html_cgu(info))
            par = "sur le réseau local" if route == "direct" else "par Internet (relais Flux)"
            self.fen.toast(f"Relié à « {info.get('nom', 'Flux')} » {par}. Clé vérifiée.", "ok")
            self.montrer()

        def echec(msg):
            self.b_appairer.setEnabled(True)
            self._msg(self.l_appairage, msg, True)
        t = Tache(self._essayer, hotes, port, cle, relais)
        t.fini.connect(fini)
        t.echec.connect(echec)
        t.lancer()

    @staticmethod
    def _essayer(hotes, port, cle, relais):
        try:
            return module_api.appairer(hotes, port, cle, relais or None)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(module_api.message_erreur(e)) from None

    # --- conditions d'utilisation ------------------------------------------------------------------
    def _cgu(self):
        carte = Carte(720)
        carte.v.addWidget(entete("Conditions d'utilisation", "À lire et accepter une fois par serveur."))
        self.cgu_texte = QTextBrowser()
        self.cgu_texte.setOpenExternalLinks(False)
        self.cgu_texte.setMinimumHeight(340)
        self.cgu_texte.setHtml(html_cgu(None))
        carte.v.addWidget(self.cgu_texte, 1)
        self.chk_cgu = QCheckBox("J'ai lu les conditions d'utilisation et l'information sur mes données personnelles.")
        carte.v.addWidget(self.chk_cgu)
        b = Bouton("J'accepte les conditions d'utilisation", "primaire")
        b.setEnabled(False)
        self.chk_cgu.toggled.connect(b.setEnabled)
        b.clicked.connect(self._accepter)
        carte.v.addWidget(b)
        b2 = Bouton("Changer de serveur", "fantome")
        b2.clicked.connect(self._changer_serveur)
        carte.v.addWidget(b2, 0, Qt.AlignmentFlag.AlignLeft)
        self._bouton_annuler(carte)
        return centre(carte)

    def _accepter(self):
        self.reg.set("cgu", module_api.VERSION_CGU)
        self.montrer()

    def _changer_serveur(self):
        self.reg.oublier_serveur()
        self.reg.set("cgu", "")
        self.montrer()

    # --- connexion et inscription ------------------------------------------------------------------
    def _connexion(self):
        carte = Carte(560)
        self.ent_connexion = entete("Connexion", "")
        carte.v.addWidget(self.ent_connexion)
        self.onglets = QStackedWidget()
        # connexion
        w1 = QWidget()
        v1 = QVBoxLayout(w1)
        v1.setContentsMargins(0, 0, 0, 0)
        v1.addWidget(QLabel("Adresse mail"))
        self.c_mail = champ("vous@entreprise.be")
        v1.addWidget(self.c_mail)
        v1.addWidget(QLabel("Mot de passe"))
        self.c_mdp = champ("", True)
        self.c_mdp.returnPressed.connect(self._se_connecter)
        v1.addWidget(self.c_mdp)
        self.l_connexion = etiquette("")
        v1.addWidget(self.l_connexion)
        self.b_reutiliser = Bouton("Créer mon compte sur ce serveur avec mes informations", "discret", "plus")
        self.b_reutiliser.setToolTip("Mêmes nom, prénom, mail et société que sur vos autres serveurs Flux. Le responsable "
                                     "de ce serveur valide le compte.")
        self.b_reutiliser.clicked.connect(self._reutiliser)
        self.b_reutiliser.hide()
        v1.addWidget(self.b_reutiliser)
        self.b_connexion = Bouton("Se connecter", "primaire")
        self.b_connexion.clicked.connect(self._se_connecter)
        v1.addWidget(self.b_connexion)
        v1.addWidget(etiquette("Mot de passe oublié ? Demandez au responsable de le réinitialiser depuis Flux."))
        b_insc = Bouton("Créer un compte", "fantome")
        b_insc.clicked.connect(lambda: self.onglets.setCurrentIndex(1))
        v1.addWidget(b_insc, 0, Qt.AlignmentFlag.AlignLeft)
        v1.addStretch(1)
        self.onglets.addWidget(w1)
        # inscription
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        v2.setContentsMargins(0, 0, 0, 0)
        h = QHBoxLayout()
        self.i_prenom, self.i_nom = champ("Prénom"), champ("Nom")
        h.addWidget(self.i_prenom)
        h.addWidget(self.i_nom)
        v2.addLayout(h)
        self.i_mail = champ("Adresse mail")
        v2.addWidget(self.i_mail)
        self.i_societe = champ("Société (votre employeur ou client)")
        v2.addWidget(self.i_societe)
        self.i_mdp = champ("Mot de passe (10 caractères, lettres et chiffres)", True)
        v2.addWidget(self.i_mdp)
        self.barre_force = QProgressBar()
        self.barre_force.setRange(0, 100)
        self.barre_force.setTextVisible(False)
        self.barre_force.setFixedHeight(6)
        v2.addWidget(self.barre_force)
        self.l_force = etiquette("Au moins 10 caractères, avec des lettres et des chiffres.")
        v2.addWidget(self.l_force)
        self.i_mdp2 = champ("Confirmer le mot de passe", True)
        v2.addWidget(self.i_mdp2)
        self.i_mdp.textChanged.connect(self._force)
        self.l_inscription = etiquette("")
        v2.addWidget(self.l_inscription)
        self.b_inscription = Bouton("Créer mon compte", "primaire")
        self.b_inscription.clicked.connect(self._inscrire)
        v2.addWidget(self.b_inscription)
        b_ret = Bouton("J'ai déjà un compte", "fantome")
        b_ret.clicked.connect(lambda: self.onglets.setCurrentIndex(0))
        v2.addWidget(b_ret, 0, Qt.AlignmentFlag.AlignLeft)
        self.onglets.addWidget(w2)
        carte.v.addWidget(self.onglets)
        carte.v.addSpacing(8)
        b_serv = Bouton("Changer de serveur", "fantome", "reseau")
        b_serv.clicked.connect(self._changer_serveur)
        carte.v.addWidget(b_serv, 0, Qt.AlignmentFlag.AlignLeft)
        self._bouton_annuler(carte)
        return centre(carte)

    def _maj_connexion(self):
        nom = self.reg["nom_serveur"] or "Flux"
        lab = self.ent_connexion.findChild(QLabel, "soustitre")
        if lab:
            lab.setText(f"Serveur « {nom} » · connexion chiffrée, clé vérifiée.")
            lab.setStyleSheet(f"color: {C['succes']};")

    def _force(self, m):
        k, conseil = force_mdp(m)
        self.barre_force.setValue(int(k * 100))
        teinte = C["danger"] if k < 0.45 else C["attention"] if k < 0.8 else C["succes"]
        self.barre_force.setStyleSheet(f"QProgressBar::chunk {{ background: {teinte}; border-radius: 3px; }}")
        self.l_force.setText(conseil if m else "Au moins 10 caractères, avec des lettres et des chiffres.")

    def _msg(self, lab, texte, erreur=False):
        lab.setText(texte)
        lab.setStyleSheet(f"color: {C['danger'] if erreur else C['texte2']};")

    def _se_connecter(self):
        mail, mdp = self.c_mail.text().strip(), self.c_mdp.text()
        if not RE_MAIL.match(mail) or not mdp:
            return self._msg(self.l_connexion, "Indiquez votre adresse mail et votre mot de passe.", True)
        self.b_connexion.setEnabled(False)
        self._msg(self.l_connexion, "Connexion…")

        def fini(r):
            self.b_connexion.setEnabled(True)
            self.c_mdp.clear()
            self.reg.set("jeton", r["jeton"])
            compte = r.get("compte", {})
            if not compte.get("cgu_a_jour", True):
                Tache(self.api(r["jeton"]).modifier_profil, cgu_version=module_api.VERSION_CGU).lancer()
            self._msg(self.l_connexion, "")
            self.connecte.emit()

        def echec(msg):
            self.b_connexion.setEnabled(True)
            self._msg(self.l_connexion, msg, True)
            # Pas encore de compte sur ce serveur ? On propose de le créer avec les informations déjà connues
            if self.fen.profil_connu() and "incorrect" in msg.lower() and (self.info or {}).get("inscription", True):
                self.b_reutiliser.show()
        t = Tache(self._appel, lambda: self.api().connecter(mail, mdp))
        t.fini.connect(fini)
        t.echec.connect(echec)
        t.lancer()

    def _reutiliser(self):
        p = self.fen.profil_connu()
        self.i_prenom.setText(p.get("prenom", ""))
        self.i_nom.setText(p.get("nom", ""))
        self.i_mail.setText(self.c_mail.text().strip() or p.get("mail", ""))
        self.i_societe.setText(p.get("societe") or p.get("entreprise") or "")
        self.onglets.setCurrentIndex(1)
        self._msg(self.l_inscription, "Vos informations sont reprises : choisissez le mot de passe pour ce serveur "
                                      "(le même que d'habitude si vous voulez).")
        self.i_mdp.setFocus()

    def _inscrire(self):
        p, n, m = self.i_prenom.text().strip(), self.i_nom.text().strip(), self.i_mail.text().strip()
        mdp, mdp2 = self.i_mdp.text(), self.i_mdp2.text()
        if not p or not n:
            return self._msg(self.l_inscription, "Indiquez votre prénom et votre nom.", True)
        if not RE_MAIL.match(m):
            return self._msg(self.l_inscription, "Adresse mail invalide.", True)
        if not mdp_accepte(mdp):
            return self._msg(self.l_inscription, "Mot de passe trop faible : 10 caractères, lettres et chiffres.", True)
        if mdp != mdp2:
            return self._msg(self.l_inscription, "Les deux mots de passe diffèrent.", True)
        self.b_inscription.setEnabled(False)

        def fini(r):
            self.b_inscription.setEnabled(True)
            self.onglets.setCurrentIndex(0)
            self.c_mail.setText(m)
            self._msg(self.l_connexion, r.get("message") or "Compte créé.")
            self.i_mdp.clear()
            self.i_mdp2.clear()

        def echec(msg):
            self.b_inscription.setEnabled(True)
            self._msg(self.l_inscription, msg, True)
        t = Tache(self._appel, lambda: self.api().inscrire(m, mdp, n, p, self.i_societe.text().strip()))
        t.fini.connect(fini)
        t.echec.connect(echec)
        t.lancer()

    @staticmethod
    def _appel(f):
        try:
            return f()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(module_api.message_erreur(e)) from None


__all__ = ["Accueil", "html_cgu", "force_mdp", "mdp_accepte", "T"]
