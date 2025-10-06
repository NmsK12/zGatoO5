#!/usr/bin/env python3
"""
Script para arreglar TODOS los errores de indentación en api_nm.py
"""

def fix_all_indentation():
    with open('api_nm.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Dividir en líneas
    lines = content.split('\n')
    fixed_lines = []
    
    for i, line in enumerate(lines):
        # Si la línea está vacía, mantenerla
        if not line.strip():
            fixed_lines.append(line)
            continue
            
        # Contar espacios al inicio
        leading_spaces = len(line) - len(line.lstrip())
        
        # Si la línea tiene 8 espacios pero debería tener 12, corregir
        if leading_spaces == 8 and line.strip():
            # Verificar si es una línea que debería tener más indentación
            stripped = line.strip()
            if (stripped.startswith(('if ', 'for ', 'while ', 'try:', 'except', 'else:', 'elif ')) or
                stripped.endswith(':') or
                stripped.startswith('return ') or
                stripped.startswith('logger.') or
                stripped.startswith('await ') or
                stripped.startswith('client.') or
                stripped.startswith('global ') or
                stripped.startswith('async def') or
                stripped.startswith('def ') or
                stripped.startswith('class ') or
                stripped.startswith('import ') or
                stripped.startswith('from ') or
                stripped.startswith('#') or
                stripped.startswith('"""') or
                stripped.startswith("'''")):
                # Esta línea debería tener indentación normal (8 espacios)
                fixed_lines.append(line)
            else:
                # Esta línea debería tener más indentación (12 espacios)
                fixed_lines.append('    ' + line)
        else:
            # La línea ya tiene la indentación correcta
            fixed_lines.append(line)
    
    # Escribir el archivo corregido
    with open('api_nm.py', 'w', encoding='utf-8') as f:
        f.write('\n'.join(fixed_lines))
    
    print("Todas las indentaciones arregladas")

if __name__ == "__main__":
    fix_all_indentation()
