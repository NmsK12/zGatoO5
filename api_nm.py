#!/usr/bin/env python3
"""
API para búsqueda por nombres (/nm) - WolfData
"""
import asyncio
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from io import BytesIO

from flask import Flask, jsonify, request, send_file, make_response
from PIL import Image
from database import validate_api_key, init_database, register_api_key, delete_api_key
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import MessageMediaDocument

import config

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Inicializar Flask
app = Flask(__name__)

# Variables globales
client = None
client_ready = False

def parse_nm_response(text):
    """Parsea la respuesta del comando /nm"""
    try:
        # Buscar la línea de resultados
        results_match = re.search(r'RESULTADOS ➾ (\d+)', text)
        total_results = int(results_match.group(1)) if results_match else 0
        
        # Buscar todos los DNI en el texto
        dni_pattern = r'DNI ➾ (\d+)'
        dni_matches = re.findall(dni_pattern, text)
        
        # Buscar nombres y apellidos
        nombres_pattern = r'NOMBRES ➾ ([^\n]+)'
        apellidos_pattern = r'APELLIDOS ➾ ([^\n]+)'
        edad_pattern = r'EDAD ➾ ([^\n]+)'
        
        nombres_matches = re.findall(nombres_pattern, text)
        apellidos_matches = re.findall(apellidos_pattern, text)
        edad_matches = re.findall(edad_pattern, text)
        
        # Combinar datos
        results = []
        for i, dni in enumerate(dni_matches):
            result = {
                'dni': dni,
                'nombres': nombres_matches[i] if i < len(nombres_matches) else '',
                'apellidos': apellidos_matches[i] if i < len(apellidos_matches) else '',
                'edad': edad_matches[i] if i < len(edad_matches) else ''
            }
            results.append(result)
        
        return {
            'total_results': total_results,
            'results': results,
            'raw_text': text
        }
        
    except Exception as e:
        logger.error(f"Error parseando respuesta /nm: {e}")
        return {
            'total_results': 0,
            'results': [],
            'raw_text': text
        }

async def consult_nm_async(nombres, apellidos):
    """Consulta asíncrona para /nm"""
    global client, client_ready
    
    if not client_ready:
        raise Exception("Cliente de Telegram no inicializado")
    
    try:
        # Formatear el comando según las reglas
        if not apellidos or apellidos.strip() == '':
            # Solo un apellido: /nm NOMBRES| |APELLIDO
            command = f"/nm {nombres}| |{apellidos}"
        else:
            # Múltiples apellidos: /nm NOMBRES|APELLIDO1|APELLIDO2
            command = f"/nm {nombres}|{apellidos}"
        
        logger.info(f"Enviando comando: {command}")
        
        # Enviar comando
        await client.send_message(config.TARGET_BOT, command)
        command_time = time.time()
        
        # Esperar respuestas
        await asyncio.sleep(5)
        
        # Obtener mensajes recientes
        messages = await client.get_messages(config.TARGET_BOT, limit=10)
        
        # Buscar respuestas del bot
        bot_responses = []
        for message in messages:
            if (message.date.timestamp() > command_time - 60 and 
                message.from_id and 
                str(message.from_id) == config.TARGET_BOT_ID):
                
                if message.text and ('RENIEC X NOMBRES' in message.text or 'RESULTADOS' in message.text):
                    bot_responses.append(message.text)
                elif message.media and isinstance(message.media, MessageMediaDocument):
                    # Es un archivo .txt
                    try:
                        file_content = await client.download_media(message.media, file=BytesIO())
                        file_content.seek(0)
                        txt_content = file_content.read().decode('utf-8', errors='ignore')
                        bot_responses.append(txt_content)
                        logger.info(f"Archivo .txt descargado y procesado: {len(txt_content)} caracteres")
                    except Exception as e:
                        logger.error(f"Error descargando archivo .txt: {e}")
        
        if not bot_responses:
            raise Exception("No se recibió respuesta del bot")
        
        # Combinar todas las respuestas
        combined_text = '\n'.join(bot_responses)
        
        # Parsear respuesta
        parsed_data = parse_nm_response(combined_text)
        
        return parsed_data
        
    except Exception as e:
        logger.error(f"Error en consulta /nm: {e}")
        raise

def consult_nm_sync(nombres, apellidos):
    """Consulta síncrona para /nm"""
    global client_ready
    
    if not client_ready:
        raise Exception("Cliente de Telegram no inicializado")
    
    try:
        # Ejecutar consulta asíncrona
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(consult_nm_async(nombres, apellidos))
        loop.close()
        return result
        
    except Exception as e:
        logger.error(f"Error en consulta síncrona /nm: {e}")
        raise

