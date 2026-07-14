"""Diálogo de chat con Claude (menú 💬) + registro de decisiones.

Fuera de la pantalla principal: se abre solo cuando quieres criterio.
Cada mensaje lleva perfil de usuario + género + diagnóstico + decisiones.
"""

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout,
)

from ..claude_client import ClaudeError, enviar_mensaje
from ..context_builder import construir_contexto
from ..decisions import guardar_decision
from ..logger import get_logger

log = get_logger("mixmaster.ui.chat")


class _ChatWorker(QThread):
    """Llama a la API de Anthropic sin bloquear la UI."""

    terminado = Signal(str)
    fallo = Signal(str)

    def __init__(self, settings, contexto: str, historial: list[dict]):
        super().__init__()
        self.settings, self.contexto, self.historial = settings, contexto, historial

    def run(self):
        try:
            self.terminado.emit(enviar_mensaje(self.settings, self.contexto, self.historial))
        except ClaudeError as e:
            self.fallo.emit(str(e))
        except Exception as e:
            log.exception("Fallo inesperado en el chat")
            self.fallo.emit(f"Error inesperado: {e}")


class ChatDialog(QDialog):
    """Chat + conclusión + guardado de decisiones, en ventana aparte."""

    def __init__(self, ventana_principal):
        super().__init__(ventana_principal)
        self.win = ventana_principal  # accede a settings/proyecto/diagnóstico actuales
        self.historial_chat: list[dict] = []
        self.setWindowTitle("💬 Chat — MixMaster")
        self.resize(640, 620)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Cada mensaje lleva tu perfil + género + diagnóstico + últimas decisiones.\n"
            "Modo manual: «Copiar contexto» y pegar en claude.ai."))

        self.txt_chat = QTextEdit()
        self.txt_chat.setReadOnly(True)
        self.txt_chat.setPlaceholderText("Historial de la conversación…")
        lay.addWidget(self.txt_chat, stretch=1)

        fila_msg = QHBoxLayout()
        self.ed_mensaje = QLineEdit()
        self.ed_mensaje.setPlaceholderText("Escribe tu pregunta…")
        self.ed_mensaje.returnPressed.connect(self._enviar)
        self.btn_enviar = QPushButton("Enviar")
        self.btn_enviar.clicked.connect(self._enviar)
        btn_copiar = QPushButton("Copiar contexto")
        btn_copiar.clicked.connect(self._copiar_contexto)
        fila_msg.addWidget(self.ed_mensaje, stretch=1)
        fila_msg.addWidget(self.btn_enviar)
        fila_msg.addWidget(btn_copiar)
        lay.addLayout(fila_msg)

        lay.addWidget(QLabel("Conclusión (pega o resume la recomendación final):"))
        self.txt_conclusion = QTextEdit()
        self.txt_conclusion.setMaximumHeight(80)
        lay.addWidget(self.txt_conclusion)

        fila_dec = QHBoxLayout()
        self.cb_feedback = QComboBox()
        self.cb_feedback.addItems(["aprobado", "rechazado", "ajustado"])
        btn_regla = QPushButton("★ Al género")
        btn_regla.setToolTip(
            "Fija la conclusión como regla aprendida del género activo\n"
            "(versionado, reversible en Settings). Frases concretas y medibles.")
        btn_regla.clicked.connect(self._regla_al_genero)
        btn_guardar = QPushButton("Guardar decisión")
        btn_guardar.clicked.connect(self._guardar_decision)
        fila_dec.addWidget(QLabel("Feedback:"))
        fila_dec.addWidget(self.cb_feedback)
        fila_dec.addStretch()
        fila_dec.addWidget(btn_regla)
        fila_dec.addWidget(btn_guardar)
        lay.addLayout(fila_dec)

        self.lbl_estado = QLabel("")
        lay.addWidget(self.lbl_estado)

    # ------------------------------------------------------------- helpers

    def _contexto(self, mensaje: str) -> str:
        return construir_contexto(
            self.win.settings, self.win.proyecto, self.win.diagnostico, mensaje)

    def _agregar(self, quien: str, texto: str):
        self.txt_chat.append(f"<b>{quien}:</b>")
        self.txt_chat.append(texto.replace("\n", "<br>"))
        self.txt_chat.append("")

    # -------------------------------------------------------------- chat

    def _enviar(self):
        """Envía por API si está configurada; si no, copia el contexto."""
        mensaje = self.ed_mensaje.text().strip()
        if not mensaje:
            return
        s = self.win.settings
        if s.get("modo") != "api" or not s.get("api_key"):
            self._copiar_contexto()
            return
        contexto = self._contexto(mensaje)
        self._agregar("Tú", mensaje)
        self.ed_mensaje.clear()
        self.btn_enviar.setEnabled(False)
        self.lbl_estado.setText("Consultando a Claude…")
        self._worker = _ChatWorker(s, contexto, list(self.historial_chat))
        self._worker.terminado.connect(lambda r: self._chat_ok(contexto, r))
        self._worker.fallo.connect(self._chat_error)
        self._worker.start()

    def _chat_ok(self, contexto: str, respuesta: str):
        self.historial_chat.append({"role": "user", "content": contexto})
        self.historial_chat.append({"role": "assistant", "content": respuesta})
        self._agregar("Claude", respuesta)
        self.btn_enviar.setEnabled(True)
        self.lbl_estado.setText("Respuesta recibida.")

    def _chat_error(self, msg: str):
        self._agregar("⚠ Sistema", msg)
        self.btn_enviar.setEnabled(True)
        self.lbl_estado.setText("Error en la consulta (ver app.log).")

    def _copiar_contexto(self):
        mensaje = self.ed_mensaje.text().strip() or "(escribe aquí tu pregunta)"
        QGuiApplication.clipboard().setText(self._contexto(mensaje))
        if self.ed_mensaje.text().strip():
            self._agregar("Tú (manual)", mensaje)
            self.ed_mensaje.clear()
        self.lbl_estado.setText("Contexto copiado — pégalo en claude.ai")

    # --------------------------------------------------------- aprendizaje

    def _regla_al_genero(self):
        """Promueve la conclusión a regla del género activo (versionado)."""
        from PySide6.QtWidgets import QInputDialog

        from ..profiles import agregar_regla_genero
        genero = self.win.settings.genero_activo()
        texto = self.txt_conclusion.toPlainText().strip()
        regla, ok = QInputDialog.getText(
            self, "Regla del género",
            f"Regla a fijar en «{genero}» (concreta y medible):", text=texto[:200])
        if not ok or not regla.strip():
            return
        cancion = self.win.diagnostico["archivo"] if self.win.diagnostico else ""
        try:
            agregar_regla_genero(genero, regla.strip(), cancion)
            self.lbl_estado.setText(f"★ Regla guardada en generos/{genero}.md")
        except Exception as e:
            log.exception("Error guardando regla desde el chat")
            QMessageBox.critical(self, "Error", f"No se pudo guardar la regla:\n{e}")

    # --------------------------------------------------------- decisiones

    def _guardar_decision(self):
        if not self.win.proyecto:
            QMessageBox.information(self, "Sin proyecto", "Abre un proyecto primero.")
            return
        texto = self.txt_conclusion.toPlainText().strip()
        if not texto:
            QMessageBox.information(self, "Sin texto", "Escribe o pega la conclusión primero.")
            return
        diag = self.win.diagnostico
        version = diag["version"] if diag else "V01"
        cancion = diag["archivo"] if diag else self.win.proyecto.nombre
        try:
            guardar_decision(self.win.proyecto, version, cancion, texto,
                             self.cb_feedback.currentText())
            self.txt_conclusion.clear()
            self.lbl_estado.setText("Decisión guardada en decisiones-y-feedback.md")
        except Exception as e:
            log.exception("Error guardando decisión")
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{e}")
