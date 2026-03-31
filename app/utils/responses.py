from fastapi import HTTPException
from typing import Optional, Dict, Any

def success_response(message: str = "Operación exitosa", data: Any = None) -> Dict:
    """Respuesta de éxito estándar."""
    return {
        "success": True,
        "message": message,
        "data": data,
        "error": None
    }


def error_response(
    message: str, 
    status_code: int = 400, 
    error_details: Optional[Dict] = None
) -> None:
    """
    Respuesta de error estándar usando HTTPException.
    Lanza automáticamente la excepción con formato consistente.
    """
    raise HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "message": message,
            "data": None,
            "error": error_details or {"detail": message}
        }
    )