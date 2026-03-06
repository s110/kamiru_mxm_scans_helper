#!/usr/bin/env python3
"""
app.py — Interfaz gráfica de escritorio para el pipeline de Mixed Media.

Encapsula los dos scripts (generador_hojas.py y procesador_scans.py)
en una interfaz visual amigable para usuarios no técnicos en Windows.

Uso:
    uv run python app.py
"""

from __future__ import annotations

import io
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path
from datetime import datetime


def _get_resource_path(filename: str) -> Path:
    """Devuelve la ruta al recurso, compatible con PyInstaller --onefile."""
    # Cuando PyInstaller empaqueta, extrae a un directorio temporal _MEIPASS
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return base / filename


# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE COLORES Y ESTILOS (Tema Oscuro)
# ─────────────────────────────────────────────────────────────

BG_DARK = "#1e1e2e"        # Fondo principal
BG_CARD = "#2a2a3d"        # Fondo de tarjetas
BG_INPUT = "#363650"       # Fondo de campos de texto
FG_TEXT = "#e0e0e0"        # Texto principal
FG_DIM = "#8888aa"         # Texto secundario
FG_WHITE = "#ffffff"       # Texto brillante

ACCENT_ORANGE = "#e67e22"  # Paso 1
ACCENT_GREEN = "#27ae60"   # Paso 2
ACCENT_ORANGE_HOVER = "#f39c12"
ACCENT_GREEN_HOVER = "#2ecc71"

BG_LOG = "#141420"         # Fondo del registro
FG_LOG = "#b0b0cc"         # Texto del registro

FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_LABEL = ("Segoe UI", 11)
FONT_BUTTON = ("Segoe UI", 12, "bold")
FONT_INPUT = ("Segoe UI", 10)
FONT_LOG = ("Consolas", 9)
FONT_SLIDER = ("Segoe UI", 10)

WINDOW_WIDTH = 780
WINDOW_HEIGHT = 820

PAD_X = 18
PAD_Y = 8


# ─────────────────────────────────────────────────────────────
# CLASE Principal: APP
# ─────────────────────────────────────────────────────────────

