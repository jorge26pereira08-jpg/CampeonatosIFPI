from app import app, init_db
with app.app_context():
    init_db()
    print("Banco de dados inicializado com sucesso.")
