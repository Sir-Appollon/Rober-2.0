#!/bin/bash

echo "========== 🧪 DIAGNOSTIC PLEX & RESEAU =========="

echo -e "\n===== 1. Vérification que Plex tourne ====="
docker ps --format "table {{.Names}}\t{{.Status}}" | grep plex

echo -e "\n===== 2. Ports écoutés par le système (80, 443, 32400) ====="
if command -v netstat &> /dev/null; then
  sudo netstat -tulnp | grep -E ':(80|443|32400)'
else
  ss -tulnp | grep -E ':(80|443|32400)'
fi

echo -e "\n===== 3. Services exposés par Docker ====="
docker inspect plex-server | grep HostPort || echo "Pas de ports explicitement exposés (network_mode: host)"

echo -e "\n===== 4. Fichiers de conf NGINX (NPM) montés ====="
find ${ROOT}/config/npm -name "*.conf"

echo -e "\n===== 5. IP publique et résolution DuckDNS ====="
echo "IP publique : $(curl -s https://api.ipify.org)"
echo "IP DuckDNS  : $(dig +short robert2-0.duckdns.org)"

echo -e "\n===== 6. Vérification des règles iptables (ports clés) ====="
sudo iptables -L -n -v | grep -i 'dpt:80\|dpt:443\|dpt:32400'

echo -e "\n===== 7. Certificats Let's Encrypt présents ? ====="
ls -l ${ROOT}/config/npm/letsencrypt/live/* 2>/dev/null || echo "Pas de certificats trouvés"

echo -e "\n===== 8. Vérification de la configuration NGINX Proxy Manager ====="
NGINX_CONTAINER=$(docker ps --filter "ancestor=jc21/nginx-proxy-manager" --format "{{.Names}}")

if [ -n "$NGINX_CONTAINER" ]; then
    echo "Conteneur NGINX Proxy Manager détecté : $NGINX_CONTAINER"

    echo -e "\n→ Fichiers de configuration utilisés :"
    docker exec "$NGINX_CONTAINER" nginx -T | grep -Ei "conf|include"

    echo -e "\n→ Redirections potentiellement actives :"
    docker exec "$NGINX_CONTAINER" nginx -T | grep -Ei "location|proxy_pass"
else
    echo "Aucun conteneur NGINX Proxy Manager actif."
fi

echo -e "\n========== ✅ FIN DU DIAGNOSTIC ==========\n"
