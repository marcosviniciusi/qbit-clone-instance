# qBittorrent Clone Tool

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Ferramenta inteligente para sincronização automática de torrents entre instâncias qBittorrent.**

Ideal para configurações de seedbox em duas camadas: uma instância para download/aquisição e outra dedicada exclusivamente para seeding de longo prazo.

---

## 🎯 Características

- ✅ **Sincronização Automática** - Clona torrents em seeding da origem para o destino
- ✅ **Upload-Only** - Detecta e remove torrents que começam a baixar no destino
- ✅ **Blacklist Inteligente** - Não re-importa torrents problemáticos (downloads/erros)
- ✅ **Force Upload** - Aplica super seeding automático nos torrents clonados
- ✅ **Batch Operations** - Gravações em lote no banco (alta performance)
- ✅ **HTTPS + DNS** - Suporte completo para conexões seguras
- ✅ **Auto-Cleanup** - Remove órfãos e limpa blacklist automaticamente
- ✅ **Filtros Avançados** - Por categoria, tamanho, ratio, upload, etc.

---

## 📋 Pré-requisitos

- Python 3.8 ou superior
- qBittorrent v4.5.0+ (para suporte a `torrents_export` API)
- Acesso WebUI habilitado em ambas as instâncias
- Mesmos caminhos de arquivos acessíveis em ambas instâncias

---

## 🚀 Instalação

### 1. Clone o repositório
```bash
git clone https://github.com/seu-usuario/qbittorrent-clone-tool.git
cd qbittorrent-clone-tool
```

### 2. Instale as dependências
```bash
pip3 install qbittorrent-api
```

### 3. Crie os diretórios necessários
```bash
sudo mkdir -p /etc/qbit-clone
sudo mkdir -p /var/lib/qbit-clone
sudo mkdir -p /var/log
```

### 4. Configure as permissões
```bash
# Diretório de configuração (somente root pode ler - contém senhas)
sudo chmod 700 /etc/qbit-clone

# Diretório do banco de dados
sudo chmod 755 /var/lib/qbit-clone

# Log
sudo touch /var/log/qbit-clone.log
sudo chmod 644 /var/log/qbit-clone.log
```

### 5. Copie e configure os arquivos
```bash
# Copie o arquivo de configuração
sudo cp config.example.py /etc/qbit-clone/config.py

# Edite com suas credenciais
sudo nano /etc/qbit-clone/config.py
```

**Configure as seguintes variáveis:**
```python
# Origem
SRC_HOST = 'qbit-origem.seudominio.com'
SRC_PORT = 443
SRC_USER = 'admin'
SRC_PASS = 'sua_senha_origem'

# Destino
DST_HOST = 'qbit-destino.seudominio.com'
DST_PORT = 443
DST_USER = 'admin'
DST_PASS = 'sua_senha_destino'
```

### 6. Instale o script principal
```bash
# Copie o script
sudo cp qbit-migrate.py /usr/local/bin/qbit-migrate

# Torne executável
sudo chmod +x /usr/local/bin/qbit-migrate
```

### 7. (Opcional) Instale o script de estatísticas
```bash
sudo cp qbit-stats.py /usr/local/bin/qbit-stats
sudo chmod +x /usr/local/bin/qbit-stats
```

---

## 📖 Uso

### Sincronização Manual
```bash
# Executa sincronização completa
qbit-migrate
```

### Sincronização Automática (Cron)
```bash
# Edite o crontab
sudo crontab -e

# Adicione (executa a cada hora)
0 * * * * /usr/local/bin/qbit-migrate >> /var/log/qbit-clone-cron.log 2>&1
```

### Hook do qBittorrent (Opcional)

Para migrar automaticamente quando um torrent completa:

**qBittorrent → Ferramentas → Opções → Downloads → "Executar programa externo ao concluir"**
```bash
/usr/local/bin/qbit-migrate "%I"
```

### Ver Estatísticas
```bash
qbit-stats
```

**Saída:**
```
============================================================
  📊 BANCO DE DADOS
============================================================

📸 STATE ORIGEM (snapshot atual)
  543 torrents | 8234.5 GB

📝 CLONED (histórico)
  549 torrents | 8240.1 GB

🚷 BLACKLIST
  14 torrents

  Últimos 10:
  • Movie.Error.mkv... (erro:missingFiles) - 3x
  • Download.Test.iso... (download) - 1x

📈 Operações 24h:
  CLONE: 22
  DELETE: 3
  BLACKLIST: 2
  UNBLACKLIST: 3
============================================================
```

