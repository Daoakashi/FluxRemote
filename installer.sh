#!/usr/bin/env bash
# ===========================================================================
#  Flux Remote - installation pour Linux (Linux Mint, Ubuntu, Debian)
#  Paquets systeme, Python, environnement, dependances, icone et lanceur sur le bureau.
#  Peut etre relance sans risque (reparation / mise a jour).
#
#  Utilisation :  bash installer.sh          (options : --auto  --oui  --non)
# ===========================================================================
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
RACINE="$(pwd)"

AUTO=ask
for a in "$@"; do
    case "$a" in
        --auto|--oui) AUTO=yes ;;
        --non)        AUTO=no ;;
    esac
done

if [ -t 1 ]; then V=$'\e[32m'; R=$'\e[31m'; J=$'\e[33m'; B=$'\e[1m'; N=$'\e[0m'; else V=; R=; J=; B=; N=; fi
etape()  { echo; echo "${B}[$1/5]${N} $2"; }
ok()     { echo "      ${V}OK${N}  $*"; }
info()   { echo "      $*"; }
alerte() { echo "      ${J}Attention :${N} $*"; }
erreur() {
    echo; echo "  ${R}${B}L'installation s'est arretee.${N}"; echo "  $*"
    echo "  Corrigez le probleme puis relancez :  bash installer.sh"
    exit 1
}
oui() { # oui "question" defaut(o|n) mode(ask|yes|no)
    case "$3" in yes) return 0 ;; no) return 1 ;; esac
    [ -t 0 ] || { [ "$2" = o ]; return; }
    local rep; read -r -p "      $1 [$( [ "$2" = o ] && echo O/n || echo o/N )] " rep
    case "${rep,,}" in o|oui|y|yes) return 0 ;; n|non|no) return 1 ;; *) [ "$2" = o ] ;; esac
}

echo
echo "  =========================================="
echo "   Installation de Flux Remote (Linux)"
echo "  =========================================="
[ "$(id -u)" -eq 0 ] && erreur "Ne lancez pas ce script avec sudo : lancez-le avec votre compte normal (il demandera le mot de passe quand il en a besoin)."

# ---------------------------------------------------------------------------
# 1. Paquets du systeme (Python, bibliotheques graphiques de Qt, son des alertes)
# ---------------------------------------------------------------------------
etape 1 "Paquets du systeme..."
PAQUETS="python3 python3-venv python3-pip zenity xdg-user-dirs pulseaudio-utils libgl1 libegl1 libglib2.0-0 \
libdbus-1-3 libfontconfig1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1"
if command -v apt-get >/dev/null 2>&1; then
    MANQUANTS=""
    for p in $PAQUETS; do
        dpkg -s "$p" >/dev/null 2>&1 || MANQUANTS="$MANQUANTS $p"
    done
    if [ -z "$MANQUANTS" ]; then
        ok "Tous les paquets sont deja installes."
    elif ! command -v sudo >/dev/null 2>&1; then
        alerte "sudo est absent : installez a la main ces paquets :$MANQUANTS"
    else
        info "Le mot de passe de votre session peut etre demande."
        sudo apt-get update -qq || alerte "apt update a echoue (depots indisponibles ?), on continue."
        # paquet par paquet : un nom absent sur cette version de Linux ne bloque pas les autres
        for p in $MANQUANTS; do
            sudo apt-get install -y -qq "$p" >/dev/null 2>&1 || alerte "Paquet $p non installe (absent de cette version ?)."
        done
        ok "Paquets du systeme prets."
    fi
else
    alerte "apt-get absent : installez Python 3.10+ (avec venv et pip) et les bibliotheques de Qt avec le gestionnaire de paquets de votre systeme."
fi

# ---------------------------------------------------------------------------
# 2. Python
# ---------------------------------------------------------------------------
etape 2 "Python..."
PY=""
for c in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" 2>/dev/null; then
        PY="$c"; break
    fi
