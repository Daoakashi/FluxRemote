# Licences des composants de Flux Remote

Flux Remote n'utilise que des composants gratuits, sans licence payante, qui peuvent être distribués dans un logiciel vendu.

| Composant | Rôle | Licence | Ce qu'il faut respecter |
|---|---|---|---|
| Python | langage | PSF License | rien de particulier |
| Qt for Python (PySide6) et Qt 6 | interface | LGPL v3 | Bibliothèques Qt livrées en fichiers séparés (c'est le cas : mode « dossier »), mention de la licence, possibilité pour l'utilisateur de les remplacer. Pas de modification du code de Qt. |
| cryptography | vérification de la clé du serveur | Apache 2.0 / BSD | garder la mention de licence |
| OpenSSL (inclus dans Python et cryptography) | chiffrement TLS | Apache 2.0 | garder la mention de licence |
| PyInstaller (sert seulement à compiler) | création du programme | GPL v2 avec exception | l'exception autorise la vente du programme compilé, sans obligation sur son code |
| Polices et icônes | interface | dessinées dans le code de Flux Remote | aucune |

Textes complets :
- LGPL v3 : https://www.gnu.org/licenses/lgpl-3.0.html
- Qt for Python : https://doc.qt.io/qtforpython-6/licenses.html
- Apache 2.0 : https://www.apache.org/licenses/LICENSE-2.0
- PSF : https://docs.python.org/3/license.html

Le code source de Qt est disponible sur https://download.qt.io/official_releases/qt/.
