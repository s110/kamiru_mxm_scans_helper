"""
build_exe.py — Compila la aplicación en un ejecutable .exe portable para Windows.

Este script utiliza PyInstaller para empaquetar app.py junto con todos sus
scripts dependientes (generador_hojas.py, procesador_scans.py) y recursos
(icon.ico) en un solo archivo .exe que no requiere Python instalado.

Uso (en PowerShell/CMD):
    uv run python build_exe.py

El ejecutable resultante estará en la carpeta 'dist/'.
"""

import subprocess
import sys
from pathlib import Path


def main():
    project_dir = Path(__file__).parent

    # Archivos del proyecto
    app_file = project_dir / "app.py"
    icon_file = project_dir / "icon.ico"
    generador = project_dir / "generador_hojas.py"
    procesador = project_dir / "procesador_scans.py"

    # Verificar que todo existe
    for f in [app_file, icon_file, generador, procesador]:
        if not f.exists():
            print(f"❌ Error: No se encontró el archivo: {f}")
            sys.exit(1)

    print("=" * 60)
    print("  COMPILANDO EJECUTABLE — Kamiru MXM Scanner Helper")
    print("=" * 60)
    print()

    # Comando de PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",

        # Un solo archivo .exe
        "--onefile",

        # Modo ventana (sin consola negra detrás)
        "--windowed",

        # Nombre del ejecutable
        "--name", "KamiruMXM",

        # Ícono del gatito pixel
        "--icon", str(icon_file),

        # Agregar icon.ico como dato (para que app.py lo encuentre en runtime)
        "--add-data", f"{icon_file}{';' if sys.platform == 'win32' else ':'}.",

        # Incluir los scripts como módulos ocultos (los importamos dinámicamente)
        "--hidden-import", "generador_hojas",
        "--hidden-import", "procesador_scans",

        # Incluir los scripts como datos para que PyInstaller los encuentre
        "--add-data", f"{generador}{';' if sys.platform == 'win32' else ':'}.",
        "--add-data", f"{procesador}{';' if sys.platform == 'win32' else ':'}.",

        # Limpiar la build anterior
        "--clean",

        # No pedir confirmación
        "--noconfirm",

        # Archivo principal
        str(app_file),
    ]

    print("📦 Ejecutando PyInstaller...")
    print(f"   Comando: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=str(project_dir))

    if result.returncode == 0:
        print()
        print("=" * 60)
        print("  ✅ ¡COMPILACIÓN EXITOSA!")
        print("=" * 60)
        print()
        dist_dir = project_dir / "dist"
        exe_name = "KamiruMXM.exe" if sys.platform == "win32" else "KamiruMXM"
        print(f"  El ejecutable está en: {dist_dir / exe_name}")
        print()
        print("  📋 Instrucciones:")
        print(f"     1. Ve a la carpeta:  {dist_dir}")
        print(f"     2. Copia '{exe_name}' a donde quieras.")
        print( "     3. ¡Doble clic para abrir!")
        print()
    else:
        print()
        print("❌ La compilación falló. Revisa los errores arriba.")
        sys.exit(1)


if __name__ == "__main__":
    main()
