import sqlite3
import os
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from functools import wraps

app = Flask(__name__)
app.secret_key = 'ifpi_campeonatos_secret_key_2024'

DATABASE = os.path.join(os.path.dirname(__file__), 'db.sqlite3')

# ─────────────────────────────────────────────
# CONTROLE DE TENTATIVAS (em memória, sem imports externos)
# ─────────────────────────────────────────────
tentativas_senha = {}
tentativas_pergunta = {}

MAX_TENTATIVAS_SENHA = 3
MAX_TENTATIVAS_PERGUNTA = 1
BLOQUEIO_SENHA_MIN = 5
BLOQUEIO_PERGUNTA_MIN = 10


def verificar_bloqueio(dicionario, chave):
    if chave not in dicionario:
        return False, 0
    info = dicionario[chave]
    if info.get('bloqueado_ate') and datetime.now() < info['bloqueado_ate']:
        restante = (info['bloqueado_ate'] - datetime.now()).seconds
        return True, restante
    return False, 0


def registrar_tentativa_falha(dicionario, chave, max_tentativas, minutos_bloqueio):
    if chave not in dicionario:
        dicionario[chave] = {'tentativas': 0, 'bloqueado_ate': None}
    
    info = dicionario[chave]
    if info.get('bloqueado_ate') and datetime.now() >= info['bloqueado_ate']:
        dicionario[chave] = {'tentativas': 0, 'bloqueado_ate': None}
        info = dicionario[chave]
    
    info['tentativas'] += 1
    if info['tentativas'] >= max_tentativas:
        info['bloqueado_ate'] = datetime.now() + timedelta(minutes=minutos_bloqueio)
        info['tentativas'] = 0


def resetar_tentativas(dicionario, chave):
    if chave in dicionario:
        dicionario[chave] = {'tentativas': 0, 'bloqueado_ate': None}


def tentativas_restantes(dicionario, chave, max_tentativas):
    if chave not in dicionario:
        return max_tentativas
    info = dicionario[chave]
    if info.get('bloqueado_ate') and datetime.now() < info['bloqueado_ate']:
        return 0
    if info.get('bloqueado_ate') and datetime.now() >= info['bloqueado_ate']:
        return max_tentativas
    return max(0, max_tentativas - info.get('tentativas', 0))


# ─────────────────────────────────────────────
# POLÍTICA DE SENHA FORTE
# ─────────────────────────────────────────────

