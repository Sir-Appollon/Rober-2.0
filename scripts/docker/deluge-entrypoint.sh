#!/bin/bash
echo "[DELUGE] Lancement du script Python de configuration..."
python3 /scripts/start_deluge_after_vpn.py

echo "[DELUGE] Script terminé, lancement de Deluge..."
exec /init
