# Implantação em outra plataforma

O que foi **testado** e o que **não** foi está marcado em cada item. Antes de expor a clientes, leia `SEGURANCA.md`.

## 1. A plataforma precisa ter (requisitos que decidem se serve)

| Requisito | Por quê |
|---|---|
| **Disco persistente** (volume/disco montado) | os dados são SQLite + arquivos em pasta. Sem disco persistente, tudo some ao reiniciar |
| **Uma única instância** (não escalar horizontalmente) | SQLite não é compartilhado entre servidores e o limite de requisições fica na memória do processo |
| **Servidor de longa duração** (processo ou contêiner) | não serve para funções "serverless" (Vercel, Netlify, Cloud Functions, Lambda): não há disco persistente nem processo contínuo |
| **HTTPS pela plataforma** | o app não termina TLS; os cookies são `Secure` |
| Python 3.12 (ou 3.13) **ou** Docker | versões testadas |
| Variável de ambiente `PORT` (a maioria das plataformas define) | o servidor lê `PORT`; padrão 8000 |

Serve: VPS (Hetzner, DigitalOcean, Contabo, Oracle, AWS Lightsail), Docker em qualquer servidor, e PaaS que ofereça disco persistente
(Render com disk, Railway com volume, Fly.io com volume, etc., conferindo o plano). Não serve: planos que apagam o disco a cada
deploy e plataformas serverless.

## 2. Variáveis de ambiente

Modelo em `.env.example`. Principais:

| Variável | Obrigatória | O que é |
|---|---|---|
| `CONCILIADOR_CHAVE` | sim | chave de criptografia dos arquivos (`python scripts/gerar_chave.py`). **Guarde uma cópia fora do backup dos dados. Perdê-la é perder os arquivos** |
| `CONCILIADOR_DATA_DIR` | sim | pasta dos dados, no disco persistente (ex.: `/dados`) |
| `CONCILIADOR_ADMIN_EMAIL`, `CONCILIADOR_ADMIN_SENHA` | só no 1º início | cria o primeiro administrador se ainda não houver usuários. A senha deve atender à política; é de uso único e deve ser trocada no 1º acesso. **Remova a SENHA da plataforma depois** |
| `FORWARDED_ALLOW_IPS` | recomendado | IPs do proxy confiáveis para `X-Forwarded-For`. Use `*` só se o app não for acessível sem passar pelo proxy da plataforma |
| `PORT` | a plataforma define | porta do servidor |

O servidor **se recusa a subir sem `CONCILIADOR_CHAVE`**.

## 3. Comando de início

```bash
pip install -r requirements.txt            # só dependências de execução, versões fixadas
python scripts/rodar_web.py --host 0.0.0.0 --atras-de-proxy
```

Endereço de verificação de saúde (sem login, não expõe dados): `GET /saude` → `ok`.
O arquivo `Procfile` já traz essa linha para plataformas que o usam.

## 4. Docker (não testado aqui, sem Docker no ambiente de construção)

```bash
docker build -t conciliador conciliador_fortes
docker run -d --name conciliador -p 8000:8000 \
  -v conciliador_dados:/dados \
  -e CONCILIADOR_CHAVE="$(python scripts/gerar_chave.py)" \
  -e CONCILIADOR_ADMIN_EMAIL=voce@seudominio.com.br \
  -e CONCILIADOR_ADMIN_SENHA='Troque-Esta-Senha-42!' \
  conciliador
```

O `Dockerfile` usa Python 3.12, usuário sem privilégios, `HEALTHCHECK` em `/saude` e `/dados` como volume.
Guarde o valor da chave: o exemplo acima a gera e **não a mostra**; gere antes, anote e passe o valor.

## 5. Servidor próprio sem Docker (Linux, não testado aqui)

1. `python3.12 -m venv venv && venv/bin/pip install -r requirements.txt`
2. Defina as variáveis acima num arquivo `/etc/conciliador.env` (permissão 600).
3. Serviço `systemd` (`/etc/systemd/system/conciliador.service`):
   ```
   [Service]
   User=conciliador
   WorkingDirectory=/opt/conciliador_fortes
   EnvironmentFile=/etc/conciliador.env
   ExecStart=/opt/conciliador_fortes/venv/bin/python scripts/rodar_web.py --host 127.0.0.1 --port 8000 --atras-de-proxy
   Restart=on-failure
   ```
4. Proxy com HTTPS na frente (exemplo Caddy, certificado automático; exige domínio apontado para o servidor):
   ```
   conciliador.seudominio.com.br {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   Aqui deixe `FORWARDED_ALLOW_IPS=127.0.0.1`.

## 6. Depois de subir

1. Abra a URL, entre com o administrador, troque a senha e ative o 2FA (obrigatório).
2. Remova `CONCILIADOR_ADMIN_SENHA` da plataforma.
3. Em Administração: crie as empresas, os usuários e as permissões.
4. Backup: copie a pasta de dados (o banco vai em claro; **cifre o destino**) e guarde a chave separada.
   `python scripts/teste_restauracao.py --data-dir /dados` testa a restauração em pasta temporária.
5. Faça a homologação com o Fortes (`homologacao/instrucoes-escritorio.md`) antes de usar com empresas reais.

## 7. Atualizar o sistema

Os bancos se migram sozinhos ao abrir (colunas novas são acrescentadas). Faça backup antes de atualizar o código.

## 8. Teste local sem instalar

`python scripts/rodar_web.py --demo` (dados de mentira, sem HTTPS, sem 2FA; **nunca em produção**) ou o pacote Windows
(`python scripts/montar_pacote.py`, ver `README.md`).
