"""
main.py — Punto de entrada único de Violette POS

USO:
    python main.py          → Levanta el backend en http://127.0.0.1:8000
    uvicorn app.main:app    → Equivalente directo

NOTA:
    Toda la lógica de la app (routers, startup events, middleware)
    vive en app/main.py.  Este archivo solo sirve como lanzador.
"""

import uvicorn


def main():
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        reload=False,       # En producción siempre False
    )


if __name__ == "__main__":
    main()