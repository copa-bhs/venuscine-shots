#!/bin/bash

# ═══════════════════════════════════════════════════════════════════════
# REMOÇÃO DA API REELSHORT
# ═══════════════════════════════════════════════════════════════════════

# Configurações
APP_DIR=/var/www/reelshort
USER_NAME=reelshort
DOMAIN=cine.venusdev.xyz

# Verifica se está rodando como root
if [ "$(whoami)" != "root" ]; then
    echo -e "\033[31m[ERRO]\033[0m Este script precisa ser rodado como root. Use: sudo bash uninstall.sh"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════════
# REMOÇÃO
# ═══════════════════════════════════════════════════════════════════════

# [1/5] Parando o serviço
systemctl stop reelshort
systemctl disable reelshort

# [2/5] Removendo serviço systemd
rm -f /etc/systemd/system/reelshort.service
systemctl daemon-reload

# [3/5] Removendo config Nginx
rm -f /etc/nginx/sites-available/$DOMAIN
rm -f /etc/nginx/sites-enabled/$DOMAIN
nginx -t
systemctl reload nginx

# [4/5] Removendo pasta do app
rm -rf $APP_DIR

# [5/5] Removendo usuário (opcional)
userdel -r $USER_NAME

# ═══════════════════════════════════════════════════════════════════════
# RESUMO
# ═══════════════════════════════════════════════════════════════════════

echo -e "\033[32m[SUCESSO]\033[0m Remoção concluída!"