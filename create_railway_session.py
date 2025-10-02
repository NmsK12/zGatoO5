#!/usr/bin/env python3
"""
Script para crear una sesión de Telegram específica para Railway
"""

import asyncio
from telethon import TelegramClient
import os

# Configuración
API_ID = 20463783
API_HASH = "652a0cf6932332ccf668be49bc3480f4"
SESSION_NAME = "telethon_railway_session"

async def create_session():
    print("=== CREANDO SESION PARA RAILWAY ===")
    print(f"API ID: {API_ID}")
    print(f"API Hash: {API_HASH}")
    print("Iniciando cliente...")
    
    # Crear cliente
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    try:
        await client.start()
        print("Sesion creada exitosamente!")
        print(f"Archivo: {SESSION_NAME}.session")
        print("IMPORTANTE: Esta sesion es SOLO para Railway")
        print("NO la uses localmente para evitar conflictos")
        print(f"Usuario: {await client.get_me()}")
        print("Sesion lista para Railway!")
        
    except Exception as e:
        print(f"Error creando sesion: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(create_session())
