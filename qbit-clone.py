#!/usr/bin/env python3
"""
qBittorrent Clone Tool - Versão Final com Blacklist Inteligente
Sincroniza torrents em SEEDING entre instâncias

Recursos:
- Blacklist automática de torrents problemáticos (download/erro)
- Limpeza automática da blacklist (remove se não existe mais na origem)
- Operações em lote no banco de dados (batch)
- Force upload opcional nos torrents clonados
- Aguarda 10s após clonar para verificar estados

Uso: qbit-migrate.py [HASH]
"""

import sys
import time
import urllib3
import sqlite3
from typing import Optional, List
from pathlib import Path
from datetime import datetime

# Importa configurações
sys.path.insert(0, '/etc/qbit-clone')

try:
    import config
except ImportError:
    print("❌ ERRO: /etc/qbit-clone/config.py não encontrado!")
    sys.exit(1)

try:
    from qbittorrentapi import Client
except ImportError:
    print("❌ ERRO: pip install qbittorrent-api")
    sys.exit(1)

if not config.SRC_VERIFY_SSL or not config.DST_VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ==================== DATABASE ====================

class SyncDatabase:
    """Banco de dados otimizado com blacklist inteligente"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Cria estrutura do banco"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # TABELA 1: State da origem (SOBRESCREVE a cada execução)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS state_origem (
                hash TEXT PRIMARY KEY,
                name TEXT,
                category TEXT,
                size_bytes INTEGER,
                state TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # TABELA 2: Histórico de clonagens (APPEND ONLY)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cloned_torrents (
                hash TEXT PRIMARY KEY,
                name TEXT,
                category TEXT,
                size_bytes INTEGER,
                cloned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # TABELA 3: Log de operações
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                operation TEXT,
                torrent_hash TEXT,
                torrent_name TEXT,
                details TEXT
            )
        ''')
        
        # TABELA 4: Blacklist de torrents problemáticos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blacklist_torrents (
                hash TEXT PRIMARY KEY,
                name TEXT,
                reason TEXT,
                blacklisted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                attempts INTEGER DEFAULT 1
            )
        ''')
        
        # Índices para performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cloned_hash ON cloned_torrents(hash)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_state_hash ON state_origem(hash)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_blacklist_hash ON blacklist_torrents(hash)')
        
        conn.commit()
        conn.close()
    
    def update_state_origem(self, torrents: list):
        """SOBRESCREVE tabela state_origem com snapshot atual (BATCH)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM state_origem')
        
        batch = [(t.hash, t.name, t.category or '', t.size, t.state) for t in torrents]
        cursor.executemany('''
            INSERT INTO state_origem (hash, name, category, size_bytes, state)
            VALUES (?, ?, ?, ?, ?)
        ''', batch)
        
        conn.commit()
        conn.close()
    
    def get_state_origem_hashes(self) -> set:
        """Retorna set de hashes na origem"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT hash FROM state_origem')
        hashes = {row[0] for row in cursor.fetchall()}
        conn.close()
        return hashes
    
    def get_blacklist_hashes(self) -> set:
        """Retorna set de hashes na blacklist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT hash FROM blacklist_torrents')
        hashes = {row[0] for row in cursor.fetchall()}
        conn.close()
        return hashes
    
    def add_to_blacklist_batch(self, torrents: List[tuple]):
        """
        Adiciona múltiplos torrents à blacklist
        
        Args:
            torrents: Lista de tuplas (hash, name, reason)
        """
        if not torrents:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Insert ou update
        for hash, name, reason in torrents:
            cursor.execute('''
                INSERT INTO blacklist_torrents (hash, name, reason, attempts)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(hash) DO UPDATE SET
                    attempts = attempts + 1,
                    blacklisted_at = CURRENT_TIMESTAMP,
                    reason = excluded.reason
            ''', (hash, name, reason))
        
        # Log
        log_batch = [(
            'BLACKLIST',
            t[0],  # hash
            t[1],  # name
            f'Reason: {t[2]}'
        ) for t in torrents]
        
        cursor.executemany('''
            INSERT INTO operation_log (operation, torrent_hash, torrent_name, details)
            VALUES (?, ?, ?, ?)
        ''', log_batch)
        
        conn.commit()
        conn.close()
    
    def cleanup_blacklist(self, origem_hashes: set) -> int:
        """
        Remove da blacklist torrents que não existem mais na origem
        
        Args:
            origem_hashes: Set de hashes atualmente na origem
            
        Returns:
            Número de itens removidos da blacklist
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Busca todos os hashes na blacklist
        cursor.execute('SELECT hash, name FROM blacklist_torrents')
        blacklist_items = cursor.fetchall()
        
        to_remove = []
        for hash, name in blacklist_items:
            if hash not in origem_hashes:
                to_remove.append((hash, name))
        
        if to_remove:
            # Remove da blacklist
            hashes = [t[0] for t in to_remove]
            placeholders = ','.join('?' * len(hashes))
            cursor.execute(f'DELETE FROM blacklist_torrents WHERE hash IN ({placeholders})', hashes)
            
            # Log
            log_batch = [(
                'UNBLACKLIST',
                t[0],
                t[1],
                'Não existe mais na origem'
            ) for t in to_remove]
            
            cursor.executemany('''
                INSERT INTO operation_log (operation, torrent_hash, torrent_name, details)
                VALUES (?, ?, ?, ?)
            ''', log_batch)
        
        conn.commit()
        conn.close()
        
        return len(to_remove)
    
    def add_cloned_batch(self, torrents: List[tuple]):
        """Adiciona múltiplos torrents clonados (BATCH)"""
        if not torrents:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.executemany('''
            INSERT OR IGNORE INTO cloned_torrents (hash, name, category, size_bytes)
            VALUES (?, ?, ?, ?)
        ''', torrents)
        
        log_batch = [(
            'CLONE',
            t[0],
            t[1],
            f'Category: {t[2]}'
        ) for t in torrents]
        
        cursor.executemany('''
            INSERT INTO operation_log (operation, torrent_hash, torrent_name, details)
            VALUES (?, ?, ?, ?)
        ''', log_batch)
        
        conn.commit()
        conn.close()
    
    def remove_cloned_batch(self, torrents: List[tuple]):
        """Remove múltiplos torrents (BATCH)"""
        if not torrents:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        hashes = [t[0] for t in torrents]
        placeholders = ','.join('?' * len(hashes))
        cursor.execute(f'DELETE FROM cloned_torrents WHERE hash IN ({placeholders})', hashes)
        
        log_batch = [(
            'DELETE',
            t[0],
            t[1]
        ) for t in torrents]
        
        cursor.executemany('''
            INSERT INTO operation_log (operation, torrent_hash, torrent_name)
            VALUES (?, ?, ?)
        ''', log_batch)
        
        conn.commit()
        conn.close()
    
    def get_stats(self) -> dict:
        """Estatísticas rápidas"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*), SUM(size_bytes) FROM state_origem')
        origem_count, origem_size = cursor.fetchone()
        
        cursor.execute('SELECT COUNT(*), SUM(size_bytes) FROM cloned_torrents')
        cloned_count, cloned_size = cursor.fetchone()
        
        cursor.execute('SELECT COUNT(*) FROM blacklist_torrents')
        blacklist_count = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT operation, COUNT(*) FROM operation_log 
            WHERE timestamp > datetime('now', '-24 hours')
            GROUP BY operation
        ''')
        ops_24h = dict(cursor.fetchall())
        
        conn.close()
        
        return {
            'origem_count': origem_count or 0,
            'origem_size_gb': (origem_size or 0) / (1024**3),
            'cloned_count': cloned_count or 0,
            'cloned_size_gb': (cloned_size or 0) / (1024**3),
            'blacklist_count': blacklist_count,
            'ops_24h': ops_24h
        }


# ==================== FUNÇÕES ====================

def log(msg: str, level: int = 1):
    """Log com nível de verbosidade"""
    if config.VERBOSE >= level:
        print(msg)


def log_error(msg: str):
    """Log de erro em arquivo"""
    try:
        Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_FILE, 'a') as f:
            f.write(f"[{datetime.now()}] {msg}\n")
    except:
        pass


def build_url(host: str, port: int, use_https: bool) -> str:
    """Monta URL"""
    protocol = 'https' if use_https else 'http'
    return f"{protocol}://{host}:{port}"


def get_clients():
    """Conecta nas instâncias"""
    log("🔌 Conectando...", 1)
    
    try:
        src = Client(
            host=build_url(config.SRC_HOST, config.SRC_PORT, config.SRC_USE_HTTPS),
            username=config.SRC_USER,
            password=config.SRC_PASS,
            VERIFY_WEBUI_CERTIFICATE=config.SRC_VERIFY_SSL,
            REQUESTS_ARGS={'timeout': config.REQUEST_TIMEOUT}
        )
        
        dst = Client(
            host=build_url(config.DST_HOST, config.DST_PORT, config.DST_USE_HTTPS),
            username=config.DST_USER,
            password=config.DST_PASS,
            VERIFY_WEBUI_CERTIFICATE=config.DST_VERIFY_SSL,
            REQUESTS_ARGS={'timeout': config.REQUEST_TIMEOUT}
        )
        
        src.auth_log_in()
        dst.auth_log_in()
        
        log(f"✅ ORIGEM: {config.SRC_HOST}:{config.SRC_PORT} | v{src.app.version}", 1)
        log(f"✅ DESTINO: {config.DST_HOST}:{config.DST_PORT} | v{dst.app.version}", 1)
        
        return src, dst
        
    except Exception as e:
        log(f"❌ Erro de autenticação: {e}", 0)
        log_error(f"Auth error: {e}")
        sys.exit(1)


def apply_filters(torrent) -> tuple[bool, str]:
    """Aplica filtros configurados"""
    if config.ONLY_SEEDING_STATE:
        if torrent.state not in config.VALID_SEEDING_STATES:
            return False, f"Estado {torrent.state} inválido"
    
    if config.FILTER_CATEGORIES:
        if torrent.category not in config.FILTER_CATEGORIES:
            return False, f"Categoria filtrada"
    
    if config.MIN_SIZE_GB:
        if torrent.size / (1024**3) < config.MIN_SIZE_GB:
            return False, "Tamanho menor que mínimo"
    
    if config.MIN_RATIO and torrent.ratio < config.MIN_RATIO:
        return False, "Ratio menor que mínimo"
    
    if config.MIN_UPLOAD_GB:
        if torrent.uploaded / (1024**3) < config.MIN_UPLOAD_GB:
            return False, "Upload menor que mínimo"
    
    return True, "OK"


def sync_categories(src, dst):
    """Sincroniza categorias"""
    log("\n📂 Sincronizando categorias...", 1)
    
    try:
        src_cats = src.torrents_categories()
        dst_cats = dst.torrents_categories()
        
        created = 0
        for name, info in src_cats.items():
            if config.FILTER_CATEGORIES and name not in config.FILTER_CATEGORIES:
                continue
            
            if name not in dst_cats:
                dst.torrents_create_category(name=name, save_path=info.get('savePath', ''))
                log(f"  ➕ {name}", 1)
                created += 1
        
        log(f"  ✅ {created} categorias criadas" if created else "  ✅ Categorias OK", 1)
        
    except Exception as e:
        log(f"  ⚠️  Erro: {e}", 0)


def clone_torrent_verified(src, dst, torrent) -> bool:
    """Clona torrent e confirma adição com force upload"""
    try:
        torrent_file = src.torrents_export(torrent_hash=torrent.hash)
        if not torrent_file:
            log(f"     ⚠️  Falha ao exportar .torrent", 2)
            return False
        
        result = dst.torrents_add(
            torrent_files=torrent_file,
            save_path=torrent.save_path,
            category=torrent.category,
            tags=torrent.tags,
            is_skip_checking=config.SKIP_CHECKING,
            is_paused=config.START_PAUSED,
            use_auto_torrent_management=torrent.auto_tmm
        )
        
        if result != "Ok.":
            log(f"     ⚠️  API retornou: {result}", 2)
            return False
        
        clone_confirmed = False
        for attempt in range(2):
            time.sleep(0.5)
            check = dst.torrents_info(torrent_hashes=torrent.hash)
            if check:
                clone_confirmed = True
                break
        
        if not clone_confirmed:
            log_error(f"Clone unconfirmed: {torrent.hash}")
            return False
        
        if config.FORCE_UPLOAD:
            try:
                dst.torrents_set_force_start(torrent_hashes=torrent.hash, enable=True)
                log(f"     ⚡ Force upload ativado", 2)
            except Exception as e:
                log_error(f"Force upload failed {torrent.hash}: {e}")
        
        return True
        
    except Exception as e:
        log_error(f"Clone error {torrent.hash}: {e}")
        return False


def delete_torrent_verified(dst, torrent) -> bool:
    """Deleta torrent e confirma remoção"""
    try:
        delete_files = (config.CLEANUP_MODE == 'delete')
        dst.torrents_delete(delete_files=delete_files, torrent_hashes=torrent.hash)
        
        delete_confirmed = False
        for attempt in range(2):
            time.sleep(0.5)
            if not dst.torrents_info(torrent_hashes=torrent.hash):
                delete_confirmed = True
                break
        
        if not delete_confirmed:
            log_error(f"Delete unconfirmed: {torrent.hash}")
            return False
        
        return True
        
    except Exception as e:
        log_error(f"Delete error {torrent.hash}: {e}")
        return False


def remove_unwanted_torrents(dst, db: SyncDatabase) -> dict:
    """
    Remove torrents indesejados e adiciona à blacklist
    """
    log("\n🚫 Removendo torrents indesejados...", 1)
    
    try:
        dst_torrents = dst.torrents_info()
        
        downloading_states = [
            'downloading', 'metaDL', 'allocating', 'checkingDL',
            'pausedDL', 'queuedDL', 'stalledDL', 'forcedDL'
        ]
        
        error_states = ['error', 'missingFiles', 'unknown']
        
        downloading = [t for t in dst_torrents if t.state in downloading_states]
        errored = [t for t in dst_torrents if t.state in error_states]
        
        total_unwanted = len(downloading) + len(errored)
        
        if total_unwanted == 0:
            log(f"  ✅ Nenhum torrent indesejado", 1)
            return {'downloading': 0, 'error': 0, 'total': 0}
        
        log(f"  🚫 {total_unwanted} torrents indesejados detectados:", 1)
        if downloading:
            log(f"     📥 {len(downloading)} em download", 1)
        if errored:
            log(f"     ⚠️  {len(errored)} com erro", 1)
        
        removed_batch = []
        blacklist_batch = []
        failed = 0
        to_remove = downloading + errored
        
        for idx, t in enumerate(to_remove, 1):
            is_download = t.state in downloading_states
            reason = "download" if is_download else f"erro:{t.state}"
            
            log(f"  [{idx}/{len(to_remove)}] {t.name[:45]}... ({reason})", 1)
            
            try:
                dst.torrents_delete(delete_files=False, torrent_hashes=t.hash)
                time.sleep(0.5)
                
                if not dst.torrents_info(torrent_hashes=t.hash):
                    removed_batch.append((t.hash, t.name))
                    blacklist_batch.append((t.hash, t.name, reason))
                    log(f"     ✅ Removido e adicionado à blacklist", 1)
                else:
                    log(f"     ❌ Falha ao remover", 0)
                    failed += 1
                
            except Exception as e:
                log(f"     ❌ Erro: {e}", 0)
                log_error(f"Remove unwanted error {t.hash}: {e}")
                failed += 1
            
            time.sleep(0.2)
        
        # Atualiza banco
        if removed_batch:
            log(f"\n  💾 Atualizando banco ({len(removed_batch)} remoções)...", 1)
            db.remove_cloned_batch(removed_batch)
            log(f"  ✅ Banco atualizado", 1)
        
        # Adiciona à blacklist
        if blacklist_batch:
            log(f"  🚷 Adicionando {len(blacklist_batch)} à blacklist...", 1)
            db.add_to_blacklist_batch(blacklist_batch)
            log(f"  ✅ Blacklist atualizada", 1)
        
        log(f"\n  📊 Removidos: {len(removed_batch)} | Falhas: {failed}", 1)
        
        return {
            'downloading': len(downloading),
            'error': len(errored),
            'total': len(removed_batch)
        }
        
    except Exception as e:
        log(f"  ⚠️  Erro ao verificar: {e}", 0)
        log_error(f"Check unwanted failed: {e}")
        return {'downloading': 0, 'error': 0, 'total': 0}


def execute_sync(single_hash: Optional[str] = None):
    """
    TAREFA ÚNICA DE SINCRONIZAÇÃO COM BLACKLIST INTELIGENTE
    
    1. Snapshot origem → state_origem
    2. Limpa blacklist (remove se não existe mais na origem)
    3. Clona faltantes (pula blacklist)
    4. Remove órfãos
    5. Aguarda 10s (se clonou)
    6. Remove download/erro + adiciona blacklist
    """
    
    db = SyncDatabase(config.DATABASE_FILE)
    src, dst = get_clients()
    
    # ========== MODO SINGLE HASH (via hook) ==========
    if single_hash:
        log(f"\n🎯 Modo: Hook (hash: {single_hash})", 1)
        
        # Verifica blacklist
        if db.get_blacklist_hashes() and single_hash in db.get_blacklist_hashes():
            log(f"🚷 Torrent está na blacklist, pulando...", 1)
            return
        
        torrents = src.torrents_info(torrent_hashes=single_hash)
        if not torrents:
            log("⚠️  Hash não encontrado", 0)
            return
        
        t = torrents[0]
        
        passed, reason = apply_filters(t)
        if not passed:
            log(f"⏭️  Filtrado: {reason}", 1)
            return
        
        if dst.torrents_info(torrent_hashes=single_hash):
            log("⏭️  Já existe no destino", 1)
            return
        
        sync_categories(src, dst)
        
        log(f"\n🔄 {t.name}", 1)
        log(f"   {t.size / (1024**3):.2f} GB | Ratio: {t.ratio:.2f}", 1)
        
        if clone_torrent_verified(src, dst, t):
            db.add_cloned_batch([(t.hash, t.name, t.category or '', t.size)])
            force_msg = " + force upload" if config.FORCE_UPLOAD else ""
            log(f"   ✅ Clonado{force_msg}", 1)
        else:
            log("   ❌ Falha", 0)
        
        return
    
    # ========== MODO SINCRONIZAÇÃO COMPLETA ==========
    log(f"\n🎯 Modo: Sincronização completa", 1)
    
    stats = db.get_stats()
    log(f"\n📊 Estado do banco:", 1)
    log(f"  Origem snapshot: {stats['origem_count']} torrents ({stats['origem_size_gb']:.1f} GB)", 1)
    log(f"  Histórico clonados: {stats['cloned_count']} ({stats['cloned_size_gb']:.1f} GB)", 1)
    log(f"  Blacklist: {stats['blacklist_count']} torrents", 1)
    if stats['ops_24h']:
        log(f"  Operações 24h: {stats['ops_24h']}", 1)
    
    # Configurações
    log(f"\n⚙️  Configurações:", 1)
    log(f"  Force Upload: {'✅ Ativado' if config.FORCE_UPLOAD else '❌ Desativado'}", 1)
    log(f"  Skip Checking: {'✅ Ativado' if config.SKIP_CHECKING else '❌ Desativado'}", 1)
    log(f"  Cleanup Mode: {config.CLEANUP_MODE}", 1)
    
    # PASSO 1: Snapshot da origem
    log("\n📸 [1/5] Capturando estado da origem...", 1)
    src_seeding = src.torrents_info(filter='seeding')
    
    src_filtered = []
    for t in src_seeding:
        passed, _ = apply_filters(t)
        if passed:
            src_filtered.append(t)
    
    log(f"  📊 {len(src_seeding)} em seeding → {len(src_filtered)} após filtros", 1)
    
    db.update_state_origem(src_filtered)
    log(f"  ✅ State atualizado (batch)", 1)
    
    # PASSO 2: Limpa blacklist (remove se não existe mais na origem)
    log("\n🧹 [2/5] Limpando blacklist...", 1)
    origem_hashes = db.get_state_origem_hashes()
    removed_from_blacklist = db.cleanup_blacklist(origem_hashes)
    
    if removed_from_blacklist > 0:
        log(f"  ✅ {removed_from_blacklist} torrents removidos da blacklist (não existem mais na origem)", 1)
    else:
        log(f"  ✅ Blacklist OK", 1)
    
    # PASSO 3: Clona faltantes (pula blacklist)
    log("\n⬇️  [3/5] Clonando faltantes...", 1)
    
    dst_hashes = {t.hash for t in dst.torrents_info()}
    blacklist_hashes = db.get_blacklist_hashes()
    
    log(f"  📊 {len(dst_hashes)} torrents no destino", 1)
    log(f"  🚷 {len(blacklist_hashes)} torrents na blacklist", 1)
    
    # Filtra: não existe no destino E não está na blacklist
    to_clone = [t for t in src_filtered if t.hash not in dst_hashes and t.hash not in blacklist_hashes]
    
    skipped_blacklist = len([t for t in src_filtered if t.hash not in dst_hashes and t.hash in blacklist_hashes])
    if skipped_blacklist > 0:
        log(f"  ⏭️  {skipped_blacklist} torrents pulados (blacklist)", 1)
    
    cloned_something = False
    
    if to_clone:
        sync_categories(src, dst)
        
        force_msg = " (com force upload)" if config.FORCE_UPLOAD else ""
        log(f"  🚀 Clonando {len(to_clone)} torrents{force_msg}...", 1)
        
        success_batch = []
        failed = 0
        
        for idx, t in enumerate(to_clone, 1):
            if idx % 10 == 0 or idx == len(to_clone):
                log(f"  [{idx}/{len(to_clone)}] Processando...", 1)
            
            if clone_torrent_verified(src, dst, t):
                success_batch.append((t.hash, t.name, t.category or '', t.size))
            else:
                failed += 1
            
            time.sleep(config.SYNC_INTERVAL)
        
        if success_batch:
            log(f"\n  💾 Gravando {len(success_batch)} torrents no banco...", 1)
            db.add_cloned_batch(success_batch)
            log(f"  ✅ Banco atualizado em lote", 1)
            cloned_something = True
        
        log(f"\n  📊 Clonados: {len(success_batch)} | Falhas: {failed}", 1)
    else:
        log(f"  ✅ Nada para clonar", 1)
    
    # PASSO 4: Remove órfãos
    log("\n🗑️  [4/5] Limpando órfãos...", 1)
    
    dst_current = dst.torrents_info()
    to_delete = [t for t in dst_current if t.hash not in origem_hashes]
    
    if to_delete:
        log(f"  🗑️  {len(to_delete)} órfãos detectados", 1)
        
        deleted_batch = []
        failed = 0
        
        for idx, t in enumerate(to_delete, 1):
            if idx % 10 == 0 or idx == len(to_delete):
                log(f"  [{idx}/{len(to_delete)}] Processando...", 1)
            
            if delete_torrent_verified(dst, t):
                deleted_batch.append((t.hash, t.name))
            else:
                failed += 1
            
            time.sleep(0.3)
        
        if deleted_batch:
            log(f"\n  💾 Atualizando banco ({len(deleted_batch)} remoções)...", 1)
            db.remove_cloned_batch(deleted_batch)
            log(f"  ✅ Banco atualizado em lote", 1)
        
        action = "deletados" if config.CLEANUP_MODE == 'delete' else "removidos"
        log(f"\n  📊 {action}: {len(deleted_batch)} | Falhas: {failed}", 1)
    else:
        log(f"  ✅ Sem órfãos", 1)
    
    # ⏰ AGUARDA 10 SEGUNDOS SE CLONOU ALGO
    if cloned_something:
        log("\n⏰ Aguardando 10 segundos para qBittorrent processar...", 1)
        for i in range(10, 0, -1):
            log(f"  {i}s...", 1)
            time.sleep(1)
    
    # PASSO 5: Remove torrents indesejados + adiciona blacklist
    log("\n🚫 [5/5] Verificando torrents indesejados...", 1)
    unwanted_stats = remove_unwanted_torrents(dst, db)
    
    # Estatísticas finais
    stats = db.get_stats()
    
    log("\n" + "="*60, 1)
    log("✅ SINCRONIZAÇÃO CONCLUÍDA", 1)
    log(f"  Origem: {stats['origem_count']} torrents ({stats['origem_size_gb']:.1f} GB)", 1)
    log(f"  Histórico clonados: {stats['cloned_count']} ({stats['cloned_size_gb']:.1f} GB)", 1)
    log(f"  Blacklist: {stats['blacklist_count']} torrents", 1)
    
    if unwanted_stats['total'] > 0:
        log(f"\n  🚫 Removidos indesejados: {unwanted_stats['total']}", 1)
        if unwanted_stats['downloading'] > 0:
            log(f"     • Em download: {unwanted_stats['downloading']}", 1)
        if unwanted_stats['error'] > 0:
            log(f"     • Com erro: {unwanted_stats['error']}", 1)
    
    log("="*60, 1)


# ==================== MAIN ====================

if __name__ == "__main__":
    log("="*60, 1)
    log("  qBittorrent Clone Tool v5.0", 1)
    log("  Upload-Only + Smart Blacklist", 1)
    log("="*60, 1)
    
    single_hash = sys.argv[1] if len(sys.argv) > 1 else None
    
    try:
        execute_sync(single_hash)
    except KeyboardInterrupt:
        log("\n⚠️  Interrompido", 0)
        sys.exit(0)
    except Exception as e:
        log(f"\n❌ Erro fatal: {e}", 0)
        log_error(f"Fatal: {e}")
        sys.exit(1)