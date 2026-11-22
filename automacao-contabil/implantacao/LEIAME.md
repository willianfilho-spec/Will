# Hospedar o Conciliador Fortes num servidor

Esta etapa coloca o sistema na internet **só para a equipe do escritório**,
com login pela conta Google (Cloudflare Access). Os clientes da Equilibra
ainda não entram: o portal do cliente é uma etapa posterior.

## Como fica

```
navegador (qualquer lugar)
   │  login Google (Cloudflare Access: só e-mails autorizados)
   ▼
Cloudflare  ──túnel──►  servidor
                         ├─ app      o Conciliador (sem porta aberta na internet)
                         ├─ tunel    conector da Cloudflare
                         └─ backup   cópia diária + teste de restauração
                            dados/   empresas, extratos, lançamentos, auditoria
                            backups/ cópias (30 diárias + 12 mensais)
```

- O servidor não abre nenhuma porta para a internet: o túnel sai dele até a
  Cloudflare.
- O app confere a assinatura do login em cada sessão e a lista de autorizados
  (`config/acesso.json`). No servidor, **ninguém entra sem login**, nem pelo
  próprio servidor (`"acesso_local_sem_login": false`).
- A sugestão por IA fica desligada no servidor (o pacote nem é instalado).
- Os dados ficam no disco do servidor, em SQLite por empresa, como no
  computador do escritório. Não foi preciso reescrever o motor.

## Onde hospedar: comparativo

Os preços e condições abaixo foram consultados em novembro de 2026 e mudam
com frequência: confira na hora de contratar.

| Opção | Custo | Dados no Brasil | Pontos de atenção |
| --- | --- | --- | --- |
| Computador do escritório + túnel (já pronto, `5_CONFIGURAR_ACESSO_REMOTO.bat`) | Sem custo | Sim, no escritório | Depende do computador ligado e da internet do escritório |
| Oracle Cloud, plano gratuito permanente, região São Paulo | Sem custo | Sim, se a região inicial for São Paulo | Em agosto de 2026 a Oracle reduziu os limites do plano gratuito de máquinas Arm e desativou instâncias acima do novo limite; instância acima do limite é apagada em 30 dias sem conta paga. Falta de capacidade é comum. Sem suporte. |
| AWS Lightsail, região São Paulo (disponível desde junho de 2026) | Plano mais barato anunciado a partir de US$ 5/mês (varia por região; confira São Paulo); 3 meses grátis em planos selecionados | Sim | Cobrança em dólar; instantâneos (snapshots) do disco pagos à parte |
| Locaweb Cloud | VMs anunciadas a partir de R$ 20/mês, cobradas por hora com teto mensal | Sim | Confirmar o tamanho mínimo que atende (abaixo) |
| Outras nuvens brasileiras (ex.: Magalu Cloud) | Consultar | Sim | Comparar com as anteriores |

**Tamanho mínimo sugerido:** 2 GB de memória, 1 a 2 vCPU, 20 GB de disco,
Ubuntu 24.04 ou Debian 12 (x86-64 ou Arm).

**Recomendação para o piloto com dados reais de clientes:** um servidor
**pago e pequeno numa região do Brasil** (Lightsail São Paulo ou Locaweb).
O plano gratuito da Oracle serve para testes com dados fictícios, mas a
mudança de limites de 2026 mostra o risco de a máquina ser desativada sem
escolha do escritório. Seja qual for a opção: contrato em nome da Equilibra,
região no Brasil e leitura dos termos de tratamento de dados (LGPD) do
provedor.

## Passo a passo

### 1. Servidor

1. Crie o servidor no provedor escolhido (Ubuntu 24.04), em nome da Equilibra.
2. Acesse por SSH com chave (não por senha). Libere no firewall do provedor
   **só a porta 22 (SSH)**. Nenhuma outra porta é necessária.
3. Ative as atualizações automáticas de segurança:
   `sudo apt install -y unattended-upgrades`.

### 2. Cloudflare e Google

Siga os passos 1 a 4 do `GUIA_ACESSO_REMOTO.pdf`, com uma diferença no
túnel: no endereço público, o serviço é **HTTP** e o endereço é
**`app:8501`** (o nome do contêiner), não `localhost:8501`.

