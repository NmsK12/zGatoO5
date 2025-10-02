#!/usr/bin/env python3
"""
API para búsqueda por nombres (/nm) - WolfData
"""
import asyncio
import base64
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from io import BytesIO

from flask import Flask, jsonify, request, send_file, make_response
from PIL import Image
from database_postgres import validate_api_key, init_database, register_api_key, delete_api_key
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
loop = None

def parse_nm_response(text):
    """Parsea la respuesta del comando /nm"""
    try:
        # Buscar la línea de resultados (puede estar en diferentes formatos)
        results_match = re.search(r'RESULTADOS ➾ (\d+)', text)
        if not results_match:
            # Si no encuentra "RESULTADOS", contar los DNI encontrados
            dni_count = len(re.findall(r'\*\*DNI\*\* ➾ `(\d+)`', text))
            total_results = dni_count
        else:
            total_results = int(results_match.group(1))
        
        # Buscar todos los DNI en el texto (formato: **DNI** ➾ `123`)
        dni_pattern = r'\*\*DNI\*\* ➾ `(\d+)`'
        dni_matches = re.findall(dni_pattern, text)
        
        # Buscar nombres y apellidos (formato: **NOMBRES** ➾ PEDRO ANTONIO)
        nombres_pattern = r'\*\*NOMBRES\*\* ➾ ([^\n]+)'
        apellidos_pattern = r'\*\*APELLIDOS\*\* ➾ ([^\n]+)'
        edad_pattern = r'\*\*EDAD\*\* ➾ ([^\n]+)'
        
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
            'results': results
        }
        
    except Exception as e:
        logger.error(f"Error parseando respuesta /nm: {e}")
        return {
            'total_results': 0,
            'results': []
        }

async def consult_nm_async(nombres, apellidos):
    """Consulta asíncrona para /nm"""
    global client, client_ready
    
    if not client_ready:
        raise Exception("Cliente de Telegram no inicializado")
    
    try:
        # Formatear el comando según las reglas del bot
        # Formato: /nm NOMBRES|APELLIDO1|APELLIDO2
        # Nombres separados por comas, apellidos separados por |
        command = f"/nm {nombres}|{apellidos}"
        
        logger.info(f"Enviando comando: {command}")
        
        # Enviar comando
        await client.send_message(config.TARGET_BOT, command)
        command_time = time.time()
        
        # Esperar respuestas
        await asyncio.sleep(5)
        
        # Obtener mensajes recientes (más mensajes para capturar fotos)
        messages = await client.get_messages(config.TARGET_BOT, limit=20)
        
        # Buscar respuestas del bot
        bot_responses = []
        photos_data = {}
        
        for message in messages:
            # Verificar que sea del bot (from_id puede ser None o el ID del bot)
            is_from_bot = (
                (message.from_id and str(message.from_id) == config.TARGET_BOT_ID) or
                message.from_id is None  # Algunos mensajes del bot tienen from_id None
            )
            
            if (message.date.timestamp() > command_time - 60 and is_from_bot):
                
                if message.text and ('RENIEC X NOMBRES' in message.text or 'RESULTADOS' in message.text or 'DNI ➾' in message.text or 'Ahora puedes previsualizar' in message.text):
                    # Filtrar mensajes de carga
                    if 'Estamos procesando tu solicitud' not in message.text:
                        bot_responses.append(message.text)
                        logger.info(f"Respuesta del bot detectada: {message.text[:100]}...")
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
                elif message.media and hasattr(message.media, 'photo'):
                    # Es una foto - verificar que no sea del mensaje de carga
                    try:
                        # Solo procesar fotos si hay texto asociado con DNI
                        if message.text and 'DNI ➾' in message.text:
                            # Buscar DNI en el texto del mensaje
                            dni_match = re.search(r'DNI ➾ (\d+)', message.text)
                            
                            if dni_match:
                                dni = dni_match.group(1)
                                # Descargar foto y convertir a base64
                                photo_bytes = await client.download_media(message.media, file=BytesIO())
                                photo_bytes.seek(0)
                                photo_base64 = base64.b64encode(photo_bytes.getvalue()).decode('utf-8')
                                photos_data[f"foto_{dni}"] = f"data:image/jpeg;base64,{photo_base64}"
                                logger.info(f"Foto extraída para DNI {dni}")
                            else:
                                logger.info("Foto detectada pero sin DNI asociado - ignorando")
                        else:
                            logger.info("Foto detectada pero sin texto de DNI - ignorando")
                    except Exception as e:
                        logger.error(f"Error extrayendo foto: {e}")
        
        if not bot_responses:
            raise Exception("No se recibió respuesta del bot")
        
        # Combinar todas las respuestas
        combined_text = '\n'.join(bot_responses)
        
        # Parsear respuesta
        parsed_data = parse_nm_response(combined_text)
        
        # Agregar fotos si las hay
        if photos_data:
            parsed_data['fotos'] = photos_data
        
        return parsed_data
        
    except Exception as e:
        logger.error(f"Error en consulta /nm: {e}")
        raise

