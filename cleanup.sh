#!/bin/bash
# ============================================================
# Violette POS — Limpieza de archivos innecesarios
# Ejecutar desde la raíz del proyecto: bash cleanup.sh
# ============================================================

set -e

echo ""
echo "🧹 Violette POS — Limpieza de archivos innecesarios"
echo "════════════════════════════════════════════════════"
echo ""

# 7.1 — PDFs de ventas de prueba/producción
if [ -d "app/pdfs" ]; then
    count=$(find app/pdfs -name "*.pdf" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        rm -f app/pdfs/*.pdf
        echo "✅ Eliminados $count PDFs de ventas (app/pdfs/)"
    fi
    # Crear .gitkeep para mantener la carpeta
    touch app/pdfs/.gitkeep
fi

# 7.2 — Backups SQL con datos reales
if [ -d "app/backups" ]; then
    count=$(find app/backups -name "*.sql" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        rm -f app/backups/*.sql
        echo "✅ Eliminados $count backups SQL (app/backups/)"
    fi
    touch app/backups/.gitkeep
fi

# 7.3 — Cachés de Python compilados
count=$(find . -type d -name "__pycache__" 2>/dev/null | wc -l)
if [ "$count" -gt 0 ]; then
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    echo "✅ Eliminadas $count carpetas __pycache__"
fi

count=$(find . -name "*.pyc" -o -name "*.pyo" 2>/dev/null | wc -l)
if [ "$count" -gt 0 ]; then
    find . -name "*.pyc" -delete 2>/dev/null || true
    find . -name "*.pyo" -delete 2>/dev/null || true
    echo "✅ Eliminados $count archivos .pyc/.pyo"
fi

# Crear carpetas de runtime si no existen
mkdir -p generated_pdfs exports
touch generated_pdfs/.gitkeep exports/.gitkeep

echo ""
echo "✅ Limpieza completada."
echo "   Ejecutá 'git add .gitignore && git commit' para que no vuelvan a entrar."
echo ""
