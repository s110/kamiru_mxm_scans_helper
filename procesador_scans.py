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
    # OpenCV imread podría fallar/ser lento con tiff hiper gigantes.
    # Leer en su defecto a memoria, o, el usuario debería asegurarse
    # de tener memoria suficiente. Cargamos:
    img_bgr = cv2.imread(str(img_path))
    if img_bgr is None:
        raise ValueError(f"No se pudo leer la imagen: {img_path}")

    # Escalar a la escala proxy (0.25 = 1/4 = 300 ppi aprox)
    factor_proxy = 1.0 / SCALE_FACTOR
    proxy = cv2.resize(img_bgr, (0, 0), fx=factor_proxy, fy=factor_proxy, interpolation=cv2.INTER_AREA)

    # Convertir a grises
    gray = cv2.cvtColor(proxy, cv2.COLOR_BGR2GRAY)

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

    # Deforma la imagen en bruto al tamaño perfecto ideal de 1200 PPI (muy exigente de RAM)
    warp = cv2.warpPerspective(img_gigante, M, (canvas_w, canvas_h), flags=cv2.INTER_LINEAR)

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
    Asegura que siempre termine en _procesado.tiff sin importar la extensión original.
    """
    path_obj = Path(path_original)
    nombre = f"{path_obj.stem}_procesado.tiff"
    ruta_final = dir_salida / nombre
    
    cv2.imwrite(str(ruta_final), recorte_frame)
    h, w = recorte_frame.shape[:2]
    print(f"      ✅ Frame procesado: {nombre} ({w}x{h})")

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
    parser.add_argument("--bleed", type=float, default=0.015, help="Porcentaje para recortar el marco evitando bordes extra (default 1.5%)")

    args = parser.parse_args()

    main(
        input_dir=args.input,
        layout_file=args.layout,
        output_dir=args.output,
        bleed=args.bleed
    )