---

## ⚙️ Configuração Avançada

### Filtros

Edite `/etc/qbit-clone/config.py`:
```python
# Migrar apenas categorias específicas
FILTER_CATEGORIES = ['Movies', 'TV Shows']

# Apenas torrents maiores que 5GB
MIN_SIZE_GB = 5.0

# Apenas torrents com ratio >= 1.0
MIN_RATIO = 1.0

# Apenas torrents que já fizeram 10GB+ de upload
MIN_UPLOAD_GB = 10.0
```

### Modos de Limpeza
```python
# Remove apenas o torrent, mantém arquivos (padrão)
CLEANUP_MODE = 'remove'

# Remove torrent E deleta arquivos
CLEANUP_MODE = 'delete'
```

### Force Upload
```python
# Ativa super seeding (recomendado para seedbox dedicada)
FORCE_UPLOAD = True

# Desativa (respeita limites globais)
FORCE_UPLOAD = False
```

---

## 🗂️ Estrutura de Arquivos
```
/etc/qbit-clone/
└── config.py                    # Configurações (senhas)

/var/lib/qbit-clone/
└── state.db                     # Banco de dados SQLite

/var/log/
└── qbit-clone.log              # Logs de operação

/usr/local/bin/
├── qbit-migrate                # Script principal
└── qbit-stats                  # Script de estatísticas
```

---

## 🗄️ Estrutura do Banco de Dados

### Tabelas

**`state_origem`** - Snapshot atual dos torrents na origem (sobrescreve a cada execução)
```sql
hash, name, category, size_bytes, state, updated_at
```

**`cloned_torrents`** - Histórico de clonagens (append only)
```sql
hash, name, category, size_bytes, cloned_at
```

**`blacklist_torrents`** - Torrents problemáticos (não re-importar)
```sql
hash, name, reason, blacklisted_at, attempts
```

**`operation_log`** - Log de todas as operações
```sql
id, timestamp, operation, torrent_hash, torrent_name, details
```

---

## 🔄 Fluxo de Sincronização
```
┌─────────────────────────────────────────────┐
│ 1. Snapshot Origem                          │
│    • Busca torrents em seeding             │
│    • Aplica filtros configurados            │
│    • Sobrescreve state_origem               │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 2. Limpa Blacklist                          │
│    • Remove da blacklist se não existe      │
│      mais na origem                         │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 3. Clona Faltantes                          │
│    • Compara origem vs destino              │
│    • Pula torrents na blacklist             │
│    • Clona em batch                         │
│    • Aplica force upload                    │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 4. Remove Órfãos                            │
│    • Remove do destino torrents que não     │
│      existem mais na origem                 │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 5. Aguarda 10s (se clonou algo)             │
│    • Tempo para qBittorrent processar       │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 6. Remove Indesejados                       │
│    • Detecta torrents em DOWNLOAD           │
│    • Detecta torrents com ERRO              │
│    • Remove do destino                      │
│    • Adiciona na blacklist                  │
└─────────────────────────────────────────────┘
```

---

## 🚫 Blacklist Inteligente

### Como Funciona

1. **Detecção Automática**
   - Torrents em estado de download (`downloading`, `metaDL`, etc)
   - Torrents com erro (`error`, `missingFiles`, `unknown`)

2. **Ação**
   - Remove do destino (sem deletar arquivos)
   - Adiciona hash na blacklist com motivo

3. **Prevenção**
   - Ao clonar, verifica blacklist primeiro
   - Pula torrents que já deram problema

4. **Limpeza Automática**
   - Se torrent não existe mais na origem
   - Remove da blacklist automaticamente
   - Permite nova tentativa futura se aparecer novamente

### Exemplo de Blacklist
```sql
hash                                  | name              | reason            | attempts
--------------------------------------|-------------------|-------------------|----------
abc123...                            | Movie.Error.mkv   | erro:missingFiles | 3
def456...                            | Ubuntu.Test.iso   | download          | 1
```

---

## 🐛 Troubleshooting

