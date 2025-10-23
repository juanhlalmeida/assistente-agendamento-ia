
# app/routes.py
import os
import logging
import pytz
import google.generativeai as genai
from datetime import datetime, date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from sqlalchemy.orm import joinedload

# 🚀 CORREÇÃO: Importações de modelos corretas
from app.models.tables import Agendamento, Profissional, Servico, User, Barbearia 
from app.extensions import db
from app.models.tables import Barbearia 
from app.whatsapp_client import WhatsAppClient, sanitize_msisdn    
from app.services import ai_service 
from app.commands import reset_database_logic

# 🚀 CORREÇÃO: Reativadas importações do flask_login
from flask_login import login_required, current_user, login_user, logout_user 

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bp = Blueprint('main', __name__)

conversation_history = {}

# --- FUNÇÕES DE AUTENTICAÇÃO (REATIVADAS E CORRIGIDAS) ---

@bp.route('/', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Log se já estiver autenticado
        current_app.logger.info(f"Usuário já autenticado ({current_user.email}), redirecionando para agenda.")
        return redirect(url_for('main.agenda'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        current_app.logger.info(f"Tentativa de login para o email: {email}")
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            current_app.logger.info(f"Usuário encontrado no banco: {user.email} (ID: {user.id})")
            # Log ANTES de verificar a senha
            current_app.logger.info("Verificando senha...")
            
            # Verifica a senha
            if user.check_password(password):
                current_app.logger.info(f"Senha CORRETA para {user.email}. Realizando login.")
                
                # Faz o login do usuário
                login_user(user, remember=request.form.get('remember-me') is not None)
                
                # Log APÓS o login_user
                current_app.logger.info(f"Função login_user executada. Usuário {user.email} deve estar na sessão.")
                
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('main.agenda')
                flash('Login realizado com sucesso!', 'success')
                return redirect(next_page)
            else:
                # Log se a senha estiver incorreta
                current_app.logger.warning(f"Senha INCORRETA para o email: {email}")
                flash('Email ou senha inválidos.', 'danger')
        else:
            # Log se o usuário não for encontrado
            current_app.logger.warning(f"Usuário NÃO encontrado no banco para o email: {email}")
            flash('Email ou senha inválidos.', 'danger')
            
    # Se for GET ou se o login falhar no POST, mostra a página de login
    return render_template('login.html')


@bp.route('/logout')
@login_required # Protege a rota de logout
def logout():
    logout_user() # Desloga o usuário
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('main.login')) # Redireciona para a página de login

# --- FUNÇÕES DO PAINEL WEB (COM MULTI-TENANCY E LOGIN) ---
def _range_do_dia(dia_dt: datetime):
    inicio = datetime.combine(dia_dt.date(), time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim

def calcular_horarios_disponiveis_web(profissional: Profissional, dia_selecionado: datetime):
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    HORA_INICIO_TRABALHO = 9
    HORA_FIM_TRABALHO = 20
    INTERVALO_MINUTOS = 30
    horarios_disponiveis = []
    horario_iteracao = sao_paulo_tz.localize(dia_selecionado.replace(hour=HORA_INICIO_TRABALHO, minute=0, second=0, microsecond=0))
    fim_do_dia = sao_paulo_tz.localize(dia_selecionado.replace(hour=HORA_FIM_TRABALHO, minute=0, second=0, microsecond=0))
    inicio, fim = _range_do_dia(dia_selecionado)
    # Busca agendamentos APENAS do profissional selecionado
    agendamentos_do_dia = (
        Agendamento.query
        .options(joinedload(Agendamento.servico))
        .filter(Agendamento.profissional_id == profissional.id) 
        .filter(Agendamento.data_hora >= inicio, Agendamento.data_hora < fim)
        .all()
    )
    intervalos_ocupados = []
    for ag in agendamentos_do_dia:
        inicio_ocupado = sao_paulo_tz.localize(ag.data_hora) if ag.data_hora.tzinfo is None else ag.data_hora.astimezone(sao_paulo_tz)
        fim_ocupado = inicio_ocupado + timedelta(minutes=ag.servico.duracao)
        intervalos_ocupados.append((inicio_ocupado, fim_ocupado))
        
    agora = datetime.now(sao_paulo_tz)
    
    while horario_iteracao < fim_do_dia:
        esta_ocupado = any(i <= horario_iteracao < f for i, f in intervalos_ocupados)
        if not esta_ocupado and horario_iteracao > agora:
            # Retorna o objeto datetime com timezone para o template
            horarios_disponiveis.append(horario_iteracao) 
        horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)
    return horarios_disponiveis


@bp.route('/agenda', methods=['GET', 'POST'])
@login_required # 🚀 CORREÇÃO: Login reativado!
def agenda():
    # --- LÓGICA MULTI-TENANCY ---
    if not hasattr(current_user, 'role'):
         flash('Erro de configuração da conta de usuário.', 'danger')
         logout_user()
         return redirect(url_for('main.login'))

    if current_user.role == 'super_admin':
         flash('Área restrita para administradores de barbearia.', 'warning')
         return redirect(url_for('main.login')) # Ou uma página de admin global futura

    barbearia_id_logada = current_user.barbearia_id
    if not barbearia_id_logada:
        flash('Erro: Usuário não associado a uma barbearia.', 'danger')
        logout_user() 
        return redirect(url_for('main.login'))
    # --- FIM DA LÓGICA ---

    if request.method == 'POST':
        nome_cliente = request.form.get('nome_cliente')
        telefone_cliente = request.form.get('telefone_cliente')
        data_hora_str = request.form.get('data_hora')
        profissional_id = request.form.get('profissional_id')
        servico_id = request.form.get('servico_id')
        
        if not all([nome_cliente, telefone_cliente, data_hora_str, profissional_id, servico_id]):
            flash('Erro: Todos os campos são obrigatórios.', 'danger')
            return redirect(url_for('main.agenda'))
            
        try:
            # Verifica se o profissional e serviço pertencem à barbearia logada
            profissional = Profissional.query.filter_by(id=profissional_id, barbearia_id=barbearia_id_logada).first()
            if not profissional:
                flash('Profissional inválido ou não pertence à sua barbearia.', 'danger')
                raise ValueError("Profissional inválido.")

            servico = Servico.query.filter_by(id=servico_id, barbearia_id=barbearia_id_logada).first()
            if not servico:
                 flash('Serviço inválido ou não pertence à sua barbearia.', 'danger')
                 raise ValueError("Serviço inválido.")
            
            novo_inicio = datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M')
            novo_fim = novo_inicio + timedelta(minutes=servico.duracao)
            inicio_dia, fim_dia = _range_do_dia(novo_inicio)

            # Verifica conflitos APENAS para esta barbearia e profissional
            ags = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(
                    Agendamento.barbearia_id == barbearia_id_logada, 
                    Agendamento.profissional_id == profissional.id,
                    Agendamento.data_hora >= inicio_dia, 
                    Agendamento.data_hora < fim_dia
                )
                .all()
            )
            conflito = any(
                max(novo_inicio, ag.data_hora) < min(novo_fim, ag.data_hora + timedelta(minutes=ag.servico.duracao))
                for ag in ags
            )

            if conflito:
                flash('Erro: O profissional já está ocupado neste horário.', 'danger')
            else:
                novo_agendamento = Agendamento(
                    nome_cliente=nome_cliente,
                    telefone_cliente=telefone_cliente,
                    data_hora=novo_inicio,
                    profissional_id=profissional.id,
                    servico_id=servico.id,
                    barbearia_id=barbearia_id_logada 
                )
                db.session.add(novo_agendamento)
                db.session.commit()
                flash('Agendamento criado com sucesso!', 'success')
        except ValueError as ve: # Captura erros de validação específicos
             # O flash já foi dado dentro do 'try'
             pass # Apenas evita o flash genérico abaixo
        except Exception as e:
            db.session.rollback() 
            flash(f'Ocorreu um erro ao processar o agendamento: {str(e)}', 'danger')
            
        redirect_date_str = (novo_inicio if 'novo_inicio' in locals() else datetime.now()).strftime('%Y-%m-%d')
        prof_id_redirect = profissional_id if 'profissional_id' in locals() and profissional_id else None 
        
        # Garante que estamos a redirecionar para um prof_id válido desta barbearia
        if prof_id_redirect:
             prof_check = Profissional.query.filter_by(id=prof_id_redirect, barbearia_id=barbearia_id_logada).first()
             if not prof_check:
                  prof_id_redirect = None # Reseta se for inválido

        return redirect(url_for('main.agenda', data=redirect_date_str, profissional_id=prof_id_redirect))
    
    # --- Lógica GET (Filtros Multi-Tenancy) ---
    data_sel_str = request.args.get('data', date.today().strftime('%Y-%m-%d'))
    profissional_sel_id = request.args.get('profissional_id')
    try:
        data_sel = datetime.strptime(data_sel_str, '%Y-%m-%d')
    except ValueError:
        flash('Data inválida fornecida.', 'warning')
        data_sel = datetime.combine(date.today(), time.min) # Usa hoje como fallback
        data_sel_str = data_sel.strftime('%Y-%m-%d')

    # Busca APENAS profissionais desta barbearia
    profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Profissional.nome).all()
    # Busca APENAS serviços desta barbearia
    servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    
    horarios_disponiveis = []
    profissional_sel = None

    if profissional_sel_id:
        profissional_sel = Profissional.query.filter_by(id=profissional_sel_id, barbearia_id=barbearia_id_logada).first()
        if not profissional_sel and profissionais:
             profissional_sel = profissionais[0]
    elif profissionais: 
        profissional_sel = profissionais[0]

    if profissional_sel:
        horarios_disponiveis = calcular_horarios_disponiveis_web(profissional_sel, data_sel) 
        
    inicio, fim = _range_do_dia(data_sel)
    # Busca APENAS agendamentos desta barbearia para o dia
    ags_dia = (
        Agendamento.query
        .options(joinedload(Agendamento.servico), joinedload(Agendamento.profissional))
        .filter(
            Agendamento.barbearia_id == barbearia_id_logada, 
            Agendamento.data_hora >= inicio, 
            Agendamento.data_hora < fim
        )
        # Se um profissional foi selecionado no filtro, filtra a lista principal também
        .filter(Agendamento.profissional_id == profissional_sel.id if profissional_sel else True) 
        .order_by(Agendamento.data_hora.asc())
        .all()
    )

    return render_template(
        'agenda.html',
        agendamentos=ags_dia,
        profissionais=profissionais, 
        servicos=servicos,           
        horarios_disponiveis=horarios_disponiveis,
        data_selecionada=data_sel,
        profissional_selecionado=profissional_sel 
    )

