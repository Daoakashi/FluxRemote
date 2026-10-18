# Flux Remote

La télécommande de Flux sur ordinateur (Windows 10/11 et Linux). Flux Remote se connecte au PC qui fait tourner Flux, avec la même clé et les mêmes comptes que l'application FluxLite.

## Installer

Deux façons, au choix.

**Comme Flux, avec Python (recommandé pour l'instant)**
1. Décompressez l'archive dans un dossier à vous, par exemple `Documents\Flux Remote`.
2. Installez :
   - **Windows** : double-cliquez sur `installer.bat`. Il installe Python si besoin, l'environnement, les dépendances et un raccourci sur le bureau.
   - **Linux** : ouvrez un terminal dans le dossier et tapez `bash installer.sh`. Il installe les paquets du système et les dépendances, puis ajoute une icône dans le menu et sur le bureau. Option `--auto` pour lancer Flux Remote à l'ouverture de session.
3. Lancez Flux Remote avec le raccourci, ou avec `FluxRemote.bat` (Windows) ou `./FluxRemote.sh` (Linux).

Relancer l'installateur répare l'installation sans rien perdre. Si une mise à jour ajoute une dépendance, `FluxRemote.bat` et `FluxRemote.sh` l'installent tout seuls au lancement suivant.

**Programme prêt à l'emploi (sans Python)**
1. Téléchargez l'archive Windows ou Linux sur https://daoakashi.github.io/flux-web/telecharger.html#remote et décompressez-la dans un dossier à vous. Évitez « Program Files » : Flux Remote doit pouvoir s'y mettre à jour.
2. Lancez `FluxRemote.exe` (Windows) ou `FluxRemote` (Linux).

Au premier lancement, Windows peut afficher « Windows a protégé votre ordinateur », car le programme n'est pas encore signé par un certificat payant. Cliquez sur « Informations complémentaires » puis « Exécuter quand même ».

## Plusieurs PC Flux

Flux Remote peut suivre plusieurs PC Flux à la fois, par exemple un directeur et tous ses établissements.

- **Ajouter un serveur** : Tableau de bord, Compte ou Réglages › Serveurs Flux. Même démarche que pour le premier.
  - Si votre responsable a transféré votre compte (Flux › FluxLite › Transférer), connectez-vous avec le même mail et le même mot de passe.
  - Sinon, « Créer mon compte sur ce serveur avec mes informations » reprend vos nom, prénom, mail et société.
- **Caméras, Tableau de bord et Journal** : tout est regroupé, avec le nom du serveur. Le bouton « Tous les serveurs » permet de n'en afficher qu'un ou quelques-uns.
- **Contrôle** : choisissez le serveur à piloter. « Appliquer aussi aux autres serveurs » envoie le même réglage partout : détection, niveau de scan, délais, notifications.
- **Compte** : chaque serveur garde ses propres comptes, droits et sessions.

## Se connecter

1. Dans Flux, page **FluxLite** : activez le serveur, puis cliquez sur **Copier le lien pour Flux Remote**.
2. Dans Flux Remote, collez ce lien (ou saisissez l'adresse, le port et la clé), puis cliquez sur **Se connecter au serveur**.
3. Acceptez les conditions d'utilisation, puis connectez-vous ou créez votre compte.
4. Dans Flux, validez le compte. Pour les commandes, clic droit sur le compte › **Autoriser le pilotage à distance**.

**Depuis n'importe où** (version 1.1.0) : sur le réseau du PC Flux, la connexion est directe. Ailleurs (autre site, partage de connexion), Flux Remote passe tout seul par Internet grâce au **relais Flux**. Il n'y a rien à ouvrir dans la box, et c'est le même compte. Le chiffrement reste de bout en bout avec la clé du PC Flux. La barre du bas indique le chemin utilisé : « réseau local » ou « par Internet ». Hors du réseau, l'adresse locale est même facultative : la clé suffit. Pour utiliser un autre relais que celui du site : **Réglages › Serveur Flux › Relais Internet…**

## Ce que fait Flux Remote

- **Tableau de bord** : caméras en direct, personnes à l'image, alertes du jour, état de la détection, actions rapides.
- **Caméras** : mur de caméras (1 à 4 colonnes). Un double-clic ouvre une caméra en vidéo directe dans sa propre fenêtre, avec plein écran, toujours au premier plan et capture.
- **Contrôle** (comptes autorisés) :
  - détection générale et par caméra ;
  - démarrer ou arrêter une caméra ;
  - enregistrer une vidéo sur le PC Flux ;
  - niveau de scan ;
  - notifications, mails, WhatsApp, Telegram, SMS… ;
  - délais.
- **Journal** : toutes les alertes avec photo, recherche, filtre par caméra, export CSV.
- **Alertes sur cet ordinateur** : notification près de l'horloge avec un son. Vous pouvez les rendre silencieuses, les couper, les mettre en pause, fixer un délai, ou couper une caméra précise.
- **Compte** : nom, mot de passe, appareils connectés, export et suppression des données.
- **Réglages** : thème clair ou sombre, taille du texte, démarrage avec l'ordinateur, fermeture dans la zone de notification, raccourci sur le bureau, dossier des captures, mises à jour.

Raccourcis : `Ctrl+1` à `Ctrl+6` pour changer de page, `F5` pour actualiser. Dans une fenêtre vidéo, `F11` passe en plein écran et `Ctrl+S` fait une capture.

## Mises à jour

Flux Remote vérifie au démarrage le fichier https://daoakashi.github.io/flux-web/remote/version.json. Il propose la nouvelle version, la télécharge depuis GitHub, vérifie son empreinte SHA-256, l'installe puis redémarre. Cela marche pour les deux façons d'installer : la version Python reçoit le paquet des sources et garde son environnement `venv`. Vos réglages, rangés dans votre dossier utilisateur, sont conservés.

## Pour le développeur

- Lancer depuis les sources : `installer.bat` / `installer.sh`, puis `FluxRemote.bat` / `./FluxRemote.sh`.
- Compiler : `pip install pyinstaller`, puis `python construire.py`.
- Publier : augmentez `VERSION` dans `fluxremote/version.py`, puis lancez **Actions › Publier Flux Remote** dans ce dépôt. Le robot compile pour Windows et Linux, publie les archives dans les *Releases* de ce dépôt (tag `v1.1.0`…), puis le site recopie leur `version.json` (tout de suite avec le secret facultatif `SITE_TOKEN`, sinon dans l'heure).
- Dépôts liés : [Flux](https://github.com/Daoakashi/Flux) (le serveur, sur le PC des caméras) et [flux-web](https://github.com/Daoakashi/flux-web) (le site et le relais).

## Licence, juridique et IA

Flux Remote est un logiciel libre de DMS Security sous licence GNU AGPL-3.0 (`LICENSE`), sans garantie. Il a été conçu et développé avec l'aide d'outils d'intelligence artificielle, sous la direction et la vérification de son auteur. Textes juridiques : dossier [`juridique/`](juridique/LISEZMOI.md). Feedback : bouton dans le programme, ou dms.security.list@gmail.com.

