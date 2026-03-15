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

Uso: qbit-clone.py [HASH]
"""

import sys
import time
from typing import Optional

sys.path.insert(0, '/etc/qbit-clone')

try:
    import config
except ImportError:
    print("❌ ERRO: /etc/qbit-clone/config.py não encontrado!")
    sys.exit(1)

from logger import log, log_error
from database import SyncDatabase
from clients import get_clients
from filters import apply_filters
from sync import sync_categories, clone_torrent_verified, delete_torrent_verified, remove_unwanted_torrents


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
