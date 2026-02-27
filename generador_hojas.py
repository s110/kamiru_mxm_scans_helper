#!/usr/bin/env python3
"""
generador_hojas.py – SCRIPT 1: Generador de Hojas de Impresión (Pre-Impresión)

Pipeline automatizado que toma fotogramas digitales, los organiza en hojas A4
a 300 PPI con una grilla 2×2, añade marcadores ArUco y códigos QR, y exporta
un archivo layout.json puente para el procesador de escaneos (SCRIPT 2).

Flujo:
    1. Lee los fotogramas de la carpeta de entrada.
    2. Detecta el aspect ratio del primer frame para decidir orientación de hoja.
    3. Agrupa los frames de 4 en 4.
    4. Por cada grupo genera una hoja A4 a 300 PPI con:
       - Grilla 2×2 con los frames reducidos proporcionalmente.
       - QR + texto legible debajo de cada frame.
       - 4 marcadores ArUco (DICT_4X4_50) en las esquinas.
    5. Guarda cada hoja como TIFF a 300 PPI.
    6. Exporta layout.json con las coordenadas exactas de cada frame y QR.

Uso:
    uv run python generador_hojas.py
    uv run python generador_hojas.py --input ./mis_frames --output ./mis_hojas
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────
# CONSTANTES DE CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────

# Dimensiones A4 a 300 PPI (pixels)
A4_WIDTH_PX = 2480   # 210 mm a 300 PPI
A4_HEIGHT_PX = 3508  # 297 mm a 300 PPI
PPI = 300

# Marcadores ArUco
ARUCO_DICT_TYPE = cv2.aruco.DICT_4X4_50
ARUCO_SIZE_PX = 100        # Tamaño de cada marcador ArUco en pixels
ARUCO_MARGIN_PX = 40       # Margen desde el borde de la hoja hasta el ArUco
ARUCO_IDS = [0, 1, 2, 3]   # IDs para esquinas: TL, TR, BR, BL

# QR
QR_SIZE_PX = 120      # Tamaño del QR code en pixels
QR_MARGIN_PX = 10     # Margen entre frame y QR

# Grilla
GRID_COLS = 2
GRID_ROWS = 2
FRAMES_PER_SHEET = GRID_COLS * GRID_ROWS  # 4

# Margen del área segura (espacio reservado para ArUcos + padding)
SAFE_MARGIN_PX = ARUCO_SIZE_PX + ARUCO_MARGIN_PX + 20

# Extensiones de imagen soportadas
SUPPORTED_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".webp"}

# Espacio reservado debajo de cada frame para QR + texto
METADATA_HEIGHT_PX = QR_SIZE_PX + QR_MARGIN_PX


# ─────────────────────────────────────────────────────────────
# FUNCIONES DE DETECCIÓN Y CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────

def detectar_orientacion(frame_path: str | Path) -> str:
    """
    Detecta la orientación óptima de la hoja basándose en el aspect ratio
    del primer fotograma.

    Args:
        frame_path: Ruta al primer fotograma de la secuencia.

    Returns:
        'landscape' si el ancho del frame es mayor que el alto.
        'portrait' si el alto es mayor o igual al ancho.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        ValueError: Si no se puede abrir la imagen.
    """
    frame_path = Path(frame_path)
    if not frame_path.exists():
        raise FileNotFoundError(f"Frame no encontrado: {frame_path}")

    with Image.open(frame_path) as img:
        ancho, alto = img.size

    if ancho > alto:
        return "landscape"
    else:
        return "portrait"


def obtener_dimensiones_lienzo(orientacion: str) -> tuple[int, int]:
    """
    Devuelve las dimensiones del lienzo A4 a 300 PPI según la orientación.

    Args:
        orientacion: 'landscape' o 'portrait'.

    Returns:
        Tupla (ancho_px, alto_px) del lienzo.
    """
    if orientacion == "landscape":
        return A4_HEIGHT_PX, A4_WIDTH_PX  # 3508 x 2480
    else:
        return A4_WIDTH_PX, A4_HEIGHT_PX  # 2480 x 3508


# ─────────────────────────────────────────────────────────────
# FUNCIONES DE GENERACIÓN DE LIENZO Y GRILLA
# ─────────────────────────────────────────────────────────────

def crear_lienzo(ancho: int, alto: int) -> Image.Image:
    """
    Crea un lienzo blanco (RGB) con las dimensiones especificadas.

    Args:
        ancho: Ancho en pixels.
        alto: Alto en pixels.

    Returns:
        Imagen PIL en modo RGB, fondo blanco.
    """
    return Image.new("RGB", (ancho, alto), color=(255, 255, 255))


def calcular_grilla_2x2(
    canvas_w: int,
    canvas_h: int,
) -> list[dict[str, int]]:
    """
    Calcula las posiciones de los 4 cuadrantes de la grilla 2×2 dentro
    del área segura del lienzo (descontando márgenes para ArUcos).

    Cada cuadrante reserva espacio inferior para la metadata (QR + texto).

    Args:
        canvas_w: Ancho total del lienzo en pixels.
        canvas_h: Alto total del lienzo en pixels.

    Returns:
        Lista de 4 diccionarios, cada uno con:
            - 'x': coordenada X de la esquina superior-izquierda del cuadrante.
            - 'y': coordenada Y de la esquina superior-izquierda del cuadrante.
            - 'w': ancho disponible para el frame en el cuadrante.
            - 'h': alto disponible para el frame (descontando metadata).
            - 'meta_y': coordenada Y donde empieza la zona de metadata.
    """
    # Área segura (interior a los márgenes de ArUco)
    area_x = SAFE_MARGIN_PX
    area_y = SAFE_MARGIN_PX
    area_w = canvas_w - 2 * SAFE_MARGIN_PX
    area_h = canvas_h - 2 * SAFE_MARGIN_PX

    # Cada celda
    cell_w = area_w // GRID_COLS
    cell_h = area_h // GRID_ROWS

    cuadrantes = []
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            x = area_x + col * cell_w
            y = area_y + row * cell_h
            # El espacio para el frame se reduce para dejar lugar al QR + texto
            frame_h = cell_h - METADATA_HEIGHT_PX
            cuadrantes.append({
                "x": x,
                "y": y,
                "w": cell_w,
                "h": frame_h,
                "meta_y": y + frame_h,
            })

    return cuadrantes


# ─────────────────────────────────────────────────────────────
# FUNCIONES DE COLOCACIÓN DE FRAMES
# ─────────────────────────────────────────────────────────────

def redimensionar_frame(
    frame: Image.Image,
    max_w: int,
    max_h: int,
) -> Image.Image:
    """
    Reduce proporcionalmente un fotograma para que quepa dentro de un
    cuadrante de dimensiones max_w × max_h, manteniendo el aspect ratio.

    Usa el filtro LANCZOS (antialiasing de alta calidad) para el downscale.

    Args:
        frame: Imagen PIL del fotograma original.
        max_w: Ancho máximo disponible en el cuadrante.
        max_h: Alto máximo disponible en el cuadrante.

    Returns:
        Imagen PIL redimensionada.
    """
    orig_w, orig_h = frame.size
    ratio = min(max_w / orig_w, max_h / orig_h)
    new_w = int(orig_w * ratio)
    new_h = int(orig_h * ratio)
    return frame.resize((new_w, new_h), Image.LANCZOS)


def colocar_frames(
    lienzo: Image.Image,
    cuadrantes: list[dict[str, int]],
    frame_paths: list[Path],
) -> dict[str, list[int]]:
    """
    Coloca los fotogramas en el lienzo, centrados dentro de sus cuadrantes.

    Args:
        lienzo: Imagen PIL del lienzo de la hoja.
        cuadrantes: Lista de cuadrantes calculados por calcular_grilla_2x2().
        frame_paths: Lista de rutas a los fotogramas (máx. 4).

    Returns:
        Diccionario { nombre_archivo: [x1, y1, x2, y2] } con las coordenadas
        exactas donde se pegó cada frame en el lienzo.
    """
    posiciones: dict[str, list[int]] = {}

    for i, frame_path in enumerate(frame_paths):
        if i >= len(cuadrantes):
            break

        cuadrante = cuadrantes[i]
        with Image.open(frame_path) as frame_original:
            # Convertir a RGB si es necesario (por si el TIFF tiene canal alpha)
            if frame_original.mode != "RGB":
                frame_original = frame_original.convert("RGB")

            frame_resized = redimensionar_frame(
                frame_original,
                cuadrante["w"],
                cuadrante["h"],
            )

        # Centrar el frame dentro del cuadrante
        fw, fh = frame_resized.size
        offset_x = cuadrante["x"] + (cuadrante["w"] - fw) // 2
        offset_y = cuadrante["y"] + (cuadrante["h"] - fh) // 2

        lienzo.paste(frame_resized, (offset_x, offset_y))

        nombre = frame_path.stem  # Nombre sin extensión
        posiciones[nombre] = [offset_x, offset_y, offset_x + fw, offset_y + fh]

    return posiciones


# ─────────────────────────────────────────────────────────────
# FUNCIONES DE METADATA VISUAL (QR + TEXTO)
# ─────────────────────────────────────────────────────────────

def generar_qr(texto: str, tamaño: int = QR_SIZE_PX) -> Image.Image:
    """
    Genera una imagen de código QR que codifica el texto dado.

    Args:
        texto: Contenido a codificar (nombre del archivo original).
        tamaño: Tamaño en pixels del QR resultante.

    Returns:
        Imagen PIL del QR code en modo RGB.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(texto)
    qr.make(fit=True)
    img_qr = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img_qr.resize((tamaño, tamaño), Image.LANCZOS)


