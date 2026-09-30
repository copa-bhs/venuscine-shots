#!/bin/bash

# ═══════════════════════════════════════════════════════════════════════
# INSTALAÇÃO DA API REELSHORT
# ═══════════════════════════════════════════════════════════════════════

# Configurações padrão (edite antes de rodar)
DOMAIN=cine.venusdev.xyz
<<<<<<< HEAD
EMAIL=seu-email@exemplo.com
=======
EMAIL=leprosoff0@gmail.com
>>>>>>> a0a56f4579ed0435a3685f22fca48b272adaccbb
GITHUB_REPO=https://github.com/copa-bhs/venuscine-shots.git
USER_NAME=reelshort
APP_DIR=/var/www/reelshort
PORT=5000
WORKERS=4

# Verifica se está rodando como root
if [ "$(whoami)" != "root" ]; then
    echo -e "\033[31m[ERRO]\033[0m Este script precisa ser rodado como root. Use: sudo bash install.sh"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════════
# PERGUNTAS AO USUÁRIO
# ═══════════════════════════════════════════════════════════════════════
read -p "Qual o domínio? (padrão: $DOMAIN) " input_domain
DOMAIN=${input_domain:-$DOMAIN}

read -p "Qual o email pro Let's Encrypt? (padrão: $EMAIL) " input_email
EMAIL=${input_email:-$EMAIL}

read -p "Qual a URL do repositório GitHub? (padrão: $GITHUB_REPO) " input_repo
GITHUB_REPO=${input_repo:-$GITHUB_REPO}

# ═══════════════════════════════════════════════════════════════════════
# INSTALAÇÃO
# ═══════════════════════════════════════════════════════════════════════

# [1/12] Atualizando o sistema
apt update && apt upgrade -y

# [2/12] Instalando dependências
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git

# [3/12] Criando usuário dedicado
useradd -r -s /bin/false $USER_NAME

# [4/12] Criando pasta do app
mkdir -p $APP_DIR
chown $USER_NAME:$USER_NAME $APP_DIR

# [5/12] Clonando repositório
cd $APP_DIR
git clone $GITHUB_REPO .
chown -R $USER_NAME:$USER_NAME .

# [6/12] Criando venv e instalando dependências
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# [7/12] Criando arquivo .env
cat > .env <<EOL
REELSHORT_BASE_URL=https://www.reelshort.com
REELSHORT_LANG=pt
REELSHORT_CACHE_TTL=600
SHORTS_PORT=$PORT
EOL
chown $USER_NAME:$USER_NAME .env

# [8/12] Configurando systemd
cp deploy/reelshort.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable reelshort

# [9/12] Configurando Nginx
cp deploy/nginx.conf /etc/nginx/sites-available/$DOMAIN
ln -s /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# [10/12] Ativando HTTPS
certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email $EMAIL --redirect

# [11/12] Iniciando serviço
systemctl start reelshort

# [12/12] Testando endpoint
sleep 5
curl -s https://$DOMAIN/health

# ═══════════════════════════════════════════════════════════════════════
# RESUMO
# ═══════════════════════════════════════════════════════════════════════

echo -e "\033[32m[SUCESSO]\033[0m Instalação concluída!"

echo -e "\033[34mURL da API:\033[0m https://$DOMAIN/health"

echo -e "\033[34mStatus do serviço:\033[0m systemctl status reelshort"

echo -e "\033[34mLogs:\033[0m journalctl -u reelshort -f"

echo -e "\033[34mComo atualizar:\033[0m bash update.sh"

echo -e "\033[34mComo remover:\033[0m bash uninstall.sh"