@bp.route('/agendamento/excluir/<int:agendamento_id>', methods=['POST'])
@login_required # 🚀 CORREÇÃO: Login reativado
def excluir_agendamento(agendamento_id):
    # --- LÓGICA MULTI-TENANCY ---
    barbearia_id_logada = current_user.barbearia_id
    # Busca o agendamento E garante que pertence à barbearia logada
    ag = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=barbearia_id_logada).first_or_404("Agendamento não encontrado ou não pertence à sua barbearia.")
    # --- FIM DA LÓGICA ---
    
    data_redirect = ag.data_hora.strftime('%Y-%m-%d')
    prof_redirect = ag.profissional_id
    try:
        db.session.delete(ag)
        db.session.commit()
        flash('Agendamento excluído com sucesso!', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir agendamento: {str(e)}', 'danger')
        
    return redirect(url_for('main.agenda', data=data_redirect, profissional_id=prof_redirect))

@bp.route('/agendamento/editar/<int:agendamento_id>', methods=['GET', 'POST'])
@login_required # 🚀 CORREÇÃO: Login reativado
def editar_agendamento(agendamento_id):
    # --- LÓGICA MULTI-TENANCY ---
    barbearia_id_logada = current_user.barbearia_id
    # Busca o agendamento E garante que pertence à barbearia logada
    ag = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=barbearia_id_logada).first_or_404("Agendamento não encontrado ou não pertence à sua barbearia.")
    # --- FIM DA LÓGICA ---

    if request.method == 'POST':
        try:
            # Valida profissional e serviço (se pertencem à barbearia)
            novo_profissional_id = int(request.form.get('profissional_id'))
            novo_servico_id = int(request.form.get('servico_id'))
            
            prof = Profissional.query.filter_by(id=novo_profissional_id, barbearia_id=barbearia_id_logada).first()
            serv = Servico.query.filter_by(id=novo_servico_id, barbearia_id=barbearia_id_logada).first()
            
            if not prof or not serv:
                 flash('Profissional ou Serviço inválido para esta barbearia.', 'danger')
                 raise ValueError("Profissional ou Serviço inválido.")

            ag.nome_cliente = request.form.get('nome_cliente')
            ag.telefone_cliente = request.form.get('telefone_cliente')
            ag.data_hora = datetime.strptime(request.form.get('data_hora'), '%Y-%m-%dT%H:%M')
            ag.profissional_id = novo_profissional_id
            ag.servico_id = novo_servico_id
            
            # (Opcional: Adicionar verificação de conflito aqui também)
            
            db.session.commit()
            flash('Agendamento atualizado com sucesso!', 'success')
            return redirect(url_for('main.agenda',
                                    data=ag.data_hora.strftime('%Y-%m-%d'),
                                    profissional_id=ag.profissional_id))
        except ValueError as ve:
             # Flash já foi dado no 'try'
             pass
        except Exception as e:
             db.session.rollback()
             flash(f'Erro ao atualizar agendamento: {str(e)}', 'danger')
             # Recarrega a página de edição em caso de erro
             return redirect(url_for('main.editar_agendamento', agendamento_id=agendamento_id))

    
    # --- Lógica GET (Filtros Multi-Tenancy) ---
    # Busca APENAS profissionais e serviços desta barbearia para os dropdowns
    profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Profissional.nome).all()
    servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    
    return render_template('editar_agendamento.html',
                           agendamento=ag, profissionais=profissionais, servicos=servicos)