def colocar_qrs(
    lienzo: Image.Image,
    cuadrantes: list[dict[str, int]],
    frame_paths: list[Path],
    posiciones_frames: dict[str, list[int]],
) -> dict[str, list[int]]:
    """
    Genera y coloca un QR + texto legible debajo de cada fotograma.

    El QR codifica el nombre original del archivo para identificación
    unívoca tras el escaneo.

    Args:
        lienzo: Imagen PIL del lienzo de la hoja.
        cuadrantes: Lista de cuadrantes.
        frame_paths: Lista de rutas a los fotogramas.
        posiciones_frames: Dict con posiciones de frames ya colocados.

    Returns:
        Diccionario { nombre_archivo: [x1, y1, x2, y2] } con coordenadas
        de cada QR en el lienzo.
    """
    posiciones_qr: dict[str, list[int]] = {}
    draw = ImageDraw.Draw(lienzo)

    # Intentar usar una fuente con tamaño razonable para el texto
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except (OSError, IOError):
        font = ImageFont.load_default()

    for i, frame_path in enumerate(frame_paths):
        if i >= len(cuadrantes):
            break

        nombre = frame_path.stem
        cuadrante = cuadrantes[i]

        # Generar el QR
        qr_img = generar_qr(nombre)

        # Posicionar QR debajo del frame, centrado horizontalmente en el cuadrante
        qr_x = cuadrante["x"] + (cuadrante["w"] - QR_SIZE_PX) // 2 - 60
        qr_y = cuadrante["meta_y"] + QR_MARGIN_PX

        lienzo.paste(qr_img, (qr_x, qr_y))
        posiciones_qr[nombre] = [qr_x, qr_y, qr_x + QR_SIZE_PX, qr_y + QR_SIZE_PX]

        # Texto legible al lado derecho del QR
        text_x = qr_x + QR_SIZE_PX + 10
        text_y = qr_y + QR_SIZE_PX // 2 - 8  # Centrado vertical aprox.
        draw.text((text_x, text_y), nombre, fill="black", font=font)

    return posiciones_qr


