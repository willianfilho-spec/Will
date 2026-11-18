# Plano de testes da homologação (P-004)

Objetivo: transformar cada pendência em teste verificável e definir quando o app pode ser liberado para uso
com o Fortes real. Rastreabilidade: `matriz-rastreabilidade.md`. Resultados: `relatorio-homologacao.md`
(ambos gerados por `scripts/relatorio_homologacao.py`). Procedimento no escritório: `instrucoes-escritorio.md`.

## 1. Duas categorias de teste

| Categoria | Onde roda | O que prova | O que NÃO prova |
|---|---|---|---|
| **Automatizado** (`pytest`, Playwright) | qualquer máquina, dados inventados | o código faz o que foi especificado e bloqueia o que deve bloquear | que o Fortes aceita o arquivo, o limite real do histórico, o formato do Razão real, o comportamento com extratos reais |
| **Instalação real** (itens H1 a H5) | máquina do escritório, Fortes de teste | compatibilidade com o Fortes e com os dados reais | nada além do que foi testado naquele dia, naquela versão |

Regra: teste automatizado nunca aprova item H. O app só registra `aprovado` com evidência anexada (arquivo com
SHA-256), por administrador, e confere em código o que consegue (H1: lote aceito e conferido no Razão; H2: limite
válido; H3: formato conhecido; H4: JSON de restauração aprovado e não sintético). O registro é só de inclusão.

## 2. Itens que dependem da instalação real

| Item | Pendência original | Critério de aprovação | Evidência exigida |
|---|---|---|---|
| H1 | Importar um lote gerado no Fortes | Lote importado sem erro; todas as marcas no Razão exportado depois, uma vez cada, com data, valor e contas iguais (conferência do app aprovada) | print/PDF da importação e do Razão |
| H2 | Limite do histórico (118 usado; há arquivo real com 123) | Fortes guarda o histórico inteiro, com a marca no fim, no limite escolhido | print do Razão com os 11 tamanhos de teste |
| H3 | Leiaute do Razão | Razão real lido pelo app; saldo do banco igual ao do Fortes | arquivo (anonimizado) e print do saldo |
| H4 | Restauração prática de backup | `teste_restauracao.py` aprovado na base do escritório | o JSON gerado |
| H5 | Extratos reais do piloto | OFX e CSV/XLSX reais carregam sem erro estrutural e o saldo final calculado bate com o do extrato | bancos e formatos, prints |

Condição de liberação: **H1 a H5 aprovados**. Enquanto isso, o app mostra aviso permanente e a conferência de
saldo sai marcada como “provisória”. Reprovação exige falha identificada e ação corretiva.

## 3. Testes automatizados

IDs começam com `test_aut_` (novos desta etapa) ou são anteriores (`test_lote_...`, `test_backup_...`).

| Área | Casos |
|---|---|
| Limite do histórico | faixa 40–250 e auditoria; histórico completo guardado; marca nunca cortada; mudar o limite não altera lote gerado |
| Duplicidade | arquivo idêntico (SHA-256); FITID; semelhança; marca já no Razão; movimento igual a lote anterior; conferência pós-importação detecta ausente, duplicado, valor e conta trocados |
| Alteração indevida | triggers do SQLite: origem do extrato, movimento exportado, lote aceito, lotes, itens, auditoria, originais, homologação; arquivo de lote adulterado (SHA-256) |
| Perda de informação | releitura do arquivo gerado (ida e volta) detecta linha perdida, valor, fim de linha; falha cancela o lote sem deixar arquivo; migração de banco antigo preserva dados |
| Razão | conferência marcada provisória até o H3 ser aprovado |
| Homologação | aprovação exige evidência, administrador e condições de cada item; reprovação exige falha e ação; histórico imutável; relatório de restauração sintético é recusado |
| Backup | restauração em pasta temporária; contagens, integrity_check e SHA-256 comparados; original corrompido reprova |

**Verificação por mutação** (feita à mão nesta etapa): desliguei uma proteção por vez no código e conferi que ao
menos um teste falha. Todas foram detectadas: duplicidade contra o Razão e contra lote anterior, contagem de
duplicados na conferência, corte do histórico, ida e volta, triggers de origem e de exportado, SHA-256 do lote,
condição do H1. Na primeira rodada um teste de duplicidade passou mesmo com a proteção desligada; foi reescrito.

## 4. Fora do escopo desta etapa

- Etapa B (clientes externos, HTTPS, recuperação de senha, teste de intrusão).
- Mudança do leiaute de importação conhecido: nada foi alterado nele.
- Qualquer resultado nos itens H1 a H5: nenhum foi executado.
