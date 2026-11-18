# Segurança e proteção de dados — Conciliador Fortes (web)

Escrito para quem decide se o sistema pode ser exposto a clientes. Separa **o que está implementado e testado**
do que **depende de implantação** e do que **não foi feito**. Nenhum pentest independente foi realizado.

## 1. Implementado e coberto por teste automatizado

| Controle | Como funciona | Teste |
|---|---|---|
| Autenticação | e-mail e senha; PBKDF2-SHA256 (200 mil iterações); mesmo custo de verificação para e-mail inexistente (sem enumeração por tempo); mensagem genérica | `test_sec_02`, `test_web_03` |
| Política de senha | mínimo 10, 3 tipos de caractere, sem senhas comuns, sem e-mail/nome na senha | `test_sec_01`, `test_web_09` |
| Bloqueio de login | 5 falhas por e-mail ou 20 por IP = 15 min; o administrador desbloqueia | `test_sec_02`, `test_web_04` |
| 2FA (TOTP) | obrigatório para a equipe e o administrador, opcional para clientes; compatível com os vetores da RFC 6238; código não reutilizável; 8 códigos de recuperação de uso único; semente cifrada no banco | `test_sec_04/05`, `test_web_08` |
| Sessão | no servidor; cookie `HttpOnly`, `Secure`, `SameSite=Strict`; o banco guarda só o SHA-256 do token; expira em 30 min sem uso e 8 h no total; token trocado após o 2FA; logout e troca de senha derrubam sessões | `test_sec_03/06`, `test_web_06/07/09` |
| CSRF | token por sessão conferido em toda ação que altera dados; token próprio no login | `test_web_03/05` |
| Cabeçalhos | CSP restritiva (sem scripts, sem estilo em linha, sem frames), X-Frame-Options, nosniff, Referrer-Policy, HSTS, `Cache-Control: no-store` | `test_web_01` |
| Isolamento entre empresas | banco e pasta separados por empresa; empresa alheia responde 404 (não confirma que existe); tentativas negadas ficam no log | `test_web_10`, `test_fluxo` |
| Isolamento entre clientes | cada cliente só vê e baixa os próprios envios; só vê o texto dos pedidos, sem dados de movimentos nem nomes da equipe | `test_doc_02`, `test_web_14` |
| Separação de papéis | cliente só recebe o papel "cliente"; a equipe não; ações da equipe exigem papel; operador não confirma nem exporta | `test_sec_08`, `test_web_10/11` |
| Segregação de função | quem revisa não confirma; quem cria lançamento manual não confirma; identidade inclui o id (homônimos não se confundem) | `test_segregacao_de_funcao`, `test_lanc_03` |
| Upload | tamanho, extensão permitida e conferência do conteúdo (assinatura); nome do arquivo nunca vai para o disco; limite por minuto | `test_doc_01`, `test_web_12` |
| XSS | saída escapada; textos do extrato com `<script>` aparecem como texto | `test_web_13` |
| Criptografia em repouso | arquivos enviados e lotes em AES-256-GCM, chave derivada por empresa; arquivo de uma empresa não abre com a chave de outra; adulteração é detectada | `test_cri_01`, `test_web_15` |
| Rastreabilidade | auditoria com cadeia de hash (apagar ou alterar linha por fora do app é detectado); triggers do banco impedem alterar auditoria, origem do extrato, lotes e originais | `test_aud_01/02`, `test_aut_int_*` |
| Erros | sem stack trace para o usuário; erros inesperados ficam no log do servidor | `test_web_20` |

## 2. Depende de como você implanta (o código não resolve sozinho)

- **HTTPS.** O app não termina TLS. Rode atrás de um proxy reverso com certificado (exemplo em `IMPLANTACAO.md`).
  Sem HTTPS, os cookies `Secure` não funcionam e a senha trafega em claro. Não exponha na internet sem isso.
- **Chave de criptografia.** Defina `CONCILIADOR_CHAVE` (gere com `scripts/gerar_chave.py`) e guarde uma cópia **fora**
  do backup dos dados. Perder a chave é perder os arquivos. Sem a variável, o app cria `data/chave.key` ao lado dos
  dados: serve para demonstração, não para produção.
- **Banco SQLite sem criptografia.** Os arquivos enviados são cifrados; o banco não (nomes, valores e históricos ficam
  legíveis para quem ler o arquivo). Use criptografia de disco (BitLocker, LUKS) na máquina e restrinja o acesso à pasta.
- **IP real do cliente.** Atrás de proxy, inicie o servidor com `--proxy-headers` e `--forwarded-allow-ips` apontando
  só para o proxy; senão o limite por IP enxerga o IP do proxy.
- **Backup.** Os backups copiam os arquivos já cifrados, mas **o banco vai em claro**. Cifre o destino do backup.
- **Processo único.** O limite de requisições é em memória e vale por processo. Com vários processos, mova para o proxy.

## 3. Não feito / limitações conhecidas

- Nenhum teste de intrusão independente. Os testes automatizados cobrem os controles acima, não substituem um pentest.
- Recuperação de senha por e-mail: não existe. O administrador redefine e entrega uma senha temporária.
- O bloqueio por e-mail permite que alguém trave a conta de outra pessoa por 15 min (o administrador desbloqueia).
- A cadeia de auditoria detecta adulteração parcial, mas quem controla o arquivo inteiro pode refazê-la. Mitigação:
  guardar o hash final fora do servidor (o relatório de integridade o mostra) e comparar depois.
- Os contadores de limite de requisições e de tentativas por IP não protegem contra ataque distribuído.
- O banco não é cifrado (ver acima). Dados em memória e logs não foram tratados.
- LGPD: não há rotina automática de retenção, anonimização ou exportação de dados do titular. É decisão do escritório
  (controlador) definir prazos; hoje a eliminação exigiria intervenção manual do administrador, e os triggers
  de imutabilidade foram feitos justamente para impedir apagar registros contábeis.
- Sem antivírus nos uploads. O app não executa nem interpreta os arquivos enviados além de lê-los como dados, mas
  um arquivo malicioso baixado por um funcionário continua sendo um risco da estação dele.
- Nenhuma IA ligada. Se for ligada, o texto do extrato passa a ser entrada não confiável do modelo (injeção de
  instruções) e dados de clientes sairiam do escritório: exige decisão formal de sigilo/LGPD antes.

## 4. Fluxo de dados (para o registro de tratamento)

Cliente → navegador (HTTPS) → servidor do escritório → arquivo cifrado em disco + registros no SQLite da empresa.
Equipe acessa pelo navegador. Nada sai do servidor para serviços externos. Dados pessoais: nomes e e-mails dos
usuários; nomes de favorecidos, CPF/CNPJ e valores nos extratos e documentos enviados.
