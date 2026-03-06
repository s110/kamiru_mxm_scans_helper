"""
build_exe.py — Compila la aplicación en un ejecutable .exe portable para Windows.

Este script utiliza PyInstaller para empaquetar app.py junto con todos sus
scripts dependientes (generador_hojas.py, procesador_scans.py) y recursos
(icon.ico) en un solo archivo .exe que no requiere Python instalado.

Uso (en PowerShell/CMD):
    uv run python build_exe.py

El ejecutable resultante estará en la carpeta 'dist/'.
"""

import importlib
import subprocess
import sys
from pathlib import Path


def _find_pyzbar_dlls() -> list[str]:
    """
    Localiza las DLLs nativas de pyzbar (libiconv.dll, libzbar-64.dll, etc.)
    que PyInstaller no detecta automáticamente.

    Retorna una lista de argumentos --add-binary para PyInstaller.
    """
    sep = ";" if sys.platform == "win32" else ":"
    args = []

    try:
        spec = importlib.util.find_spec("pyzbar")
        if spec and spec.origin:
            pyzbar_dir = Path(spec.origin).parent
            dlls = list(pyzbar_dir.glob("*.dll")) + list(pyzbar_dir.glob("*.so")) + list(pyzbar_dir.glob("*.dylib"))
            for dll in dlls:
                # Incluir cada DLL en el directorio pyzbar/ del paquete
                args.extend(["--add-binary", f"{dll}{sep}pyzbar"])
                print(f"  📎 DLL encontrada: {dll.name}")

            if not dlls:
                print("  ⚠️  No se encontraron DLLs de pyzbar. Puede que los QR no funcionen en el .exe.")
        else:
            print("  ⚠️  No se pudo localizar el paquete pyzbar.")
    except Exception as e:
        print(f"  ⚠️  Error buscando DLLs de pyzbar: {e}")

    return args


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

    # Detectar DLLs nativas de pyzbar que PyInstaller no incluye por sí solo
    print("🔍 Buscando DLLs nativas de pyzbar...")
    pyzbar_dll_args = _find_pyzbar_dlls()
    print()

    # Separador de rutas: ';' en Windows, ':' en Linux/Mac
    sep = ";" if sys.platform == "win32" else ":"

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
        "--add-data", f"{icon_file}{sep}.",

        # Incluir los scripts como módulos ocultos (los importamos dinámicamente)
        "--hidden-import", "generador_hojas",
        "--hidden-import", "procesador_scans",

        # Incluir los scripts como datos para que PyInstaller los encuentre
        "--add-data", f"{generador}{sep}.",
        "--add-data", f"{procesador}{sep}.",

        # Asegurar que pyzbar y sus dependencias se incluyan
        "--hidden-import", "pyzbar",
        "--hidden-import", "pyzbar.pyzbar",

        # Limpiar la build anterior
        "--clean",

        # No pedir confirmación
        "--noconfirm",

        # Archivo principal
        str(app_file),
    ]

    # Inyectar las DLLs de pyzbar al comando
    cmd.extend(pyzbar_dll_args)

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