def validar_senha_forte(senha):
    """Valida se a senha atende à política de senha forte.
    Retorna (True, None) se válida ou (False, mensagem) se inválida."""
    if len(senha) < 8:
        return False, 'A senha deve ter no mínimo 8 caracteres.'
    if not re.search(r'[A-Z]', senha):
        return False, 'A senha deve conter ao menos uma letra maiúscula.'
    if not re.search(r'[a-z]', senha):
        return False, 'A senha deve conter ao menos uma letra minúscula.'
    if not re.search(r'[0-9]', senha):
        return False, 'A senha deve conter ao menos um número.'
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{}|;:\'",.<>?/`~\\]', senha):
        return False, 'A senha deve conter ao menos um caractere especial (!@#$%^&* etc.).'
    return True, None


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        db.executescript('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user', -- 'user', 'admin', 'dono'
                pergunta_seguranca TEXT,
                resposta_seguranca TEXT,
                acesso_liberado INTEGER DEFAULT 0,
                bloqueado INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS solicitacoes_acesso (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                data_solicitacao TEXT NOT NULL,
                status TEXT DEFAULT 'pendente',
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            );

            CREATE TABLE IF NOT EXISTS equipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                modalidade TEXT NOT NULL,
                capitao_id INTEGER,
                FOREIGN KEY (capitao_id) REFERENCES usuarios(id)
            );

            CREATE TABLE IF NOT EXISTS jogadores_equipe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipe_id INTEGER NOT NULL,
                usuario_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                FOREIGN KEY (equipe_id) REFERENCES equipes(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            );

            CREATE TABLE IF NOT EXISTS amistosos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time1_id INTEGER NOT NULL,
                time2_id INTEGER NOT NULL,
                modalidade TEXT NOT NULL,
                data TEXT NOT NULL,
                horario TEXT NOT NULL,
                local TEXT NOT NULL,
                status TEXT DEFAULT 'aberto',
                placar_time1 INTEGER,
                placar_time2 INTEGER,
                artilheiro TEXT,
                wo INTEGER DEFAULT 0,
                motivo_wo TEXT,
                FOREIGN KEY (time1_id) REFERENCES equipes(id),
                FOREIGN KEY (time2_id) REFERENCES equipes(id)
            );

            CREATE TABLE IF NOT EXISTS campeonatos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                modalidade TEXT NOT NULL,
                qtd_equipes INTEGER NOT NULL,
                data TEXT NOT NULL,
                horario TEXT NOT NULL,
                local TEXT NOT NULL,
                status TEXT DEFAULT 'aberto',
                campeao_id INTEGER,
                vice_id INTEGER,
                artilheiro TEXT,
                FOREIGN KEY (campeao_id) REFERENCES equipes(id),
                FOREIGN KEY (vice_id) REFERENCES equipes(id)
            );

            CREATE TABLE IF NOT EXISTS participantes_campeonato (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campeonato_id INTEGER NOT NULL,
                equipe_id INTEGER NOT NULL,
                UNIQUE(campeonato_id, equipe_id),
                FOREIGN KEY (campeonato_id) REFERENCES campeonatos(id),
                FOREIGN KEY (equipe_id) REFERENCES equipes(id)
            );

            CREATE TABLE IF NOT EXISTS inscricoes_campeonato (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campeonato_id INTEGER NOT NULL,
                usuario_id INTEGER NOT NULL,
                equipe_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pendente',
                UNIQUE(campeonato_id, usuario_id),
                FOREIGN KEY (campeonato_id) REFERENCES campeonatos(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
                FOREIGN KEY (equipe_id) REFERENCES equipes(id)
            );

            CREATE TABLE IF NOT EXISTS convites_amistoso (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_origem_id INTEGER NOT NULL,
                usuario_destino_id INTEGER NOT NULL,
                equipe_origem_id INTEGER NOT NULL,
                equipe_destino_id INTEGER,
                status TEXT DEFAULT 'pendente',
                FOREIGN KEY (usuario_origem_id) REFERENCES usuarios(id),
                FOREIGN KEY (usuario_destino_id) REFERENCES usuarios(id),
                FOREIGN KEY (equipe_origem_id) REFERENCES equipes(id),
                FOREIGN KEY (equipe_destino_id) REFERENCES equipes(id)
            );

            CREATE TABLE IF NOT EXISTS partidas_campeonato (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campeonato_id INTEGER NOT NULL,
                equipe1_id INTEGER NOT NULL,
                equipe2_id INTEGER,
                fase TEXT NOT NULL,
                numero_partida INTEGER NOT NULL,
                status TEXT DEFAULT 'aberto',
                placar_equipe1 INTEGER,
                placar_equipe2 INTEGER,
                artilheiro TEXT,
                data TEXT,
                horario TEXT,
                local TEXT,
                vencedor_id INTEGER,
                wo INTEGER DEFAULT 0,
                motivo_wo TEXT,
                FOREIGN KEY (campeonato_id) REFERENCES campeonatos(id),
                FOREIGN KEY (equipe1_id) REFERENCES equipes(id),
                FOREIGN KEY (equipe2_id) REFERENCES equipes(id),
                FOREIGN KEY (vencedor_id) REFERENCES equipes(id)
            );
        ''')

        try:
            db.execute("ALTER TABLE usuarios ADD COLUMN acesso_liberado INTEGER DEFAULT 0")
            db.commit()
        except Exception:
            pass

        try:
            db.execute('''CREATE TABLE IF NOT EXISTS solicitacoes_acesso (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                data_solicitacao TEXT NOT NULL,
                status TEXT DEFAULT 'pendente',
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )''')
            db.commit()
        except Exception:
            pass

        try:
            db.execute("ALTER TABLE equipes ADD COLUMN capitao_id INTEGER REFERENCES usuarios(id)")
            db.commit()
        except Exception:
            pass

        try:
            db.execute("ALTER TABLE convites_amistoso ADD COLUMN equipe_destino_id INTEGER REFERENCES equipes(id)")
            db.commit()
        except Exception:
            pass

        try:
            db.execute("ALTER TABLE usuarios ADD COLUMN bloqueado INTEGER DEFAULT 0")
            db.commit()
        except Exception:
            pass

        # O admin fixo foi removido para permitir o setup inicial pelo usuário
        pass


# ─────────────────────────────────────────────
# DECORATORS
# ─────────────────────────────────────────────

def check_setup(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        db = get_db()
        dono = db.execute("SELECT id FROM usuarios WHERE role = 'dono'").fetchone()
        if not dono and request.endpoint != 'setup':
            return redirect(url_for('setup'))
        return f(*args, **kwargs)
    return decorated

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') not in ['admin', 'dono']:
            flash('Acesso restrito a administradores.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def dono_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'dono':
            flash('Acesso restrito ao Dono do sistema.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def validar_equipe(modalidade, titulares, reservas):
    if modalidade == 'futsal':
        n_titulares, n_reservas_max = 5, 3
    elif modalidade == 'volei':
        n_titulares, n_reservas_max = 7, 5
    elif modalidade == 'x1':
        n_titulares, n_reservas_max = 1, 0
    else:
        return False, "Modalidade inválida"
    if len(titulares) != n_titulares:
        return False, f"Titulares obrigatórios: {n_titulares} jogador(es)"
    if len(reservas) > n_reservas_max:
        return False, f"Máximo de {n_reservas_max} reservas permitidas"
    return True, None

def validar_jogadores_disponiveis(db, modalidade, titulares, reservas, equipe_id_atual=None):
    """Valida se os jogadores estão disponíveis e não há duplicatas no mesmo time."""
    todos_jogadores = [str(j) for j in titulares + reservas if j]
    titulares_str = [str(j) for j in titulares if j]
    reservas_str = [str(j) for j in reservas if j]

    # 1) Verificar duplicatas dentro do mesmo time (titular aparece duas vezes, reserva aparece duas vezes)
    if len(titulares_str) != len(set(titulares_str)):
        from collections import Counter
        duplicados = [uid for uid, cnt in Counter(titulares_str).items() if cnt > 1]
        nomes = []
        for uid in duplicados:
            u = db.execute("SELECT username FROM usuarios WHERE id = ?", (uid,)).fetchone()
            if u:
                nomes.append(u['username'])
        return False, f"Jogador(es) duplicado(s) entre os titulares: {', '.join(nomes)}"

    if len(reservas_str) != len(set(reservas_str)):
        from collections import Counter
        duplicados = [uid for uid, cnt in Counter(reservas_str).items() if cnt > 1]
        nomes = []
        for uid in duplicados:
            u = db.execute("SELECT username FROM usuarios WHERE id = ?", (uid,)).fetchone()
            if u:
                nomes.append(u['username'])
        return False, f"Jogador(es) duplicado(s) entre as reservas: {', '.join(nomes)}"

    # 2) Verificar se um jogador aparece como titular E reserva ao mesmo tempo
    titulares_set = set(titulares_str)
    reservas_set = set(reservas_str)
    sobreposicao = titulares_set & reservas_set
    if sobreposicao:
        nomes = []
        for uid in sobreposicao:
            u = db.execute("SELECT username FROM usuarios WHERE id = ?", (uid,)).fetchone()
            if u:
                nomes.append(u['username'])
        return False, f"O(s) jogador(es) não pode(m) ser titular e reserva ao mesmo tempo: {', '.join(nomes)}"

    # 3) Verificar se algum jogador já está em outra equipe da mesma modalidade
    for usuario_id in todos_jogadores:
        equipe_existente = db.execute(
            """SELECT e.id, e.nome FROM jogadores_equipe je
               JOIN equipes e ON je.equipe_id = e.id
               WHERE je.usuario_id = ? AND e.modalidade = ? AND e.id != ?""",
            (usuario_id, modalidade, equipe_id_atual or -1)
        ).fetchone()

        if equipe_existente:
            usuario = db.execute("SELECT username FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            return False, f"O jogador {usuario['username']} já está na equipe '{equipe_existente['nome']}' ({modalidade.upper()}). Um jogador não pode estar em dois times da mesma modalidade."

    return True, None


def processar_jogadores_equipe(db, equipe_id, titulares, reservas):
    """Processa a adição/atualização de jogadores, permitindo troca de posição"""
    todos_jogadores = titulares + reservas
    
    # Remover jogadores que não estão mais na lista
    jogadores_atuais = db.execute(
        "SELECT usuario_id FROM jogadores_equipe WHERE equipe_id = ?",
        (equipe_id,)
    ).fetchall()
    
    for jogador_atual in jogadores_atuais:
        if str(jogador_atual['usuario_id']) not in todos_jogadores:
            db.execute(
                "DELETE FROM jogadores_equipe WHERE equipe_id = ? AND usuario_id = ?",
                (equipe_id, jogador_atual['usuario_id'])
            )
    
    # Adicionar ou atualizar jogadores
    for usuario_id in titulares:
        existing = db.execute(
            "SELECT id, tipo FROM jogadores_equipe WHERE equipe_id = ? AND usuario_id = ?",
            (equipe_id, usuario_id)
        ).fetchone()
        
        if existing:
            # Se já existe, atualizar tipo (troca de posição)
            if existing['tipo'] != 'titular':
                db.execute(
                    "UPDATE jogadores_equipe SET tipo = 'titular' WHERE equipe_id = ? AND usuario_id = ?",
                    (equipe_id, usuario_id)
                )
        else:
            # Se não existe, inserir
            db.execute(
                "INSERT INTO jogadores_equipe (equipe_id, usuario_id, tipo) VALUES (?, ?, 'titular')",
                (equipe_id, usuario_id)
            )
    
    for usuario_id in reservas:
        existing = db.execute(
            "SELECT id, tipo FROM jogadores_equipe WHERE equipe_id = ? AND usuario_id = ?",
            (equipe_id, usuario_id)
        ).fetchone()
        
        if existing:
            # Se já existe, atualizar tipo (troca de posição)
            if existing['tipo'] != 'reserva':
                db.execute(
                    "UPDATE jogadores_equipe SET tipo = 'reserva' WHERE equipe_id = ? AND usuario_id = ?",
                    (equipe_id, usuario_id)
                )
        else:
            # Se não existe, inserir
            db.execute(
                "INSERT INTO jogadores_equipe (equipe_id, usuario_id, tipo) VALUES (?, ?, 'reserva')",
                (equipe_id, usuario_id)
            )



def get_equipes_info(equipe_ids):
    db = get_db()
    equipes_data = []
    for eq_id in equipe_ids:
        eq = db.execute("SELECT * FROM equipes WHERE id = ?", (eq_id,)).fetchone()
        if eq:
            titulares = db.execute(
                "SELECT u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'titular'",
                (eq['id'],)
            ).fetchall()
            reservas = db.execute(
                "SELECT u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'reserva'",
                (eq['id'],)
            ).fetchall()
            equipes_data.append({
                'id': eq['id'],
                'nome': eq['nome'],
                'modalidade': eq['modalidade'],
                'titulares': [t['username'] for t in titulares],
                'reservas': [r['username'] for r in reservas],
            })
    return equipes_data


def validar_data_futura(data_str):
    try:
        data = datetime.strptime(data_str, '%Y-%m-%d').date()
        hoje = datetime.now().date()
        return data >= hoje
    except:
        return False


def get_nome_modalidade(modalidade):
    modalidades = {
        'futsal': '⚽ Futsal',
        'volei': '🏐 Vôlei',
        'x1': '🥊 X1'
    }
    return modalidades.get(modalidade, modalidade)


def get_emoji_modalidade(modalidade):
    emojis = {
        'futsal': '⚽',
        'volei': '🏐',
        'x1': '🥊'
    }
    return emojis.get(modalidade, '')


# ─────────────────────────────────────────────
# AUTENTICAÇÃO (UNIFICADA)
# ─────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
@check_setup
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        chave = f"login:{username}"
        bloqueado, segundos = verificar_bloqueio(tentativas_senha, chave)
        if bloqueado:
            minutos = segundos // 60
            secs = segundos % 60
            flash(f'Conta bloqueada por excesso de tentativas. Aguarde {minutos}m {secs}s.', 'danger')
            return render_template('login.html', is_auth_page=True, username_pre=username)

        db = get_db()
        user = db.execute(
            "SELECT * FROM usuarios WHERE username = ?",
            (username,)
        ).fetchone()

        # Verificar se a conta foi bloqueada administrativamente
        if user and user['bloqueado']:
            flash('Sua conta foi bloqueada. Entre em contato com um administrador.', 'danger')
            return render_template('login.html', is_auth_page=True, username_pre=username)

        if user and user['password'] == password:
            resetar_tentativas(tentativas_senha, chave)
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash(f'Bem-vindo, {user["username"]}!', 'success')
            return redirect(url_for('index'))
        else:
            registrar_tentativa_falha(tentativas_senha, chave, MAX_TENTATIVAS_SENHA, BLOQUEIO_SENHA_MIN)
            restam = tentativas_restantes(tentativas_senha, chave, MAX_TENTATIVAS_SENHA)
            if restam == 0:
                flash(f'Muitas tentativas incorretas. Conta bloqueada por {BLOQUEIO_SENHA_MIN} minutos.', 'danger')
            else:
                flash(f'Usuário ou senha incorretos. Tentativas restantes: {restam}.', 'danger')

    return render_template('login.html', is_auth_page=True)


@app.route('/cadastro', methods=['GET', 'POST'])
@check_setup
def cadastro():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        pergunta = request.form.get('pergunta_seguranca', '').strip()
        resposta = request.form.get('resposta_seguranca', '').strip().lower()
        if not username or not password or not pergunta or not resposta:
            flash('Todos os campos são obrigatórios.', 'warning')
            return render_template('cadastro.html', is_auth_page=True)
        senha_ok, senha_msg = validar_senha_forte(password)
        if not senha_ok:
            flash(f'Senha fraca: {senha_msg}', 'danger')
            return render_template('cadastro.html', is_auth_page=True)
        db = get_db()
        existing = db.execute("SELECT id FROM usuarios WHERE username = ?", (username,)).fetchone()
        if existing:
            flash('Nome de usuário já está em uso.', 'danger')
            return render_template('cadastro.html', is_auth_page=True)
        db.execute(
            "INSERT INTO usuarios (username, password, pergunta_seguranca, resposta_seguranca, role, acesso_liberado) VALUES (?, ?, ?, ?, 'user', 0)",
            (username, password, pergunta, resposta)
        )
        db.commit()
        flash('Cadastro realizado com sucesso! Aguarde aprovação do administrador.', 'success')
        return redirect(url_for('login'))
    return render_template('cadastro.html', is_auth_page=True)


@app.route('/recuperar-senha', methods=['GET', 'POST'])
@check_setup
def recuperar_senha():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        resposta_resp = request.form.get('resposta_seguranca', '').strip().lower()

        db = get_db()
        user = db.execute("SELECT * FROM usuarios WHERE username = ?", (username,)).fetchone()

        if not user:
            flash('Usuário não encontrado.', 'danger')
            return render_template('recuperar_senha.html', is_auth_page=True)

        # Passo 1: Usuário informou o nome, mostrar pergunta
        if not resposta_resp:
            return render_template('recuperar_senha.html', is_auth_page=True, user_found=True, username=username, pergunta=user['pergunta_seguranca'])

        # Passo 2: Validar resposta
        chave = f"pergunta:{username}"
        bloqueado, segundos = verificar_bloqueio(tentativas_pergunta, chave)
        if bloqueado:
            flash(f'Muitas tentativas. Aguarde {segundos // 60} minutos.', 'danger')
            return render_template('recuperar_senha.html', is_auth_page=True)

        if user['resposta_seguranca'].lower() == resposta_resp:
            resetar_tentativas(tentativas_pergunta, chave)
            return render_template('recuperar_senha.html', is_auth_page=True, user_found=True, senha_revelada=user['password'])
        else:
            registrar_tentativa_falha(tentativas_pergunta, chave, MAX_TENTATIVAS_PERGUNTA, BLOQUEIO_PERGUNTA_MIN)
            flash('Resposta incorreta.', 'danger')
            return render_template('recuperar_senha.html', is_auth_page=True, user_found=True, username=username, pergunta=user['pergunta_seguranca'])

    return render_template('recuperar_senha.html', is_auth_page=True)


@app.route('/logout')
def logout():
    session.clear()
    flash('Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('login'))


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    db = get_db()
    dono = db.execute("SELECT id FROM usuarios WHERE role = 'dono'").fetchone()
    if dono:
        flash('O sistema já foi configurado.', 'info')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        pergunta = request.form.get('pergunta_seguranca', '').strip()
        resposta = request.form.get('resposta_seguranca', '').strip().lower()
        
        if not all([username, password, pergunta, resposta]):
            flash('Todos os campos são obrigatórios para o setup.', 'warning')
        else:
            senha_ok, senha_msg = validar_senha_forte(password)
            if not senha_ok:
                flash(f'Senha fraca: {senha_msg}', 'danger')
            else:
                db.execute(
                    "INSERT INTO usuarios (username, password, role, pergunta_seguranca, resposta_seguranca, acesso_liberado) VALUES (?, ?, 'dono', ?, ?, 1)",
                    (username, password, pergunta, resposta)
                )
                db.commit()
                flash('Dono criado com sucesso! Agora você pode fazer login.', 'success')
                return redirect(url_for('login'))
            
    return render_template('setup.html', is_auth_page=True)

@app.route('/')
@check_setup
@login_required
def index():
    return render_template('index.html')


# ─────────────────────────────────────────────
# EQUIPES
# ─────────────────────────────────────────────

@app.route('/equipes', methods=['GET', 'POST'])
@check_setup
@login_required
def equipes():
    db = get_db()

    if request.method == 'POST' and session.get('role') in ['admin', 'dono']:
        tipo = request.form.get('tipo', '')  # 'individual' ou 'coletiva'
        modalidade = request.form.get('modalidade', '')
        nome = request.form.get('nome', '').strip()
        capitao_id = request.form.get('capitao_id', '')
        titulares = [str(u) for u in request.form.getlist('titulares') if u]
        reservas = [str(u) for u in request.form.getlist('reservas') if u]

        # Validar tipo
        if not tipo:
            flash('Selecione se a modalidade é individual ou coletiva.', 'warning')
        elif tipo == 'individual':
            # X1 - Modalidade Individual
            # Garantir que modalidade seja X1 para tipo individual
            modalidade = 'x1'
            if not titulares:
                flash('Selecione um jogador para a equipe X1.', 'warning')
            else:
                # Validar equipe
                valid, msg = validar_equipe(modalidade, titulares, [])
                if not valid:
                    flash(f'Erro: {msg}', 'warning')
                else:
                    # Validar disponibilidade
                    valid_disp, msg_disp = validar_jogadores_disponiveis(db, modalidade, titulares, [])
                    if not valid_disp:
                        flash(msg_disp, 'warning')
                    else:
                        try:
                            # Obter nome do jogador
                            jogador = db.execute("SELECT username FROM usuarios WHERE id = ?", (int(titulares[0]),)).fetchone()
                            if not jogador:
                                flash('Jogador não encontrado.', 'danger')
                            else:
                                nome_equipe = jogador['username']
                                db.execute("INSERT INTO equipes (nome, modalidade, capitao_id) VALUES (?, ?, ?)", (nome_equipe, modalidade, None))
                                db.commit()
                                equipe_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                                db.execute("INSERT INTO jogadores_equipe (equipe_id, usuario_id, tipo) VALUES (?, ?, 'titular')", (equipe_id, int(titulares[0])))
                                db.commit()
                                flash('Equipe X1 criada com sucesso!', 'success')
                                return redirect(url_for('equipes'))
                        except Exception as e:
                            db.rollback()
                            flash(f'Erro ao criar equipe: {str(e)}', 'danger')
        elif tipo == 'coletiva':
            # Futsal ou Vôlei - Modalidades Coletivas
            if not nome:
                flash('Informe o nome da equipe.', 'warning')
            elif not modalidade or modalidade == 'x1':
                flash('Selecione uma modalidade coletiva (Futsal ou Volei).', 'warning')
            elif not capitao_id:
                flash('Selecione um capitão para a equipe.', 'warning')
            elif not titulares:
                flash('Selecione pelo menos um jogador titular.', 'warning')
            else:
                # Validar se o capitao eh um dos integrantes
                capitao_id_int = int(capitao_id)
                jogadores_ids = [int(u) for u in titulares] + [int(u) for u in reservas]
                if capitao_id_int not in jogadores_ids:
                    flash('O capitao deve ser um dos integrantes da equipe (titular ou reserva).', 'warning')
                else:
                    # Validar equipe
                    valid, msg = validar_equipe(modalidade, titulares, reservas)
                    if not valid:
                        flash(f'Erro: {msg}', 'warning')
                    else:
                        # Validar disponibilidade
                        valid_disp, msg_disp = validar_jogadores_disponiveis(db, modalidade, titulares, reservas)
                        if not valid_disp:
                            flash(msg_disp, 'warning')
                        else:
                            try:
                                db.execute("INSERT INTO equipes (nome, modalidade, capitao_id) VALUES (?, ?, ?)", (nome, modalidade, int(capitao_id)))
                                db.commit()
                                equipe_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                                for uid in titulares:
                                    db.execute("INSERT INTO jogadores_equipe (equipe_id, usuario_id, tipo) VALUES (?, ?, 'titular')", (equipe_id, int(uid)))
                                for uid in reservas:
                                    db.execute("INSERT INTO jogadores_equipe (equipe_id, usuario_id, tipo) VALUES (?, ?, 'reserva')", (equipe_id, int(uid)))
                                db.commit()
                                flash('Equipe criada com sucesso!', 'success')
                                return redirect(url_for('equipes'))
                            except Exception as e:
                                db.rollback()
                                flash(f'Erro ao criar equipe: {str(e)}', 'danger')
        else:
            flash('Tipo de modalidade inválido.', 'warning')

    todas_equipes = db.execute("SELECT * FROM equipes ORDER BY nome").fetchall()
    usuarios = db.execute("SELECT id, username FROM usuarios WHERE role = 'user' ORDER BY username").fetchall()

    equipes_data = []
    for eq in todas_equipes:
        titulares = db.execute(
            "SELECT u.id, u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'titular'",
            (eq['id'],)
        ).fetchall()
        reservas = db.execute(
            "SELECT u.id, u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'reserva'",
            (eq['id'],)
        ).fetchall()
        capitao = db.execute(
            "SELECT id, username FROM usuarios WHERE id = ?",
            (eq['capitao_id'],)
        ).fetchone() if eq['capitao_id'] else None
        equipes_data.append({
            'id': eq['id'],
            'nome': eq['nome'],
            'modalidade': eq['modalidade'],
            'capitao_id': eq['capitao_id'],
            'capitao_nome': capitao['username'] if capitao else 'N/A',
            'titulares': [t['username'] for t in titulares],
            'reservas': [r['username'] for r in reservas],
        })

    return render_template('equipes.html', equipes=equipes_data, usuarios=usuarios)


@app.route('/equipes/<int:equipe_id>/capitao', methods=['POST'])
@check_setup
@admin_required
def alterar_capitao(equipe_id):
    novo_capitao_id = request.form.get('novo_capitao_id', '')
    db = get_db()
    equipe = db.execute("SELECT * FROM equipes WHERE id = ?", (equipe_id,)).fetchone()
    
    if not equipe:
        flash('Equipe não encontrada.', 'danger')
        return redirect(url_for('equipes'))
    
    if equipe['modalidade'] == 'x1':
        flash('Equipes X1 não possuem capitão.', 'warning')
        return redirect(url_for('equipes'))
    
    if not novo_capitao_id:
        flash('Selecione um novo capitão.', 'warning')
        return redirect(url_for('equipes'))
    
    db.execute("UPDATE equipes SET capitao_id = ? WHERE id = ?", (novo_capitao_id, equipe_id))
    db.commit()
    flash('Capitão alterado com sucesso!', 'success')
    return redirect(url_for('equipes'))


@app.route('/equipes/<int:equipe_id>/integrantes')
@login_required
def get_integrantes_equipe(equipe_id):
    from flask import jsonify
    db = get_db()
    integrantes = db.execute(
        """SELECT DISTINCT u.id, u.username FROM usuarios u
           JOIN jogadores_equipe je ON u.id = je.usuario_id
           WHERE je.equipe_id = ?
           ORDER BY u.username""",
        (equipe_id,)
    ).fetchall()
    return jsonify([dict(row) for row in integrantes])


@app.route('/equipes/<int:equipe_id>')
@login_required
def visualizar_equipe(equipe_id):
    db = get_db()
    equipe = db.execute("SELECT * FROM equipes WHERE id = ?", (equipe_id,)).fetchone()
    
    if not equipe:
        flash('Equipe não encontrada.', 'danger')
        return redirect(url_for('equipes'))
    
    titulares = db.execute(
        "SELECT u.id, u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'titular' ORDER BY u.username",
        (equipe_id,)
    ).fetchall()
    reservas = db.execute(
        "SELECT u.id, u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'reserva' ORDER BY u.username",
        (equipe_id,)
    ).fetchall()
    capitao = db.execute(
        "SELECT id, username FROM usuarios WHERE id = ?",
        (equipe['capitao_id'],)
    ).fetchone() if equipe['capitao_id'] else None
    
    equipe_data = {
        'id': equipe['id'],
        'nome': equipe['nome'],
        'modalidade': equipe['modalidade'],
        'capitao_id': equipe['capitao_id'],
        'capitao_nome': capitao['username'] if capitao else 'N/A',
        'titulares': titulares,
        'reservas': reservas,
    }
    
    usuarios = db.execute("SELECT id, username FROM usuarios WHERE role = 'user' ORDER BY username").fetchall()
    
    return render_template('detalhes_equipe.html', equipe=equipe_data, usuarios=usuarios)


@app.route('/equipes/<int:equipe_id>/editar', methods=['GET', 'POST'])
@check_setup
@admin_required
def editar_equipe(equipe_id):
    db = get_db()
    equipe = db.execute("SELECT * FROM equipes WHERE id = ?", (equipe_id,)).fetchone()
    
    if not equipe:
        flash('Equipe não encontrada.', 'danger')
        return redirect(url_for('equipes'))
    
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        capitao_id = request.form.get('capitao_id', '')
        titulares = [u for u in request.form.getlist('titulares') if u]
        reservas = [u for u in request.form.getlist('reservas') if u]
        
        if not nome:
            flash('Informe o nome da equipe.', 'warning')
        elif equipe['modalidade'] != 'x1' and not capitao_id:
            flash('Selecione um capitão para a equipe.', 'warning')
        else:
            valid, msg = validar_equipe(equipe['modalidade'], titulares, reservas)
            if not valid:
                flash(f'Erro na seleção de jogadores. {msg}', 'warning')
            else:
                # Validar disponibilidade dos jogadores (excluindo a equipe atual)
                valid_disp, msg_disp = validar_jogadores_disponiveis(db, equipe['modalidade'], titulares, reservas, equipe_id)
                if not valid_disp:
                    flash(msg_disp, 'warning')
                else:
                    capitao_para_salvar = capitao_id if equipe['modalidade'] != 'x1' else None
                    db.execute("UPDATE equipes SET nome = ?, capitao_id = ? WHERE id = ?", (nome, capitao_para_salvar, equipe_id))
                    db.commit()
                    processar_jogadores_equipe(db, equipe_id, titulares, reservas)
                    db.commit()
                    flash('Equipe atualizada com sucesso!', 'success')
                    return redirect(url_for('visualizar_equipe', equipe_id=equipe_id))
    
    titulares = db.execute(
        "SELECT u.id, u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'titular' ORDER BY u.username",
        (equipe_id,)
    ).fetchall()
    reservas = db.execute(
        "SELECT u.id, u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'reserva' ORDER BY u.username",
        (equipe_id,)
    ).fetchall()
    capitao = db.execute(
        "SELECT id, username FROM usuarios WHERE id = ?",
        (equipe['capitao_id'],)
    ).fetchone() if equipe['capitao_id'] else None
    
    equipe_data = {
        'id': equipe['id'],
        'nome': equipe['nome'],
        'modalidade': equipe['modalidade'],
        'capitao_id': equipe['capitao_id'],
        'capitao_nome': capitao['username'] if capitao else 'N/A',
        'titulares': [{'id': t['id'], 'username': t['username']} for t in titulares],
        'reservas': [{'id': r['id'], 'username': r['username']} for r in reservas],
    }
    
    usuarios = db.execute("SELECT id, username FROM usuarios WHERE role = 'user' ORDER BY username").fetchall()
    
    return render_template('editar_equipe.html', equipe=equipe_data, usuarios=usuarios)


@app.route('/equipes/excluir/<int:equipe_id>', methods=['POST'])
@check_setup
@admin_required
def excluir_equipe(equipe_id):
    db = get_db()
    db.execute("DELETE FROM jogadores_equipe WHERE equipe_id = ?", (equipe_id,))
    db.execute("DELETE FROM equipes WHERE id = ?", (equipe_id,))
    db.commit()
    flash('Equipe excluída com sucesso.', 'success')
    return redirect(url_for('equipes'))


# ─────────────────────────────────────────────
# AMISTOSOS
# ─────────────────────────────────────────────

@app.route('/amistosos', methods=['GET', 'POST'])
@check_setup
@login_required
def amistosos():
    db = get_db()
    user_id = session.get('user_id')

    if request.method == 'POST' and session.get('role') in ['admin', 'dono']:
        time1_id = request.form.get('time1_id')
        time2_id = request.form.get('time2_id')
        modalidade = request.form.get('modalidade', '').strip()
        data = request.form.get('data', '').strip()
        horario = request.form.get('horario', '').strip()
        local = request.form.get('local', '').strip()

        if not all([time1_id, time2_id, modalidade, data, horario, local]):
            flash('Todos os campos são obrigatórios.', 'warning')
        elif time1_id == time2_id:
            flash('Os dois times devem ser diferentes.', 'warning')
        elif not validar_data_futura(data):
            flash('A data deve ser futura.', 'warning')
        else:
            time1 = db.execute("SELECT modalidade FROM equipes WHERE id = ?", (time1_id,)).fetchone()
            time2 = db.execute("SELECT modalidade FROM equipes WHERE id = ?", (time2_id,)).fetchone()
            if not time1 or not time2:
                flash('Uma ou ambas as equipes não foram encontradas.', 'danger')
            elif time1['modalidade'] != modalidade or time2['modalidade'] != modalidade:
                flash('Ambos os times devem ser da mesma modalidade do amistoso.', 'warning')
            else:
                db.execute(
                    "INSERT INTO amistosos (time1_id, time2_id, modalidade, data, horario, local) VALUES (?, ?, ?, ?, ?, ?)",
                    (time1_id, time2_id, modalidade, data, horario, local)
                )
                db.commit()
                flash('Amistoso cadastrado com sucesso!', 'success')
                return redirect(url_for('amistosos'))

    todos_amistosos = db.execute(
        """SELECT a.id, e1.id as time1_id, e1.nome as time1, e1.modalidade as modalidade1,
                  e2.id as time2_id, e2.nome as time2, e2.modalidade as modalidade2,
                  a.modalidade, a.data, a.horario, a.local, a.status, a.placar_time1, a.placar_time2, a.artilheiro
           FROM amistosos a
           JOIN equipes e1 ON a.time1_id = e1.id
           JOIN equipes e2 ON a.time2_id = e2.id
           ORDER BY a.data DESC"""
    ).fetchall()

    equipes = db.execute("SELECT id, nome FROM equipes ORDER BY nome").fetchall()

    # Buscar equipes do usuário atual
    minhas_equipes = db.execute(
        "SELECT DISTINCT e.id, e.nome, e.modalidade FROM equipes e JOIN jogadores_equipe je ON e.id = je.equipe_id WHERE je.usuario_id = ? UNION SELECT id, nome, modalidade FROM equipes WHERE capitao_id = ?",
        (user_id, user_id)
    ).fetchall()

    convites_pendentes = db.execute(
        """SELECT c.id, u.username as usuario_origem, e_origem.nome as equipe_origem, e_destino.nome as equipe_destino, e_destino.id as equipe_destino_id
           FROM convites_amistoso c
           JOIN usuarios u ON c.usuario_origem_id = u.id
           JOIN equipes e_origem ON c.equipe_origem_id = e_origem.id
           LEFT JOIN equipes e_destino ON c.equipe_destino_id = e_destino.id
           WHERE c.usuario_destino_id = ? AND c.status = 'pendente'""",
        (user_id,)
    ).fetchall()

    return render_template('amistosos.html', amistosos=todos_amistosos, equipes=equipes, minhas_equipes=minhas_equipes,
                         convites_pendentes=convites_pendentes, user_id=user_id, get_nome_modalidade=get_nome_modalidade)


@app.route('/amistosos/usuarios-modalidade/<int:equipe_id>')
@login_required
def get_usuarios_modalidade(equipe_id):
    """Retorna lista de capitães/jogadores X1 da mesma modalidade (AJAX)"""
    import json
    db = get_db()
    equipe = db.execute("SELECT modalidade FROM equipes WHERE id = ?", (equipe_id,)).fetchone()
    
    if not equipe:
        return json.dumps({'error': 'Equipe não encontrada'}), 404
    
    if equipe['modalidade'] == 'x1':
        # Para X1, retornar todos os jogadores de X1
        usuarios = db.execute(
            """SELECT DISTINCT u.id, u.username FROM usuarios u
               JOIN jogadores_equipe je ON u.id = je.usuario_id
               JOIN equipes e ON je.equipe_id = e.id
               WHERE e.modalidade = 'x1' AND u.id != ?
               ORDER BY u.username""",
            (session['user_id'],)
        ).fetchall()
    else:
        # Para outras modalidades, retornar capitães da mesma modalidade
        usuarios = db.execute(
            """SELECT id, username FROM usuarios
               WHERE id IN (
                   SELECT capitao_id FROM equipes WHERE modalidade = ? AND capitao_id IS NOT NULL
               ) AND id != ?
               ORDER BY username""",
            (equipe['modalidade'], session['user_id'])
        ).fetchall()
    
    return json.dumps([{'id': u['id'], 'username': u['username']} for u in usuarios])


@app.route('/amistosos/convidar/<int:usuario_destino_id>/<int:equipe_origem_id>', methods=['POST'])
@login_required
def convidar_amistoso(usuario_destino_id, equipe_origem_id):
    db = get_db()
    user_id = session['user_id']
    
    equipe_origem = db.execute("SELECT * FROM equipes WHERE id = ?", (equipe_origem_id,)).fetchone()
    
    if not equipe_origem:
        flash('Equipe não encontrada.', 'danger')
        return redirect(url_for('amistosos'))
    
    # Verificar se o usuário é capitão ou membro da equipe
    if equipe_origem['modalidade'] != 'x1':
        if equipe_origem['capitao_id'] != user_id:
            flash('Apenas o capitão pode enviar convites de amistoso.', 'warning')
            return redirect(url_for('amistosos'))
    else:
        # Para X1, verificar se é membro
        membro = db.execute(
            "SELECT id FROM jogadores_equipe WHERE equipe_id = ? AND usuario_id = ?",
            (equipe_origem_id, user_id)
        ).fetchone()
        if not membro:
            flash('Você não é membro desta equipe.', 'warning')
            return redirect(url_for('amistosos'))
    
    existing = db.execute(
        "SELECT id FROM convites_amistoso WHERE usuario_origem_id = ? AND usuario_destino_id = ? AND status = 'pendente'",
        (user_id, usuario_destino_id)
    ).fetchone()
    
    if existing:
        flash('Você já enviou um convite pendente para este usuário.', 'warning')
    else:
        # Determinar qual equipe do destinatário deve receber o convite
        equipe_destino = db.execute(
            "SELECT id FROM equipes WHERE modalidade = ? AND (capitao_id = ? OR (modalidade = 'x1' AND id IN (SELECT equipe_id FROM jogadores_equipe WHERE usuario_id = ?)))",
            (equipe_origem['modalidade'], usuario_destino_id, usuario_destino_id)
        ).fetchone()
        
        if not equipe_destino:
            flash('O usuário destino não possui uma equipe nesta modalidade.', 'warning')
            return redirect(url_for('amistosos'))

        db.execute(
            "INSERT INTO convites_amistoso (usuario_origem_id, usuario_destino_id, equipe_origem_id, equipe_destino_id, status) VALUES (?, ?, ?, ?, 'pendente')",
            (user_id, usuario_destino_id, equipe_origem_id, equipe_destino['id'])
        )
        db.commit()
        flash('Convite enviado com sucesso!', 'success')
    
    return redirect(url_for('amistosos'))


@app.route('/amistosos/responder-convite/<int:convite_id>/<acao>', methods=['POST'])
@login_required
def responder_convite(convite_id, acao):
    db = get_db()
    convite = db.execute("SELECT * FROM convites_amistoso WHERE id = ?", (convite_id,)).fetchone()
    
    if not convite or convite['usuario_destino_id'] != session['user_id']:
        flash('Convite não encontrado.', 'danger')
        return redirect(url_for('amistosos'))
    
    if acao == 'aceitar':
        # Priorizar equipe_destino_id do convite, senão pegar do form
        equipe_destino_id = convite['equipe_destino_id'] or request.form.get('equipe_destino_id')
        data = request.form.get('data')
        horario = request.form.get('horario')
        local = request.form.get('local')
        
        if not all([equipe_destino_id, data, horario, local]):
            flash('Todos os campos são obrigatórios.', 'warning')
        elif not validar_data_futura(data):
            flash('A data deve ser futura.', 'warning')
        else:
            equipe_origem = db.execute("SELECT modalidade FROM equipes WHERE id = ?", (convite['equipe_origem_id'],)).fetchone()
            if equipe_origem:
                db.execute(
                    "INSERT INTO amistosos (time1_id, time2_id, modalidade, data, horario, local) VALUES (?, ?, ?, ?, ?, ?)",
                    (convite['equipe_origem_id'], equipe_destino_id, equipe_origem['modalidade'], data, horario, local)
                )
                db.execute("UPDATE convites_amistoso SET status = 'aceito' WHERE id = ?", (convite_id,))
                db.commit()
                flash('Convite aceito! Amistoso criado com sucesso!', 'success')
    else:
        db.execute("UPDATE convites_amistoso SET status = 'recusado' WHERE id = ?", (convite_id,))
        db.commit()
        flash('Convite recusado.', 'info')
    
    return redirect(url_for('amistosos'))


@app.route('/amistosos/cancelar/<int:amistoso_id>', methods=['POST'])
@check_setup
@admin_required
def cancelar_amistoso(amistoso_id):
    db = get_db()
    db.execute("DELETE FROM amistosos WHERE id = ?", (amistoso_id,))
    db.commit()
    flash('Amistoso cancelado com sucesso.', 'success')
    return redirect(url_for('amistosos'))


@app.route('/amistosos/<int:amistoso_id>/concluir', methods=['GET', 'POST'])
@check_setup
@admin_required
def concluir_amistoso(amistoso_id):
    db = get_db()
    amistoso = db.execute("SELECT * FROM amistosos WHERE id = ?", (amistoso_id,)).fetchone()

    if not amistoso:
        flash('Amistoso não encontrado.', 'danger')
        return redirect(url_for('amistosos'))

    if request.method == 'POST':
        placar_time1 = request.form.get('placar_time1', '0')
        placar_time2 = request.form.get('placar_time2', '0')
        artilheiro = request.form.get('artilheiro', '').strip()
        wo = 1 if request.form.get('wo') else 0
        motivo_wo = request.form.get('motivo_wo', '').strip()
        
        try:
            placar_time1 = int(placar_time1)
            placar_time2 = int(placar_time2)
        except:
            flash('Placares inválidos.', 'warning')
            return redirect(url_for('amistosos'))
            
        db.execute(
            "UPDATE amistosos SET status = 'concluído', placar_time1 = ?, placar_time2 = ?, artilheiro = ?, wo = ?, motivo_wo = ? WHERE id = ?",
            (placar_time1, placar_time2, artilheiro, wo, motivo_wo, amistoso_id)
        )
        db.commit()
        flash('Amistoso marcado como concluído!', 'success')
        return redirect(url_for('amistosos'))

    return render_template('concluir_amistoso.html', amistoso=amistoso)


# ─────────────────────────────────────────────
# CAMPEONATOS
# ─────────────────────────────────────────────

@app.route('/campeonatos', methods=['GET', 'POST'])
@check_setup
@login_required
def campeonatos():
    db = get_db()
    user_id = session.get('user_id')

    if request.method == 'POST' and session.get('role') in ['admin', 'dono']:
        nome = request.form.get('nome', '').strip()
        modalidade = request.form.get('modalidade', '').strip()
        qtd_equipes = request.form.get('qtd_equipes', '0').strip()
        data = request.form.get('data', '').strip()
        horario = request.form.get('horario', '').strip()
        local = request.form.get('local', '').strip()
        try:
            qtd_equipes = int(qtd_equipes)
        except ValueError:
            qtd_equipes = 0
        if not all([nome, modalidade, data, horario, local]):
            flash('Todos os campos são obrigatórios.', 'warning')
        elif qtd_equipes < 3:
            flash('O campeonato deve ter no mínimo 3 equipes.', 'warning')
        elif not validar_data_futura(data):
            flash('A data deve ser futura.', 'warning')
        else:
            db.execute(
                "INSERT INTO campeonatos (nome, modalidade, qtd_equipes, data, horario, local) VALUES (?, ?, ?, ?, ?, ?)",
                (nome, modalidade, qtd_equipes, data, horario, local)
            )
            db.commit()
            flash('Campeonato cadastrado com sucesso!', 'success')
            return redirect(url_for('campeonatos'))

    todos_campeonatos = db.execute("SELECT * FROM campeonatos ORDER BY data DESC").fetchall()
    campeonatos_data = []
    for camp in todos_campeonatos:
        participantes = db.execute(
            "SELECT COUNT(*) as total FROM participantes_campeonato WHERE campeonato_id = ?",
            (camp['id'],)
        ).fetchone()
        inscricao = db.execute(
            "SELECT id, status FROM inscricoes_campeonato WHERE campeonato_id = ? AND usuario_id = ?",
            (camp['id'], user_id)
        ).fetchone()
        campeao_nome = None
        vice_nome = None
        if camp['campeao_id']:
            campeao_row = db.execute("SELECT nome FROM equipes WHERE id = ?", (camp['campeao_id'],)).fetchone()
            campeao_nome = campeao_row['nome'] if campeao_row else None
        if camp['vice_id']:
            vice_row = db.execute("SELECT nome FROM equipes WHERE id = ?", (camp['vice_id'],)).fetchone()
            vice_nome = vice_row['nome'] if vice_row else None
        campeonatos_data.append({
            'id': camp['id'],
            'nome': camp['nome'],
            'modalidade': camp['modalidade'],
            'qtd_equipes': camp['qtd_equipes'],
            'data': camp['data'],
            'horario': camp['horario'],
            'local': camp['local'],
            'status': camp['status'],
            'participantes_atuais': participantes['total'],
            'inscrito': inscricao is not None,
            'status_inscricao': inscricao['status'] if inscricao else None,
            'campeao_nome': campeao_nome,
            'vice_nome': vice_nome,
            'artilheiro': camp['artilheiro']
        })

    return render_template('campeonatos.html', campeonatos=campeonatos_data)


@app.route('/campeonatos/<int:campeonato_id>')
@login_required
def detalhes_campeonato(campeonato_id):
    db = get_db()
    if not campeonato_id:
        flash('Campeonato não encontrado.', 'danger')
        return redirect(url_for('campeonatos'))
    participantes = db.execute(
        """SELECT e.id, e.nome, e.modalidade
           FROM participantes_campeonato pc
           JOIN equipes e ON pc.equipe_id = e.id
           WHERE pc.campeonato_id = ?""",
        (campeonato_id,)
    ).fetchall()
    participantes_data = []
    for eq in participantes:
        titulares = db.execute(
            "SELECT u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'titular'",
            (eq['id'],)
        ).fetchall()
        reservas = db.execute(
            "SELECT u.username FROM jogadores_equipe je JOIN usuarios u ON je.usuario_id = u.id WHERE je.equipe_id = ? AND je.tipo = 'reserva'",
            (eq['id'],)
        ).fetchall()
        participantes_data.append({
            'id': eq['id'],
            'nome': eq['nome'],
            'modalidade': eq['modalidade'],
            'titulares': [t['username'] for t in titulares],
            'reservas': [r['username'] for r in reservas]
        })
    campeonato = db.execute("SELECT * FROM campeonatos WHERE id = ?", (campeonato_id,)).fetchone()
    if not campeonato:
        flash('Campeonato não encontrado.', 'danger')
        return redirect(url_for('campeonatos'))
    equipes_disponiveis = db.execute(
        """SELECT id, nome FROM equipes
           WHERE modalidade = ? AND id NOT IN (SELECT equipe_id FROM participantes_campeonato WHERE campeonato_id = ?)
           ORDER BY nome""",
        (campeonato['modalidade'], campeonato_id)
    ).fetchall()
    # Obter partidas do chaveamento
    partidas = db.execute(
        """SELECT pc.*, e1.nome as equipe1_nome, e2.nome as equipe2_nome
           FROM partidas_campeonato pc
           LEFT JOIN equipes e1 ON pc.equipe1_id = e1.id
           LEFT JOIN equipes e2 ON pc.equipe2_id = e2.id
           WHERE pc.campeonato_id = ?
           ORDER BY pc.fase, pc.numero_partida""",
        (campeonato_id,)
    ).fetchall()
    
    partidas_data = [dict(p) for p in partidas]
    
    return render_template('detalhes_campeonato.html', campeonato=campeonato, participantes=participantes_data,
                         equipes_disponiveis=equipes_disponiveis, get_nome_modalidade=get_nome_modalidade, partidas=partidas_data)


@app.route('/campeonatos/<int:campeonato_id>/adicionar-equipe', methods=['POST'])
@check_setup
@admin_required
def adicionar_equipe_campeonato(campeonato_id):
    equipe_id = request.form.get('equipe_id')
    db = get_db()
    if not equipe_id:
        flash('Selecione uma equipe.', 'warning')
        return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))
    campeonato = db.execute("SELECT modalidade FROM campeonatos WHERE id = ?", (campeonato_id,)).fetchone()
    equipe = db.execute("SELECT modalidade FROM equipes WHERE id = ?", (equipe_id,)).fetchone()
    if not campeonato or not equipe:
        flash('Campeonato ou equipe não encontrados.', 'danger')
        return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))
    if equipe['modalidade'] != campeonato['modalidade']:
        flash(f'A equipe deve ser da modalidade {campeonato["modalidade"].upper()}.', 'warning')
        return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))
    existing = db.execute(
        "SELECT id FROM participantes_campeonato WHERE campeonato_id = ? AND equipe_id = ?",
        (campeonato_id, equipe_id)
    ).fetchone()
    if existing:
        flash('Esta equipe já participa do campeonato.', 'warning')
    else:
        db.execute(
            "INSERT INTO participantes_campeonato (campeonato_id, equipe_id) VALUES (?, ?)",
            (campeonato_id, equipe_id)
        )
        db.commit()
        flash('Equipe adicionada ao campeonato com sucesso!', 'success')
    return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))


@app.route('/campeonatos/<int:campeonato_id>/remover-equipe/<int:equipe_id>', methods=['POST'])
@check_setup
@admin_required
def remover_equipe_campeonato(campeonato_id, equipe_id):
    db = get_db()
    db.execute(
        "DELETE FROM participantes_campeonato WHERE campeonato_id = ? AND equipe_id = ?",
        (campeonato_id, equipe_id)
    )
    db.commit()
    flash('Equipe removida do campeonato.', 'success')
    return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))


@app.route('/campeonatos/<int:campeonato_id>/concluir', methods=['GET', 'POST'])
@check_setup
@admin_required
def concluir_campeonato(campeonato_id):
    db = get_db()
    campeonato = db.execute("SELECT * FROM campeonatos WHERE id = ?", (campeonato_id,)).fetchone()
    if not campeonato:
        flash('Campeonato não encontrado.', 'danger')
        return redirect(url_for('campeonatos'))
    equipes = db.execute(
        """SELECT e.id, e.nome FROM participantes_campeonato pc
           JOIN equipes e ON pc.equipe_id = e.id
           WHERE pc.campeonato_id = ?""",
        (campeonato_id,)
    ).fetchall()
    if request.method == 'POST':
        campeao_id = request.form.get('campeao_id')
        vice_id = request.form.get('vice_id')
        artilheiro = request.form.get('artilheiro', '').strip()
        if not campeao_id or not vice_id:
            flash('Campeão e vice são obrigatórios.', 'warning')
        elif campeao_id == vice_id:
            flash('Campeão e vice devem ser diferentes.', 'warning')
        else:
            db.execute(
                "UPDATE campeonatos SET status = 'concluído', campeao_id = ?, vice_id = ?, artilheiro = ? WHERE id = ?",
                (campeao_id, vice_id, artilheiro, campeonato_id)
            )
            db.commit()
            flash('Campeonato marcado como concluído!', 'success')
            return redirect(url_for('campeonatos'))
    return render_template('concluir_campeonato.html', campeonato=campeonato, equipes=equipes)


@app.route('/campeonatos/<int:campeonato_id>/inscrever', methods=['POST'])
@login_required
def inscrever_campeonato(campeonato_id):
    equipe_id = request.form.get('equipe_id')
    db = get_db()
    user_id = session['user_id']
    campeonato = db.execute("SELECT modalidade FROM campeonatos WHERE id = ?", (campeonato_id,)).fetchone()
    equipe = db.execute("SELECT modalidade, capitao_id FROM equipes WHERE id = ?", (equipe_id,)).fetchone()
    
    if not campeonato or not equipe:
        flash('Campeonato ou equipe não encontrados.', 'danger')
        return redirect(url_for('campeonatos'))
    
    # Verificar se o usuário é capitão ou se é X1
    if equipe['modalidade'] != 'x1':
        if equipe['capitao_id'] != user_id:
            flash('Apenas o capitão pode inscrever a equipe em campeonatos.', 'warning')
            return redirect(url_for('campeonatos'))
    else:
        # Para X1, verificar se é membro
        membro = db.execute(
            "SELECT id FROM jogadores_equipe WHERE equipe_id = ? AND usuario_id = ?",
            (equipe_id, user_id)
        ).fetchone()
        if not membro:
            flash('Você não é membro desta equipe.', 'warning')
            return redirect(url_for('campeonatos'))
    
    if equipe['modalidade'] != campeonato['modalidade']:
        flash(f'Sua equipe deve ser da modalidade {campeonato["modalidade"].upper()} para se inscrever.', 'warning')
        return redirect(url_for('campeonatos'))
    
    existing = db.execute(
        "SELECT id FROM inscricoes_campeonato WHERE campeonato_id = ? AND usuario_id = ?",
        (campeonato_id, user_id)
    ).fetchone()
    
    if existing:
        flash('Você já se inscreveu neste campeonato.', 'warning')
    else:
        db.execute(
            "INSERT INTO inscricoes_campeonato (campeonato_id, usuario_id, equipe_id, status) VALUES (?, ?, ?, 'pendente')",
            (campeonato_id, user_id, equipe_id)
        )
        db.commit()
        flash('Inscrição enviada com sucesso! Aguarde aprovação do administrador.', 'success')
    
    return redirect(url_for('campeonatos'))


@app.route('/campeonatos/cancelar/<int:campeonato_id>', methods=['POST'])
@check_setup
@admin_required
def cancelar_campeonato(campeonato_id):
    db = get_db()
    db.execute("DELETE FROM participantes_campeonato WHERE campeonato_id = ?", (campeonato_id,))
    db.execute("DELETE FROM inscricoes_campeonato WHERE campeonato_id = ?", (campeonato_id,))
    db.execute("DELETE FROM campeonatos WHERE id = ?", (campeonato_id,))
    db.commit()
    flash('Campeonato cancelado com sucesso.', 'success')
    return redirect(url_for('campeonatos'))


# ─────────────────────────────────────────────
# ADMINISTRAÇÃO DE USUÁRIOS
# ─────────────────────────────────────────────

@app.route('/admin/usuarios')
@check_setup
@check_setup
@admin_required
def admin_usuarios():
    db = get_db()
    usuarios = db.execute("SELECT id, username, role, pergunta_seguranca, resposta_seguranca, acesso_liberado, bloqueado FROM usuarios ORDER BY username ASC").fetchall()
    solicitacoes = db.execute(
        """SELECT s.id, s.usuario_id, u.username, s.data_solicitacao, s.status
           FROM solicitacoes_acesso s
           JOIN usuarios u ON s.usuario_id = u.id
           WHERE s.status = 'pendente'
           ORDER BY s.data_solicitacao DESC"""
    ).fetchall()
    return render_template('admin_usuarios.html', usuarios=usuarios, solicitacoes=solicitacoes)


@app.route('/admin/usuarios/<int:usuario_id>')
@check_setup
@admin_required
def admin_ver_usuario(usuario_id):
    db = get_db()
    usuario = db.execute(
        "SELECT id, username, password, role, pergunta_seguranca, resposta_seguranca, acesso_liberado, bloqueado FROM usuarios WHERE id = ?",
        (usuario_id,)
    ).fetchone()
    if not usuario:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('admin_usuarios'))
    return render_template('admin_ver_usuario.html', usuario=usuario)


@app.route('/admin/usuarios/<int:usuario_id>/editar', methods=['POST'])
@check_setup
@admin_required
def admin_editar_usuario(usuario_id):
    db = get_db()
    usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not usuario:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('admin_usuarios'))

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    new_role = request.form.get('role', usuario['role']).strip()
    pergunta = request.form.get('pergunta_seguranca', '').strip()
    resposta = request.form.get('resposta_seguranca', '').strip().lower()
    acesso_liberado = 1 if request.form.get('acesso_liberado') else 0
    bloqueado = 1 if request.form.get('bloqueado') else 0

    # Proteção: Apenas Dono pode promover usuários a Administrador
    if new_role == 'admin' and usuario['role'] != 'admin':
        if session.get('role') != 'dono':
            flash('Apenas o Dono pode promover usuários a Administrador.', 'danger')
            return redirect(url_for('admin_ver_usuario', usuario_id=usuario_id))
        
        # Exigir senha do dono para confirmar promoção
        senha_dono = request.form.get('senha_confirmacao_dono')
        dono = db.execute("SELECT password FROM usuarios WHERE id = ?", (session['user_id'],)).fetchone()
        if not senha_dono or senha_dono != dono['password']:
            flash('Senha do Dono incorreta. Promoção cancelada.', 'danger')
            return redirect(url_for('admin_ver_usuario', usuario_id=usuario_id))

    if not username:
        flash('Nome de usuário é obrigatório.', 'warning')
        return redirect(url_for('admin_ver_usuario', usuario_id=usuario_id))

    # Se uma nova senha foi informada, validar a política de senha forte
    if password:
        senha_ok, senha_msg = validar_senha_forte(password)
        if not senha_ok:
            flash(f'Senha fraca: {senha_msg}', 'danger')
            return redirect(url_for('admin_ver_usuario', usuario_id=usuario_id))
        nova_senha = password
    else:
        # Manter a senha atual
        nova_senha = usuario['password']

    existing = db.execute("SELECT id FROM usuarios WHERE username = ? AND id != ?", (username, usuario_id)).fetchone()
    if existing:
        flash('Nome de usuário já está em uso por outro usuário.', 'danger')
        return redirect(url_for('admin_ver_usuario', usuario_id=usuario_id))

    db.execute(
        "UPDATE usuarios SET username = ?, password = ?, role = ?, pergunta_seguranca = ?, resposta_seguranca = ?, acesso_liberado = ?, bloqueado = ? WHERE id = ?",
        (username, nova_senha, new_role, pergunta, resposta, acesso_liberado, bloqueado, usuario_id)
    )
    db.commit()
    flash(f'Dados do usuário {username} atualizados com sucesso!', 'success')
    return redirect(url_for('admin_ver_usuario', usuario_id=usuario_id))


@app.route('/admin/usuarios/criar', methods=['GET', 'POST'])
@check_setup
@admin_required
def admin_criar_usuario():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'user').strip()
        pergunta = request.form.get('pergunta_seguranca', '').strip()
        resposta = request.form.get('resposta_seguranca', '').strip().lower()

        if not username or not password:
            flash('Usuário e senha são obrigatórios.', 'warning')
            return render_template('admin_criar_usuario.html')

        senha_ok, senha_msg = validar_senha_forte(password)
        if not senha_ok:
            flash(f'Senha fraca: {senha_msg}', 'danger')
            return render_template('admin_criar_usuario.html')

        db = get_db()
        
        # Proteção: Apenas Dono pode criar Admins
        if role == 'admin':
            if session.get('role') != 'dono':
                flash('Apenas o Dono pode criar novos Administradores.', 'danger')
                return render_template('admin_criar_usuario.html')
            
            # Exigir senha do dono para confirmar criação
            senha_dono = request.form.get('senha_confirmacao_dono')
            dono = db.execute("SELECT password FROM usuarios WHERE id = ?", (session['user_id'],)).fetchone()
            if not senha_dono or senha_dono != dono['password']:
                flash('Senha do Dono incorreta. Criação de Admin cancelada.', 'danger')
                return render_template('admin_criar_usuario.html')
        existing = db.execute("SELECT id FROM usuarios WHERE username = ?", (username,)).fetchone()
        if existing:
            flash('Nome de usuário já está em uso.', 'danger')
            return render_template('admin_criar_usuario.html')

        db.execute(
            "INSERT INTO usuarios (username, password, role, pergunta_seguranca, resposta_seguranca, acesso_liberado) VALUES (?, ?, ?, ?, ?, 1)",
            (username, password, role, pergunta or 'Qual é o nome do sistema?', resposta or 'ifpi campeonatos')
        )
        db.commit()
        flash(f'Usuário {username} criado com sucesso!', 'success')
        return redirect(url_for('admin_usuarios'))

    return render_template('admin_criar_usuario.html')


@app.route('/admin/usuarios/excluir/<int:usuario_id>', methods=['POST'])
@check_setup
@admin_required
def excluir_usuario(usuario_id):
    db = get_db()
    target_user = db.execute("SELECT role FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    
    if not target_user:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('admin_usuarios'))

    if usuario_id == session.get('user_id'):
        flash('Você não pode excluir sua própria conta.', 'warning')
    elif target_user['role'] == 'dono':
        flash('O Dono do sistema não pode ser excluído.', 'danger')
    elif target_user['role'] == 'admin' and session.get('role') != 'dono':
        flash('Apenas o Dono pode excluir outros Administradores.', 'danger')
    else:
        db.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        db.commit()
        flash('Usuário excluído com sucesso.', 'success')
    return redirect(url_for('admin_usuarios'))


@app.route('/admin/solicitacoes/<int:solicitacao_id>/liberar', methods=['POST'])
@check_setup
@admin_required
def liberar_acesso(solicitacao_id):
    db = get_db()
    solicitacao = db.execute("SELECT * FROM solicitacoes_acesso WHERE id = ?", (solicitacao_id,)).fetchone()
    if not solicitacao:
        flash('Solicitação não encontrada.', 'danger')
        return redirect(url_for('admin_usuarios'))
    usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (solicitacao['usuario_id'],)).fetchone()
    if usuario:
        for role in ['user', 'admin']:
            chave_senha = f"{role}:{usuario['username']}"
            chave_pergunta = f"pergunta:{role}:{usuario['username']}"
            resetar_tentativas(tentativas_senha, chave_senha)
            resetar_tentativas(tentativas_pergunta, chave_pergunta)
        db.execute("UPDATE solicitacoes_acesso SET status = 'liberado' WHERE id = ?", (solicitacao_id,))
        db.commit()
        flash(f'Acesso do usuário {usuario["username"]} liberado com sucesso!', 'success')
    return redirect(url_for('admin_usuarios'))


@app.route('/admin/solicitacoes/<int:solicitacao_id>/recusar', methods=['POST'])
@check_setup
@admin_required
def recusar_solicitacao(solicitacao_id):
    db = get_db()
    db.execute("UPDATE solicitacoes_acesso SET status = 'recusado' WHERE id = ?", (solicitacao_id,))
    db.commit()
    flash('Solicitação recusada.', 'info')
    return redirect(url_for('admin_usuarios'))


# ─────────────────────────────────────────────
# CHAVEAMENTO E PARTIDAS DE CAMPEONATO
# ─────────────────────────────────────────────

@app.route('/campeonatos/<int:campeonato_id>/gerar-chaveamento', methods=['POST'])
@check_setup
@admin_required
def gerar_chaveamento(campeonato_id):
    """Gera o chaveamento (quartas, semis, final) para um campeonato"""
    from helpers_chaveamento import gerar_chaveamento_quartas
    db = get_db()
    
    campeonato = db.execute("SELECT * FROM campeonatos WHERE id = ?", (campeonato_id,)).fetchone()
    if not campeonato:
        flash('Campeonato não encontrado.', 'danger')
        return redirect(url_for('campeonatos'))
    
    # Obter equipes participantes
    equipes = db.execute(
        """SELECT e.id FROM participantes_campeonato pc
           JOIN equipes e ON pc.equipe_id = e.id
           WHERE pc.campeonato_id = ?""",
        (campeonato_id,)
    ).fetchall()
    
    equipes_ids = [e['id'] for e in equipes]
    
    if len(equipes_ids) < 4:
        flash('É necessário no mínimo 4 equipes para gerar o chaveamento.', 'warning')
        return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))
    
    # Deletar partidas anteriores se existirem
    db.execute("DELETE FROM partidas_campeonato WHERE campeonato_id = ?", (campeonato_id,))
    
    # Gerar partidas das quartas
    partidas_quartas = gerar_chaveamento_quartas(equipes_ids)
    for i, partida in enumerate(partidas_quartas, 1):
        status = 'concluído' if partida['equipe2'] is None else 'aberto'
        vencedor_id = partida['equipe1'] if partida['equipe2'] is None else None
        db.execute(
            """INSERT INTO partidas_campeonato 
               (campeonato_id, equipe1_id, equipe2_id, fase, numero_partida, status, vencedor_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (campeonato_id, partida['equipe1'], partida['equipe2'], 'quartas', i, status, vencedor_id)
        )
    
    db.commit()
    flash(f'Chaveamento gerado com {len(partidas_quartas)} partidas nas quartas!', 'success')
    return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))


@app.route('/campeonatos/<int:campeonato_id>/partida/<int:partida_id>', methods=['GET', 'POST'])
@check_setup
@admin_required
def gerenciar_partida(campeonato_id, partida_id):
    """Exibe e gerencia os detalhes de uma partida do campeonato"""
    db = get_db()
    
    partida = db.execute(
        """SELECT pc.*, e1.nome as equipe1_nome, e2.nome as equipe2_nome
           FROM partidas_campeonato pc
           LEFT JOIN equipes e1 ON pc.equipe1_id = e1.id
           LEFT JOIN equipes e2 ON pc.equipe2_id = e2.id
           WHERE pc.id = ? AND pc.campeonato_id = ?""",
        (partida_id, campeonato_id)
    ).fetchone()
    
    if not partida:
        flash('Partida não encontrada.', 'danger')
        return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))
    
    if request.method == 'POST':
        placar_equipe1 = request.form.get('placar_equipe1', '0')
        placar_equipe2 = request.form.get('placar_equipe2', '0')
        artilheiro = request.form.get('artilheiro', '').strip()
        wo = 1 if request.form.get('wo') else 0
        motivo_wo = request.form.get('motivo_wo', '').strip()
        vencedor_id_manual = request.form.get('vencedor_id_wo')
        
        try:
            placar_equipe1 = int(placar_equipe1)
            placar_equipe2 = int(placar_equipe2)
        except:
            flash('Placares inválidos.', 'warning')
            return redirect(url_for('gerenciar_partida', campeonato_id=campeonato_id, partida_id=partida_id))
        
        # Determinar vencedor
        vencedor_id = None
        if wo:
            if not vencedor_id_manual:
                flash('Em caso de WO, você deve selecionar o vencedor.', 'warning')
                return redirect(url_for('gerenciar_partida', campeonato_id=campeonato_id, partida_id=partida_id))
            vencedor_id = int(vencedor_id_manual)
        else:
            if placar_equipe1 > placar_equipe2:
                vencedor_id = partida['equipe1_id']
            elif placar_equipe2 > placar_equipe1:
                vencedor_id = partida['equipe2_id']
            else:
                flash('A partida não pode terminar empatada. Defina um vencedor.', 'warning')
                return redirect(url_for('gerenciar_partida', campeonato_id=campeonato_id, partida_id=partida_id))
        
        # Atualizar partida
        db.execute(
            """UPDATE partidas_campeonato 
               SET status = 'concluído', placar_equipe1 = ?, placar_equipe2 = ?, 
                   artilheiro = ?, vencedor_id = ?, wo = ?, motivo_wo = ?
               WHERE id = ?""",
            (placar_equipe1, placar_equipe2, artilheiro, vencedor_id, wo, motivo_wo, partida_id)
        )
        db.commit()
        
        # Verificar se foi a final e se está concluída
        if partida['fase'] == 'final':
            # Determinar o vice-campeão
            vice_id = partida['equipe2_id'] if vencedor_id == partida['equipe1_id'] else partida['equipe1_id']
            
            # Marcar campeonato como concluído com o vencedor e vice da final
            db.execute(
                """UPDATE campeonatos 
                   SET status = 'concluído', campeao_id = ?, vice_id = ?
                   WHERE id = ?""",
                (vencedor_id, vice_id, campeonato_id)
            )
            db.commit()
            flash('Campeonato concluído! Campeão e Vice definidos!', 'success')
        else:
            flash('Partida concluída com sucesso!', 'success')
        
        return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))
    
    return render_template('gerenciar_partida.html', partida=partida, campeonato_id=campeonato_id)


@app.route('/campeonatos/<int:campeonato_id>/avancar-fase', methods=['POST'])
@check_setup
@admin_required
def avancar_fase(campeonato_id):
    """Avança para a próxima fase do campeonato (quartas -> semis -> final)"""
    from helpers_chaveamento import gerar_chaveamento_semis, gerar_chaveamento_final, obter_melhor_perdedor, obter_times_que_passam_direto
    db = get_db()
    
    campeonato = db.execute("SELECT * FROM campeonatos WHERE id = ?", (campeonato_id,)).fetchone()
    if not campeonato:
        flash('Campeonato não encontrado.', 'danger')
        return redirect(url_for('campeonatos'))
    
    # Obter fase atual
    fase_atual = request.form.get('fase_atual', 'quartas')
    
    # Obter vencedores da fase atual (excluindo times que passaram direto)
    vencedores = db.execute(
        """SELECT vencedor_id FROM partidas_campeonato 
           WHERE campeonato_id = ? AND fase = ? AND status = 'concluído' AND equipe2_id IS NOT NULL
           ORDER BY numero_partida""",
        (campeonato_id, fase_atual)
    ).fetchall()
    
    vencedores_ids = [v['vencedor_id'] for v in vencedores]
    
    # Obter times que passaram direto (bye)
    times_bye = obter_times_que_passam_direto(db, campeonato_id, fase_atual)
    
    # Adicionar times que passaram direto aos vencedores
    vencedores_ids.extend(times_bye)
    
    # Verificar se todas as partidas foram concluídas
    total_partidas = db.execute(
        "SELECT COUNT(*) as total FROM partidas_campeonato WHERE campeonato_id = ? AND fase = ?",
        (campeonato_id, fase_atual)
    ).fetchone()['total']
    
    if len(vencedores_ids) != total_partidas:
        flash(f'Nem todas as partidas das {fase_atual} foram concluídas.', 'warning')
        return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))
    
    # Obter melhor perdedor se necessário
    melhor_perdedor = None
    if len(vencedores_ids) % 2 != 0:
        melhor_perdedor = obter_melhor_perdedor(db, campeonato_id, fase_atual)
    
    # Gerar próxima fase
    if fase_atual == 'quartas':
        partidas_proxima = gerar_chaveamento_semis(vencedores_ids, melhor_perdedor)
        proxima_fase = 'semi'
    elif fase_atual == 'semi':
        partidas_proxima = gerar_chaveamento_final(vencedores_ids, melhor_perdedor)
        proxima_fase = 'final'
    else:
        flash('Fase desconhecida.', 'danger')
        return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))
    
    # Inserir partidas da próxima fase
    for i, partida in enumerate(partidas_proxima, 1):
        status = 'concluído' if partida['equipe2'] is None else 'aberto'
        vencedor_id = partida['equipe1'] if partida['equipe2'] is None else None
        db.execute(
            """INSERT INTO partidas_campeonato 
               (campeonato_id, equipe1_id, equipe2_id, fase, numero_partida, status, vencedor_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (campeonato_id, partida['equipe1'], partida['equipe2'], proxima_fase, i, status, vencedor_id)
        )
    
    db.commit()
    flash(f'Chaveamento avançado para {proxima_fase}!', 'success')
    
    # Se avançou para a final, redirecionar para a página de conclusão
    if proxima_fase == 'final':
        flash('Chaveamento chegou à final! Aguarde a conclusão da última partida.', 'info')
    
    return redirect(url_for('detalhes_campeonato', campeonato_id=campeonato_id))


@app.route('/api/minha-equipe')
@login_required
def api_minha_equipe():
    """Retorna lista de equipes que o usuário atual pode gerenciar (AJAX)"""
    from flask import jsonify
    db = get_db()
    user_id = session.get('user_id')
    
    # Buscar equipes onde o usuário é capitão ou membro de X1
    equipes = db.execute(
        """SELECT DISTINCT e.id, e.nome, e.modalidade FROM equipes e 
           LEFT JOIN jogadores_equipe je ON e.id = je.equipe_id 
           WHERE e.capitao_id = ? OR (e.modalidade = 'x1' AND je.usuario_id = ?)""",
        (user_id, user_id)
    ).fetchall()
    
    return jsonify([dict(row) for row in equipes])


@app.route('/equipes/jogadores-disponiveis/<string:modalidade>')
@login_required
def jogadores_disponiveis(modalidade):
    """Retorna lista de jogadores que ainda não têm equipe na modalidade especificada (AJAX)"""
    from flask import jsonify
    db = get_db()
    
    try:
        # Obter IDs de jogadores que já têm equipe na modalidade selecionada
        jogadores_ocupados = db.execute(
            """SELECT DISTINCT je.usuario_id FROM jogadores_equipe je
               JOIN equipes e ON je.equipe_id = e.id
               WHERE e.modalidade = ?""",
            (modalidade,)
        ).fetchall()
        
        ids_ocupados = [j['usuario_id'] for j in jogadores_ocupados]
        
        # Obter todos os usuários que não estão ocupados nessa modalidade
        if ids_ocupados:
            placeholders = ','.join('?' * len(ids_ocupados))
            usuarios = db.execute(
                f"SELECT id, username FROM usuarios WHERE role = 'user' AND id NOT IN ({placeholders}) ORDER BY username",
                ids_ocupados
            ).fetchall()
        else:
            usuarios = db.execute(
                "SELECT id, username FROM usuarios WHERE role = 'user' ORDER BY username"
            ).fetchall()
        
        resultado = [{'id': u['id'], 'username': u['username']} for u in usuarios]
        return jsonify(resultado)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
