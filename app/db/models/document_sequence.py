# app/db/models/document_sequence.py
"""
Modelo SQLAlchemy para la tabla document_sequences.

Almacena el consecutivo por (sucursal, terminal, tipo de documento)
para la generación de claves de comprobantes electrónicos.

Antes esta tabla solo se creaba con SQL crudo (ON DUPLICATE KEY UPDATE)
en app/einvoice/sequence.py, lo que causaba que create_all() nunca
la generara y la primera factura fallara.
"""

from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from app.db.database import Base
from app.utils.dt import utcnow


class DocumentSequence(Base):
    __tablename__ = "document_sequences"

    id = Column(Integer, primary_key=True, autoincrement=True)

    branch_code = Column(String(3), nullable=False, default="001")
    terminal_code = Column(String(5), nullable=False, default="00001")
    document_type = Column(String(2), nullable=False)  # 01=FE, 04=TE, 10=REP, etc.

    next_number = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "branch_code", "terminal_code", "document_type",
            name="uq_branch_terminal_doctype"
        ),
    )

    def __repr__(self):
        return (
            f"<DocumentSequence {self.branch_code}-{self.terminal_code}-"
            f"{self.document_type} next={self.next_number}>"
        )