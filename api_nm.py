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
import uuid
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

# Variables globales
client = None
loop = None

# Crear la aplicación Flask
app = Flask(__name__)

# Inicializar base de datos
init_database()

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

async def consult_nm_async(nombres, apellidos, request_id):
    """Consulta asíncrona del NM con manejo inteligente de colas."""
    global client
    
    try:
        max_attempts = 3  # Máximo 3 intentos
        
        for attempt in range(1, max_attempts + 1):
            logger.info(f"[{request_id}] Intento {attempt}/{max_attempts} para NM {nombres}|{apellidos}")
            
            # Procesar parámetros para el comando del bot
            # Convertir comas en espacios para nombres múltiples
            nombres_formatted = nombres.replace(',', ' ')
            apellidos_formatted = apellidos.replace(',', ' ')
            
            # Enviar comando /nm con formato correcto para el bot
            command = f"/nm {nombres_formatted}|{apellidos_formatted}"
            await client.send_message(config.TARGET_BOT, command)
            logger.info(f"[{request_id}] Comando /nm enviado: {command} (intento {attempt})")
            
            # Esperar un poco antes de revisar mensajes
            await asyncio.sleep(2)
            
            # Obtener mensajes recientes
            messages = await client.get_messages(config.TARGET_BOT, limit=20)
            current_timestamp = time.time()
            
            logger.info(f"[{request_id}] Revisando {len(messages)} mensajes totales...")
            
            # Filtrar mensajes que sean respuestas a nuestro comando específico
            relevant_messages = []
            for msg in messages:
                if msg.date.timestamp() > current_timestamp - 120:  # Últimos 2 minutos
                    logger.info(f"[{request_id}] Mensaje reciente: {msg.text[:100] if msg.text else 'Sin texto'}... (from_id: {msg.from_id})")
                    
                    # Verificar que sea del bot (from_id puede ser None o el ID del bot)
                    is_from_bot = (
                        (msg.from_id and str(msg.from_id) == config.TARGET_BOT_ID) or
                        msg.from_id is None  # Algunos mensajes del bot tienen from_id None
                    )
                    
                    if is_from_bot and msg.text:
                        # Verificar que sea respuesta a nuestro comando específico
                        if ('RENIEC X NOMBRES' in msg.text or
                            'RESULTADOS' in msg.text or
                            'DNI ➾' in msg.text or
                            'OLIMPO_BOT' in msg.text):
                            relevant_messages.append(msg)
                            logger.info(f"[{request_id}] ✅ Mensaje relevante detectado: {msg.text[:50]}...")
            
            logger.info(f"[{request_id}] Revisando {len(relevant_messages)} mensajes relevantes para NM {nombres}|{apellidos}...")
            
            for message in relevant_messages:
                logger.info(f"[{request_id}] Mensaje relevante: {message.text[:100] if message.text else 'Sin texto'}...")
                
                # Buscar mensajes de espera/procesamiento
                if message.text and "espera" in message.text.lower() and "segundos" in message.text.lower():
                    wait_match = re.search(r'(\d+)\s*segundos?', message.text)
                    if wait_match:
                        wait_time = int(wait_match.group(1))
                        logger.info(f"[{request_id}] Esperando {wait_time} segundos...")
                        await asyncio.sleep(wait_time)
                        continue
                
                # Verificar si el mensaje tiene un archivo adjunto
                if message.media and hasattr(message.media, 'document'):
                    logger.info(f"[{request_id}] 📎 Archivo detectado: {message.media.document.mime_type}")
                    
                    # Verificar si es un archivo .txt
                    if message.media.document.mime_type == 'text/plain':
                        logger.info(f"[{request_id}] 📄 Archivo .txt detectado, descargando...")
                        
                        try:
                            # Descargar el archivo
                            file_path = await client.download_media(message.media, file=f"/tmp/nm_{request_id}.txt")
                            
                            if file_path and os.path.exists(file_path):
                                # Leer el contenido del archivo
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    file_content = f.read()
                                
                                logger.info(f"[{request_id}] 📄 Contenido del archivo leído: {len(file_content)} caracteres")
                                
                                # Parsear el contenido del archivo
                                parsed_data = parse_nm_response(file_content)
                                logger.info(f"[{request_id}] Datos parseados del archivo: {parsed_data}")
                                
                                # Limpiar archivo temporal
                                try:
                                    os.remove(file_path)
                                except:
                                    pass
                                
                                return {
                                    'success': True,
                                    'text_data': file_content,
                                    'parsed_data': parsed_data,
                                    'request_id': request_id,
                                    'source': 'file'
                                }
                            else:
                                logger.error(f"[{request_id}] Error descargando archivo")
                        except Exception as e:
                            logger.error(f"[{request_id}] Error procesando archivo: {str(e)}")
                
                # Buscar respuesta específica para NM en el texto del mensaje
                if message.text:
                    clean_message = message.text.replace('`', '').replace('*', '').replace('**', '')
                    if ('RENIEC X NOMBRES' in clean_message and 
                        ('OLIMPO_BOT' in clean_message or 'GRATIS' in clean_message)):
                        
                        logger.info(f"[{request_id}] ¡Respuesta encontrada para NM {nombres}|{apellidos}!")
                        logger.info(f"[{request_id}] Texto completo: {message.text}")
                        
                        # Encontramos la respuesta
                        text_data = message.text
                        
                        parsed_data = parse_nm_response(text_data)
                        logger.info(f"[{request_id}] Datos parseados: {parsed_data}")
                        
                        return {
                            'success': True,
                            'text_data': text_data,
                            'parsed_data': parsed_data,
                            'request_id': request_id,
                            'source': 'text'
                        }
            
            # Si no se encontró respuesta, esperar antes del siguiente intento
            if attempt < max_attempts:
                logger.warning(f"[{request_id}] No se detectó respuesta en intento {attempt}. Esperando 3 segundos...")
                await asyncio.sleep(3)
        
        logger.error(f"[{request_id}] Timeout consultando NM {nombres}|{apellidos}")
        return {
            'success': False,
            'error': 'Timeout: No se recibió respuesta después de 3 intentos',
            'request_id': request_id
        }
        
    except Exception as e:
        logger.error(f"[{request_id}] Error consultando NM {nombres}|{apellidos}: {str(e)}")
        return {
            'success': False,
            'error': f'Error en la consulta: {str(e)}',
            'request_id': request_id
        }

