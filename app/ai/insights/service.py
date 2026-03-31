from datetime import date, datetime, timedelta
from app.utils.dt import today_cr
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models.sale import Sale
from app.db.models.product import Product
from app.db.models.cash_session import CashSession
from app.db.models.customer import Customer
from .rules import estimated_lost_revenue
from .rules import suggested_purchase_quantity
from .customers_data import get_customers_credit_base_data
from app.ai.insights.credit_alerts import get_customers_near_credit_limit
from app.ai.kpis.credit_usage_kpi import get_top_credit_usage_clients

from .predictions import predict_sales_next_7_days_avg
from .schemas import Insight, InsightsResponse
from .rules import (
    sales_drop_percentage,
    sales_drop_level,
    stock_level,
    credit_risk_level,
    build_daily_series,
    predict_today_sales,
    should_raise_sales_prediction_alert,
)

from app.db.models.sale_detail import SaleDetail
from app.db.models.supplier import Supplier
from app.db.models.purchase import Purchase
from .rules import (
    avg_daily_consumption,
    stock_coverage_days,
    stock_break_risk_level,
)


def get_today_insights(db: Session) -> InsightsResponse:
    alerts: list[Insight] = []

    today = today_cr()
    start_today = datetime.combine(today, datetime.min.time())
    end_today = datetime.combine(today, datetime.max.time())

    # -------------------------------------------------
    # 1️⃣ VENTAS DE HOY + PREDICCIÓN (estable)
    # -------------------------------------------------
    today_sales = float(
        db.query(func.sum(Sale.total))
        .filter(Sale.created_at >= start_today)
        .filter(Sale.created_at <= end_today)
        .scalar()
        or 0.0
    )

    # --- Serie completa últimos 14 días (incluye ceros) ---
    # Ventana: 14 días incluyendo HOY
    series_days = 14
    start_window_day = (today - timedelta(days=series_days - 1))  # incluye hoy
    start_window_dt = datetime.combine(start_window_day, datetime.min.time())

    # Traemos sumas por día (solo días con ventas), luego rellenamos huecos con 0
    rows = (
        db.query(func.date(Sale.created_at), func.sum(Sale.total))
        .filter(Sale.created_at >= start_window_dt)
        .filter(Sale.created_at <= end_today)
        .group_by(func.date(Sale.created_at))
        .all()
    )

    daily_series_including_today = build_daily_series(
        rows=[(r[0], float(r[1] or 0.0)) for r in rows],
        start_day=start_window_day,
        end_day=today,
    )

    # Para el "promedio semanal" y la predicción usamos HISTORIAL sin hoy
    history_excl_today = daily_series_including_today[:-1]  # últimos 13 días
    last_7_avg = (sum(history_excl_today[-7:]) / 7) if len(history_excl_today) >= 7 else 0.0

    # 1) Regla actual: caída vs promedio semanal (pero estable, incluye ceros)
    drop_pct_vs_avg = sales_drop_percentage(today_sales, last_7_avg)
    if last_7_avg > 0 and drop_pct_vs_avg >= 20:
        alerts.append(
            Insight(
                type="sales",
                level="warning",
                message="Ventas de hoy por debajo del promedio",
                meta={
                    "action": "open_sales_history",
                    "today_sales": today_sales,
                    "avg_last_7": last_7_avg,
                    "drop_pct_vs_avg": drop_pct_vs_avg,
                }
            )
        )

    # 2) Predicción: promedio móvil últimos 7 días (incluye ceros)
    predicted_today = predict_today_sales(history_excl_today, window=7)
    should_alert, drop_pct_vs_pred = should_raise_sales_prediction_alert(
        today_sales=today_sales,
        predicted_sales=predicted_today,
        threshold_pct=25.0,    # ajustable
        min_predicted=0.0,     # si querés menos ruido: poné 5000 o 10000
    )

    if should_alert:
        alerts.append(
            Insight(
                type="sales",
                level="warning",
                message="Predicción por debajo de lo esperado",
                meta={
                    "action": "open_sales_history",
                    "predicted_today": predicted_today,
                    "today_sales": today_sales,
                    "drop_pct_vs_pred": drop_pct_vs_pred,
                }
            )
        )

    # -------------------------------------------------
    # 2️⃣ STOCK BAJO / CRÍTICO
    # -------------------------------------------------
    products = (
        db.query(Product)
        .filter(Product.is_active == True)
        .all()
    )

    for p in products:
        level = stock_level(p.stock, p.min_stock)
        if level:
            alerts.append(
                Insight(
                    type="stock",
                    level=level,
                    message=f"Stock bajo — {p.name}",
                    reference=str(p.id),
                    meta={
                        "action": "open_low_stock",
                        "product_name": p.name,
                        "current_stock": int(p.stock or 0),
                    }
                )
            )

    # -------------------------------------------------
    # 3️⃣ CAJA DE HOY
    # -------------------------------------------------
    cash_session = (
        db.query(CashSession)
        .filter(CashSession.date == today)
        .first()
    )

    if cash_session and cash_session.status == "closed":
        if cash_session.difference and cash_session.difference < 0:
            alerts.append(
                Insight(
                    type="cash",
                    level="warning",
                    message=(
                        f"La caja cerró con una diferencia negativa de "
                        f"₡{abs(cash_session.difference):,.2f}."
                    ),
                    meta={
                        "action": "open_cash",
                        "balance": cash_session.difference,
                    }
                )
            )

    # -------------------------------------------------
    # 4️⃣ CRÉDITOS EN RIESGO
    # -------------------------------------------------
    customers = (
        db.query(Customer)
        .filter(Customer.credit_balance > 0)
        .all()
    )

    for c in customers:
        level = credit_risk_level(c.credit_balance)
        if level:
            alerts.append(
                Insight(
                    type="credit",
                    level=level,
                    message=f"Crédito pendiente — {c.name}",
                    reference=str(c.id),
                    meta={
                        "action": "open_customer_credit",
                        "customer_name": c.name,
                        "credit_balance": c.credit_balance,
                    }
                )
            )

    # -------------------------------------------------
    # 5️⃣ PREDICCIÓN SIMPLE (OPCIONAL, SEGURA)
    # -------------------------------------------------
    pred = predict_sales_next_7_days_avg(db)

    if pred:
        level = "info"
        if pred.trend_pct <= -15:
            level = "warning"

        alerts.append(
            Insight(
                type="sales",
                level=level,
                message="Proyección semanal de ventas",
                meta={
                    "action": "open_sales_history",
                    "forecast_avg": pred.forecast_avg_next_7,
                    "avg_last_7": pred.avg_last_7,
                    "avg_prev_7": pred.avg_prev_7,
                    "trend_pct": pred.trend_pct,
                }
            )
        )

    # -------------------------------------------------
    # 2️⃣.2 PREDICCIÓN DE QUIEBRE DE STOCK
    # -------------------------------------------------
    lookback_days = 14
    start_lookback = start_today - timedelta(days=lookback_days)

    # Consumo real por producto (cantidad vendida)
    consumption_rows = (
        db.query(
            Product.id,
            Product.name,
            Product.stock,
            func.sum(SaleDetail.quantity),
            func.avg(SaleDetail.unit_price)
        )
        .join(SaleDetail, SaleDetail.product_id == Product.id)
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .filter(Sale.created_at >= start_lookback)
        .group_by(Product.id)
        .all()
    )

    for product_id, name, stock, total_sold, avg_price in consumption_rows:
        total_sold = float(total_sold or 0.0)
        stock = int(stock or 0)

        daily_consumption = avg_daily_consumption(
            total_sold=total_sold,
            days=lookback_days
        )

        coverage = stock_coverage_days(
            stock=stock,
            daily_consumption=daily_consumption
        )
        
        avg_price = float(avg_price or 0.0)

        # Si se quiebra, estimamos días sin stock (máx 7 para no exagerar)
        if coverage is None or coverage == float("inf"):
            days_without_stock = 0.0
        else:
            days_without_stock = max(0.0, 7 - coverage)


        lost_revenue = estimated_lost_revenue(
            daily_consumption=daily_consumption,
            avg_price=avg_price,
            days_without_stock=days_without_stock
        )

        suggested_qty = suggested_purchase_quantity(
            daily_consumption=daily_consumption,
            current_stock=stock,
            target_days=7
        )


        level = stock_break_risk_level(coverage)

        if level:
            alerts.append(
                Insight(
                    type="stock",
                    level=level,
                    message=f"Riesgo de quiebre — {name}",
                    reference=str(product_id),
                    meta={
                        "action": "open_low_stock",
                        "product_name": name,
                        "current_stock": stock,
                        "coverage_days": coverage,
                        "restock_suggested": True,
                        "lost_revenue": lost_revenue,
                        "suggested_qty": suggested_qty,
                    }
                )
            )

    # -------------------------------------------------
    # 🏭 2.1 ALERTA: PROVEEDOR CON PRODUCTOS EN STOCK CRÍTICO
    # -------------------------------------------------
    # Agrupamos productos críticos (stock <= min_stock) por supplier_id
    critical_by_supplier: dict[int, dict] = {}

    for p in products:
        if p.stock <= p.min_stock and p.supplier_id:
            entry = critical_by_supplier.setdefault(
                p.supplier_id,
                {"count": 0, "name": None}
            )
            entry["count"] += 1

    # Resolver nombres de proveedores en un solo query
    if critical_by_supplier:
        supplier_ids = list(critical_by_supplier.keys())
        suppliers_rows = (
            db.query(Supplier.id, Supplier.name)
            .filter(Supplier.id.in_(supplier_ids))
            .all()
        )
        for sid, sname in suppliers_rows:
            if sid in critical_by_supplier:
                critical_by_supplier[sid]["name"] = sname

    # Emitir alerta por proveedor (limitado a top 10 por impacto)
    supplier_critical_sorted = sorted(
        critical_by_supplier.items(),
        key=lambda x: x[1]["count"],
        reverse=True
    )[:5]

    for supplier_id, info in supplier_critical_sorted:
        count = info["count"]
        name = info["name"] or f"Proveedor #{supplier_id}"
        level = "critical" if count >= 5 else "warning"
        alerts.append(
            Insight(
                type="supplier",
                level=level,
                message=f"⚠ {name} tiene {count} productos en stock crítico.",
                reference=str(supplier_id),
                meta={
                    "supplier_name": name,
                    "critical_count": count,
                    "action": "open_supplier_products",
                }
            )
        )

    # -------------------------------------------------
    # 🏭 2.2 ALERTA: SIN COMPRAS EN 90+ DÍAS
    # -------------------------------------------------
    threshold_days = 90

    # MAX(entry_date) por proveedor activo
    purchase_rows = (
        db.query(Purchase.supplier_id, func.max(Purchase.entry_date))
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .filter(Supplier.is_active == True)
        .group_by(Purchase.supplier_id)
        .all()
    )
    last_purchase_map: dict[int, date | None] = {
        row[0]: row[1] for row in purchase_rows
    }

    # Proveedores activos que nunca tuvieron compra o llevan 90+ días
    active_suppliers = (
        db.query(Supplier)
        .filter(Supplier.is_active == True)
        .all()
    )

    inactive_alerts = []
    for s in active_suppliers:
        last_date = last_purchase_map.get(s.id)
        if last_date is None:
            days_since = None
            last_str = "Nunca"
        else:
            # last_date puede ser date o datetime
            if hasattr(last_date, "date"):
                last_date = last_date.date()
            days_since = (today - last_date).days
            last_str = str(last_date)

        if days_since is None or days_since >= threshold_days:
            inactive_alerts.append((days_since or 9999, s.id, s.name, last_str, days_since))

    # Ordenar por días desc, limitar top 10
    inactive_alerts.sort(key=lambda x: -x[0])
    for _, supplier_id, supplier_name, last_str, days_since in inactive_alerts[:5]:
        days_label = days_since if days_since is not None else "?"
        alerts.append(
            Insight(
                type="supplier",
                level="warning",
                message=f"Proveedor inactivo — {supplier_name}",
                reference=str(supplier_id),
                meta={
                    "supplier_name": supplier_name,
                    "last_purchase_date": last_str,
                    "days": days_label,
                    "action": "open_supplier_purchases",
                }
            )
        )

    # -------------------------------------------------
    # 🔢 PRIORIDAD DE ALERTAS (impacto económico + nivel)
    # -------------------------------------------------
    LEVEL_WEIGHT = {
        "critical": 3,
        "warning": 2,
        "info": 1,
    }

    TYPE_WEIGHT = {
        "stock": 6,
        "credit": 5,
        "cash": 4,
        "supplier": 3,
        "sales": 2,
        "kpi": 1,
    }

    def alert_priority(alert: Insight):
        """
        Devuelve una tupla para ordenar alertas.
        Prioriza:
        1) relevancia operativa
        2) severidad
        3) impacto económico
        """
        message = alert.message or ""
        meta = alert.meta or {}

        impact = 0.0
        try:
            if "₡" in message:
                part = message.split("₡")[1]
                number = part.split()[0].replace(",", "")
                impact = float(number)
        except Exception:
            impact = 0.0

        alert_type_score = TYPE_WEIGHT.get(alert.type, 0)
        level_score = LEVEL_WEIGHT.get(alert.level, 0)

        # Bonus por datos operativos concretos
        operational_bonus = 0

        if alert.type == "stock":
            stock_now = meta.get("current_stock")
            if stock_now is not None:
                try:
                    stock_now = float(stock_now)
                    if stock_now <= 0:
                        operational_bonus += 3
                    elif stock_now <= 2:
                        operational_bonus += 2
                except Exception:
                    pass

        if alert.type == "credit":
            usage_percent = meta.get("usage_percent")
            if usage_percent is not None:
                try:
                    usage_percent = float(usage_percent)
                    if usage_percent >= 95:
                        operational_bonus += 3
                    elif usage_percent >= 85:
                        operational_bonus += 2
                except Exception:
                    pass

        if alert.type == "supplier":
            critical_count = meta.get("critical_count")
            if critical_count is not None:
                try:
                    critical_count = int(critical_count)
                    operational_bonus += min(critical_count, 3)
                except Exception:
                    pass

        return (
            -alert_type_score,
            -(level_score + operational_bonus),
            -impact,
        )
    
    
    # -------------------------------------------------
    # 💥 CLIENTES CERCA DEL LÍMITE DE CRÉDITO
    # -------------------------------------------------
    credit_alerts = get_customers_near_credit_limit(db)

    for a in credit_alerts:
        alerts.append(
            Insight(
                type="credit",
                level=a["level"],
                message=a["message"],  
                reference=str(a["customer_id"]),  
                meta={  
                    "action": "open_customer_credit",
                    "customer_name": a.get("customer_name"),
                    "usage_percent": a["usage_percent"],
                    "credit_balance": a["credit_balance"],
                    "credit_limit": a["credit_limit"]
                }
            )
        )

    # -------------------------------------------------
    # 📊 KPI – CLIENTES CON MAYOR USO DE CRÉDITO
    # -------------------------------------------------
    top_credit_users = get_top_credit_usage_clients(db, limit=5)

    if top_credit_users:
        alerts.append(
            Insight(
                type="kpi",
                level="info",
                message="Top clientes con mayor uso de crédito",  
                reference=None,
                meta={  
                    "action": "open_credit_ranking",
                    "description": "Top clientes que más porcentaje de su crédito han utilizado",
                    "items": top_credit_users
                }
            )
        )

    # -------------------------------------------------
    # 🔔 ALERTAS PROACTIVAS: INACTIVIDAD Y MOROSOS
    # -------------------------------------------------
    credit_data = get_customers_credit_base_data(db)

    for cd in credit_data:
        cid = cd["customer_id"]
        cname = cd["name"]

        # Cliente no compra hace > 60 días
        days_inactive = cd.get("days_since_last_sale")
        if days_inactive is not None and days_inactive > 60:
            lvl = "critical" if days_inactive > 90 else "warning"
            alerts.append(
                Insight(
                    type="credit",
                    level=lvl,
                    message=f"{cname} no compra hace {days_inactive} días",
                    reference=str(cid),
                    meta={
                        "action": "open_customer_credit",
                        "customer_name": cname,
                        "days_inactive": days_inactive,
                    }
                )
            )

        # Moroso: deuda + sin pago > 60 días
        balance = cd.get("credit_balance", 0)
        days_no_pay = cd.get("days_since_last_payment")
        if balance > 0 and days_no_pay is not None and days_no_pay > 60:
            lvl = "critical" if days_no_pay > 90 else "warning"
            alerts.append(
                Insight(
                    type="credit",
                    level=lvl,
                    message=f"{cname} lleva {days_no_pay} días sin abonar (₡{balance:,.0f})",
                    reference=str(cid),
                    meta={
                        "action": "open_customer_credit",
                        "customer_name": cname,
                        "credit_balance": balance,
                        "days_since_last_payment": days_no_pay,
                    }
                )
            )

        # Segmentación: etiquetas automáticas como insight info
        tags = cd.get("auto_tags", [])
        if "Moroso" in tags and "VIP" in tags:
            alerts.append(
                Insight(
                    type="credit",
                    level="critical",
                    message=f"⚠ {cname} es VIP pero está moroso",
                    reference=str(cid),
                    meta={
                        "action": "open_customer_credit",
                        "customer_name": cname,
                        "auto_tags": tags,
                        "total_all_amount": cd.get("total_all_amount", 0),
                    }
                )
            )


    
    # -------------------------------------------------
    # 🧠 RESUMEN GENERAL
    # -------------------------------------------------
    critical_count = sum(1 for a in alerts if a.level == "critical")
    warning_count = sum(1 for a in alerts if a.level == "warning")

    if not alerts:
        summary = "Todo se ve normal hoy 💚"
    elif critical_count > 0:
        summary = f"Hay {critical_count} alerta(s) crítica(s) y {warning_count} de atención para revisar hoy."
    else:
        summary = f"Se detectaron {warning_count} alerta(s) operativas para seguimiento hoy."

    alerts.sort(key=alert_priority)

    
    return InsightsResponse(
        summary=summary,
        alerts=alerts,
    )