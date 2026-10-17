"""Écoute des alertes du PC Flux (attente longue : la requête reste ouverte jusqu'à la prochaine alerte)."""
import threading

from PySide6.QtCore import QObject, Signal

from .api import ErreurApi


class Ecoute(QObject):
    evenements = Signal(list)
    session_perdue = Signal(str)
    connecte = Signal(bool)

    def __init__(self, api):
        super().__init__()
        self.api = api
        self._stop = threading.Event()
        self.dernier = None
        threading.Thread(target=self._boucle, daemon=True, name="flux-remote-alertes").start()

    def arreter(self):
        self._stop.set()

    def _boucle(self):
        attente = 2
        while not self._stop.is_set():
            try:
                if self.dernier is None:
                    self.dernier = self.api.attente(None).get("dernier", 0)
                r = self.api.attente(self.dernier, 40)
                if self._stop.is_set():
                    return
                if r.get("evenements"):
                    self.evenements.emit(r["evenements"])
                self.dernier = r.get("dernier", self.dernier)
                self.connecte.emit(True)
                attente = 2
            except ErreurApi as e:
                if e.code == 401:
                    self.session_perdue.emit(str(e))
                    return
                self.connecte.emit(False)
                self._stop.wait(attente)
                attente = min(60, attente * 2)
            except Exception:  # noqa: BLE001
                self.connecte.emit(False)
                self._stop.wait(attente)
                attente = min(60, attente * 2)
