# -*- mode: python ; coding: utf-8 -*-
"""
violette_pos.spec — Configuración de PyInstaller para Violette POS

USO:
    pyinstaller violette_pos.spec

RESULTADO:
    dist/ViolettePOS/ViolettePOS.exe  (carpeta con todos los archivos)

NOTAS:
    - Incluye XSD schemas, assets UI, .env template
    - Incluye economic_activities.csv (catálogo Hacienda CR)
    - PySide6 se incluye automáticamente
    - El .exe busca .env en su propio directorio

AUDITORÍA FIX 1.2: Agregado economic_activities.csv al bundle para
que seed_db pueda importar las actividades económicas en el .exe.

FASE 4 — Fix 4.8: economic_activities.csv se movió de la raíz del
proyecto a app/data/. La tupla `datas` se actualizó en consecuencia:
ahora se copia desde app/data/economic_activities.csv al directorio
app/data/ dentro del .exe distribuido.

FASE 4 — Fix 4.7 (Camino B): pruning de matplotlib para reducir el
peso del bundle (~30 MB en el .exe original). Se agregaron excludes
de submódulos no usados: tests, mpl_toolkits, backends de toolkits
gráficos rivales (Tk/Wx/GTK), backends macOS/web/notebook, y
backends de exportación PDF/PS/SVG (la app solo guarda PNG).
Ahorro estimado: 8-15 MB de módulos Python. Adicionalmente, al
final del bloque Analysis hay un filtro OPCIONAL de archivos de
datos (fuentes AFM y sample_data) — comentado por defecto.
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Directorio del proyecto ──
PROJECT_DIR = os.path.abspath('.')

# ── Recolectar submódulos que PyInstaller no detecta automáticamente ──
hidden_imports = [
    # FastAPI + uvicorn
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'uvicorn.workers',

    # SQLAlchemy dialects
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.dialects.mysql',
    'sqlalchemy.dialects.mysql.pymysql',

    # Pydantic
    'pydantic',
    'pydantic_settings',
    'pydantic.deprecated.decorator',

    # Auth
    'bcrypt',

    # XML
    'lxml',
    'lxml.etree',

    # PDF
    'reportlab',
    'qrcode',

    # Email
    'yagmail',

    # Database drivers
    'pymysql',

    # Otros
    'multipart',
    'email_validator',

    # App modules que podrían no detectarse
    'app.db.models',
    'app.routers',
    'app.einvoice',
    'app.services',
    'app.scripts',
    'app.ai',
    'app.ai.insights',
]

# Agregar todos los submódulos de la app
hidden_imports += collect_submodules('app')
hidden_imports += collect_submodules('ui')

# ── Archivos de datos a incluir ──
# (source, dest_folder_in_bundle)
datas = [
    # XSD Schemas para validación offline
    ('app/einvoice/schemas', 'app/einvoice/schemas'),

    # Assets de UI
    ('ui/assets', 'ui/assets'),

    # Template de configuración
    ('.env.example', '.'),

    # Catálogo de actividades económicas (Hacienda CR)
    # FASE 4 — Fix 4.8: ubicación canónica app/data/ (antes raíz).
    ('app/data/economic_activities.csv', 'app/data'),

    # Fix 3.1: Alembic — migraciones de BD para actualizaciones de esquema
    ('alembic', 'alembic'),
    ('alembic.ini', '.'),

    # Fix 3.2: Archivo de versión (fuente única de verdad)
    ('VERSION', '.'),
]

# ── FASE 7 — Fix 7.3: NUNCA empaquetar .env en el .exe ──
# Si se construye el .exe en una máquina con .env real,
# las credenciales (SECRET_KEY, HACIENDA_PASSWORD, DB_PASSWORD)
# quedarían dentro del instalador y se distribuirían a todos.
# La app crea su propio .env en la primera ejecución (ver _ensure_secret_key).

# ── Análisis ──
a = Analysis(
    ['launcher.py'],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ── Excludes preexistentes (no relacionados a matplotlib) ──
        'tkinter',
        'unittest',
        'test',
        'tests',
        'pytest',
        'IPython',
        'notebook',
        'jupyter',
        'sphinx',
        'docutils',

        # ═════════════════════════════════════════════════════════
        # FASE 4 — Fix 4.7: pruning de matplotlib (Camino B)
        # ═════════════════════════════════════════════════════════
        # OBJETIVO: reducir el tamaño del bundle (~30 MB de matplotlib
        # en el .exe original) sin tocar el código de las vistas que lo
        # usan. Estimado de ahorro con módulos: 8-15 MB.
        #
        # Si después de aplicar esto el .exe falla al arrancar con
        # `ModuleNotFoundError: No module named 'matplotlib.backends.X'`
        # o similar, basta con comentar el exclude correspondiente y
        # rebuildear. Los excludes están agrupados por tier para que
        # el rollback sea fácil de localizar.
        #
        # Verificación previa (greps en el proyecto):
        #   - Backends usados: qt5agg, qtagg (Agg renderer)
        #   - fig.savefig solo a PNG (3 sitios), nunca PDF/PS/SVG
        #   - mpl_toolkits sin uso (3D, axes_grid, axisartist)

        # ── Tier 1: suites de test ──
        # Solo se usan al correr `pytest matplotlib/tests/`, jamás en
        # runtime. Eliminación totalmente segura.
        'matplotlib.tests',
        'matplotlib.testing',
        'numpy.tests',
        # Nota: NO excluimos `numpy.testing` porque algunos módulos
        # internos de matplotlib (`_mathtext`, ciertos polynomial)
        # importan helpers desde ahí. La diferencia de peso es chica.

        # ── Tier 2: subpaquetes no usados (greppeado en el proyecto) ──
        'mpl_toolkits',                   # axes_grid1, axisartist, 3D

        # ── Tier 3: backends de toolkit gráfico no usados ──
        # La app usa Qt vía qt5agg/qtagg. Los siguientes son backends
        # para otros toolkits (Tk, Wx, GTK), macOS, notebook web, etc.
        # En una app Windows + PySide6 son lastre puro.
        'matplotlib.backends.backend_tkagg',
        'matplotlib.backends.backend_tkcairo',
        'matplotlib.backends.backend_wx',
        'matplotlib.backends.backend_wxagg',
        'matplotlib.backends.backend_wxcairo',
        'matplotlib.backends.backend_gtk3',
        'matplotlib.backends.backend_gtk3agg',
        'matplotlib.backends.backend_gtk3cairo',
        'matplotlib.backends.backend_gtk4',
        'matplotlib.backends.backend_gtk4agg',
        'matplotlib.backends.backend_gtk4cairo',
        'matplotlib.backends.backend_macosx',
        'matplotlib.backends.backend_webagg',
        'matplotlib.backends.backend_webagg_core',
        'matplotlib.backends.backend_nbagg',
        'matplotlib.backends.backend_template',
        'matplotlib.backends.backend_pgf',
        'matplotlib.backends.backend_qtcairo',
        'matplotlib.backends.backend_qt5cairo',

        # ── Tier 4: backends de exportación no usados ──
        # Greppeado: todos los `fig.savefig(...)` y `plt.savefig(...)`
        # del proyecto usan PNG. Si en el futuro se exporta a PDF/PS/SVG
        # desde matplotlib, hay que sacar el exclude correspondiente.
        'matplotlib.backends.backend_pdf',
        'matplotlib.backends.backend_ps',
        'matplotlib.backends.backend_svg',
        # ═════════════════════════════════════════════════════════
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ═════════════════════════════════════════════════════════════════
# FASE 4 — Fix 4.7 (OPCIONAL): pruning de archivos de datos de matplotlib
# ═════════════════════════════════════════════════════════════════
# Los `excludes` arriba eliminan MÓDULOS Python, pero el hook de
# matplotlib en PyInstaller también copia toda la carpeta `mpl-data/`
# (fuentes, sample data, stylesheets). Estos archivos suman ~7 MB más.
#
# El siguiente bloque filtra dos subcarpetas que la app no necesita:
#   - mpl-data/fonts/afm/  → fuentes PostScript (solo usadas por el
#                            backend PS, que ya excluimos arriba).
#   - mpl-data/sample_data/ → imágenes de ejemplo de la doc de mpl.
#
# Ahorro adicional estimado: 2-4 MB.
#
# Riesgo: bajo. Si por alguna razón matplotlib intenta cargar una
# fuente AFM o un sample_data en runtime (no debería con nuestros
# excludes de backend), se vería como un FileNotFoundError en logs.
#
# Está ACTIVADO por defecto. Si tras buildear vieras errores de
# matplotlib buscando archivos de mpl-data, comentá las dos líneas
# del filter y rebuildeá.
def _prune_matplotlib_datas(datas_list):
    """Quita archivos pesados de matplotlib que no usamos."""
    drop_prefixes = (
        # En Windows PyInstaller usa '\\' o '/' según fuente, normalizamos.
        ('matplotlib', 'mpl-data', 'fonts', 'afm'),
        ('matplotlib', 'mpl-data', 'sample_data'),
    )
    def _keep(item):
        dest = item[0].replace('\\', '/').lower()
        parts = tuple(dest.split('/'))
        for prefix in drop_prefixes:
            # Match si los primeros N segmentos del path coinciden.
            if parts[:len(prefix)] == tuple(p.lower() for p in prefix):
                return False
        return True
    return [item for item in datas_list if _keep(item)]


a.datas = _prune_matplotlib_datas(a.datas)


# ── Empaquetado ──
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ViolettePOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # FASE 3.1: UPX DESACTIVADO. Comprimir el binario
                             # con UPX dispara falsos positivos de antivirus y
                             # puede corromper las DLLs de Qt6/PySide6 (cuelgues
                             # "access violation" al arrancar). Reliability > size.
    console=False,           # Sin ventana de consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ui/assets/logo.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,               # FASE 3.1: UPX desactivado también en COLLECT
                             # (mismas razones que en EXE: AV + DLLs de Qt6).
    upx_exclude=[],          # Irrelevante con upx=False; se deja por claridad.
    name='ViolettePOS',
)
