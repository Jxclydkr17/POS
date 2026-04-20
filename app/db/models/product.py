from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime
from app.utils.dt import utcnow
from app.db.database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)

    # 🔢 Datos principales
    code = Column(String(50), unique=True, nullable=False, index=True)
    barcode = Column(String(100), nullable=True, unique=True, index=True)  
    name = Column(String(150), nullable=False)
    description = Column(String(500), nullable=True)

    # 🏷️ CABYS
    cabys_code = Column(String(50), nullable=True)         
    cabys_name = Column(String(500), nullable=True)        

    # 🧾 IVA
    tax_type = Column(String(100), nullable=True)
    # ── FASE 2 — Fix 2.1: Float → Numeric ──
    tax_rate = Column(Numeric(5, 2), nullable=True)

    # 🏷️ Categoría (RELACIÓN REAL)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)  # FASE 3
    category = relationship("Category", back_populates="products")

    # 🚚 Proveedor principal (legacy 1-a-1, se mantiene por compatibilidad)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)  # FASE 3
    supplier = relationship("Supplier", back_populates="products")

    # 🚚 Proveedores múltiples (relación M2M vía supplier_products)
    # ── FASE 4 — Fix 4.4: lazy="select" (default) en vez de "selectin".
    # "selectin" lanza una query extra automática en cada carga de producto.
    # Los endpoints que necesiten supplier_products deben usar
    # .options(selectinload(Product.supplier_products)) explícitamente. ──
    supplier_products = relationship(
        "SupplierProduct",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # 💰 Valores
    # ── FASE 2 — Fix 2.1: Float → Numeric para evitar redondeo IEEE 754 ──
    price = Column(Numeric(12, 2), nullable=False)
    cost = Column(Numeric(12, 2), nullable=True)

    # 📦 Stock
    stock = Column(Numeric(12, 3), nullable=False, default=0)
    min_stock = Column(Numeric(12, 3), nullable=True, default=3)

    # 📏 Unidad de medida
    unit_type = Column(String(10), nullable=False, default="Unid")

    # 🖼️ Imagen
    image_path = Column(String(255), nullable=True)

    # ⚙️ Estado
    is_active = Column(Boolean, default=True)

    # 🕒 Timestamps
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    is_pos_favorite = Column(Boolean, default=False)

    # ═══ FASE 1 ═══
    registro_fiscal_8707 = Column(String(12), nullable=True)
    tax_tarifa_code_override = Column(String(2), nullable=True)

    # ═══ FASE 2 ═══
    partida_arancelaria = Column(String(12), nullable=True)

    # ═══════════════════════════════════════════════════════════
    # FASE 3.1 — Campos nuevos v4.4 línea de detalle
    # ═══════════════════════════════════════════════════════════

    # Código de impuesto principal (nota 8). Default "01" = IVA.
    impuesto_code = Column(String(2), nullable=True, default="01")

    # Factor para IVA Bienes Usados (código 08 nota 8).
    # ── FASE 2 — Fix 2.1: Float → Numeric ──
    factor_calculo_iva = Column(Numeric(5, 4), nullable=True)

    # TipoTransaccion (nota 22): default para este producto.
    tipo_transaccion = Column(String(2), nullable=True)

    # Número VIN o Serie para vehículos/aeronaves/embarcaciones (máx 17).
    numero_vin_serie = Column(String(17), nullable=True)

    # Registro de medicamento (registro sanitario Ministerio de Salud).
    registro_medicamento = Column(String(100), nullable=True)

    # Forma farmacéutica (nota 19, código 3 posiciones).
    forma_farmaceutica = Column(String(3), nullable=True)

    # IVA cobrado a nivel de fábrica (nota 21).
    iva_cobrado_fabrica = Column(String(2), nullable=True)

    # Código de descuento default para este producto (nota 20).
    discount_code_default = Column(String(2), nullable=True, default="07")

    # ═══════════════════════════════════════════════════════════
    # FASE 3.5 — Datos para impuestos específicos (códigos 03-06)
    # ── FASE 2 — Fix 2.1: Todos Float → Numeric ──
    # ═══════════════════════════════════════════════════════════

    # Impuesto por unidad (obligatorio para códigos 03,04,05,06)
    imp_esp_impuesto_unidad = Column(Numeric(18, 5), nullable=True)

    # Porcentaje alcohol (obligatorio para código 04 bebidas alcohólicas)
    imp_esp_porcentaje = Column(Numeric(5, 2), nullable=True)

    # Volumen por unidad de consumo en mL (obligatorio para código 05)
    imp_esp_volumen_unidad_consumo = Column(Numeric(12, 3), nullable=True)

    # Cantidad de la unidad de medida (litros para 03, mL envase para 04/05)
    imp_esp_cantidad_unidad_medida = Column(Numeric(12, 3), nullable=True)

    def __repr__(self):
        return f"<Product(name='{self.name}', price={self.price}, unit={self.unit_type})>"