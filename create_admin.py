from app.db.database import SessionLocal
from app.db.models.user import User, ALL_PERMISSIONS
from passlib.context import CryptContext
import json

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_initial_user():
    db = SessionLocal()
    admin_user = User(
        username="admin",
        password=pwd_context.hash("123456"),
        full_name="Administrador",
        role="admin",
        is_active=True,
        permissions=json.dumps(ALL_PERMISSIONS),
    )
    db.add(admin_user)
    db.commit()
    db.close()
    print("✅ Usuario admin creado con éxito")

if __name__ == "__main__":
    create_initial_user()