# --- WEBHOOK (Já estava OK com Multi-Tenancy) ---
@bp.route('/webhook', methods=['POST'])
def webhook():
    data = request.values
    logging.info("PAYLOAD RECEBIDO DA TWILIO: %s", data)
    
    try:
        msg_text = data.get('Body')
        from_number_raw = data.get('From')
        to_number_raw = data.get('To') 
        
        if not from_number_raw or not msg_text or not to_number_raw:
            logging.warning("Webhook da Twilio recebido sem 'From', 'Body' ou 'To'.")
            # Retorna OK mesmo se faltar dados para evitar retentativas da Twilio
            return 'OK', 200 
        
        from_number = sanitize_msisdn(from_number_raw)
        barbearia_phone = sanitize_msisdn(to_number_raw)

        barbearia = Barbearia.query.filter_by(telefone_whatsapp=barbearia_phone).first()

        if not barbearia:
            logging.error(f"CRÍTICO: Nenhuma barbearia encontrada para o número {barbearia_phone}. Ignorando mensagem.")
            return 'OK', 200 
        
        if barbearia.status_assinatura != 'ativa':
             logging.warning(f"Mensagem recebida para barbearia '{barbearia.nome_fantasia}' com assinatura '{barbearia.status_assinatura}'. Ignorando.")
             # (Opcional: enviar msg de "serviço suspenso" )
             # client = WhatsAppClient()
             # client.send_text(from_number, "Desculpe, nosso serviço de agendamento está temporariamente suspenso.")
             return 'OK', 200
             
        barbearia_id = barbearia.id
        logging.info(f"Mensagem roteada para Barbearia ID: {barbearia_id} ({barbearia.nome_fantasia})")
        
        if ai_service.model is None:
            logging.error("Modelo da IA não inicializado. Usando fallback.")
            reply_text = "Olá! Estamos com um problema técnico em nossa IA. Tente novamente em breve, por favor."
            client = WhatsAppClient()
            client.send_text(from_number, reply_text)
            return 'OK', 200
        
        history_key = f"{barbearia_id}:{from_number}"
        historico_atual = conversation_history.get(history_key, [])
        
        if not historico_atual:
            # TODO: O template da IA precisa ser ajustado para receber as datas dinamicamente
            # current_date_str = datetime.now().strftime('%d de %B de %Y')
            # next_date_str = (datetime.now() + timedelta(days=1)).strftime('%d de %B de %Y')
            # system_instruction_filled = ai_service.SYSTEM_INSTRUCTION_TEMPLATE.format(current_date=current_date_str, next_date=next_date_str)
            # A inicialização do chat deveria usar isso, mas precisa refatorar o ai_service
            
            # Por agora, mantemos o fluxo simples
             current_date_str = datetime.now().strftime('%d de %B de %Y')
             historico_atual = [
                 {"role": "user", "parts": [f"[CONTEXTO DO SISTEMA: Hoje é {current_date_str}]"]},
                 {"role": "model", "parts": ["Entendido. Como posso ajudá-lo?"]}
             ]

        # TODO: Refatorar ai_service para inicializar o model DENTRO da requisição ou usar um cache melhor
        # A forma atual pode ter problemas com concorrência ou contexto errado.
        # Por agora, vamos assumir que o model global funciona.
        
        chat_session = ai_service.model.start_chat(history=historico_atual)
        response = chat_session.send_message(msg_text)
        
        while response.parts and any(part.function_call for part in response.parts):
            for part in response.parts:
                if part.function_call:
                    func_name = part.function_call.name
                    args = dict(part.function_call.args)
                    
                    logging.info(f"IA solicitou a ferramenta '{func_name}' com os argumentos: {args}")
                    
                    result = "Erro interno ao chamar ferramenta." # Valor padrão
                    try:
                        if func_name == 'criar_agendamento':
                            # Garante que o telefone_cliente está no formato correto (+55...)
                            # A função sanitize_msisdn remove o 'whatsapp:', então precisamos adicionar '+'
                            args['telefone_cliente'] = f"+{from_number}" 
                            result = ai_service.criar_agendamento(barbearia_id=barbearia_id, **args)
                        elif func_name == 'listar_profissionais':
                            result = ai_service.listar_profissionais(barbearia_id=barbearia_id)
                        elif func_name == 'listar_servicos':
                            result = ai_service.listar_servicos(barbearia_id=barbearia_id)
                        elif func_name == 'calcular_horarios_disponiveis':
                            result = ai_service.calcular_horarios_disponiveis(barbearia_id=barbearia_id, **args)
                        else:
                            result = "Ferramenta desconhecida."
                    except Exception as tool_exc:
                         logging.error(f"Erro ao executar a ferramenta '{func_name}': {tool_exc}", exc_info=True)
                         result = f"Desculpe, ocorreu um erro ao tentar {func_name.replace('_', ' ')}."

                    function_response = genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=func_name,
                            response={"result": result}
                        )
                    )
                    response = chat_session.send_message([function_response])
        
        reply_text = response.text
        client = WhatsAppClient()
        # Garante que estamos a enviar para o número correto (+55...)
        api_res = client.send_text(f"+{from_number}", reply_text) 
        
        if api_res.get("status") not in ('queued', 'sent', 'delivered', 'accepted'): # Adicionado 'accepted'
            logging.error("Falha no envio da resposta da IA via Twilio: %s", api_res)
        
        conversation_history[history_key] = chat_session.history
        
    except Exception as e:
        # Loga o erro
        logging.error("Erro CRÍTICO no processamento do webhook: %s", e, exc_info=True)
        # --- CORREÇÃO: Adiciona o return DENTRO do except ---
        # Responde OK para a Twilio mesmo se houver erro, 
        # para evitar que ela tente reenviar a mesma mensagem.
        return 'OK', 200 
        # --------------------------------------------------
    
    # Este return é para o caso de sucesso (nenhuma exceção ocorreu)
    return 'OK', 200

