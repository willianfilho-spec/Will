# Implantação do web app

> Os arquivos `Dockerfile`, `docker-compose.yml` e `Caddyfile` abaixo **não foram executados** neste ambiente
> (não há Docker aqui). O servidor Python foi testado por `pytest` e no navegador; a parte de proxy/HTTPS não.

## Demonstração local (sem HTTPS, só nesta máquina)

```bash
cd conciliador_fortes
pip install -r requirements.txt
python scripts/rodar_web.py --demo
```

Cria dados de exemplo em uma pasta temporária e sobe em `http://127.0.0.1:8000`. Logins de demonstração (senha
`Demo-Conciliador-2026!`): `admin@demo.test`, `operador@demo.test`, `revisor@demo.test`, `cliente@demo.test`.
O modo demo desliga o 2FA e o cookie `Secure`. **Nunca use `--demo` em produção.**

## Produção (resumo)

1. Máquina com disco cifrado e acesso restrito à pasta de dados.
2. Gere e guarde a chave: `python scripts/gerar_chave.py` → defina `CONCILIADOR_CHAVE` (cofre/gerenciador de senhas).
3. Pasta de dados fora do repositório: `CONCILIADOR_DATA_DIR=/var/lib/conciliador`.
4. Crie o primeiro administrador: `python scripts/criar_admin.py` (pede nome, e-mail e senha; valida a política).
5. Suba o servidor só em localhost e coloque um proxy com HTTPS na frente:
   ```bash
   python scripts/rodar_web.py --host 127.0.0.1 --port 8000
   ```
   O script se recusa a subir sem `CONCILIADOR_CHAVE` (ou `--demo`).
6. No primeiro acesso o administrador é levado a ativar o 2FA. Depois cria empresas, usuários e permissões em /admin.
7. Faça backup (ver README) **e** copie a chave separadamente.

### Proxy com HTTPS (exemplo Caddy, não testado aqui)

```
conciliador.seudominio.com.br {
    reverse_proxy 127.0.0.1:8000
}
```

O Caddy obtém e renova o certificado sozinho (exige um domínio apontando para o servidor e as portas 80/443 abertas).
Inicie o app com `--proxy-headers --forwarded-allow-ips 127.0.0.1` (o `rodar_web.py --atras-de-proxy` faz isso).

### Variáveis de ambiente

| Variável | Para quê |
|---|---|
| `CONCILIADOR_CHAVE` | chave mestra (base64, 32 bytes). Obrigatória em produção |
| `CONCILIADOR_DATA_DIR` | pasta de dados |
| `CONCILIADOR_EXIGIR_2FA` | `1` (padrão) exige 2FA da equipe; `0` só para testes |
| `CONCILIADOR_HTTP_LOCAL` | `1` desliga o cookie `Secure` (só teste local sem HTTPS) |
| `CONCILIADOR_MAX_UPLOAD` | limite de upload em bytes (padrão 20 MB) |
