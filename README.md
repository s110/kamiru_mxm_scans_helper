# ⚠️ Este proyecto se fusionó en **Kamiru Studio** (v2)

Todo lo que hacía esta app (hojas de impresión con marcadores ArUco + QR, y
el procesador de escaneos) ahora vive, **muy mejorado**, dentro de la super
app **Kamiru Studio**, en el repositorio:

> **`kamiru_video_to_contact_sheets`** → https://github.com/s110/kamiru_video_to_contact_sheets

## ¿Por qué migrar?

Kamiru Studio hace todo lo de aquí y además:

- **Una sola app con ventana** para el flujo completo:
  video → hojas → pintura/cianotipia → escaneo → video final.
- **Marcadores ArUco redundantes** (8-12 en vez de 4): la hoja se procesa
  aunque varios marcadores queden pintados, tapados o cortados.
- **Escaneos a cualquier resolución y en cualquier orientación** (la escala
  se mide sola; ya no hace falta escanear exactamente a 1200 PPI).
- **Un solo QR legible identifica toda la hoja** (antes tenía que leerse el
  QR exacto de cada posición).
- **Modo cianotipia** ☀️: negativos para acetato (invertidos, espejados, con
  curva de compensación calibrable estilo *easy digital negatives*).
- **Calibración de impresora** (escala real, respuesta tonal, tamaño mínimo
  fiable de marcador/QR).
- Cuadrícula libre (no solo 2×2), cualquier tamaño de papel, deduplicación
  de dibujos repetidos, hojas de rescate, informe con miniaturas,
  procesamiento en paralelo y reconstrucción del video final.

## ¿Y mis proyectos viejos?

Los `layout.json` generados por esta app **siguen funcionando**: la fase
«② Procesar escaneos» de Kamiru Studio los lee directamente (compatibilidad
v1). Los scripts de este repositorio quedan tal cual como referencia, pero ya
no se mantienen.
