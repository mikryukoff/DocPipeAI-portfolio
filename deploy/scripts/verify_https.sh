#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-example.com}"
WWW_DOMAIN="${2:-www.example.com}"
IP_EXPECTED="${3:-203.0.113.10}"
HTTPS_PORT="${4:-8000}"
CRT_PATH="${5:-/etc/ssl/example/example.com.crt}"
KEY_PATH="${6:-/etc/ssl/example/example.com.key}"

ISSUES=0

_path_exists() {
  local p="$1"
  [[ -e "${p}" ]] && return 0
  command -v sudo >/dev/null 2>&1 && sudo test -e "${p}" 2>/dev/null
}

_path_readable() {
  local p="$1"
  [[ -r "${p}" ]] && return 0
  command -v sudo >/dev/null 2>&1 && sudo test -r "${p}" 2>/dev/null
}

note_issue() {
  echo "!! $*"
  ISSUES=$((ISSUES + 1))
}

curl_head() {
  local label="$1"
  local url="$2"
  local extra_args="${3:-}"
  local optional="${4:-0}"
  echo "-- ${label}: ${url}"
  # shellcheck disable=SC2086
  if curl -sS -m 10 ${extra_args} -I "${url}" 2>&1 | sed -n '1,10p'; then
    echo "   OK"
  elif [[ "${optional}" == "1" ]]; then
    echo "   пропуск (не критично с этого же хоста)"
  else
    note_issue "${label} недоступен: ${url}"
  fi
  echo
}

echo "== DNS (ожидается A -> ${IP_EXPECTED}) =="
for host in "${DOMAIN}" "${WWW_DOMAIN}"; do
  if command -v dig >/dev/null 2>&1; then
    ips="$(dig +short A "${host}" | tr '\n' ' ' | sed 's/ $//')"
    echo "A ${host}: ${ips:-<нет записи>}"
    if [[ -z "${ips}" ]]; then
      note_issue "нет A-записи для ${host}"
    elif [[ " ${ips} " != *" ${IP_EXPECTED} "* ]]; then
      note_issue "${host} указывает на ${ips}, нужно ${IP_EXPECTED}"
    else
      echo "   OK"
    fi
  elif command -v getent >/dev/null 2>&1; then
    getent hosts "${host}" || note_issue "getent не нашёл ${host}"
  fi
done

echo
echo "== DNS AAAA (битая IPv6-запись ломает домен без www) =="
if command -v dig >/dev/null 2>&1; then
  for host in "${DOMAIN}" "${WWW_DOMAIN}"; do
    aaaa="$(dig +short AAAA "${host}" | tr '\n' ' ' | sed 's/ $//')"
    echo "AAAA ${host}: ${aaaa:-<нет>}"
    if [[ -n "${aaaa}" ]]; then
      note_issue "${host} имеет AAAA (${aaaa}) — если IPv6 не настроен на сервере, удалите AAAA у регистратора"
    fi
  done
fi

echo
echo "== Сертификат: имена (SAN) =="
if _path_exists "${CRT_PATH}"; then
  _read_crt() {
    if _path_readable "${CRT_PATH}"; then
      openssl x509 -in "${CRT_PATH}" -noout -text
    else
      sudo openssl x509 -in "${CRT_PATH}" -noout -text
    fi
  }
  san_block="$(_read_crt 2>/dev/null | sed -n '/Subject Alternative Name/,/^            X/p')"
  echo "${san_block:-<SAN не найден>}"
  for host in "${DOMAIN}" "${WWW_DOMAIN}"; do
    if _read_crt 2>/dev/null | grep -q "DNS:${host}"; then
      echo "   OK: сертификат покрывает ${host}"
    else
      note_issue "сертификат НЕ покрывает ${host} — перевыпустите с обоими именами в SAN"
    fi
  done
fi

echo
echo "== Локальные адреса сервера =="
if command -v hostname >/dev/null 2>&1; then
  echo "hostname: $(hostname -f 2>/dev/null || hostname)"
fi
if command -v ip >/dev/null 2>&1; then
  ip -4 addr show scope global 2>/dev/null | awk '/inet /{print "  " $2 " dev " $NF}' || true
elif command -v ip addr >/dev/null 2>&1; then
  ip addr show scope global 2>/dev/null | awk '/inet /{print "  " $2}' || true
fi
echo "Публичный IP ${IP_EXPECTED} с этого же хоста часто не отвечает (NAT/hairpin) — ниже проверяем 127.0.0.1."

