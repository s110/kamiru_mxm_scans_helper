# 📄 DOCUMENTO DE DISEÑO DE SISTEMA: PIPELINE AUTOMATIZADO PARA MIXED MEDIA

## 1. OBJETIVO DEL SISTEMA
Automatizar el flujo de trabajo de pre-impresión y post-escaneo para una artista de animación *mixed media*. El sistema debe tomar fotogramas digitales (hasta 4K), generar hojas de impresión optimizadas (4 fotogramas por hoja), permitir la intervención física (pintura), y procesar escaneos masivos en ultra alta resolución (TIFF a 1200 PPI) para devolver fotogramas digitales perfectamente alineados, recortados y nombrados, listos para compilación en video.

## 2. STACK TECNOLÓGICO REQUERIDO
*   **Lenguaje:** Python 3.x
*   **Librerías principales:**
    *   `Pillow (PIL)`: Para la creación rápida del layout de impresión.
    *   `OpenCV (cv2)` y `NumPy`: Para visión por computadora, matrices, detección de ArUcos y transformación de perspectiva (Homografía).
    *   `qrcode` y `pyzbar`: Para generar y leer códigos QR.
    *   `json`: Para persistencia de coordenadas entre los dos scripts.

---

## 3. ARQUITECTURA DEL SISTEMA (Los 2 Scripts)

El sistema se divide en dos programas independientes que se comunican mediante un archivo `layout.json`.

### SCRIPT 1: `generador_hojas.py` (Fase de Pre-Impresión)
**Propósito:** Leer los fotogramas originales, calcular la grilla, y generar el PDF/TIFF de impresión a 300 PPI.

**Lógica de Implementación y "El Por Qué":**
1.  **Detección de Aspect Ratio y Orientación de Hoja:**
    *   *Por qué:* Para maximizar el área de dibujo.
    *   *Lógica:* El script lee el primer frame. Si el ancho es mayor que el alto (ej. 16:9), define el lienzo A4 a 300 PPI en modo Apaisado (Landscape: 3508x2480 px). Si el alto es mayor o igual (ej. 9:16 o 1:1), lo define en Vertical (Portrait: 2480x3508 px).
2.  **Generación de la Grilla 2x2:**
    *   *Por qué:* La artista exige exactamente 4 fotogramas por hoja para su flujo manual.
    *   *Lógica:* Se divide el área segura del lienzo en 4 cuadrantes iguales. El fotograma (ej. 4K) se reduce proporcionalmente (*downscale* con antialiasing) para caber dentro del cuadrante, dejando un pequeño margen inferior.
3.  **Generación de Metadata Visual (QR y Texto):**
    *   *Por qué:* Para identificar cada frame unívocamente tras el escaneo.
    *   *Lógica:* Se genera un QR con el nombre original del archivo (ej. `secuencia1_frame001`) y se pega debajo del fotograma, junto con el texto legible.
4.  **Colocación de Marcadores ArUco:**
    *   *Por qué:* Para la alineación matemática posterior que elimina el error humano y la rotación del escáner.
    *   *Lógica:* Se pegan 4 marcadores ArUco (diccionario 4x4) en las esquinas extremas del lienzo A4.
5.  **Exportación del Archivo Puente (`layout.json`):**
    *   *Por qué:* Evita que el segundo script tenga que "adivinar" dónde están los cuadros. Hace al sistema agnóstico a la resolución.
    *   *Lógica:* Se guarda un JSON con la resolución del lienzo, la ubicación exacta `[x1, y1, x2, y2]` de cada fotograma y cada QR generados en esa sesión.

---

### FASE FÍSICA (Intervención del Humano)
1.  La artista imprime las hojas generadas a 300 PPI.
2.  Coloca cinta (*masking tape*) sobre los 4 ArUcos y los QRs.
3.  Pinta libremente (incluso saliédose de los bordes).
4.  Retira la cinta y escanea todo el fajo en formato **TIFF a 1200 PPI** (generando archivos muy pesados).