class MixedMediaApp:
    """Interfaz gráfica principal del pipeline de Mixed Media."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Kamiru MXM — Mixed Media Scanner Helper")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(True, True)
        self.root.minsize(700, 750)

        # Centrar la ventana en pantalla
        self._center_window(WINDOW_WIDTH, WINDOW_HEIGHT)

        # Cargar ícono del gatito pixel
        icon_path = _get_resource_path("icon.ico")
        try:
            self.root.iconbitmap(str(icon_path))
        except Exception:
            pass  # Si no encuentra el ícono, continuar sin él

        # Variables de estado
        self.running = False

        # ── Scroll container ──
        self._build_ui()

    def _center_window(self, w: int, h: int):
        """Centra la ventana en la pantalla."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ─────────────────────────────────────────────────────────
    # CONSTRUCCIÓN DE LA INTERFAZ
    # ─────────────────────────────────────────────────────────

    def _build_ui(self):
        """Construye todos los elementos de la interfaz."""

        # Container con scroll
        main_frame = tk.Frame(self.root, bg=BG_DARK)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # ══════════════════════════════════════════════════════
        # PASO 1 — Generar Hojas de Impresión
        # ══════════════════════════════════════════════════════
        card1 = self._create_card(main_frame, "PASO 1 — Generar Hojas de Impresión", ACCENT_ORANGE)

        # Carpeta de Frames
        self.input_frames_var = tk.StringVar()
        self._create_folder_row(card1, "Carpeta de Frames:", self.input_frames_var, self._browse_input_frames)

        # Carpeta de Salida
        self.output_hojas_var = tk.StringVar()
        self._create_folder_row(card1, "Carpeta de Salida:", self.output_hojas_var, self._browse_output_hojas)

        # Botón Generar
        self.btn_generar = self._create_action_button(
            card1, "🖨️  Generar Hojas", ACCENT_ORANGE, ACCENT_ORANGE_HOVER, self._run_generar
        )

        # ══════════════════════════════════════════════════════
        # PASO 2 — Procesar Escaneos
        # ══════════════════════════════════════════════════════
        card2 = self._create_card(main_frame, "PASO 2 — Procesar Escaneos", ACCENT_GREEN)

        # Carpeta de Escaneos
        self.input_scans_var = tk.StringVar()
        self._create_folder_row(card2, "Carpeta de Escaneos:", self.input_scans_var, self._browse_input_scans)

        # Archivo layout.json
        self.layout_json_var = tk.StringVar()
        self._create_folder_row(card2, "Archivo layout.json:", self.layout_json_var, self._browse_layout_json, is_file=True)

        # Carpeta de Salida
        self.output_frames_var = tk.StringVar()
        self._create_folder_row(card2, "Carpeta de Salida:", self.output_frames_var, self._browse_output_frames)

        # Slider de Bleed
        self._create_bleed_slider(card2)

        # Botón Procesar
        self.btn_procesar = self._create_action_button(
            card2, "⚙️  Procesar Escaneos", ACCENT_GREEN, ACCENT_GREEN_HOVER, self._run_procesar
        )

        # ══════════════════════════════════════════════════════
        # REGISTRO DE ACTIVIDAD (Log)
        # ══════════════════════════════════════════════════════
        log_label = tk.Label(
            main_frame, text="Registro de Actividad", font=("Segoe UI", 10, "bold"),
            bg=BG_DARK, fg=FG_DIM, anchor="w"
        )
        log_label.pack(fill=tk.X, padx=4, pady=(12, 2))

        log_frame = tk.Frame(main_frame, bg=BG_LOG, bd=1, relief=tk.SOLID, highlightbackground="#333355", highlightthickness=1)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        self.log_text = tk.Text(
            log_frame, bg=BG_LOG, fg=FG_LOG, font=FONT_LOG,
            wrap=tk.WORD, bd=0, padx=10, pady=8,
            insertbackground=FG_LOG, state=tk.DISABLED,
            height=10
        )
        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview, bg=BG_LOG, troughcolor=BG_LOG)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Tags para colores en el log
        self.log_text.tag_configure("info", foreground=FG_LOG)
        self.log_text.tag_configure("success", foreground="#2ecc71")
        self.log_text.tag_configure("warning", foreground="#f39c12")
        self.log_text.tag_configure("error", foreground="#e74c3c")
        self.log_text.tag_configure("header", foreground=FG_WHITE, font=("Consolas", 10, "bold"))

        self._log("Bienvenida al pipeline de Mixed Media. Selecciona las carpetas y presiona el botón correspondiente.", "info")

    # ─────────────────────────────────────────────────────────
    # COMPONENTES REUTILIZABLES
    # ─────────────────────────────────────────────────────────

    def _create_card(self, parent: tk.Widget, title: str, accent_color: str) -> tk.Frame:
        """Crea una tarjeta visual con borde de acento a la izquierda."""
        outer = tk.Frame(parent, bg=BG_DARK)
        outer.pack(fill=tk.X, pady=(0, 10))

        # Borde de acento
        accent = tk.Frame(outer, bg=accent_color, width=5)
        accent.pack(side=tk.LEFT, fill=tk.Y)

        # Contenido de la tarjeta
        card = tk.Frame(outer, bg=BG_CARD, padx=PAD_X, pady=14)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Título
        lbl = tk.Label(card, text=title, font=FONT_TITLE, bg=BG_CARD, fg=FG_WHITE, anchor="w")
        lbl.pack(fill=tk.X, pady=(0, 10))

        return card

    def _create_folder_row(
        self,
        parent: tk.Widget,
        label_text: str,
        var: tk.StringVar,
        browse_cmd,
        is_file: bool = False
    ):
        """Crea una fila con etiqueta, campo de texto y botón Examinar."""
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill=tk.X, pady=(0, 8))

        lbl = tk.Label(row, text=label_text, font=FONT_LABEL, bg=BG_CARD, fg=FG_TEXT, width=22, anchor="w")
        lbl.pack(side=tk.LEFT)

        entry = tk.Entry(
            row, textvariable=var, font=FONT_INPUT,
            bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
            relief=tk.FLAT, bd=0, highlightthickness=1,
            highlightbackground="#444466", highlightcolor=ACCENT_ORANGE
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 8))

        btn = tk.Button(
            row, text="Examinar", font=("Segoe UI", 9),
            bg="#444466", fg=FG_TEXT, activebackground="#555577", activeforeground=FG_WHITE,
            relief=tk.FLAT, cursor="hand2", padx=12, pady=3,
            command=browse_cmd
        )
        btn.pack(side=tk.RIGHT)

    def _create_bleed_slider(self, parent: tk.Widget):
        """Crea el slider para controlar el porcentaje de bleed."""
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill=tk.X, pady=(4, 8))

        self.bleed_var = tk.DoubleVar(value=1.5)

        self.bleed_label = tk.Label(
            row, text="Bleed (sangrado): 1.5\%", font=FONT_SLIDER,
            bg=BG_CARD, fg=FG_TEXT, width=22, anchor="w"
        )
        self.bleed_label.pack(side=tk.LEFT)

        slider = tk.Scale(
            row, from_=0.0, to=3.0, resolution=0.1,
            orient=tk.HORIZONTAL, variable=self.bleed_var,
            bg=BG_CARD, fg=FG_TEXT, troughcolor=BG_INPUT,
            highlightbackground=BG_CARD, highlightthickness=0,
            activebackground=ACCENT_GREEN, sliderrelief=tk.FLAT,
            bd=0, font=FONT_SLIDER, showvalue=False,
            command=self._update_bleed_label
        )
        slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

    def _update_bleed_label(self, val):
        """Actualiza el texto del label del bleed."""
        self.bleed_label.configure(text=f"Bleed (sangrado): {float(val):.1f}%")

    def _create_action_button(
        self,
        parent: tk.Widget,
        text: str,
        color: str,
        hover_color: str,
        command
    ) -> tk.Button:
        """Crea un botón de acción grande y vistoso."""
        btn = tk.Button(
            parent, text=text, font=FONT_BUTTON,
            bg=color, fg=FG_WHITE, activebackground=hover_color, activeforeground=FG_WHITE,
            relief=tk.FLAT, cursor="hand2", pady=10,
            command=command
        )
        btn.pack(fill=tk.X, pady=(6, 0), ipady=2)

        # Hover effects
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover_color))
        btn.bind("<Leave>", lambda e: btn.configure(bg=color))

        return btn

    # ─────────────────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────────────────

    def _log(self, message: str, tag: str = "info"):
        """Agrega un mensaje al registro de actividad (thread-safe)."""
        def _insert():
            self.log_text.configure(state=tk.NORMAL)
            timestamp = datetime.now().strftime("%H:%M:%S")

            # Prefijo visual según tipo
            prefix = {
                "info": "   ",
                "success": " ✅",
                "warning": " ⚠️",
                "error": " ❌",
                "header": " ══",
            }.get(tag, "   ")

            self.log_text.insert(tk.END, f"[{timestamp}]{prefix} {message}\n", tag)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.root.after(0, _insert)

    # ─────────────────────────────────────────────────────────
    # DIÁLOGOS DE SELECCIÓN DE CARPETA/ARCHIVO
    # ─────────────────────────────────────────────────────────

    def _browse_input_frames(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta con tus fotogramas originales")
        if path:
            self.input_frames_var.set(path)

    def _browse_output_hojas(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta donde guardar las hojas de impresión")
        if path:
            self.output_hojas_var.set(path)

    def _browse_input_scans(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta con tus escaneos a 1200 PPI")
        if path:
            self.input_scans_var.set(path)

    def _browse_layout_json(self):
        path = filedialog.askopenfilename(
            title="Selecciona el archivo layout.json",
            filetypes=[("Archivo JSON", "*.json"), ("Todos los archivos", "*.*")]
        )
        if path:
            self.layout_json_var.set(path)

    def _browse_output_frames(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta donde guardar los fotogramas procesados")
        if path:
            self.output_frames_var.set(path)

    # ─────────────────────────────────────────────────────────
    # REDIRECCIONADOR DE STDOUT (captura prints de los scripts)
    # ─────────────────────────────────────────────────────────

    class _StdoutRedirector(io.StringIO):
        """Captura la salida estándar (prints) y la redirige al log de la GUI."""

        def __init__(self, log_func):
            super().__init__()
            self.log_func = log_func

        def write(self, text: str):
            text = text.strip()
            if text:
                # Determinar el tag según el contenido
                if "✅" in text or "✓" in text:
                    tag = "success"
                elif "⚠️" in text:
                    tag = "warning"
                elif "❌" in text:
                    tag = "error"
                elif "═" in text or "──" in text:
                    tag = "header"
                else:
                    tag = "info"
                self.log_func(text, tag)

        def flush(self):
            pass

    # ─────────────────────────────────────────────────────────
    # EJECUCIÓN DE LOS SCRIPTS
    # ─────────────────────────────────────────────────────────

    def _set_running(self, is_running: bool):
        """Deshabilita/habilita los botones mientras corre un proceso."""
        self.running = is_running
        state = tk.DISABLED if is_running else tk.NORMAL
        self.btn_generar.configure(state=state)
        self.btn_procesar.configure(state=state)

    def _run_generar(self):
        """Ejecuta el Script 1 (generador_hojas.py) en un hilo separado."""
        input_dir = self.input_frames_var.get().strip()
        output_dir = self.output_hojas_var.get().strip()

        if not input_dir:
            self._log("Por favor selecciona la carpeta de frames.", "warning")
            return
        if not output_dir:
            self._log("Por favor selecciona la carpeta de salida.", "warning")
            return
        if not Path(input_dir).is_dir():
            self._log(f"La carpeta de frames no existe: {input_dir}", "error")
            return

        self._set_running(True)
        self._log("Iniciando generación de hojas de impresión...", "header")

        def _worker():
            old_stdout = sys.stdout
            sys.stdout = self._StdoutRedirector(self._log)
            try:
                import generador_hojas
                generador_hojas.main(input_dir=input_dir, output_dir=output_dir)
                self._log("¡Hojas generadas exitosamente! Revisa tu carpeta de salida.", "success")

                # Auto-llenar el layout.json para el Paso 2
                layout_path = str(Path(output_dir) / "layout.json")
                self.root.after(0, lambda: self.layout_json_var.set(layout_path))

            except Exception as e:
                self._log(f"Error durante la generación: {e}", "error")
            finally:
                sys.stdout = old_stdout
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=_worker, daemon=True).start()

    def _run_procesar(self):
        """Ejecuta el Script 2 (procesador_scans.py) en un hilo separado."""
        input_dir = self.input_scans_var.get().strip()
        layout_file = self.layout_json_var.get().strip()
        output_dir = self.output_frames_var.get().strip()
        bleed = self.bleed_var.get() / 100.0  # Convertir de % a decimal

        if not input_dir:
            self._log("Por favor selecciona la carpeta de escaneos.", "warning")
            return
        if not layout_file:
            self._log("Por favor selecciona el archivo layout.json.", "warning")
            return
        if not output_dir:
            self._log("Por favor selecciona la carpeta de salida.", "warning")
            return
        if not Path(input_dir).is_dir():
            self._log(f"La carpeta de escaneos no existe: {input_dir}", "error")
            return
        if not Path(layout_file).is_file():
            self._log(f"El archivo layout.json no existe: {layout_file}", "error")
            return

        self._set_running(True)
        self._log(f"Iniciando procesamiento de escaneos (bleed: {bleed:.3f})...", "header")

        def _worker():
            old_stdout = sys.stdout
            sys.stdout = self._StdoutRedirector(self._log)
            try:
                import procesador_scans
                procesador_scans.main(
                    input_dir=input_dir,
                    layout_file=layout_file,
                    output_dir=output_dir,
                    bleed=bleed
                )
                self._log("¡Procesamiento completado! Revisa tu carpeta de salida.", "success")
            except Exception as e:
                self._log(f"Error durante el procesamiento: {e}", "error")
            finally:
                sys.stdout = old_stdout
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=_worker, daemon=True).start()


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def main():
    # En Windows, establecer el AppUserModelID para que la barra de tareas
    # muestre nuestro ícono personalizado en vez del ícono genérico de Python
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "kamiru.mxm.scanner.helper"
        )
    except (AttributeError, OSError):
        pass  # No estamos en Windows, no pasa nada

    root = tk.Tk()
    app = MixedMediaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
