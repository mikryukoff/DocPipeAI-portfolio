#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-example.com}"
WWW_DOMAIN="${2:-www.example.com}"
UPSTREAM="${3:-127.0.0.1:8001}"
CRT_PATH="${4:-}"
KEY_PATH="${5:-}"
LISTEN_PORT="${6:-8000}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

_find_ssl_pair() {
  local crt key
  local candidates=(
    "${REPO_ROOT}/example.com.crt:${REPO_ROOT}/example.com.key"
    "${REPO_ROOT}/${DOMAIN}.crt:${REPO_ROOT}/${DOMAIN}.key"
    "/root/example.com.crt:/root/example.com.key"
    "/root/${DOMAIN}.crt:/root/${DOMAIN}.key"
    "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem:/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
  )
  for pair in "${candidates[@]}"; do
    crt="${pair%%:*}"
    key="${pair##*:}"
    if [[ -f "${crt}" && -f "${key}" ]]; then
      echo "${crt}:${key}"
      return 0
    fi
  done
  return 1
}

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root."
  echo "Usage:"
  echo "  sudo $0 <domain> <www_domain> <upstream_host:port> <crt_path> <key_path> [listen_port]"
  echo "Example:"
  echo "  sudo $0 example.com www.example.com 127.0.0.1:8001"
  echo "  (ищет example.com.crt/.key в корне репозитория или /root/)"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
apt-get install -y nginx curl openssl >/dev/null

if [[ -z "${CRT_PATH}" || -z "${KEY_PATH}" ]]; then
  if found="$(_find_ssl_pair)"; then
    CRT_PATH="${found%%:*}"
    KEY_PATH="${found##*:}"
    echo "Auto-detected certificate pair:"
    echo "  CRT=${CRT_PATH}"
    echo "  KEY=${KEY_PATH}"
  else
    echo "ERROR: CRT_PATH and KEY_PATH are required (or place example.com.crt/.key in repo root)."
    echo "Searched:"
    echo "  ${REPO_ROOT}/example.com.crt + .key"
    echo "  /root/example.com.crt + /root/example.com.key"
    echo "  /root/${DOMAIN}.crt + /root/${DOMAIN}.key"
    echo "  /etc/letsencrypt/live/${DOMAIN}/fullchain.pem + privkey.pem"
    exit 1
  fi
fi
if [[ ! -f "${CRT_PATH}" || ! -f "${KEY_PATH}" ]]; then
  echo "ERROR: certificate/key files not found."
  echo "CRT_PATH=${CRT_PATH}"
  echo "KEY_PATH=${KEY_PATH}"
  exit 1
fi

install -d -m 755 /etc/ssl/example
install -m 644 "${CRT_PATH}" /etc/ssl/example/example.com.crt
install -m 600 "${KEY_PATH}" /etc/ssl/example/example.com.key

cat >"/etc/nginx/sites-available/${DOMAIN}.conf" <<EOF
# HTTPS only on custom port (no :80/:443 changes).
server {
    listen ${LISTEN_PORT} ssl http2;
    listen [::]:${LISTEN_PORT} ssl http2;
    server_name ${DOMAIN} ${WWW_DOMAIN};

    ssl_certificate     /etc/ssl/example/example.com.crt;
    ssl_certificate_key /etc/ssl/example/example.com.key;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;
    ssl_stapling on;
    ssl_stapling_verify on;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy no-referrer-when-downgrade always;

    client_max_body_size 100m;

    location / {
        proxy_pass http://${UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
EOF

ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
if [[ -f /etc/nginx/sites-enabled/default ]]; then
  rm -f /etc/nginx/sites-enabled/default
fi

nginx -t
systemctl enable nginx
systemctl reload nginx

openssl x509 -noout -modulus -in /etc/ssl/example/example.com.crt | openssl md5
openssl rsa -noout -modulus -in /etc/ssl/example/example.com.key | openssl md5

echo
echo "HTTPS setup finished."
echo "Check:"
echo "  https://${DOMAIN}:${LISTEN_PORT}"
echo "  https://${WWW_DOMAIN}:${LISTEN_PORT}"
