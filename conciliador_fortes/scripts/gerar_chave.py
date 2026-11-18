"""Gera uma chave mestra para CONCILIADOR_CHAVE.

    python scripts/gerar_chave.py

Guarde o valor num cofre ou gerenciador de senhas, FORA do backup dos dados. Sem a chave os arquivos
cifrados não abrem. Nunca coloque a chave no repositório.
"""
import base64
import secrets

print(base64.b64encode(secrets.token_bytes(32)).decode())
