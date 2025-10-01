#!/usr/bin/env python3
"""
Configuración para el servidor de búsqueda por nombres
"""
import os

# Configuración de Telegram
API_ID = int(os.getenv('API_ID', '20463783'))
API_HASH = os.getenv('API_HASH', '652a0cf6932332ccf668be49bc3480f4')
SESSION_NAME = os.getenv('SESSION_NAME', 'telethon_session')
TARGET_BOT = os.getenv('TARGET_BOT', '@OlimpoDataBot')
TARGET_BOT_ID = os.getenv('TARGET_BOT_ID', '2919287240')
