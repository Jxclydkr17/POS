# -*- mode: python ; coding: utf-8 -*-
"""
violette_pos.spec — Configuración de PyInstaller para Violette POS

USO:
    pyinstaller violette_pos.spec

RESULTADO:
    dist/ViolettePOS/ViolettePOS.exe  (carpeta con todos los archivos)

NOTAS:
    - Incluye XSD schemas, assets UI, .env template
    - PySide6 se incluye automáticamente
    - El .exe busca .env en su propio directorio
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
    'passlib.handlers.bcrypt',
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
]

# Agregar .env si existe (para desarrollo)
if os.path.exists('.env'):
    datas.append(('.env', '.'))

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
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='ViolettePOS',
)