# ─────────────────────────────────────────────────────────────
# FUNCIONES DE MARCADORES ARUCO
# ─────────────────────────────────────────────────────────────

def generar_aruco(marker_id: int, tamaño: int = ARUCO_SIZE_PX) -> Image.Image:
    """
    Genera un marcador ArUco del diccionario 4×4_50.

    Args:
        marker_id: ID del marcador (0-49).
        tamaño: Tamaño en pixels del marcador resultante.

    Returns:
        Imagen PIL del marcador ArUco en modo RGB.
    """
    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
    marker_img = cv2.aruco.generateImageMarker(aruco_dict, marker_id, tamaño)
    # OpenCV genera en escala de grises, convertir a RGB para PIL
    marker_rgb = cv2.cvtColor(marker_img, cv2.COLOR_GRAY2RGB)
    return Image.fromarray(marker_rgb)


def colocar_arucos(lienzo: Image.Image, canvas_w: int, canvas_h: int) -> None:
    """
    Coloca 4 marcadores ArUco en las esquinas extremas del lienzo A4.

    Distribución:
        - ID 0: Esquina superior-izquierda (TL)
        - ID 1: Esquina superior-derecha (TR)
        - ID 2: Esquina inferior-derecha (BR)
        - ID 3: Esquina inferior-izquierda (BL)

    Args:
        lienzo: Imagen PIL del lienzo donde se pegarán los marcadores.
        canvas_w: Ancho del lienzo en pixels.
        canvas_h: Alto del lienzo en pixels.
    """
    # Posiciones de las 4 esquinas (x, y) para cada marcador
    posiciones = {
        0: (ARUCO_MARGIN_PX, ARUCO_MARGIN_PX),                                          # TL
        1: (canvas_w - ARUCO_MARGIN_PX - ARUCO_SIZE_PX, ARUCO_MARGIN_PX),               # TR
        2: (canvas_w - ARUCO_MARGIN_PX - ARUCO_SIZE_PX, canvas_h - ARUCO_MARGIN_PX - ARUCO_SIZE_PX),  # BR
        3: (ARUCO_MARGIN_PX, canvas_h - ARUCO_MARGIN_PX - ARUCO_SIZE_PX),               # BL
    }

    for marker_id, (x, y) in posiciones.items():
        aruco_img = generar_aruco(marker_id)
        lienzo.paste(aruco_img, (x, y))


