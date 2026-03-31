# app/config/settings.py
"""
⛔ MÓDULO DEPRECADO — NO USAR

Este archivo era el sistema legacy de configuración basado en JSON
(app_settings.json). Toda la configuración de negocio ahora vive en
la tabla `settings` de la base de datos.

Acceso correcto:
    from app.services.settings_service import get_settings, get_business_name

Si ves este error, significa que algún módulo aún importa desde aquí
y necesita ser migrado.
"""

raise ImportError(
    "app.config.settings está deprecado. "
    "Usa app.services.settings_service en su lugar. "
    "Ver docstring de este archivo para detalles."
)