"""
Módulo de operações de sincronização do qBittorrent Clone Tool
"""

import time

from qbit_clone.database import SyncDatabase
from qbit_clone.logger import log, log_error


def sync_categories(src, dst, config):
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


def clone_torrent_verified(src, dst, torrent, config) -> bool:
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


def delete_torrent_verified(dst, torrent, config) -> bool:
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


def remove_unwanted_torrents(dst, db: SyncDatabase, config) -> dict:
    """Remove torrents indesejados e adiciona à blacklist"""
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

        if removed_batch:
            log(f"\n  💾 Atualizando banco ({len(removed_batch)} remoções)...", 1)
            db.remove_cloned_batch(removed_batch)
            log(f"  ✅ Banco atualizado", 1)

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