def check_connection():
    """Verifica si el cliente está conectado y lo reconecta si es necesario."""
    global client, loop
    
    if not client:
        logger.warning("Cliente no inicializado, reiniciando...")
        restart_telethon()
        return False
    
    if not client.is_connected():
        logger.warning("Cliente desconectado, reconectando...")
        try:
            restart_telethon()
            time.sleep(3)
            return client and client.is_connected()
        except Exception as e:
            logger.error(f"Error reconectando: {str(e)}")
            return False
    
    return True

def consult_nm_sync(nombres, apellidos, request_id=None):
    """Consulta el NM usando Telethon de forma síncrona."""
    global client, loop
    
    # Verificar conexión antes de proceder
    if not check_connection():
        return {
            'success': False,
            'error': 'Cliente de Telegram no disponible. Intenta en unos segundos.'
        }
    
    # Verificar que el loop esté disponible
    if not loop:
        logger.error("Loop de asyncio no disponible")
        return {
            'success': False,
            'error': 'Servicio no está completamente inicializado. Intenta en unos segundos.'
        }
    
    # Generar request_id único si no se proporciona
    if not request_id:
        request_id = str(uuid.uuid4())[:8]
    
    try:
        # Ejecutar la consulta asíncrona en el loop existente
        future = asyncio.run_coroutine_threadsafe(consult_nm_async(nombres, apellidos, request_id), loop)
        result = future.result(timeout=35)  # 35 segundos de timeout
        return result
        
    except asyncio.TimeoutError:
        logger.error(f"Timeout consultando /nm para {nombres} {apellidos}")
        return {
            'success': False,
            'error': 'Timeout: No se recibió respuesta en 35 segundos'
        }
    except Exception as e:
        logger.error(f"Error consultando /nm para {nombres} {apellidos}: {str(e)}")
        # Si es un error de Constructor ID, intentar reiniciar la sesión
        if "Constructor ID" in str(e) or "020b1422" in str(e) or "8f97c628" in str(e):
            logger.error("Error de Constructor ID detectado - versión de Telethon incompatible")
            logger.info("Intentando reiniciar sesión...")
            restart_telethon()
            return {
                'success': False,
                'error': 'Error de compatibilidad detectado. Intenta nuevamente en unos segundos.'
            }
        
        # Si es un error de sesión usada en múltiples IPs
        if "authorization key" in str(e) and "two different IP addresses" in str(e):
            logger.error("Sesión usada en múltiples IPs. Detén el proceso local y usa solo en contenedor.")
            return {
                'success': False,
                'error': 'Sesión en conflicto. Detén el proceso local y usa solo en contenedor.'
            }
        
        # Si es error de desconexión, intentar reconectar
        if "disconnected" in str(e).lower() or "connection" in str(e).lower() or "Cannot send requests while disconnected" in str(e):
            logger.info("Error de desconexión detectado, intentando reconectar...")
            try:
                # Verificar si el cliente está conectado
                if client and not client.is_connected():
                    logger.info("Cliente desconectado, reiniciando...")
                    restart_telethon()
                    # Esperar un poco para que se reconecte
                    time.sleep(5)
                    
                    # Verificar que se reconectó correctamente
                    if client and client.is_connected():
                        logger.info("Cliente reconectado exitosamente")
                        # Intentar la consulta nuevamente
                        future = asyncio.run_coroutine_threadsafe(consult_nm_async(nombres, apellidos, request_id), loop)
                        result = future.result(timeout=35)
                        return result
                    else:
                        logger.error("No se pudo reconectar el cliente")
                        return {
                            'success': False,
                            'error': 'Error de conexión. El servicio se está reiniciando, intenta en unos segundos.'
                        }
                else:
                    logger.error("Cliente no disponible para reconexión")
                    return {
                        'success': False,
                        'error': 'Error de conexión. El servicio no está disponible.'
                    }
            except Exception as retry_error:
                logger.error(f"Error en reintento: {str(retry_error)}")
                return {
                    'success': False,
                    'error': 'Error de conexión. Intenta nuevamente en unos segundos.'
                }
        
        return {
            'success': False,
            'error': f'Error en la consulta: {str(e)}'
        }