echo
echo "== Port listeners :${HTTPS_PORT} =="
if ss -tulpn "( sport = :${HTTPS_PORT} )" 2>/dev/null; then
  :
else
  note_issue "порт ${HTTPS_PORT} не слушается"
fi

echo
echo "== Local cert/key files =="
if _path_exists "${CRT_PATH}"; then
  echo "CRT found: ${CRT_PATH}"
else
  note_issue "CRT missing: ${CRT_PATH}"
fi
if _path_exists "${KEY_PATH}"; then
  echo "KEY found: ${KEY_PATH}"
else
  note_issue "KEY missing: ${KEY_PATH}"
fi

if _path_exists "${CRT_PATH}" && _path_exists "${KEY_PATH}"; then
  echo "Cert/key modulus MD5:"
  if _path_readable "${CRT_PATH}"; then
    openssl x509 -noout -modulus -in "${CRT_PATH}" | openssl md5
  else
    sudo openssl x509 -noout -modulus -in "${CRT_PATH}" | openssl md5
  fi
  if _path_readable "${KEY_PATH}"; then
    openssl rsa -noout -modulus -in "${KEY_PATH}" | openssl md5
  else
    sudo openssl rsa -noout -modulus -in "${KEY_PATH}" | openssl md5
  fi
else
  echo "== Nginx ssl_certificate (если уже настроен) =="
  if [[ -d /etc/nginx/sites-enabled ]]; then
    grep -R "ssl_certificate" /etc/nginx/sites-enabled/ 2>/dev/null | grep -v "#" || true
  fi
  echo "Установка: sudo bash deploy/scripts/setup_https_nginx_certbot.sh ${DOMAIN} ${WWW_DOMAIN}"
fi

echo
echo "== HTTPS availability on :${HTTPS_PORT} =="
curl_head "localhost" "https://127.0.0.1:${HTTPS_PORT}" "-k"
curl_head "SNI ${DOMAIN} (через 127.0.0.1)" "https://${DOMAIN}:${HTTPS_PORT}" "--resolve ${DOMAIN}:${HTTPS_PORT}:127.0.0.1 -k"
curl_head "SNI ${WWW_DOMAIN} (через 127.0.0.1)" "https://${WWW_DOMAIN}:${HTTPS_PORT}" "--resolve ${WWW_DOMAIN}:${HTTPS_PORT}:127.0.0.1 -k"
curl_head "public IP (с этого хоста может не работать)" "https://${IP_EXPECTED}:${HTTPS_PORT}" "-k" 1

echo "== Certificate (SNI ${DOMAIN} via 127.0.0.1) =="
if echo | openssl s_client -servername "${DOMAIN}" -connect "127.0.0.1:${HTTPS_PORT}" 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates 2>/dev/null; then
  :
else
  note_issue "не удалось прочитать сертификат с 127.0.0.1:${HTTPS_PORT}"
fi

echo
echo "== Итог =="
if [[ "${ISSUES}" -eq 0 ]]; then
  echo "Проверки пройдены. Сайт: https://${DOMAIN}:${HTTPS_PORT}"
else
  echo "Найдено проблем: ${ISSUES}"
  echo
  echo "Типичные шаги:"
  echo "  1. DNS: A для ${DOMAIN} и ${WWW_DOMAIN} -> ${IP_EXPECTED}"
  echo "     (сейчас ${DOMAIN} часто указывает на внутренний 192.0.2.10 — исправьте у регистратора)"
  echo "  2. Сертификат (положите .crt/.key в /root/example.com.* и запустите):"
  echo "     sudo bash deploy/scripts/setup_https_nginx_certbot.sh \\"
  echo "       ${DOMAIN} ${WWW_DOMAIN} 127.0.0.1:8001"
  echo "  3. Backend: docker compose up -d (127.0.0.1:8001)"
  echo "  4. Файрвол: открыть tcp/${HTTPS_PORT} снаружи"
  echo "  5. Если www открывается, а apex (без www) — нет:"
  echo "     - перевыпустите сертификат с SAN: ${DOMAIN} и ${WWW_DOMAIN}"
  echo "     - или удалите лишнюю AAAA-запись у ${DOMAIN} у регистратора"
  echo "     - или настройте редирект ${DOMAIN} -> ${WWW_DOMAIN} в DNS регистратора"
fi
