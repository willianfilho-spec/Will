---
name: ollama-n8n
description: Liga o Ollama (modelos de IA locais) ao n8n no Windows ou Linux. Cobre instalação, escolha de modelo, credencial "Ollama API", nós Ollama Chat Model / Embeddings Ollama, n8n no Docker (host.docker.internal, OLLAMA_HOST) e diagnóstico de erros de conexão. Use quando o usuário quiser usar Ollama no n8n, trocar OpenAI por modelo local num workflow, ou estiver com erro "ECONNREFUSED 11434" / "fetch failed" no n8n.
---

# Ollama + n8n

Objetivo: o n8n chamar um modelo rodando no Ollama, no mesmo computador.

## 1. Descobrir o cenário (pergunte se não souber)

| Onde o n8n roda | Base URL da credencial |
|---|---|
| Instalado direto no PC (`npx n8n`, `npm i -g n8n`, app desktop) | `http://localhost:11434` |
| Docker Desktop (Windows/Mac) | `http://host.docker.internal:11434` |
| Docker no Linux | `http://host.docker.internal:11434` + `--add-host=host.docker.internal:host-gateway` no container |
| Ollama e n8n no mesmo `docker compose` | `http://ollama:11434` (nome do serviço) |
| n8n Cloud (n8n.io) | Não alcança o PC do usuário. Veja a seção 6. |

Se `localhost` falhar com Docker, é quase sempre porque dentro do container `localhost` é o próprio container.

## 2. Ollama instalado e respondendo

Windows (PowerShell):

```powershell
irm https://ollama.com/install.ps1 | iex
ollama pull llama3.2          # ~2 GB, bom para começar
curl.exe http://localhost:11434/api/tags
```

O último comando deve devolver um JSON com `"models"`. Se der erro, o Ollama não está rodando: abra o app Ollama (ícone na bandeja) ou rode `ollama serve`.

Modelos sugeridos:
- Conversa/texto simples: `llama3.2` (3B) ou `gemma3:4b`.
- **AI Agent com ferramentas (tools)**: precisa de modelo com suporte a tool calling: `qwen2.5:7b`, `llama3.1:8b` ou `qwen3:8b`. Modelos sem esse suporte dão erro ou ignoram as ferramentas.
- Embeddings (RAG, vector store): `nomic-embed-text`.

Com 8 GB de RAM, fique em modelos de até ~4B.

## 3. Deixar o Docker enxergar o Ollama (só se o n8n estiver em Docker)

Por padrão o Ollama só escuta em `127.0.0.1`. Se o teste da seção 5 falhar de dentro do container, faça o Ollama escutar em todas as interfaces:

Windows:
```powershell
setx OLLAMA_HOST "0.0.0.0:11434"
```
Depois **feche o Ollama pela bandeja** (Quit) e abra de novo. `setx` só vale para processos novos.

Linux (systemd):
```bash
sudo systemctl edit ollama
# adicionar:
# [Service]
# Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl restart ollama
```

Aviso de segurança: `0.0.0.0` expõe o Ollama na rede local, e ele não tem senha. Não abra a porta 11434 no roteador. Em rede pública (Wi-Fi de café, etc.), bloqueie a porta no firewall do Windows para redes "Públicas".

## 4. Credencial no n8n

1. n8n → **Credentials** → **Add credential** → procurar **Ollama** (tipo "Ollama API").
2. **Base URL**: a da tabela da seção 1. Sem barra no final, sem `/api`.
3. API Key: deixe em branco (Ollama local não usa).
4. Salvar. O n8n testa a conexão; se ficar verde, está ligado.

## 5. Testar a conexão de dentro do container (quando der erro)

```powershell
docker exec -it n8n wget -qO- http://host.docker.internal:11434/api/tags
```
(troque `n8n` pelo nome do container, visto em `docker ps`)

- Devolveu JSON → a rede está ok; revise a Base URL na credencial.
- `Connection refused` → faltou a seção 3 (OLLAMA_HOST) ou o Ollama não está rodando.
- `bad address` / não resolve → no Linux faltou `--add-host=host.docker.internal:host-gateway`.

## 6. n8n Cloud

O n8n Cloud roda nos servidores da n8n e não enxerga `localhost` do usuário. As saídas são:
- rodar o n8n localmente (recomendado para quem já tem Ollama local: `npx n8n` ou Docker); ou
- expor o Ollama por um túnel (Cloudflare Tunnel, ngrok) **com autenticação na frente**. Sem autenticação, qualquer pessoa com a URL usa o computador do usuário. Só sugira isso se o usuário entender o risco.

## 7. Usar no workflow

Nós do n8n que usam a credencial:
- **Ollama Chat Model**: sub-nó ligado a um **AI Agent**, **Basic LLM Chain**, **Summarization Chain**, **Question and Answer Chain**, etc. É o que se usa na maioria dos casos.
- **Ollama Model**: modelo de completar texto (não-chat). Raramente necessário.
- **Embeddings Ollama**: para vector stores (RAG).

No sub-nó, escolha a credencial e o modelo na lista (a lista vem do `/api/tags`; se estiver vazia, nenhum modelo foi baixado com `ollama pull`).

Workflow pronto para importar: `workflow-exemplo.json` nesta pasta (Chat Trigger → Basic LLM Chain → Ollama Chat Model com `llama3.2`). No n8n: menu **⋯** → **Import from File**, depois abra o nó "Ollama Chat Model" e selecione a credencial.

## 8. Problemas comuns

| Sintoma | Causa provável | Correção |
|---|---|---|
| `ECONNREFUSED 127.0.0.1:11434` | n8n em Docker usando `localhost` | Base URL `http://host.docker.internal:11434` |
| `ECONNREFUSED` com host.docker.internal | Ollama só em 127.0.0.1 | Seção 3 |
| `model "x" not found` | Modelo não baixado | `ollama pull x` |
| Agent não chama ferramentas / erro "does not support tools" | Modelo sem tool calling | Trocar para `qwen2.5:7b` ou `llama3.1:8b` |
| Resposta muito lenta ou timeout | Modelo grande demais para a RAM/GPU | Modelo menor; ver uso com `ollama ps` |
| Primeira resposta demora, as seguintes não | Modelo carregando na memória | Normal |

## Regras ao ajudar

- Não peça nem registre senhas ou chaves; Ollama local não precisa de nenhuma.
- Não sugira expor o Ollama à internet sem avisar do risco (seção 6).
- Confirme a versão/forma de instalação do n8n antes de dar comandos de Docker.