Anote o **token do túnel**, o **domínio da equipe** e o **AUD Tag**.

Se o escritório já usa o túnel no computador local, crie um **túnel novo**
para o servidor (ou desinstale o do computador), para os dois não
responderem pelo mesmo endereço.

### 3. Código e preparação

```bash
git clone --branch fase1/exportador-fortes https://github.com/willianfilho-spec/Will.git
cd Will/automacao-contabil/implantacao
./preparar_servidor.sh
```

O script instala o Docker (na primeira vez pede para sair e entrar de novo no
servidor e rodar outra vez), cria as pastas `dados`, `backups` e `config`
com as permissões certas, grava o token no `.env`, constrói a imagem, **roda
todos os testes automáticos dentro dela** e abre o assistente do login
(domínio da equipe, AUD e e-mails autorizados).

### 4. Subir

```bash
docker compose up -d
docker compose ps          # os três serviços "running"; app "healthy"
docker compose logs backup # deve mostrar a primeira cópia e o teste de restauração
```

Abra o endereço (ex.: `https://conciliador.equilibracontabil.com.br`) no
celular, entre com uma conta autorizada e depois tente com uma não
autorizada.

### 5. Trazer os dados do computador do escritório (se já estiverem em uso)

1. No escritório: feche o Conciliador e rode `4_FAZER_BACKUP_AGORA.bat`.
2. Copie a pasta `dados` do escritório para `implantacao/dados` no servidor
   (por exemplo, com `scp -r` ou WinSCP).
3. No servidor: `sudo chown -R 1000:1000 dados && docker compose restart app`.
4. A partir daí, use **só o servidor**. Dois sistemas recebendo extratos ao
   mesmo tempo geram bases diferentes.

## Backup

- O serviço `backup` faz uma cópia por dia (`HORA_BACKUP` no `.env`, padrão
  21:00) e testa a restauração de cada cópia. Ao iniciar, faz uma cópia se a
  última tiver mais de 24 horas.
- A barra lateral do sistema avisa se a última cópia tiver mais de 26 horas.
- **As cópias ficam no mesmo servidor.** Se o servidor for perdido, elas vão
  junto. Faça também:
  - instantâneos (snapshots) automáticos do disco no painel do provedor; e
  - uma cópia semanal para fora, por exemplo para o computador do
    escritório: `scp -r usuario@servidor:~/Will/automacao-contabil/implantacao/backups D:\backup_servidor`.
- Restaurar: pare o app (`docker compose stop app`), restaure numa pasta
  vazia, confira e só então troque a pasta `dados`:
  `docker compose run --rm backup python -m motor_contabil.backup restaurar --destino /backups --para /dados_restaurados`
  (monte uma pasta para `/dados_restaurados` ou peça ajuda ao responsável).

## Operação

| Tarefa | Comando (na pasta `implantacao`) |
| --- | --- |
| Ver situação | `docker compose ps` |
| Ver mensagens | `docker compose logs -f app` |
| Reiniciar | `docker compose restart` |
| Incluir ou retirar alguém | Na política da Cloudflare **e** `docker run --rm -it -v "$PWD/config:/config" conciliador-fortes:fase1 python -m motor_contabil.acesso configurar /config/acesso.json`, depois `docker compose restart app` |
| Situação do backup | `docker compose run --rm backup python -m motor_contabil.backup situacao --destino /backups` |
| Atualizar o sistema | `git pull`, `docker compose build`, `docker compose run --rm --no-deps -e MOTOR_CONTABIL_ACESSO= app python -m pytest -q -p no:cacheprovider`, `docker compose up -d` |
| Testar no próprio servidor sem túnel | `docker compose -f docker-compose.yml -f teste-local.yml up -d` e túnel SSH para `127.0.0.1:8501` (ainda exige login, então mostra só o aviso) |

## Limites desta etapa

- Só a equipe do escritório. Clientes não entram.
- Um servidor só, sem redundância: se ele cair, o sistema fica fora do ar até
  voltar (os dados ficam no disco e nos backups).
- A imagem não foi construída no ambiente em que foi preparada (o acesso ao
  Docker Hub estava bloqueado). A primeira construção no servidor roda os
  testes automáticos e só segue se todos passarem.
