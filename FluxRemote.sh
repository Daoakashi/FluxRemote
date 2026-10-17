#!/usr/bin/env bash
# Lance Flux Remote (Linux). Double-clic sur l'icone « Flux Remote » du bureau, ou : ./FluxRemote.sh
cd "$(dirname "$(readlink -f "$0")")" || exit 1
message() {
    if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        zenity --warning --title="Flux Remote" --no-markup --text="$1"
    else
        echo "$1"
    fi
}
if [ ! -x venv/bin/python ]; then
    message "Flux Remote n'est pas encore installe. Ouvrez un terminal dans ce dossier et tapez :  bash installer.sh"
    exit 1
fi
# Apres une mise a jour qui ajoute une dependance : installation automatique avant le lancement.
if ! cmp -s requirements.txt venv/requirements.installe; then
    venv/bin/python -m pip install -r requirements.txt --disable-pip-version-check -q \
        && cp requirements.txt venv/requirements.installe \
        || message "Mise a jour des composants impossible (connexion Internet ?). Relancez :  bash installer.sh"
fi
exec venv/bin/python flux_remote.py "$@"