---

### SCRIPT 2: `procesador_scans.py` (Fase de Post-Escaneo)
**Propósito:** Alinear los escaneos gigantes, recortar los frames pintados, restaurarlos a su tamaño 4K original y nombrarlos correctamente.

**Lógica de Implementación y "El Por Qué":**
1.  **Lectura con Estrategia "Proxy" (CRÍTICO):**
    *   *Por qué:* Un TIFF a 1200 PPI (aprox. 14,000 x 9,900 px) satura la RAM y hace que la detección de ArUcos tarde minutos por hoja o colapse el sistema.
    *   *Lógica:* 
        *   Cargar el TIFF original.
        *   Generar un *proxy* temporal reduciendo la imagen 4 veces (`cv2.resize(img, (0,0), fx=0.25, fy=0.25)`).
        *   Ejecutar la detección de los 4 ArUcos **solo en el proxy**.
2.  **Enderezado Matemático (WarpPerspective Upscaled):**
    *   *Por qué:* Para aplanar y alinear la hoja perfectamente a la grilla digital.
    *   *Lógica:* 
        *   Obtener las coordenadas de los ArUcos en el proxy.
        *   Multiplicar esas coordenadas por 4 (para trasladarlas a la escala de 1200 PPI).
        *   Calcular la Matriz de Transformación y aplicar `cv2.warpPerspective` al **TIFF gigante original**, forzando que su tamaño resultante sea exactamente 4 veces el tamaño del lienzo de 300 PPI (ej. si el A4 era 3508x2480, el canvas final en RAM debe ser 14032x9920).
3.  **Recorte a Ciegas usando JSON:**
    *   *Por qué:* Es la forma más rápida y a prueba de fallos de extraer el arte.
    *   *Lógica:* El script lee el `layout.json`. Toma las coordenadas de recorte de cada fotograma, las **multiplica por 4**, y recorta la matriz gigante en RAM.
4.  **Verificación de Identidad (Decodificación QR):**
    *   *Por qué:* Si la artista escaneó las hojas en desorden, el JSON por sí solo no sabe qué hoja es cuál.
    *   *Lógica:* El script recorta la zona del QR (usando las coordenadas del JSON x4), lo lee con `pyzbar`, y extrae el nombre de archivo real (ej. `secuencia1_frame001`).
5.  **Restauración a 4K (Upscale/Downscale final) y Guardado:**
    *   *Por qué:* El editor de video necesita los archivos en su resolución original (ej. 3840x2160), no en la resolución arbitraria resultante del escaneo a 1200 PPI.
    *   *Lógica:* El recorte final del arte pintado se redimensiona (`cv2.resize` con interpolación Lanczos4 o Bicúbica) para que coincida exactamente con las dimensiones del frame original. Se guarda como `secuencia1_frame001_procesado.tiff`.

---

## 4. CONSIDERACIONES TÉCNICAS ADICIONALES PARA LA IA
*   **Manejo de Memoria:** Al pedirle código a la IA, haz énfasis en que se libere la memoria RAM en cada iteración del bucle `for` del `procesador_scans.py` usando `del imagen_gigante` y `gc.collect()`, ya que procesar múltiples TIFFs a 1200 PPI provocará un *Memory Leak* rápidamente si no se gestiona bien.
*   **Bleed (Sangrado):** Instruir al generador de código que, al momento de recortar en el paso 3 del procesador, el *Bounding Box* del JSON se "encoja" un 1% o 2% hacia el centro. Esto evita capturar los bordes blancos del papel si la artista no pintó exactamente hasta el límite.
*   **Diccionario ArUco:** Usar `cv2.aruco.DICT_4X4_50`. Son los más simples y fáciles de detectar a distintas resoluciones.
*   **Virtual Environment:** Crear un entorno virtual para gestionar las dependencias del proyecto, usa `uv` para crearlo y gestionar las dependencias, no te olvides de tener el `pyproject.toml` y el `uv.lock` en el repositorio.