def consult_nm_sync(nombres, apellidos):
    """Consulta síncrona para /nm"""
    global client_ready, loop
    
    if not client_ready:
        raise Exception("Cliente de Telegram no inicializado")
    
    try:
        # Usar el loop global existente
        return loop.run_until_complete(consult_nm_async(nombres, apellidos))
        
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

def init_telethon():
    """Inicializa Telethon con un event loop global"""
    global client, client_ready, loop
    
    try:
        # Crear event loop global
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Crear cliente con el loop global
        client = TelegramClient(
            config.SESSION_NAME,
            config.API_ID,
            config.API_HASH,
            loop=loop
        )
        
        # Inicializar cliente
        loop.run_until_complete(start_client())
        
    except Exception as e:
        logger.error(f"Error inicializando Telethon: {e}")
        client_ready = False

async def start_client():
    """Inicia el cliente de Telegram"""
    global client_ready
    try:
        await client.start()
        client_ready = True
        logger.info("Cliente de Telethon iniciado correctamente")
    except Exception as e:
        logger.error(f"Error iniciando cliente: {e}")
        client_ready = False

# Rutas de la API
@app.route('/', methods=['GET'])
def home():
    """Página principal de la API."""
    return jsonify({
        'servicio': 'API Búsqueda por Nombres (/nm)',
        'descripcion': 'API para buscar personas por nombres y apellidos usando el bot de Telegram',
        'endpoint': '/nm',
        'metodo': 'GET',
        'parametros': {
            'nombres': 'Nombres separados por comas (ej: JOSE,PEDRO)',
            'apellidos': 'Apellidos separados por | (ej: CASTILLO|TERRONES)',
            'key': 'Tu API Key'
        },
        'ejemplos': {
            'un_nombre_dos_apellidos': '/nm?nombres=PEDRO&apellidos=CASTILLO|TERRONES&key=TU_API_KEY',
            'dos_nombres_dos_apellidos': '/nm?nombres=JOSE,PEDRO&apellidos=CASTILLO|TERRONES&key=TU_API_KEY',
            'dos_nombres_apellido_compuesto': '/nm?nombres=JUAN,PEPE&apellidos=QUISPE|DE+LA+CRUZ&key=TU_API_KEY'
        },
        'formato_bot': {
            'un_nombre_dos_apellidos': '/nm PEDRO|CASTILLO|TERRONES',
            'dos_nombres_dos_apellidos': '/nm JOSE,PEDRO|CASTILLO|TERRONES',
            'dos_nombres_apellido_compuesto': '/nm JUAN,PEPE|QUISPE|DE+LA+CRUZ'
        },
        'contacto': '@zGatoO - @WinniePoohOFC - @choco_tete'
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
init_telethon()

def update_all_time_remaining():
    """Actualiza el tiempo restante de todas las API Keys"""
    try:
        import sqlite3
        from datetime import datetime
        
        conn = sqlite3.connect('api_keys.db')
        cursor = conn.cursor()
        
        # Obtener todas las API Keys
        cursor.execute('SELECT key, expires_at FROM api_keys')
        keys = cursor.fetchall()
        
        updated_count = 0
        for key, expires_at in keys:
            # Calcular tiempo restante real
            expires_dt = datetime.fromisoformat(expires_at)
            now = datetime.now()
            time_remaining = int((expires_dt - now).total_seconds())
            
            # Actualizar en la base de datos
            cursor.execute('''
                UPDATE api_keys 
                SET time_remaining = ? 
                WHERE key = ?
            ''', (max(0, time_remaining), key))
            
            updated_count += 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Actualizadas {updated_count} API Keys")
        
    except Exception as e:
        logger.error(f"❌ Error actualizando tiempo restante: {e}")

def main():
    """Función principal."""
    # Inicializar base de datos
    init_database()
    
    # Actualizar tiempo restante de todas las keys
    update_all_time_remaining()
    
    # Iniciar Flask
    port = int(os.getenv('PORT', 8080))
    logger.info(f"Iniciando API en puerto {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
