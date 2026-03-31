# app/db/models/purchase.py

from sqlalchemy import Column, Integer, String, Date, DateTime, DECIMAL, Enum, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.database import Base
import enum


class PurchaseStatus(str, enum.Enum):
    pendiente = "pendiente"
    recibido = "recibido"
    parcial = "parcial"
    pagado = "pagado"
    vencido = "vencido"


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True, index=True)

    invoice_number = Column(String(50), nullable=False, unique=True)

    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)

    entry_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)

    amount = Column(DECIMAL(12, 2), nullable=False)

    status = Column(
        Enum(PurchaseStatus),
        nullable=False,
        default=PurchaseStatus.pendiente,
    )

    notes = Column(Text)
    pdf_path = Column(String(255))

    payment_method = Column(String(50), nullable=True)
    paid_at = Column(Date, nullable=True)
    received_at = Column(Date, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    supplier = relationship("Supplier")
    details = relationship(
        "PurchaseDetail",
        back_populates="purchase",
        cascade="all, delete-orphan",
    )
    payments = relationship(
        "PurchasePayment",
        back_populates="purchase",
        cascade="all, delete-orphan",
    )
    credit_notes = relationship(
        "PurchaseCreditNote",
        back_populates="purchase",
        cascade="all, delete-orphan",
    )

    @property
    def items_count(self) -> int:
        return len(self.details) if self.details else 0

    @property
    def items(self):
        return self.details or []

    @property
    def paid_amount(self) -> float:
        """Suma de todos los abonos registrados."""
        if not self.payments:
            return 0.0
        return float(sum(p.amount for p in self.payments))

    @property
    def credit_notes_total(self) -> float:
        """Suma de todas las notas de crédito."""
        if not self.credit_notes:
            return 0.0
        return float(sum(cn.amount for cn in self.credit_notes))

    @property
    def balance(self) -> float:
        """Saldo pendiente = monto - abonos - notas de crédito."""
        return round(float(self.amount) - self.paid_amount - self.credit_notes_total, 2)