# --- ROTAS SECRETAS ---
@bp.route('/admin/reset-database/<string:secret_key>')
def reset_database(secret_key):
    expected_key = os.getenv('RESET_DB_KEY')
    
    if not expected_key or secret_key != expected_key:
        abort(404) 
    
    try:
        logging.info("Iniciando o reset do banco de dados via rota segura...")
        # Chama a lógica no commands.py (que já está corrigida no seu Git)
        reset_database_logic() 
        logging.info("Banco de dados recriado com sucesso.")
        
        # --- CORREÇÃO DEFINITIVA: Adiciona o return para o caso de sucesso ---
        return "<h1>Banco de dados recriado com sucesso!</h1><p>Pode tentar fazer login agora.</p>", 200 
        # --------------------------------------------------------------------
        
    except Exception as e:
        # Garante rollback se o reset_database_logic falhar
        # (Embora a própria função já tenha um rollback interno)
        # db.session.rollback() # Pode ser redundante, mas seguro
        logging.error("Erro ao recriar o banco de dados: %s", e, exc_info=True)
        # Mantém o return para o caso de erro
        return f"<h1>Ocorreu um erro ao recriar o banco de dados:</h1><p>{str(e)}</p>", 500 

@bp.route('/admin/criar-primeiro-usuario/<secret_key>')
def criar_primeiro_usuario(secret_key):
    """
    Esta rota agora pode funcionar novamente, mas o ideal é criar
    o usuário via reset ou um futuro painel super-admin.
    """
    expected_key = os.getenv('ADMIN_KEY')
    if not expected_key or secret_key != expected_key:
        abort(404) 

    email_admin = "admin@email.com" 
    user = User.query.filter_by(email=email_admin).first()
    if user:
        return f"O usuário '{email_admin}' já existe."

    try:
        senha_admin = "admin123" 
        
        # Precisamos de uma barbearia para associar! Vamos pegar a primeira?
        # Ou talvez esta rota devesse receber o ID da barbearia?
        # Por agora, vamos assumir que só há uma barbearia (ID 1)
        barbearia_teste = Barbearia.query.get(1)
        if not barbearia_teste:
             return "Erro: Nenhuma barbearia encontrada no banco para associar o usuário.", 500

        u = User(email=email_admin, nome='Admin Criado Via Rota', role='admin', barbearia_id=barbearia_teste.id)
        u.set_password(senha_admin)
        db.session.add(u)
        db.session.commit()
        msg = f"Usuário '{email_admin}' (Senha: '{senha_admin}') foi criado com sucesso para a Barbearia ID {barbearia_teste.id}!"
        current_app.logger.info(msg)
        return msg
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao criar usuário admin via rota: {e}")
        return f"Ocorreu um erro: {e}", 500
