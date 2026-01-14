# run.py

from app import create_app

app = create_app()

# --- ADICIONE ISTO AQUI PARA LIGAR O GOOGLE ---
# Isso carrega o gatilho DEPOIS que o site já ligou, evitando o erro 500
with app.app_context():
    try:
        import app.google.calendar_hooks
        print("✅ Gatilhos do Google Agenda ativados com sucesso!")
    except Exception as e:
        print(f"⚠️ Erro ao ativar gatilhos do Google: {e}")
# ----------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