# ─────────────────────────────────────────────────────────────
# FUNCIONES DE EXPORTACIÓN (JSON + TIFF)
# ─────────────────────────────────────────────────────────────

def exportar_layout_json(data: dict[str, Any], output_path: str | Path) -> None:
    """
    Exporta el archivo puente layout.json con toda la información de
    coordenadas necesaria para el SCRIPT 2 (procesador_scans.py).

    Estructura del JSON:
        {
            "lienzo": {
                "ancho_px": int,
                "alto_px": int,
                "ppi": int,
                "orientacion": str
            },
            "hojas": [
                {
                    "archivo_hoja": str,
                    "frames": {
                        "nombre_frame": {
                            "bbox": [x1, y1, x2, y2],
                            "archivo_original": str
                        }
                    },
                    "qrs": {
                        "nombre_frame": {
                            "bbox": [x1, y1, x2, y2]
                        }
                    }
                }
            ]
        }

    Args:
        data: Diccionario con toda la información del layout.
        output_path: Ruta donde guardar el JSON.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  ✅ layout.json exportado en: {output_path}")


def guardar_hoja_tiff(
    lienzo: Image.Image,
    output_path: str | Path,
    ppi: int = PPI,
) -> None:
    """
    Guarda el lienzo como archivo TIFF con la metadata de resolución PPI.

    Args:
        lienzo: Imagen PIL de la hoja completa.
        output_path: Ruta de salida para el TIFF.
        ppi: Resolución en Pixels Per Inch (por defecto 300).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Guardar con metadata de resolución DPI
    lienzo.save(
        str(output_path),
        format="TIFF",
        dpi=(ppi, ppi),
        compression="tiff_lzw",  # Compresión sin pérdida
    )
    print(f"  📄 Hoja guardada: {output_path}")


# ─────────────────────────────────────────────────────────────
# FUNCIONES DE UTILIDAD
# ─────────────────────────────────────────────────────────────

