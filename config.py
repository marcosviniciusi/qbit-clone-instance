"""
Configuração do qBittorrent Clone Tool
Arquivo: /etc/qbit-clone/config.py
"""

# ==================== INSTÂNCIA ORIGEM ====================
SRC_HOST = 'qbit-origem.meudominio.com.br'
SRC_PORT = 443
SRC_USE_HTTPS = True
SRC_VERIFY_SSL = True
SRC_USER = 'admin'
SRC_PASS = 'sua_senha_origem'

# ==================== INSTÂNCIA DESTINO ====================
DST_HOST = 'qbit-destino.meudominio.com.br'
DST_PORT = 443
DST_USE_HTTPS = True
DST_VERIFY_SSL = True
DST_USER = 'admin'
DST_PASS = 'sua_senha_destino'

# ==================== BANCO DE DADOS ====================
DATABASE_FILE = '/var/lib/qbit-clone/state.db'

# Modo de limpeza:
# 'delete' = Remove torrent E arquivos do destino
# 'remove' = Remove apenas o torrent, mantém arquivos
CLEANUP_MODE = 'remove'

# ==================== OPÇÕES DE MIGRAÇÃO ====================

# Apenas torrents com estado SEEDING
ONLY_SEEDING_STATE = True

# Pula verificação de hash ao adicionar no destino
SKIP_CHECKING = True

# Adiciona torrents pausados no destino
START_PAUSED = False

# Força upload (super seeding) nos torrents clonados
# True = Torrents farão upload agressivamente (ignora filas e limites)
# False = Comportamento normal
FORCE_UPLOAD = True

# Delay entre migrações em segundos
SYNC_INTERVAL = 0.5

# ==================== LOGS ====================
LOG_FILE = '/var/log/qbit-clone.log'
VERBOSE = 1  # 0=erro, 1=normal, 2=debug

# ==================== FILTROS (OPCIONAL) ====================
FILTER_CATEGORIES = None
MIN_SIZE_GB = None
MIN_RATIO = None
MIN_UPLOAD_GB = None

# ==================== TIMEOUTS ====================
REQUEST_TIMEOUT = 30

# ==================== ESTADOS VÁLIDOS SEEDING ====================
VALID_SEEDING_STATES = ['uploading', 'stalledUP', 'queuedUP', 'forcedUP', 'checkingUP']