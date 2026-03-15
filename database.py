"""
Módulo de banco de dados do qBittorrent Clone Tool
Gerencia estado, blacklist e histórico de operações via SQLite
"""

import sqlite3
from typing import List
from pathlib import Path

from logger import log_error


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

        for hash, name, reason in torrents:
            cursor.execute('''
                INSERT INTO blacklist_torrents (hash, name, reason, attempts)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(hash) DO UPDATE SET
                    attempts = attempts + 1,
                    blacklisted_at = CURRENT_TIMESTAMP,
                    reason = excluded.reason
            ''', (hash, name, reason))

        log_batch = [(
            'BLACKLIST',
            t[0],
            t[1],
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

        cursor.execute('SELECT hash, name FROM blacklist_torrents')
        blacklist_items = cursor.fetchall()

        to_remove = []
        for hash, name in blacklist_items:
            if hash not in origem_hashes:
                to_remove.append((hash, name))

        if to_remove:
            hashes = [t[0] for t in to_remove]
            placeholders = ','.join('?' * len(hashes))
            cursor.execute(f'DELETE FROM blacklist_torrents WHERE hash IN ({placeholders})', hashes)

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
