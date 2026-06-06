from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from app.utils.dt import utcnow
from app.db.database import Base
import json


# ── Permisos disponibles en el sistema ──────────────────────
ALL_PERMISSIONS = [
    "ver_dashboard",
    "ver_ventas",
    "hacer_ventas",
    "ver_productos",
    "editar_productos",
    "ver_clientes",
    "editar_clientes",
    "ver_proveedores",
    "editar_proveedores",
    "ver_categorias",
    "editar_categorias",
    "ver_compras",
    "editar_compras",
    "ver_proformas",
    "editar_proformas",
    "ver_reportes",
    "ver_gastos",
    "editar_gastos",
    "ver_financiero",
    "facturacion_electronica",
    "acceder_configuracion",
    "gestionar_usuarios",
]

# Permisos por defecto según rol
DEFAULT_PERMISSIONS = {
    "admin": ALL_PERMISSIONS.copy(),
    "vendedor": [
        "ver_dashboard",
        "ver_ventas", "hacer_ventas",
        "ver_productos",
        "ver_clientes", "editar_clientes",
        "ver_categorias",
        "ver_reportes",
        "ver_proformas",
    ],
    "cajero": [
        "ver_ventas", "hacer_ventas",
    ],
}


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=True)
    role = Column(String(50), default="vendedor")  # admin, vendedor, cajero
    is_active = Column(Boolean, default=True)
    permissions = Column(Text, nullable=True)  # JSON list de permisos
    created_at = Column(DateTime, default=utcnow)

    # ── Recuperación de contraseña (estilo Google) ──
    # Cédula y correo del usuario. Se capturan obligatoriamente al crear el
    # administrador inicial (ver /users/setup) y habilitan el flujo de
    # "¿Olvidó su contraseña?": el admin demuestra identidad con cédula +
    # correo, recibe un código de 6 dígitos a su correo y resetea su clave.
    #
    # Son nullable porque:
    #   - Las instalaciones existentes (admin creado antes de esta función)
    #     no los tienen hasta que el admin los complete en Configuración.
    #   - Los demás roles (vendedor/cajero) no los necesitan; el admin
    #     resetea sus contraseñas desde adentro del sistema.
    cedula = Column(String(50), nullable=True)
    correo = Column(String(255), nullable=True)

    # ── FASE 3 — Fix 3.3: Revocación de tokens ──
    # Cuando se establece, todos los tokens con iat < token_revoked_at
    # son rechazados. Se actualiza al desactivar usuario o cambiar password.
    token_revoked_at = Column(DateTime, nullable=True)

    # ── FASE 6 — Fix 6.1: Forzar cambio de contraseña en primer login ──
    must_change_password = Column(Boolean, default=False)

    def get_permissions(self) -> list[str]:
        """Retorna los permisos del usuario. Si no tiene, usa los del rol."""
        if self.role == "admin":
            return ALL_PERMISSIONS.copy()
        if self.permissions:
            try:
                return json.loads(self.permissions)
            except (json.JSONDecodeError, TypeError):
                pass
        return DEFAULT_PERMISSIONS.get(self.role, [])

    def set_permissions(self, perms: list[str]):
        """Guarda la lista de permisos como JSON."""
        self.permissions = json.dumps(perms)

    def has_permission(self, perm: str) -> bool:
        """Verifica si el usuario tiene un permiso específico."""
        if self.role == "admin":
            return True
        return perm in self.get_permissions()

    def __repr__(self):
        return f"<User(username='{self.username}', role='{self.role}')>"