#!/bin/bash

# ═══════════════════════════════════════════════════════════════════════
# ATUALIZAÇÃO DA API REELSHORT
# ═══════════════════════════════════════════════════════════════════════

# Configurações
APP_DIR=/var/www/reelshort
USER_NAME=reelshort

# Verifica se está rodando como root
if [ "$(whoami)" != "root" ]; then
    echo -e "\033[31m[ERRO]\033[0m Este script precisa ser rodado como root. Use: sudo bash update.sh"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════════
# ATUALIZAÇÃO
# ═══════════════════════════════════════════════════════════════════════

# [1/3] Entrando na pasta do app
cd $APP_DIR

# [2/3] Atualizando código
git pull

# [3/3] Reiniciando serviço
systemctl restart reelshort

# ═══════════════════════════════════════════════════════════════════════
# RESUMO
# ═══════════════════════════════════════════════════════════════════════

echo -e "\033[32m[SUCESSO]\033[0m Atualização concluída!"

echo -e "\033[34mStatus do serviço:\033[0m systemctl status reelshort"

echo -e "\033[34mLogs:\033[0m journalctl -u reelshort -f"