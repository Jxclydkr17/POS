from app.db.database import SessionLocal
from app.db.models.user import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_initial_user():
    db = SessionLocal()
    # Hash de la contraseña
    hashed_password = pwd_context.hash("123456")
    
    admin_user = User(
        username="admin",
        email="admin@pos.com",
        hashed_password=hashed_password,
        full_name="Administrador",
        role="admin",  # O el rol que manejes
        is_active=True
    )
    
    db.add(admin_user)
    db.commit()
    db.close()
    print("✅ Usuario admin creado con éxito")

if __name__ == "__main__":
    create_initial_user()