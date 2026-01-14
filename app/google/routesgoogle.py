# app/google/routesgoogle.py

import os
from flask import Blueprint, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from google_auth_oauthlib.flow import Flow
from app.models.tables import Barbearia
from app.extensions import db
from app.google.google_calendar_service import CLIENT_SECRET_FILE, SCOPES

# Define o Blueprint
bp = Blueprint('google_auth', __name__, url_prefix='/google')

# Se estiver rodando local, permite HTTP. No Render (produção), exige HTTPS.
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' if os.environ.get('FLASK_ENV') == 'development' else '0'

@bp.route('/connect')
@login_required
def connect():
    """Inicia o processo de login no Google"""
    try:
        # Importa aqui para evitar ciclo
        from app.google.google_calendar_service import CLIENT_SECRET_FILE, SCOPES
        
        # Cria o fluxo
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRET_FILE,
            scopes=SCOPES,
            redirect_uri=url_for('google_auth.callback', _external=True)
        )
        
        # Gera o link de login
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=str(current_user.barbearia_id), # Passa o ID da barbearia no estado
            prompt='consent' # Força perguntar permissão para garantir o refresh_token
        )
        
        return redirect(authorization_url)
        
    except Exception as e:
        current_app.logger.error(f"Erro ao iniciar auth Google: {e}")
        flash('Erro ao conectar com Google. Verifique se o arquivo de credenciais existe.', 'danger')
        return redirect(url_for('dashboard.index'))

@bp.route('/callback')
def callback():
    """Recebe o usuário de volta do Google"""
    try:
        # Importa aqui
        from app.google.google_calendar_service import CLIENT_SECRET_FILE, SCOPES
        
        state = request.args.get('state')
        if not state:
            flash('Erro de validação do Google (State missing).', 'danger')
            return redirect(url_for('dashboard.index'))

        barbearia_id = int(state)
        
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRET_FILE,
            scopes=SCOPES,
            redirect_uri=url_for('google_auth.callback', _external=True)
        )
        
        # Troca o código temporário pelos tokens permanentes
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        
        # Salva no Banco de Dados
        barbearia = Barbearia.query.get(barbearia_id)
        if barbearia:
            barbearia.google_access_token = creds.token
            barbearia.google_refresh_token = creds.refresh_token
            db.session.commit()
            flash('✅ Google Agenda conectado com sucesso!', 'success')
        else:
            flash('Barbearia não encontrada.', 'danger')
            
        return redirect(url_for('dashboard.index'))
        
    except Exception as e:
        current_app.logger.error(f"Erro no callback Google: {e}")
        flash(f'Erro ao vincular Google Agenda: {str(e)}', 'danger')
        return redirect(url_for('dashboard.index'))