def obtener_frames(input_dir: str | Path) -> list[Path]:
    """
    Lista todos los archivos de imagen soportados en el directorio de entrada,
    ordenados alfabéticamente.

    Args:
        input_dir: Ruta al directorio con los fotogramas.

    Returns:
        Lista de objetos Path, ordenada por nombre.

    Raises:
        FileNotFoundError: Si el directorio no existe.
        ValueError: Si no se encuentran imágenes soportadas.
    """
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Directorio de entrada no encontrado: {input_dir}")

    frames = sorted([
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ])

    if not frames:
        raise ValueError(
            f"No se encontraron imágenes soportadas en: {input_dir}\n"
            f"Extensiones válidas: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    return frames


def agrupar_frames(
    frames: list[Path],
    grupo_size: int = FRAMES_PER_SHEET,
) -> list[list[Path]]:
    """
    Agrupa los fotogramas en lotes de 4 (uno por hoja).
    El último grupo puede tener menos de 4 frames.

    Args:
        frames: Lista completa de rutas a fotogramas.
        grupo_size: Cantidad de frames por grupo (por defecto 4).

    Returns:
        Lista de listas de paths agrupados.
    """
    return [
        frames[i : i + grupo_size]
        for i in range(0, len(frames), grupo_size)
    ]


# ─────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────

def main(input_dir: str = "./frames", output_dir: str = "./output") -> None:
    """
    Función principal que orquesta todo el pipeline de generación de hojas.

    Flujo:
        1. Listar y agrupar frames.
        2. Detectar orientación del lienzo según el aspect ratio.
        3. Por cada grupo de 4 frames:
           a. Crear lienzo blanco.
           b. Colocar marcadores ArUco.
           c. Calcular grilla 2×2.
           d. Colocar frames redimensionados.
           e. Colocar QRs + texto.
           f. Guardar hoja como TIFF.
        4. Exportar layout.json.

    Args:
        input_dir: Directorio con los fotogramas de entrada.
        output_dir: Directorio donde se guardarán las hojas y el JSON.
    """
    print("=" * 60)
    print("  GENERADOR DE HOJAS DE IMPRESIÓN — SCRIPT 1")
    print("=" * 60)
    print()

    # ── 1. Obtener y agrupar frames ──────────────────────────
    frames = obtener_frames(input_dir)
    grupos = agrupar_frames(frames)
    total_hojas = len(grupos)

    print(f"📂 Directorio de entrada: {Path(input_dir).resolve()}")
    print(f"📂 Directorio de salida:  {Path(output_dir).resolve()}")
    print(f"🖼️  Frames encontrados:    {len(frames)}")
    print(f"📄 Hojas a generar:       {total_hojas}")
    print()

    # ── 2. Detectar orientación según el primer frame ────────
    orientacion = detectar_orientacion(frames[0])
    canvas_w, canvas_h = obtener_dimensiones_lienzo(orientacion)

    print(f"📐 Aspect ratio detectado → Hoja en modo: {orientacion.upper()}")
    print(f"   Lienzo: {canvas_w} × {canvas_h} px a {PPI} PPI")
    print()

    # ── 3. Preparar datos para el JSON ───────────────────────
    layout_data: dict[str, Any] = {
        "lienzo": {
            "ancho_px": canvas_w,
            "alto_px": canvas_h,
            "ppi": PPI,
            "orientacion": orientacion,
        },
        "hojas": [],
    }

    # ── 4. Generar cada hoja ─────────────────────────────────
    for idx_hoja, grupo in enumerate(grupos):
        hoja_num = idx_hoja + 1
        print(f"── Generando hoja {hoja_num}/{total_hojas} "
              f"({len(grupo)} frames) ──")

        # a. Crear lienzo blanco
        lienzo = crear_lienzo(canvas_w, canvas_h)

        # b. Colocar ArUcos en las 4 esquinas
        colocar_arucos(lienzo, canvas_w, canvas_h)

        # c. Calcular cuadrantes de la grilla
        cuadrantes = calcular_grilla_2x2(canvas_w, canvas_h)

        # d. Colocar frames redimensionados
        posiciones_frames = colocar_frames(lienzo, cuadrantes, grupo)

        # e. Colocar QRs + texto legible
        posiciones_qrs = colocar_qrs(lienzo, cuadrantes, grupo, posiciones_frames)

        # f. Guardar hoja como TIFF
        nombre_hoja = f"hoja_{hoja_num:03d}.tiff"
        ruta_hoja = Path(output_dir) / nombre_hoja
        guardar_hoja_tiff(lienzo, ruta_hoja)

        # g. Registrar datos para el JSON
        hoja_data: dict[str, Any] = {
            "archivo_hoja": nombre_hoja,
            "frames": {},
            "qrs": {},
        }

        for frame_path in grupo:
            nombre = frame_path.stem
            if nombre in posiciones_frames:
                hoja_data["frames"][nombre] = {
                    "bbox": posiciones_frames[nombre],
                    "archivo_original": frame_path.name,
                }
            if nombre in posiciones_qrs:
                hoja_data["qrs"][nombre] = {
                    "bbox": posiciones_qrs[nombre],
                }

        layout_data["hojas"].append(hoja_data)

        # Liberar memoria
        del lienzo

    # ── 5. Exportar layout.json ──────────────────────────────
    json_path = Path(output_dir) / "layout.json"
    exportar_layout_json(layout_data, json_path)

    print()
    print("=" * 60)
    print(f"  ✅ PROCESO COMPLETADO: {total_hojas} hojas generadas.")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Genera hojas de impresión A4 con grilla 2×2 de fotogramas, "
                    "marcadores ArUco y códigos QR.",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="./frames",
        help="Directorio con los fotogramas de entrada (default: ./frames)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./output",
        help="Directorio de salida para hojas y layout.json (default: ./output)",
    )
    args = parser.parse_args()

    try:
        main(input_dir=args.input, output_dir=args.output)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Proceso cancelado por el usuario.", file=sys.stderr)
        sys.exit(130)
