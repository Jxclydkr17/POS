# Violette POS v1.0.0

Sistema de punto de venta para ferreterías y comercios en Costa Rica.  
Incluye facturación electrónica (Hacienda), control de inventario, caja, compras, clientes y reportes.

---

## Requisitos del Sistema

- **Sistema operativo:** Windows 10 o superior (64 bits)
- **RAM:** 4 GB mínimo (8 GB recomendado)
- **Disco:** 500 MB libres
- **Pantalla:** 1366×768 mínimo (1920×1080 recomendado)
- **Python:** 3.11 o 3.12 (solo para desarrollo; el .exe no lo requiere)

---

## Instalación

### Opción A — Ejecutable (.exe)

1. Descargue la carpeta `ViolettePOS/` o ejecute el instalador `.exe`.
2. Abra `ViolettePOS.exe`.
3. En la primera ejecución la app crea automáticamente:
   - La base de datos (`violette_pos.db`)
   - El archivo de configuración (`.env` con SECRET_KEY generada)
   - Las carpetas `data/logs/`, `data/pdfs/`, `data/backups/`
4. Inicie sesión con las credenciales iniciales (ver sección siguiente).

### Opción B — Desde código fuente (desarrollo)

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd vp0

# 2. Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. (Opcional) Instalar herramientas de desarrollo
pip install -r requirements-dev.txt

# 5. Configurar variables de entorno
copy .env.example .env
# Editar .env según sea necesario

# 6. Ejecutar
python launcher.py
```

### Compilar el .exe

```bash
# Desde la raíz del proyecto (donde está launcher.py)
build.bat
# El resultado queda en dist\ViolettePOS\ViolettePOS.exe
```

---

## Primer Inicio de Sesión

| Campo    | Valor       |
|----------|-------------|
| Usuario  | `admin`     |
| Contraseña | `admin123` |

> **Importante:** La app le pedirá cambiar la contraseña en el primer inicio de sesión.  
> Cámbiela por una contraseña segura antes de registrar datos reales.

Después del primer login puede crear usuarios adicionales con roles de cajero o administrador desde el menú de configuración.

---

## Configuración

### Base de datos

Violette POS soporta dos motores:

- **SQLite** (predeterminado): No requiere instalación adicional. La base de datos es un archivo local (`violette_pos.db`). Ideal para una sola computadora.
- **MySQL**: Para instalaciones en red con múltiples terminales. Configure las credenciales en `.env`:

```env
DB_ENGINE=mysql
DB_USER=root
DB_PASSWORD=su_password
DB_HOST=localhost
DB_PORT=3306
DB_NAME=violette_db
```

### Facturación Electrónica (Hacienda)

Para habilitar la emisión de comprobantes electrónicos:

1. Obtenga su llave criptográfica (`.p12`) del sistema de Hacienda.
2. Coloque el archivo `.p12` en la carpeta `certs/`.
3. Configure en `.env`:

```env
HACIENDA_ENV=production
HACIENDA_API=https://api.comprobanteselectronicos.go.cr
HACIENDA_CERT_PATH=certs/su_certificado.p12
HACIENDA_CERT_PASS=password_del_certificado
HACIENDA_USER=su_usuario_hacienda
HACIENDA_PASSWORD=su_password_hacienda
```

4. Complete el perfil del emisor (cédula, nombre, dirección) desde Configuración → Emisor dentro de la app.

> Puede usar `HACIENDA_ENV=sandbox` para pruebas antes de pasar a producción.

### Correo Electrónico

Para enviar comprobantes por correo automáticamente:

```env
EMAIL_USER=su_correo@gmail.com
EMAIL_PASS=contraseña_de_aplicacion
```

> Si usa Gmail, genere una "contraseña de aplicación" desde la configuración de seguridad de su cuenta Google.

---

## Respaldos

La app crea respaldos automáticos de la base de datos en `data/backups/`.

- Los respaldos se gestionan desde Configuración → Respaldos dentro de la app.
- Se crea un respaldo automático antes de cada actualización de esquema (migración).
- Los respaldos incluyen verificación de integridad.
- Se recomienda copiar periódicamente la carpeta `data/backups/` a una unidad externa o servicio en la nube.

---

## Estructura de Carpetas

```
ViolettePOS/
├── ViolettePOS.exe          # Ejecutable principal
├── .env                     # Configuración (se genera automáticamente)
├── violette_pos.db          # Base de datos SQLite (se genera automáticamente)
├── alembic/                 # Migraciones de base de datos (automáticas)
├── certs/                   # Certificados de firma digital (.p12)
├── data/
│   ├── backups/             # Respaldos de la base de datos
│   ├── logs/                # Archivos de registro
│   └── pdfs/                # Facturas y reportes generados
└── ui/
    └── assets/              # Estilos e íconos de la interfaz
```

---

## Solución de Problemas

### La app no abre / muestra "Error Fatal"

Revise `data/logs/launcher.log` y `data/logs/errors.log` para ver el detalle del error.

### "El puerto 8000 está ocupado"

Otra instancia de Violette POS (u otro programa) ya está usando el puerto. Cierre esa instancia o reinicie la computadora.

### La interfaz se congela momentáneamente

Si ocurre al abrir un diálogo o guardar datos, cierre y vuelva a abrir la app. Si persiste, revise la conexión a la base de datos (en caso de MySQL) o el espacio en disco disponible.

### Problemas con facturación electrónica

- Verifique que el certificado `.p12` esté en la carpeta `certs/` y la contraseña sea correcta.
- Confirme que las credenciales de Hacienda estén bien escritas en `.env`.
- Si no hay conexión a internet, los comprobantes se encolan automáticamente y se reintentan cuando se restablezca la conexión.

---

## Notas Técnicas

- **Puerto interno:** La app usa `127.0.0.1:8000` para comunicación entre la interfaz y el backend. No se expone a la red.
- **Migraciones automáticas:** Al actualizar la app, las migraciones de base de datos se aplican automáticamente al iniciar. Se crea un respaldo previo por seguridad.
- **SECRET_KEY:** Se genera automáticamente en la primera ejecución. No la comparta ni la modifique manualmente (invalidaría todas las sesiones activas).
- **Logs:** Se rotan automáticamente (máximo ~9 MB por componente) y se ubican en `data/logs/`.

---

## Licencia

Software propietario. Todos los derechos reservados.