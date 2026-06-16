#!/usr/bin/env python3
"""
procesador_scans.py – SCRIPT 2: Procesador de Escaneos Masivos (Post-Escaneo)

Pipeline automatizado que procesa escaneos físicos de ultra alta resolución (1200 PPI),
alineándolos, extrayendo las piezas de arte individuales, y devolviéndolas a su
resolución digital original (4K).

Flujo:
    1. Lee el archivo `layout.json` generado en la fase de pre-impresión.
    2. Itera sobre los archivos TIFF de escaneo en la carpeta de entrada.
    3. Genera un "proxy" (downscale temporal) de la imagen gigante en RAM
       para detectar los 4 marcadores ArUco rápidamente sin saturar la memoria.
    4. Con las coordenadas escaladas, aplica una transformación de perspectiva
       (warpPerspective) al TIFF original de 1200 PPI, enderezando matemáticamente
       el papel y forzando dimensiones precisas.
    5. Recorta los frames basándose en las coordenadas matemáticas del JSON (x4),
       aplicando un margen de seguridad (bleed) para evitar bordes blancos.
    6. Lee los códigos QR del escaneo para identificar de qué frame se trata.
    7. Escala de vuelta (downscale limpio) el frame pintado a su resolución digital
       original (ej. 3840×2160) y lo guarda.
    8. Libera explícitamente la memoria con `gc.collect()` para procesar la siguiente hoja.

Uso:
    uv run python procesador_scans.py --input ./scans --layout output/layout.json --output ./frames_procesados
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pyzbar.pyzbar import decode

# ─────────────────────────────────────────────────────────────
# CONSTANTES DE CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────

# Factor de escala (1200 PPI dictados por el diseño contra 300 del json)
SCALE_FACTOR = 4

# Marcadores ArUco
ARUCO_DICT_TYPE = cv2.aruco.DICT_4X4_50
ARUCO_IDS_ESPERADOS = [0, 1, 2, 3]  # TL, TR, BR, BL

# Extensiones de imagen soportadas
SUPPORTED_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

# ─────────────────────────────────────────────────────────────
# E/S ROBUSTA DE IMÁGENES (RUTAS UNICODE EN WINDOWS)
# ─────────────────────────────────────────────────────────────
#
# BUG CLÁSICO DE OPENCV EN WINDOWS:
#   cv2.imread() y cv2.imwrite() NO soportan rutas con caracteres no-ASCII
#   (tildes, ñ, etc.) porque internamente usan la codepage ANSI del sistema en
#   lugar de UTF-8. Una ruta como 'H:\\2da edición TALLER MXM\\Scans 1\\hoja.tif'
#   hace que imread() devuelva None de forma SILENCIOSA aunque el archivo exista
#   y Python (pathlib) sí lo haya encontrado. Ese era el origen del error
#   "No se pudo leer la imagen: ...".
#
# SOLUCIÓN:
#   Abrir/escribir el archivo con Python (que sí maneja Unicode nativamente) y
#   que OpenCV sólo (de)codifique los bytes en memoria con imdecode/imencode.


def leer_imagen_robusta(path: Path, flags: int = cv2.IMREAD_UNCHANGED) -> np.ndarray | None:
    """
    Lee una imagen de disco de forma robusta frente a rutas con caracteres
    no-ASCII (tildes, ñ, espacios especiales) en Windows.

    Estrategia en cascada:
      1. cv2.imread directo: rápido y de bajo consumo de memoria; funciona si la
         ruta es 100 % ASCII.
      2. np.fromfile + cv2.imdecode: Python lee los bytes (soporte Unicode nativo)
         y OpenCV sólo los decodifica en RAM. Resuelve el bug de la codepage.
      3. Pillow: último recurso para variantes de TIFF que el libtiff embebido de
         OpenCV no decodifica; también soporta rutas Unicode nativamente.

    Returns:
        Matriz numpy (BGR/BGRA, conservando profundidad de bits) o None si ninguna
        estrategia logra leer el archivo.
    """
    path = Path(path)
    ruta_str = str(path)

    # ── Estrategia 1: ruta directa (rápida, bajo consumo de memoria) ──
    # Sólo se intenta si la ruta es ASCII; con tildes/ñ en Windows imread()
    # falla SIEMPRE y además ensucia la consola con un warning, así que la
    # saltamos y vamos directo a la lectura por bytes (Unicode-safe).
    if ruta_str.isascii():
        img = cv2.imread(ruta_str, flags)
        if img is not None:
            return img

    # ── Estrategia 2: bytes con Python + decodificación en RAM (Unicode-safe) ──
    try:
        buffer = np.fromfile(ruta_str, dtype=np.uint8)
        if buffer.size > 0:
            img = cv2.imdecode(buffer, flags)
            if img is not None:
                return img
    except (OSError, ValueError):
        pass

    # ── Estrategia 3: Pillow (TIFFs exóticos / fallback) ──
    try:
        from PIL import Image

        with Image.open(path) as pil_img:
            arr = np.array(pil_img)
        # Pillow entrega RGB(A); el resto del pipeline asume orden BGR de OpenCV.
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
        elif arr.ndim == 3 and arr.shape[2] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return arr
    except Exception:
        return None


def escribir_imagen_robusta(path: Path, img: np.ndarray, params: list[int] | None = None) -> bool:
    """
    Guarda una imagen en disco soportando rutas Unicode en Windows.

    cv2.imwrite() padece el mismo bug de codepage que imread: si la carpeta de
    salida tiene tildes/ñ falla SILENCIOSAMENTE (devuelve False) y no escribe
    nada. Aquí codificamos en memoria y volcamos los bytes con Python.

    Returns:
        True si el archivo se escribió correctamente, False en caso contrario.
    """
    path = Path(path)
    ruta_str = str(path)
    params = params or []

    # ── Estrategia 1: imwrite directo (rápido) — sólo si la ruta es ASCII ──
    if ruta_str.isascii():
        try:
            if cv2.imwrite(ruta_str, img, params):
                return True
        except cv2.error:
            pass

    # ── Estrategia 2: codificar en RAM + escribir bytes con Python (Unicode-safe) ──
    ext = path.suffix if path.suffix else ".tif"
    try:
        ok, buffer = cv2.imencode(ext, img, params)
        if not ok:
            return False
        buffer.tofile(ruta_str)
        return True
    except (cv2.error, OSError):
        return False


# ─────────────────────────────────────────────────────────────
# FUNCIONES DE DETECCIÓN RÁPIDA (PROXY)
# ─────────────────────────────────────────────────────────────

def obtener_coordenadas_aruco(img_path: Path) -> dict[int, tuple[float, float]] | None:
    """
    Estrategia Proxy: Evita buscar ArUcos en la imagen completa (1200 PPI)
    que colapsaría la de memoria la librería OpenCV o tardaría minutos.

    Lee el archivo, hace un downscale drástico (escala de 300 PPI), detecta,
    y luego multiplica el resultado de vuelta al tamaño original.

    Args:
        img_path: Ruta al archivo escaneado.

    Returns:
        Un diccionario mapeando el ID del ArUco a su tupla (x, y) del centro,
        ya re-escalado al tamaño original (1200 PPI). Retorna None si no
        encuentra los 4.
    """
    # IMREAD_UNCHANGED preserva la profundidad de bits original (16-bit si el escáner lo genera)
    # Esto es CRÍTICO: sin esto, OpenCV trunca 16-bit a 8-bit y se pierde rango dinámico (causa contraste elevado)
    # leer_imagen_robusta() evita el bug de OpenCV con rutas Unicode (tildes/ñ) en Windows.
    img_bgr = leer_imagen_robusta(img_path, cv2.IMREAD_UNCHANGED)
    if img_bgr is None:
        raise ValueError(
            f"No se pudo leer la imagen: {img_path}. "
            f"Verifica que el archivo no esté corrupto, abierto en otro programa, "
            f"ni protegido contra lectura."
        )

    # Si la imagen tiene canal alpha (4 canales), descartarlo
    if len(img_bgr.shape) == 3 and img_bgr.shape[2] == 4:
        img_bgr = img_bgr[:, :, :3]

    # Para el proxy de ArUco necesitamos 8-bit. Convertir solo la copia proxy.
    factor_proxy = 1.0 / SCALE_FACTOR
    proxy = cv2.resize(img_bgr, (0, 0), fx=factor_proxy, fy=factor_proxy, interpolation=cv2.INTER_AREA)

    # Si es 16-bit, normalizar el proxy a 8-bit solo para la detección de ArUco
    if proxy.dtype == np.uint16:
        proxy_8bit = (proxy / 256).astype(np.uint8)
    else:
        proxy_8bit = proxy

    # Convertir a grises para ArUco
    gray = cv2.cvtColor(proxy_8bit, cv2.COLOR_BGR2GRAY)

    # Configurar ArUco
    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
    parameters = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, parameters)

    corners, ids, rejected = detector.detectMarkers(gray)

    # Liberar memoria de imágenes intermedias que ya no usamos
    del proxy
    del gray

    if ids is None or len(ids) < 4:
        # Faltan marcadores en la hoja, falló el escaneo parcial.
        del img_bgr
        return None

    # Queremos al menos los 4 IDs requeridos (0,1,2,3)
    ids = ids.flatten()
    centros_x4 = {}

    for i, aruco_id in enumerate(ids):
        if aruco_id in ARUCO_IDS_ESPERADOS:
            # Calcular el centro exacto del marcador en la escala proxy
            c = corners[i][0]
            centro_x = int(np.mean(c[:, 0]))
            centro_y = int(np.mean(c[:, 1]))

            # Re-escalar al tamaño bruto del escaneo a 1200 PPI
            centros_x4[aruco_id] = (centro_x * SCALE_FACTOR, centro_y * SCALE_FACTOR)

    if len(centros_x4) < 4:
        del img_bgr
        return None

    return centros_x4, img_bgr  # Retornamos el tensor cargado si todo fue exitoso para warp

# ─────────────────────────────────────────────────────────────
# FUNCIONES DE ALINEACIÓN
# ─────────────────────────────────────────────────────────────

def alinear_escaneo(
    img_gigante: np.ndarray,
    centros_reales: dict[int, tuple[float, float]],
    ancho_lienzo_base: int,
    alto_lienzo_base: int,
    margen_aruco_base: int,
    tamanio_aruco_base: int
) -> np.ndarray:
    """
    Aplica una transformación matemática iterativa de perspectiva
    (Homografía) para "planchar" la hoja. Fuerzas sus proporciones
    y borra las rotaciones o distorsiones generadas por la bandeja del escáner.

    Args:
        img_gigante: Matriz BGR de la hoja recién escaneada a resolución full.
        centros_reales: Coordenadas detectadas de los 4 ArUcos (escala grande).
        ancho_lienzo_base: Ancho en la info del JSON.
        alto_lienzo_base: Alto en la info del JSON.
        margen_aruco_base: Constante usada al generarlos.
        tamanio_aruco_base: Constante usada al generarlos.

    Returns:
        Matriz numpy transformada geométricamente y cortada exacta al tamaño
        teórico máximo del Canvas a 1200 PPI.
    """
    # Escalar medidas conceptuales del JSON
    canvas_w = int(ancho_lienzo_base * SCALE_FACTOR)
    canvas_h = int(alto_lienzo_base * SCALE_FACTOR)
    margen = int(margen_aruco_base * SCALE_FACTOR)
    mitad_aruco = int((tamanio_aruco_base * SCALE_FACTOR) / 2)


    # Coordenadas perfectas TEÓRICAS donde DEBERÍAN ESTAR en un archivo 1200 PPI inmaculado
    dist_marco = margen + mitad_aruco

    dst_puntos = np.array([
        [dist_marco, dist_marco],                                       # TL (ID 0)
        [canvas_w - dist_marco, dist_marco],                            # TR (ID 1)
        [canvas_w - dist_marco, canvas_h - dist_marco],                 # BR (ID 2)
        [dist_marco, canvas_h - dist_marco]                             # BL (ID 3)
    ], dtype="float32")

    # Coordenadas donde REALMENTE ESTABAN en el material físico escaneado
    src_puntos = np.array([
        centros_reales[0],  # TL
        centros_reales[1],  # TR
        centros_reales[2],  # BR
        centros_reales[3]   # BL
    ], dtype="float32")

    # Matriz y transformación
    M = cv2.getPerspectiveTransform(src_puntos, dst_puntos)

    # Deforma la imagen en bruto al tamaño perfecto ideal de 1200 PPI
    # INTER_LANCZOS4 = máxima calidad de interpolación (8x8 kernel)
    warp = cv2.warpPerspective(img_gigante, M, (canvas_w, canvas_h), flags=cv2.INTER_LANCZOS4)

    return warp

# ─────────────────────────────────────────────────────────────
# EXTRACCIÓN Y LECTURA
# ─────────────────────────────────────────────────────────────

def aplicar_bleed(x1: int, y1: int, x2: int, y2: int, factor_porcentaje: float) -> tuple[int,int,int,int]:
    """
    Quita un pequeño porcentaje perimetral al cuadro límite, a modo
    de sangría/bleed, para que el recorte caiga adentro del "dibujo"
    y se coma menos de los bordes blancos de papel puro fuera de la celda de trabajo original.
    """
    w = x2 - x1
    h = y2 - y1

    recorte_x = int(w * factor_porcentaje)
    recorte_y = int(h * factor_porcentaje)

    return x1 + recorte_x, y1 + recorte_y, x2 - recorte_x, y2 - recorte_y

def leer_qr(recorte_qr_img: np.ndarray) -> str | None:
    """Extrae la información string del código QR, sino devuelve None"""
    # pyzbar solo acepta 8-bit; si el scan es 16-bit, convertir
    if recorte_qr_img.dtype == np.uint16:
        recorte_qr_img = (recorte_qr_img / 256).astype(np.uint8)

    # Intentar como bgr
    codigos = decode(recorte_qr_img)
    if not codigos:
        # Intentar forzando escala de grises y threshold
        gray = cv2.cvtColor(recorte_qr_img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        codigos = decode(thresh)

    if codigos:
        # Retorna el decodificado del primero
        return codigos[0].data.decode("utf-8")
    return None

# ─────────────────────────────────────────────────────────────
# RESTAURACIÓN Y EXPORTACIÓN
# ─────────────────────────────────────────────────────────────

def guardar_resultado(recorte_frame: np.ndarray, path_original: str, dir_salida: Path):
    """
    Guarda el archivo recortado a su resolución total sin escalar hacia abajo.
    Se guarda como TIFF sin compresión para máxima calidad.
    """
    path_obj = Path(path_original)
    nombre = f"{path_obj.stem}_procesado.tif"
    ruta_final = dir_salida / nombre

    # IMWRITE_TIFF_COMPRESSION=1 = sin compresión = 0 pérdida de datos
    # escribir_imagen_robusta() evita el bug de OpenCV con rutas Unicode (tildes/ñ) en Windows.
    ok = escribir_imagen_robusta(ruta_final, recorte_frame, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
    h, w = recorte_frame.shape[:2]
    if ok:
        print(f"      ✅ Frame procesado: {nombre} ({w}x{h})")
    else:
        print(f"      ❌ [ERROR] No se pudo guardar el frame: {ruta_final}")

# ─────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL EN BUCLE MAIN
# ─────────────────────────────────────────────────────────────

def main(
    input_dir: str = "./scans",
    layout_file: str = "output/layout.json",
    output_dir: str = "./frames_procesados",
    bleed: float = 0.015
):
    print("=" * 60)
    print("  PROCESADOR DE ESCANEOS FÍSICOS — SCRIPT 2")
    print("=" * 60)
    print()

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    layout_path = Path(layout_file)

    if not input_path.exists():
        print(f"❌ Error: Directorio de escaneos no encontrado: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not layout_path.exists():
        print(f"❌ Error: Archivo de metadata JSON no encontrado: {layout_path}", file=sys.stderr)
        sys.exit(1)

    output_path.mkdir(parents=True, exist_ok=True)

    # ── 1. Cargar metadatos matriz ──
    with open(layout_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    canvas_w = data["lienzo"]["ancho_px"]
    canvas_h = data["lienzo"]["alto_px"]
    hojas_esperadas = {h["archivo_hoja"]: h for h in data["hojas"]}

    # Cargar scans
    scans = sorted([p for p in input_path.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS])
    print(f"📄 Scans encontrados para procesar:       {len(scans)}")
    print(f"📐 Tamaño de lienzo base (del pre-print): {canvas_w}x{canvas_h}")
    print()

    # ── 2. Procesar hoja por hoja de escáner en bucle ──
    for index, current_scan in enumerate(scans, start=1):
        print(f"── Procesando {current_scan.name} ({index}/{len(scans)}) ──")
        
        # OBTENCION Y MATCHEO ARUCO
        try:
            resultado = obtener_coordenadas_aruco(current_scan)
            if not resultado:
                print(f"    ⚠️ [IGNORADO] No se detectaron los 4 ArUcos en {current_scan.name}.")
                continue

            centros, img_gigante = resultado

        except MemoryError:
            print(f"    ❌ [ERROR] ¡Out Of Memory! Archivo demasiado gigante para BGR Array: {current_scan.name}")
            continue
        except Exception as e:
            # Un escaneo ilegible/corrupto no debe abortar el lote completo: se omite y se sigue.
            print(f"    ❌ [ERROR] No se pudo leer/procesar {current_scan.name}: {e}")
            continue

        print(f"    ✓ 4/4 Marcadores detectados con estrategia Proxy")

        # ALINEACION MEM-HEAVY W-PERSPECTIVE
        try:
            # Los tamaños base eran ARUCO_SIZE_PX = 100, ARUCO_MARGIN_PX = 40 (en el gen 1)
            # Pasamos valores duros del diseño para no complicar el JSON
            img_alineada = alinear_escaneo(img_gigante, centros, canvas_w, canvas_h, margen_aruco_base=40, tamanio_aruco_base=100)
            print(f"    ✓ Geometría alineada (Warp a {canvas_w * SCALE_FACTOR}x{canvas_h * SCALE_FACTOR})")
        except Exception as e:
            print(f"    ❌ [ERROR] Falló homografía geométrica: {e}")
            del img_gigante
            gc.collect()
            continue

        del img_gigante
        gc.collect() 

        # LA MAGIA: CORTA Y VERIFICA CADA PEDAJE CUALQUIER HOJA DEL JSON
        identificador_match = None
        for nombre_info_hoja, info_hoja in hojas_esperadas.items():
            # Sacamos 1 QR al azar del JSON de esta hoja y lo probamos vs la imagen de RAM,
            # para ver si esta hoja fisica es la "info_hoja" de este diccionario
            
            primer_qr_llave = list(info_hoja["qrs"].keys())[0]
            bbox_base = info_hoja["qrs"][primer_qr_llave]["bbox"]
            
            # coords json a pixels nativos 1200ppi
            qx1, qy1, qx2, qy2 = [v * SCALE_FACTOR for v in bbox_base] 
            
            # Recorta la muestra a lo pendejo en esa coordenada a ver si hay algo
            muestra_qr = img_alineada[qy1:qy2, qx1:qx2]
            
            texto_qr = leer_qr(muestra_qr)
            
            if texto_qr == primer_qr_llave:
                identificador_match = info_hoja
                print(f"    ✓ Identidad confirmada vía QR: match con estructura '{nombre_info_hoja}'")
                break
            
        
        if identificador_match is None:
             print(f"    ⚠️ [IGNORADO] Códigos QR ilegibles o borrados por el artista. Imposible identificar los frames para enrutar.")
             del img_alineada
             gc.collect()
             continue

        # AHORA QUE SABEMOS QUÉ HOJA DEL JSON ES ESE TIFFF
        # CORRE EL EXTRACTOR DE ARTES:
        
        for k_nombre, frames_meta in identificador_match["frames"].items():
            bx1, by1, bx2, by2 = frames_meta["bbox"]
            
            # escalar local
            x1 = bx1 * SCALE_FACTOR
            y1 = by1 * SCALE_FACTOR
            x2 = bx2 * SCALE_FACTOR
            y2 = by2 * SCALE_FACTOR
            
            # quitar margenes
            cx1, cy1, cx2, cy2 = aplicar_bleed(x1, y1, x2, y2, factor_porcentaje=bleed)
            
            arte = img_alineada[cy1:cy2, cx1:cx2]
            
            guardar_resultado(arte, frames_meta["archivo_original"], output_path)

        # Matar array RAM Pesado
        del img_alineada
        
        # Obligar al OS de Python a soltar la basura en RAM
        gc.collect()
        
    print()
    print("=" * 60)
    print("  ✅ PROCESAMIENTO MULTI-TIFF FINALIZADO.")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Procesador de escaneos fisicos pintados 1200ppi a RGB proxy 4k.")
    parser.add_argument("--input", default="./output_landscape", help="Directorio con TIFFs ultra pesados escaneados")
    parser.add_argument("--layout", default="./output_landscape/layout.json", help="Camino del Json bridge")
    parser.add_argument("--output", default="./frames_procesamiento", help="Destino limpios 4K")
    parser.add_argument("--bleed", type=float, default=0.015, help="Porcentaje para recortar el marco evitando bordes extra (default 1.5 porciento)")

    args = parser.parse_args()

    main(
        input_dir=args.input,
        layout_file=args.layout,
        output_dir=args.output,
        bleed=args.bleed
    )
