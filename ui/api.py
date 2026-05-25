# ui/api.py
"""
FASE 5 — Fix 5.1: API URLs como clase con métodos tipados.

Antes: dict con mezcla de strings y lambdas, sin autocompletado.
Ahora: clase ApiUrls con propiedades y métodos, con backward
       compatibility vía __getitem__ para no romper el código existente.

Uso nuevo (preferido):
    from ui.api import api
    url = api.products                    # string fijo
    url = api.product_by_id(42)          # método con parámetro
    url = api.districts("1", "01")       # método con múltiples parámetros

Uso legacy (sigue funcionando):
    from ui.api import API, BASE_URL
    url = API["products"]                # string fijo
    url = API["product_by_id"](42)       # lambda


─────────────────────────────────────────────────────────────────
FASE 6 — Fix 6.X: Auto-refresh client-side (interceptor de 401)
─────────────────────────────────────────────────────────────────

Cuando un endpoint protegido responde 401 (access_token expirado),
queremos que el cliente intente automáticamente /users/refresh con el
refresh_token persistido y reintente el request original, sin molestar
al usuario con un diálogo de re-login.

Solución: `http`, un objeto drop-in compatible con `requests` que
expone get/post/put/delete/patch/request. Migración por archivo:

    # Antes:
    import requests
    r = requests.get(url, headers=_headers(), timeout=10)

    # Después (cambio de una línea):
    from ui.api import http as requests
    r = requests.get(url, headers=_headers(), timeout=10)

`http.exceptions`, `http.Session`, `http.adapters` y `http.Response` son
passthroughs al módulo real, así que `except requests.exceptions.X`
sigue funcionando tras el rename.

Qué hace internamente:
  1. Ejecuta el request normalmente.
  2. Si vuelve 401 y hay refresh_token y no es endpoint de auth:
       a) llama session.try_refresh_access_token() (single-flight).
       b) si tuvo éxito, actualiza el header Authorization con el
          nuevo token y reintenta UNA vez.
       c) si falló, retorna la respuesta 401 original tal cual.
  3. En cualquier otro caso retorna el Response sin tocar nada.

Endpoints excluidos del retry (para no entrar en loop):
  /users/login, /users/refresh, /users/setup.
"""
import logging
import os
from urllib.parse import quote, urlsplit

import requests as _requests

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

logger = logging.getLogger(__name__)


class ApiUrls:
    """URLs del backend organizadas como propiedades y métodos."""

    def __init__(self, base: str = BASE_URL):
        self._base = base

    # ── Auth ──
    @property
    def login(self) -> str:
        return f"{self._base}/users/login"

    # ── Productos ──
    @property
    def products(self) -> str:
        return f"{self._base}/products"

    def product_by_id(self, product_id: int) -> str:
        return f"{self._base}/products/{product_id}"

    def product_movements(self, product_id: int) -> str:
        return f"{self._base}/products/{product_id}/movements"

    @property
    def reorder_suggestions(self) -> str:
        return f"{self._base}/products/reorder-suggestions"

    # ── Clientes ──
    @property
    def customers(self) -> str:
        return f"{self._base}/customers"

    def customer_by_id(self, customer_id: int) -> str:
        return f"{self._base}/customers/{customer_id}"

    # ── Ventas ──
    @property
    def sales(self) -> str:
        return f"{self._base}/sales"

    def sale_by_id(self, sale_id: int) -> str:
        return f"{self._base}/sales/{sale_id}"

    def delete_sale(self, sale_id: int) -> str:
        return f"{self._base}/sales/{sale_id}"

    # ── Créditos ──
    def credits(self, customer_id: int) -> str:
        return f"{self._base}/credits/{customer_id}"

    def create_credit(self, customer_id: int) -> str:
        return f"{self._base}/credits/{customer_id}/create"

    def add_credit_sale(self, customer_id: int) -> str:
        return f"{self._base}/credits/{customer_id}/add"

    def add_credit_payment(self, credit_id: int) -> str:
        return f"{self._base}/credits/{credit_id}/payments"

    # ── Gastos ──
    @property
    def expenses(self) -> str:
        return f"{self._base}/expenses"

    def delete_expense(self, expense_id: int) -> str:
        return f"{self._base}/expenses/{expense_id}"

    # ── Métodos de pago ──
    @property
    def payment_methods(self) -> str:
        return f"{self._base}/payment-methods"

    # ── Usuarios ──
    @property
    def users(self) -> str:
        return f"{self._base}/users"

    # ── Ubicaciones ──
    @property
    def provinces(self) -> str:
        return f"{self._base}/locations/provinces"

    def cantons(self, province_id: str) -> str:
        return f"{self._base}/locations/provinces/{province_id}/cantons"

    def districts(self, province_id: str, canton_id: str) -> str:
        return f"{self._base}/locations/provinces/{province_id}/cantons/{canton_id}/districts"

    # ── Actividades económicas ──
    def economic_activity_search(self, q: str) -> str:
        return f"{self._base}/economic-activities/search?q={quote(q)}"

    # ── Lookup cédula (Hacienda) ──
    def lookup_cedula(self, identificacion: str) -> str:
        return f"{self._base}/customers/lookup-cedula?identificacion={quote(identificacion)}"

    # ── Analytics ──
    @property
    def no_rotation(self) -> str:
        return f"{self._base}/analytics/no-rotation"

    @property
    def purchases_spending_by_supplier(self) -> str:
        return f"{self._base}/analytics/purchases/spending-by-supplier"

    @property
    def purchases_monthly_evolution(self) -> str:
        return f"{self._base}/analytics/purchases/monthly-evolution"

    @property
    def purchases_avg_payment_days(self) -> str:
        return f"{self._base}/analytics/purchases/avg-payment-days"

    @property
    def purchases_top_products(self) -> str:
        return f"{self._base}/analytics/purchases/top-products"

    def supplier_comparison(self, product_id: int) -> str:
        return f"{self._base}/analytics/purchases/supplier-comparison?product_id={product_id}"

    @property
    def multi_supplier_products(self) -> str:
        return f"{self._base}/analytics/purchases/multi-supplier-products"

    # ── Backward compatibility ──────────────────────────────
    # Permite seguir usando API["key"] y API["key"](args)
    # sin romper el código existente en dialogs.
    def __getitem__(self, key: str):
        """Acceso tipo dict para backward compatibility."""
        attr = getattr(self, key, None)
        if attr is None:
            raise KeyError(f"API endpoint '{key}' no existe")
        # Si es una property (string), retornarlo directamente
        if isinstance(attr, str):
            return attr
        # Si es un método, retornar el callable
        return attr


