#!/usr/bin/env python3
"""
Script para arreglar errores de indentación en api_nm.py
"""

def fix_indentation():
    with open('api_nm.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    fixed_lines = []
    indent_level = 0
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Si la línea está vacía, mantenerla
        if not stripped:
            fixed_lines.append(line)
            continue
            
        # Si la línea tiene contenido pero no tiene indentación correcta
        if line.startswith('        ') and not line.startswith('            '):
            # Verificar si debería tener más indentación
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
                # Esta línea debería tener indentación normal
                fixed_lines.append('        ' + stripped + '\n')
            else:
                # Esta línea debería tener más indentación
                fixed_lines.append('            ' + stripped + '\n')
        else:
            # La línea ya tiene la indentación correcta
            fixed_lines.append(line)
    
    with open('api_nm.py', 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)
    
    print("Indentación arreglada")

if __name__ == "__main__":
    fix_indentation()