def restart_telethon():
    """Reinicia la conexión de Telethon"""
    global client, client_ready
    
    try:
        logger.info("Reiniciando conexión de Telethon...")
        
        if client:
            # Desconectar cliente existente
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(client.disconnect())
                loop.close()
            except:
                pass
        
        # Crear nuevo cliente
        client = TelegramClient(
            config.SESSION_NAME,
            config.API_ID,
            config.API_HASH
        )
        
        # Inicializar en hilo separado
        def run_telethon():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def start_client():
                    global client_ready
                    await client.start()
                    client_ready = True
                    logger.info("Cliente de Telethon reiniciado correctamente")
                
                loop.run_until_complete(start_client())
                loop.run_forever()
                
            except Exception as e:
                logger.error(f"Error reiniciando Telethon: {e}")
                client_ready = False
        
        thread = threading.Thread(target=run_telethon, daemon=True)
        thread.start()
        
        # Esperar inicialización
        time.sleep(3)
        
    except Exception as e:
        logger.error(f"Error en restart_telethon: {e}")
        client_ready = False

def init_telethon_thread():
    """Inicializa Telethon en un hilo separado"""
    global client, client_ready
    
    try:
        client = TelegramClient(
            config.SESSION_NAME,
            config.API_ID,
            config.API_HASH
        )
        
        def run_telethon():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def start_client():
                    global client_ready
                    await client.start()
                    client_ready = True
                    logger.info("Cliente de Telethon iniciado correctamente")
                
                loop.run_until_complete(start_client())
                loop.run_forever()
                
            except Exception as e:
                logger.error(f"Error inicializando Telethon: {e}")
                client_ready = False
        
        # Iniciar en hilo separado
        thread = threading.Thread(target=run_telethon, daemon=True)
        thread.start()
        
        # Esperar un poco para que se inicialice
        time.sleep(3)
        
    except Exception as e:
        logger.error(f"Error inicializando Telethon: {str(e)}")

# Rutas de la API
@app.route('/', methods=['GET'])
def home():
    """Página principal de la API."""
    return jsonify({
        'servicio': 'API Búsqueda por Nombres',
        'comando': '/nm?nombres=LUIS|MIGUEL&apellidos=QUISPE|MARTINEZ&key=TU_API_KEY',
        'info': '@zGatoO - @WinniePoohOFC - @choco_tete'
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'OK',
        'service': 'Búsqueda por Nombres API',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/register-key', methods=['POST'])
def register_key():
    """Endpoint para registrar API Keys desde el panel de administración."""
    try:
        data = request.get_json()
        
        if not data or 'key' not in data:
            return jsonify({
                'success': False,
                'error': 'Datos de API Key requeridos'
            }), 400
        
        api_key = data['key']
        description = data.get('description', 'API Key desde panel')
        expires_at = data.get('expires_at', (datetime.now() + timedelta(hours=1)).isoformat())
        
        if register_api_key(api_key, description, expires_at):
            return jsonify({
                'success': True,
                'message': 'API Key registrada correctamente'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Error registrando API Key'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error interno: {str(e)}'
        }), 500

@app.route('/delete-key', methods=['POST'])
def delete_key():
    """Endpoint para eliminar API Keys desde el panel de administración."""
    try:
        data = request.get_json()
        
        if not data or 'key' not in data:
            return jsonify({
                'success': False,
                'error': 'API Key requerida'
            }), 500
        
        api_key = data['key']
        
        if delete_api_key(api_key):
            return jsonify({
                'success': True,
                'message': 'API Key eliminada correctamente'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Error eliminando API Key'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error interno: {str(e)}'
        }), 500

@app.route('/nm', methods=['GET'])
def nm_result():
    """Endpoint para búsqueda por nombres."""
    # Validar API Key
    api_key = request.args.get('key')
    validation = validate_api_key(api_key)
    
    if not validation['valid']:
        return jsonify({
            'success': False,
            'error': f"Error validando API Key: {validation['error']}"
        }), 401
    
    # Obtener parámetros
    nombres = request.args.get('nombres', '').strip()
    apellidos = request.args.get('apellidos', '').strip()
    
    if not nombres:
        return jsonify({
            'success': False,
            'error': 'Parámetro nombres es requerido'
        }), 400
    
    try:
        # Realizar consulta
        result = consult_nm_sync(nombres, apellidos)
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        logger.error(f"Error consultando /nm: {e}")
        
        # Intentar reiniciar Telethon si hay error de conexión
        if "disconnected" in str(e).lower() or "connection" in str(e).lower():
            try:
                restart_telethon()
                # Reintentar una vez
                result = consult_nm_sync(nombres, apellidos)
                return jsonify({
                    'success': True,
                    'data': result
                })
            except Exception as retry_error:
                logger.error(f"Error en reintento: {retry_error}")
        
        return jsonify({
            'success': False,
            'error': f'Error en la consulta: {str(e)}'
        }), 500

# Inicializar Telethon cuando se importa el módulo (para Gunicorn)
init_telethon_thread()

def main():
    """Función principal."""
    # Inicializar base de datos
    init_database()
    
    # Iniciar Flask
    port = int(os.getenv('PORT', 8080))
    logger.info(f"Iniciando API en puerto {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