# ── Instancia global ──
api = ApiUrls()

# ── Backward compatibility: API dict-like ──
# El código existente usa `from ui.api import API, BASE_URL`
# Esto sigue funcionando sin cambiar nada.
API = api


# ═══════════════════════════════════════════════════════════════
# FASE 6 — Fix 6.X: HTTP client con auto-refresh de access_token
# ═══════════════════════════════════════════════════════════════

# Paths (sin host) que NO deben disparar refresh+retry — son los propios
# endpoints de auth, donde un 401 ES la respuesta correcta y reintentar
# sería un loop infinito (refresh → 401 → refresh → 401 …).
_AUTH_PATHS_NO_RETRY = (
    "/users/login",
    "/users/refresh",
    "/users/setup",
)


def _is_auth_endpoint(url: str) -> bool:
    """True si la URL apunta a un endpoint de autenticación.

    Comparamos por path (no por substring sobre el URL completo) para evitar
    falsos positivos si el host o un query param contienen las palabras
    'login' o 'refresh' por casualidad.
    """
    try:
        path = urlsplit(url).path
    except Exception:
        return False
    return any(path.endswith(p) for p in _AUTH_PATHS_NO_RETRY)


def _replace_auth_header(headers, new_token: str):
    """Devuelve una copia de `headers` con Authorization actualizado.

    - Preserva el case del nombre del header tal como lo pasó el caller
      (algunos servers son case-sensitive, aunque HTTP no lo exige).
    - Si no había Authorization, no lo agrega: si el caller no lo
      mandó originalmente, asumimos que el endpoint no lo necesita y
      no queremos cambiar la semántica del request.
    - Acepta dict o None; siempre retorna dict o None.
    """
    if not headers:
        return headers
    new_headers = dict(headers)
    for k in list(new_headers.keys()):
        if isinstance(k, str) and k.lower() == "authorization":
            new_headers[k] = f"Bearer {new_token}"
    return new_headers


class _HttpClient:
    """Wrapper drop-in de `requests` con auto-refresh ante 401.

    Expone la misma superficie que el módulo `requests` para los métodos
    más usados de la app (get/post/put/delete/patch/request) más los
    atributos que el código existente referencia por dotted-access
    (exceptions, Session, adapters, Response).

    Uso:
        from ui.api import http as requests
        r = requests.get(url, headers=_headers(), timeout=10)
        # Si vuelve 401, se intenta /users/refresh y se reintenta UNA vez.
    """

    # ── Passthrough al módulo `requests` real ────────────────
    # Permite que `from ui.api import http as requests` siga funcionando
    # cuando el código hace `requests.exceptions.X`, `requests.Session()`,
    # `requests.adapters.HTTPAdapter`, etc.
    exceptions = _requests.exceptions
    Session = _requests.Session
    adapters = _requests.adapters
    Response = _requests.Response

    # ── Métodos HTTP ──────────────────────────────────────────
    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def head(self, url, **kwargs):
        return self.request("HEAD", url, **kwargs)

    def options(self, url, **kwargs):
        return self.request("OPTIONS", url, **kwargs)

    def request(self, method, url, **kwargs):
        """Ejecuta el request; si 401 y procede, refresca y reintenta UNA vez."""
        # stream=True / files=... también funcionan sin tocar nada: se pasan
        # tal cual a requests.request.
        resp = _requests.request(method, url, **kwargs)

        # ── Decisiones para auto-refresh ──
        if resp.status_code != 401:
            return resp
        if _is_auth_endpoint(url):
            return resp

        # Import local para evitar ciclo a nivel de módulo
        # (session_manager → app.core.config → … podría tocar ui.api).
        try:
            from ui.session_manager import session  # noqa: WPS433
        except Exception:
            return resp

        if not session.refresh_token:
            return resp

        # Token que ya falló. Lo usamos como "marca" para que
        # try_refresh_access_token() detecte si otro thread ya renovó.
        expired_token = session.token

        if not session.try_refresh_access_token(expired_token=expired_token):
            # No se pudo renovar (sin red, refresh expirado, etc.).
            # El caller verá el 401 original y mostrará el diálogo
            # de re-login como hasta ahora.
            return resp

        # Cerramos el primer response para liberar la conexión del pool
        # antes de emitir el segundo. requests no lo hace solo si el body
        # no fue leído.
        try:
            resp.close()
        except Exception:
            pass

        # Actualizar Authorization si el caller la había pasado.
        new_kwargs = dict(kwargs)
        new_kwargs["headers"] = _replace_auth_header(kwargs.get("headers"), session.token)

        logger.debug("Auto-refresh: reintentando %s %s con token renovado", method, url)
        return _requests.request(method, url, **new_kwargs)


# Instancia global del cliente HTTP con auto-refresh.
#
# Convención de uso recomendada:
#     from ui.api import http as requests
#     r = requests.get(url, headers=_headers(), timeout=10)
http = _HttpClient()