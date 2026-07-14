"""Diálogo de Settings: ruta de proyectos, modo, API key, modelo, perfil."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLineEdit, QMessageBox, QPushButton,
)

from ..logger import get_logger
from ..profiles import (
    agregar_cancion_entrenamiento, listar_generos, listar_versiones_genero,
    revertir_genero,
)
from ..settings import Settings

log = get_logger("mixmaster.ui.settings")


class SettingsDialog(QDialog):
    """Edición de settings.json desde la UI."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings — MixMaster")
        self.setMinimumWidth(480)

        form = QFormLayout(self)

        # Ruta de proyectos con botón examinar
        self.ed_ruta = QLineEdit(settings.get("ruta_proyectos"))
        btn_ruta = QPushButton("…")
        btn_ruta.setFixedWidth(30)
        btn_ruta.clicked.connect(self._elegir_ruta)
        fila_ruta = QHBoxLayout()
        fila_ruta.addWidget(self.ed_ruta)
        fila_ruta.addWidget(btn_ruta)
        form.addRow("Carpeta de proyectos:", fila_ruta)

        self.cb_modo = QComboBox()
        self.cb_modo.addItems(["manual", "api"])
        self.cb_modo.setCurrentText(settings.get("modo", "manual"))
        form.addRow("Modo de conexión:", self.cb_modo)

        self.ed_key = QLineEdit(settings.get("api_key", ""))
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-ant-…")
        form.addRow("API key Anthropic:", self.ed_key)

        self.ed_modelo = QLineEdit(settings.get("modelo", "claude-sonnet-5"))
        form.addRow("Modelo:", self.ed_modelo)

        self.ed_perfil = QLineEdit(settings.get("perfil_usuario"))
        btn_perfil = QPushButton("…")
        btn_perfil.setFixedWidth(30)
        btn_perfil.clicked.connect(self._elegir_perfil)
        fila_perfil = QHBoxLayout()
        fila_perfil.addWidget(self.ed_perfil)
        fila_perfil.addWidget(btn_perfil)
        form.addRow("Perfil de usuario (.md):", fila_perfil)

        self.cb_genero = QComboBox()
        generos = listar_generos() or ["math_rock"]
        self.cb_genero.addItems(generos)
        actual = settings.get("genero_activo", "math_rock")
        if actual in generos:
            self.cb_genero.setCurrentText(actual)
        self.cb_genero.setToolTip(
            "Presets en config/generos/ — cada género es un .md (texto para Claude) "
            "+ .json (umbrales de alertas). Añade archivos ahí para crear géneros.")
        form.addRow("Género activo:", self.cb_genero)

        # Perfil acumulativo: entrenar con canciones propias y revertir versiones
        fila_perfil_acc = QHBoxLayout()
        btn_entrenar = QPushButton("🎓 Añadir canción al perfil…")
        btn_entrenar.setToolTip(
            "Analiza una mezcla/master tuyo y lo registra como referencia propia "
            "del género activo (el estado anterior queda versionado).")
        btn_entrenar.clicked.connect(self._entrenar_con_cancion)
        btn_revertir = QPushButton("↩ Revertir género…")
        btn_revertir.setToolTip("Restaura el preset del género a una versión anterior.")
        btn_revertir.clicked.connect(self._revertir_genero)
        fila_perfil_acc.addWidget(btn_entrenar)
        fila_perfil_acc.addWidget(btn_revertir)
        form.addRow("Perfil acumulativo:", fila_perfil_acc)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

    def _elegir_ruta(self):
        """Selector de carpeta de proyectos."""
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de proyectos", self.ed_ruta.text())
        if ruta:
            self.ed_ruta.setText(ruta)

    def _elegir_perfil(self):
        """Selector del archivo de perfil de usuario."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Perfil de usuario", "", "Markdown (*.md);;Todos (*.*)")
        if path:
            self.ed_perfil.setText(path)

    def _entrenar_con_cancion(self):
        """Analiza un tema propio y lo registra en el género activo (versionado)."""
        genero = self.cb_genero.currentText()
        path, _ = QFileDialog.getOpenFileName(
            self, "Elige tu mezcla/master a registrar", "",
            "Audio (*.wav *.mp3 *.flac *.ogg *.aiff *.aif);;Todos (*.*)")
        if not path:
            return
        try:
            from ..audio_analysis import balance_bandas_db, cargar_audio, crest_factor_db, lufs_integrado
            self.setEnabled(False)
            audio, sr = cargar_audio(Path(path))
            lufs = lufs_integrado(audio, sr)
            crest = crest_factor_db(audio)
            bandas = balance_bandas_db(audio, sr)
            resumen = (f"LUFS {lufs:.1f}, crest {crest:.1f} dB, "
                       + ", ".join(f"{b} {v:.0f}" for b, v in bandas.items()))
            nota, ok = QInputDialog.getText(
                self, "Nota del tema",
                "¿Qué salió bien / qué aprender de este tema? (se guarda junto a las medidas):")
            if ok:
                if nota.strip():
                    resumen += f" — {nota.strip()}"
                agregar_cancion_entrenamiento(genero, Path(path).stem, resumen)
                QMessageBox.information(
                    self, "Registrado",
                    f"«{Path(path).stem}» añadido a generos/{genero}.md\n"
                    "(estado anterior versionado en generos/versiones/)")
        except Exception as e:
            log.exception("Error entrenando con canción")
            QMessageBox.critical(self, "Error", f"No se pudo analizar el tema:\n{e}")
        finally:
            self.setEnabled(True)

    def _revertir_genero(self):
        """Restaura el preset del género activo a una versión anterior."""
        genero = self.cb_genero.currentText()
        versiones = listar_versiones_genero(genero)
        if not versiones:
            QMessageBox.information(self, "Sin versiones",
                                    f"«{genero}» aún no tiene versiones guardadas.")
            return
        nombres = [v.name for v in versiones]
        elegido, ok = QInputDialog.getItem(
            self, "Revertir género",
            "Versión a restaurar (la actual se guarda antes):", nombres, 0, False)
        if not ok:
            return
        try:
            revertir_genero(genero, versiones[nombres.index(elegido)])
            QMessageBox.information(self, "Revertido",
                                    f"«{genero}» restaurado a {elegido}.")
        except Exception as e:
            log.exception("Error revirtiendo género")
            QMessageBox.critical(self, "Error", f"No se pudo revertir:\n{e}")

    def _guardar(self):
        """Persiste los cambios en settings.json y cierra."""
        s = self.settings
        s.set("ruta_proyectos", self.ed_ruta.text().strip())
        s.set("modo", self.cb_modo.currentText())
        s.set("api_key", self.ed_key.text().strip())
        s.set("modelo", self.ed_modelo.text().strip() or "claude-sonnet-5")
        s.set("perfil_usuario", self.ed_perfil.text().strip())
        s.set("genero_activo", self.cb_genero.currentText())
        self.accept()