done
[ -n "$PY" ] || erreur "Python 3.10 a 3.13 introuvable. Installez-le (sudo apt install python3 python3-venv) puis relancez."
ok "$($PY --version)"

# ---------------------------------------------------------------------------
# 3. Environnement et dependances
# ---------------------------------------------------------------------------
etape 3 "Environnement et dependances..."
if [ -x venv/bin/python ] && ! venv/bin/python -c "import sys" >/dev/null 2>&1; then
    alerte "Environnement existant casse : recreation."
    rm -rf venv
fi
if [ ! -x venv/bin/python ]; then
    "$PY" -m venv venv || erreur "Creation de l'environnement impossible (paquet python3-venv manquant ?)."
    ok "Environnement cree."
else
    ok "Environnement existant conserve."
fi
VPY="$RACINE/venv/bin/python"
"$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check || erreur "pip n'a pas pu se mettre a jour (connexion Internet ?)."
"$VPY" -m pip install -r requirements.txt --disable-pip-version-check || erreur "Installation des dependances impossible (connexion Internet ?)."
cp requirements.txt venv/requirements.installe
ok "PySide6 et cryptography installes."

# ---------------------------------------------------------------------------
# 4. Verification
# ---------------------------------------------------------------------------
etape 4 "Verification..."
QT_QPA_PLATFORM=offscreen "$VPY" -c "import PySide6.QtWidgets, PySide6.QtNetwork, cryptography.x509; import fluxremote.fenetre" \
    || erreur "Flux Remote ne se charge pas (details ci-dessus)."
ok "Tout est pret."

# ---------------------------------------------------------------------------
# 5. Lanceur, icone, demarrage automatique
# ---------------------------------------------------------------------------
etape 5 "Lanceur et icone..."
chmod +x FluxRemote.sh installer.sh 2>/dev/null
BUREAU="$(xdg-user-dir DESKTOP 2>/dev/null)"; [ -d "$BUREAU" ] || BUREAU="$HOME/Desktop"
ecrire_lanceur() { # $1 = fichier, $2 = arguments
    cat > "$1" <<FIN
[Desktop Entry]
Type=Application
Name=Flux Remote
Comment=Flux Remote - telecommande de Flux
Exec="$RACINE/FluxRemote.sh" $2
Path=$RACINE
Icon=$RACINE/ressources/flux-remote.png
Terminal=false
Categories=Utility;Security;
StartupWMClass=flux_remote.py
FIN
    chmod +x "$1"
}
mkdir -p "$HOME/.local/share/applications"
ecrire_lanceur "$HOME/.local/share/applications/flux-remote.desktop" ""
ok "Flux Remote ajoute au menu des applications."
if [ -d "$BUREAU" ]; then
    ecrire_lanceur "$BUREAU/Flux Remote.desktop" ""
    command -v gio >/dev/null 2>&1 && gio set "$BUREAU/Flux Remote.desktop" metadata::trusted true >/dev/null 2>&1
    ok "Icone Flux Remote sur le bureau."
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1

echo
if oui "Lancer Flux Remote a l'ouverture de session (reduit pres de l'horloge, pour recevoir les alertes) ?" n "$AUTO"; then
    mkdir -p "$HOME/.config/autostart"
    ecrire_lanceur "$HOME/.config/autostart/flux-remote.desktop" "--reduit"
    echo "X-GNOME-Autostart-delay=10" >> "$HOME/.config/autostart/flux-remote.desktop"
    ok "Demarrage automatique active (modifiable dans Flux Remote › Reglages)."
fi

echo
echo "  =========================================="
echo "   ${V}${B}Installation terminee.${N}"
echo "   Lancez Flux Remote avec l'icone du bureau,"
echo "   depuis le menu des applications,"
echo "   ou avec :  ./FluxRemote.sh"
echo "  =========================================="
echo
if [ -t 0 ] && oui "Lancer Flux Remote maintenant ?" o ask; then
    nohup "$RACINE/FluxRemote.sh" >/dev/null 2>&1 &
fi
