#!/bin/bash
# ============================================================
# Violette POS — Limpieza de archivos de desarrollo
# Ejecutar desde la raíz del proyecto: bash cleanup.sh
#
# FASE C — Fix C.5: Rutas actualizadas a data/ (antes app/)
# y limpieza de artefactos de desarrollo (BD, fingerprint, etc.)
# ============================================================

set -e

echo ""
echo "🧹 Violette POS — Limpieza de archivos de desarrollo"
echo "════════════════════════════════════════════════════"
echo ""

# ── BD de desarrollo ──
if [ -f "violette_pos.db" ]; then
    rm -f violette_pos.db violette_pos.db-wal violette_pos.db-shm
    echo "✅ Eliminada base de datos de desarrollo (violette_pos.db)"
fi

# ── Artefactos de desarrollo en data/ ──
if [ -f "data/.secret_key_fingerprint" ]; then
    rm -f data/.secret_key_fingerprint
    echo "✅ Eliminado data/.secret_key_fingerprint (fingerprint de dev)"
fi

if [ -f "data/login_attempts.json" ]; then
    rm -f data/login_attempts.json
    echo "✅ Eliminado data/login_attempts.json (remanente obsoleto)"
fi

# ── PDFs de ventas de prueba ──
if [ -d "data/pdfs" ]; then
    count=$(find data/pdfs -name "*.pdf" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        rm -f data/pdfs/*.pdf
        echo "✅ Eliminados $count PDFs de ventas (data/pdfs/)"
    fi
fi

# ── Backups de desarrollo ──
if [ -d "data/backups" ]; then
    count=$(find data/backups -name "backup_*" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        rm -f data/backups/backup_*
        echo "✅ Eliminados $count backups (data/backups/)"
    fi
fi

# ── Logs de desarrollo ──
if [ -d "data/logs" ]; then
    count=$(find data/logs -name "*.log" -o -name "*.log.*" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        rm -f data/logs/*.log data/logs/*.log.*
        echo "✅ Eliminados $count archivos de log (data/logs/)"
    fi
fi

# ── Session de desarrollo ──
if [ -f "session.json" ]; then
    rm -f session.json
    echo "✅ Eliminado session.json (sesión de dev)"
fi

# ── Cachés de Python compilados ──
count=$(find . -type d -name "__pycache__" 2>/dev/null | wc -l)
if [ "$count" -gt 0 ]; then
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    echo "✅ Eliminadas $count carpetas __pycache__"
fi

count=$(find . -name "*.pyc" -o -name "*.pyo" 2>/dev/null | wc -l)
if [ "$count" -gt 0 ]; then
    find . \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
    echo "✅ Eliminados $count archivos .pyc/.pyo"
fi

# ── Directorios legacy (rutas viejas, ya migradas a data/) ──
for old_dir in "app/pdfs" "app/backups"; do
    if [ -d "$old_dir" ]; then
        rm -rf "$old_dir"
        echo "✅ Eliminado directorio legacy $old_dir/"
    fi
done

# ── Asegurar estructura de directorios ──
mkdir -p data/pdfs data/backups data/logs
echo ""
echo "✅ Limpieza completada. El sistema creará la BD limpia en el primer arranque."
echo ""