def restart_telethon():
    """Reinicia la conexión de Telethon"""
    global client, loop
    
    try:
        logger.info("Reiniciando conexión de Telethon...")
        
        if client:
            # Desconectar cliente existente
            try:
                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(client.disconnect(), loop)
                    future.result(timeout=5)
                else:
                    client.disconnect()
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
            global client, loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def start_client():
                    await client.start()
                    logger.info("Cliente de Telethon reiniciado correctamente")
                
                loop.run_until_complete(start_client())
                loop.run_forever()
                
            except Exception as e:
                logger.error(f"Error reiniciando Telethon: {e}")
        
        thread = threading.Thread(target=run_telethon, daemon=True)
        thread.start()
        
        # Esperar inicialización
        time.sleep(3)
        
    except Exception as e:
        logger.error(f"Error en restart_telethon: {e}")

def init_telethon():
    """Inicializa Telethon con un event loop global"""
    global client, loop
    
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

async def start_client():
    """Inicia el cliente de Telegram"""
    try:
        await client.start()
        logger.info("Cliente de Telethon iniciado correctamente")
    except Exception as e:
        logger.error(f"Error iniciando cliente: {e}")

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
    global client
    
    try:
        # Verificar estado del cliente
        client_status = "connected" if client and client.is_connected() else "disconnected"
        
        return jsonify({
            'service': 'Búsqueda por Nombres API',
            'status': 'healthy' if client_status == "connected" else 'unhealthy',
            'telegram_client': client_status,
            'database': 'initializing',  # No verificar BD para evitar timeouts
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'service': 'Búsqueda por Nombres API',
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

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
    """Endpoint para búsqueda por nombres - Respuesta síncrona."""
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
    
    # Generar request_id único para esta consulta
    request_id = str(uuid.uuid4())[:8]
    
    try:
        # Realizar consulta síncrona (espera la respuesta completa)
        result = consult_nm_sync(nombres, apellidos, request_id)
        
        if result['success']:
            return jsonify({
                'success': True,
                'nombres': nombres,
                'apellidos': apellidos,
                'data': result.get('parsed_data', {}),
                'request_id': request_id,
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': result['error'],
                'request_id': request_id
            }), 500
        
    except Exception as e:
        logger.error(f"[{request_id}] Error consultando /nm: {e}")
        
        # Intentar reiniciar Telethon si hay error de conexión
        if "disconnected" in str(e).lower() or "connection" in str(e).lower():
            try:
                restart_telethon()
                # Reintentar una vez
                result = consult_nm_sync(nombres, apellidos, request_id)
                if result['success']:
                    return jsonify({
                        'success': True,
                        'nombres': nombres,
                        'apellidos': apellidos,
                        'data': result.get('parsed_data', {}),
                        'request_id': request_id,
                        'timestamp': datetime.now().isoformat()
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': result['error'],
                        'request_id': request_id
                    }), 500
            except Exception as retry_error:
                logger.error(f"[{request_id}] Error en reintento: {retry_error}")
        
        return jsonify({
            'success': False,
            'error': f'Error en la consulta: {str(e)}',
            'request_id': request_id
        }), 500

# Telethon se inicializa en main() para evitar problemas con Gunicorn

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

def init_telethon_thread():
    """Inicializa Telethon en un hilo separado."""
    global client, loop
    
    def run_telethon():
        global client, loop
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            client = TelegramClient(
                'telethon_session',
                config.API_ID,
                config.API_HASH
            )
            
            # Iniciar el cliente de forma asíncrona
            async def start_client():
                await client.start()
                logger.info("Cliente de Telethon iniciado correctamente")
            
            loop.run_until_complete(start_client())
            
            # Mantener el loop corriendo
            loop.run_forever()
            
        except Exception as e:
            logger.error(f"Error inicializando Telethon: {str(e)}")
    
    # Iniciar en hilo separado
    thread = threading.Thread(target=run_telethon, daemon=True)
    thread.start()
    
    # Esperar un poco para que se inicialice
    time.sleep(3)

def main():
    """Función principal."""
    # Inicializar base de datos
    init_database()
    
    # Actualizar tiempo restante de todas las keys
    update_all_time_remaining()
    
    # Inicializar Telethon en hilo separado
    init_telethon_thread()
    
    # Iniciar Flask
    port = int(os.getenv('PORT', 8080))
    logger.info(f"Iniciando API en puerto {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