### Erro de autenticação
```bash
# Verifique as credenciais em /etc/qbit-clone/config.py
# Teste manualmente:
curl -k https://qbit-origem.seudominio.com:443/api/v2/app/version \
  -u admin:senha
```

### Certificado SSL auto-assinado
```python
# Em config.py:
SRC_VERIFY_SSL = False
DST_VERIFY_SSL = False
```

### Ver logs em tempo real
```bash
tail -f /var/log/qbit-clone.log
```

### Resetar banco de dados
```bash
sudo rm /var/lib/qbit-clone/state.db
# Na próxima execução será criado novamente
```

### Limpar blacklist manualmente
```bash
sqlite3 /var/lib/qbit-clone/state.db "DELETE FROM blacklist_torrents"
```

---

## 📊 Exemplo de Execução
```
============================================================
  qBittorrent Clone Tool v5.0
  Upload-Only + Smart Blacklist
============================================================
🔌 Conectando...
✅ ORIGEM: qbit-origem.com:443 | v4.6.0
✅ DESTINO: qbit-destino.com:443 | v4.6.0

🎯 Modo: Sincronização completa

📊 Estado do banco:
  Origem snapshot: 543 torrents (8234.5 GB)
  Histórico clonados: 549 torrents (8240.1 GB)
  Blacklist: 14 torrents
  Operações 24h: {'CLONE': 22, 'DELETE': 3}

⚙️  Configurações:
  Force Upload: ✅ Ativado
  Skip Checking: ✅ Ativado
  Cleanup Mode: remove

📸 [1/5] Capturando estado da origem...
  📊 543 em seeding → 543 após filtros
  ✅ State atualizado (batch)

🧹 [2/5] Limpando blacklist...
  ✅ 3 torrents removidos da blacklist (não existem mais na origem)

⬇️  [3/5] Clonando faltantes...
  📊 543 torrents no destino
  🚷 11 torrents na blacklist
  ⏭️  11 torrents pulados (blacklist)
  🚀 Clonando 8 torrents (com force upload)...
  [8/8] Processando...

  💾 Gravando 8 torrents no banco...
  ✅ Banco atualizado em lote

  📊 Clonados: 8 | Falhas: 0

🗑️  [4/5] Limpando órfãos...
  ✅ Sem órfãos

⏰ Aguardando 10 segundos para qBittorrent processar...
  10s... 9s... 8s... 7s... 6s... 5s... 4s... 3s... 2s... 1s...

🚫 [5/5] Verificando torrents indesejados...
  🚫 2 torrents indesejados detectados:
     ⚠️  2 com erro
  [1/2] Movie.mkv... (erro:missingFiles)
     ✅ Removido e adicionado à blacklist
  [2/2] Broken.zip... (erro:error)
     ✅ Removido e adicionado à blacklist

  💾 Atualizando banco (2 remoções)...
  ✅ Banco atualizado
  🚷 Adicionando 2 à blacklist...
  ✅ Blacklist atualizada

  📊 Removidos: 2 | Falhas: 0

============================================================
✅ SINCRONIZAÇÃO CONCLUÍDA
  Origem: 543 torrents (8234.5 GB)
  Histórico clonados: 549 (8240.1 GB)
  Blacklist: 13 torrents

  🚫 Removidos indesejados: 2
     • Com erro: 2
============================================================
```

---

## 🤝 Contribuindo

Contribuições são bem-vindas! Por favor:

1. Fork o projeto
2. Crie uma branch para sua feature (`git checkout -b feature/MinhaFeature`)
3. Commit suas mudanças (`git commit -m 'Adiciona MinhaFeature'`)
4. Push para a branch (`git push origin feature/MinhaFeature`)
5. Abra um Pull Request

---

## 📝 Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

## ⚠️ Avisos

- **Backup**: Sempre faça backup do seu banco de dados antes de updates
- **Testes**: Teste em ambiente de desenvolvimento primeiro
- **Senhas**: Nunca commite o arquivo `config.py` com senhas reais
- **Performance**: Em grandes volumes (1000+ torrents), ajuste `SYNC_INTERVAL`

---

## 🙏 Agradecimentos

- [qbittorrent-api](https://github.com/rmartin16/qbittorrent-api) - Excelente biblioteca Python
- Comunidade qBittorrent

---