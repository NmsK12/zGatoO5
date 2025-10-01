import psycopg2
import os

# URL de conexión a PostgreSQL del servidor NM
DATABASE_URL = 'postgresql://postgres:yrgxHVIPjGFTNBQXTLiDltHAzFkaNCUr@gondola.proxy.rlwy.net:49761/railway'

def fix_database():
    """Arregla la base de datos del servidor NM"""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Verificar si la tabla existe
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'api_keys'
            );
        """)
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            print("Creando tabla api_keys...")
            cursor.execute('''
                CREATE TABLE api_keys (
                    key TEXT PRIMARY KEY,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT DEFAULT '',
                    last_used TIMESTAMP NULL,
                    usage_count INTEGER DEFAULT 0,
                    created_by TEXT DEFAULT '',
                    time_remaining INTEGER DEFAULT 0
                )
            ''')
        else:
            print("Tabla api_keys existe, verificando columnas...")
            
            # Verificar columnas existentes
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'api_keys'
            """)
            columns = [row[0] for row in cursor.fetchall()]
            print(f"Columnas existentes: {columns}")
            
            # Agregar columna created_by si no existe
            if 'created_by' not in columns:
                print("Agregando columna created_by...")
                cursor.execute('ALTER TABLE api_keys ADD COLUMN created_by TEXT DEFAULT \'\'')
            
            # Agregar columna time_remaining si no existe
            if 'time_remaining' not in columns:
                print("Agregando columna time_remaining...")
                cursor.execute('ALTER TABLE api_keys ADD COLUMN time_remaining INTEGER DEFAULT 0')
        
        conn.commit()
        print("Base de datos arreglada correctamente")
        
    except Exception as e:
        print(f"Error arreglando base de datos: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    fix_database()
