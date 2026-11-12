/************************************************************
 * DIOAC / PROEN / UFMA
 * AUTOMAÇÃO DE TRIAGEM, ATRIBUIÇÃO E ENCAMINHAMENTO DE E-MAILS
 *
 * TRIAGEM CONSOLIDADA: fluxo-triagem-email-dioac.md
 * MODO PADRÃO: SIMULAÇÃO (nada é enviado, encaminhado ou alterado)
 *
 * O QUE O SCRIPT FAZ:
 * 1. Classifica a última mensagem de cada conversa não lida.
 * 2. Mérito, anexo ou dado identificável -> auditoria técnica
 *    (marcador existente + rascunho; nunca resposta automática).
 * 3. Consulta procedimental simples -> marcador do responsável e
 *    confirmação automática de recebimento.
 * 4. Encaminhamento a outros setores: desativado até o piloto.
 * 5. Mensagem não reconhecida -> fica intacta no Gmail.
 * 6. Controle de duplicidade invisível (propriedades do script).
 *
 * NÃO utiliza Gemini nem IA externa.
 * NÃO cria marcadores.
 * NÃO usa o endereço do remetente para classificar.
 * NÃO registra remetente, assunto ou conteúdo nos logs.
 * ROBERTA NÃO participa da atribuição.
 * PROFA. KÁTIA NÃO recebe atribuição automática: atua no
 * escalonamento (pedido fora do prazo, situação não prevista nas
 * normas ou demanda fora das atribuições dos demais técnicos).
 ************************************************************/


/************************************************************
 * CONFIGURAÇÃO
 ************************************************************/

const CONFIG = Object.freeze({

  LIMITE_THREADS: 20,

  // true = simulação | false = execução real
  SIMULACAO_ONLY: true,

  // Confirmação automática: somente consulta procedimental simples.
  ENVIAR_CONFIRMACAO_SIMPLES: true,

  // Encaminhamento de conteúdo: desativado até validação do piloto.
  ENCAMINHAR_AUTOMATICAMENTE: false,

  // Casos de auditoria com responsável definido recebem rascunho.
  CRIAR_RASCUNHO_PARA_AUDITORIA: true,

  // Conversas sem ação entram no controle invisível (o Gmail não é
  // alterado). Evita que as mesmas conversas ocupem as vagas do
  // lote em toda execução.
  REGISTRAR_SEM_ACAO: true,

  // O controle guarda somente ID opaco da conversa e data.
  PRAZO_RETENCAO_CONTROLE_DIAS: 180,

  // Aviso preventivo: as propriedades do script têm limite de espaço.
  ALERTA_REGISTROS_CONTROLE: 5000,

  // Marcador antigo: usado só na migração inicial.
  LABEL_PROCESSADO_ANTIGO: 'DIOAC_PROCESSADO',

  // Marcador (já existente) para auditoria sem responsável definido.
  LABEL_EM_ANALISE: 'Em análise',

  PREFIXO_CONTROLE_INTERNO: 'DIOAC_PROCESSADO_THREAD_',
  PREFIXO_CONTROLE_RASCUNHO: 'DIOAC_RASCUNHO_AUDITORIA_',
  CHAVE_MIGRACAO: 'DIOAC_MIGRACAO_CONTROLE_INTERNO_V1',
  CHAVE_ULTIMA_LIMPEZA: 'DIOAC_ULTIMA_LIMPEZA_CONTROLE',

  EMAIL_DIOAC: 'dioac.proen@ufma.br',

  // CONFIRMAR: o código original usava dois nomes diferentes para a
  // diretoria. Mantido um só; ajuste aqui se o oficial for outro.
  ASSINATURA: 'Diretoria de Organização Acadêmica - DIOAC'
});


/************************************************************
 * MARCADORES COLORIDOS JÁ EXISTENTES NO GMAIL
 * (o script nunca cria marcadores)
 ************************************************************/

const MARCADORES_RESPONSAVEIS = {
  'Ana Paula': 'ANA PAULA',
  'Jorge Henrique': 'JORGE',
  'Kellen': 'KELLEN',
  'Keila': 'KEYLA',
  'José de Ribamar': 'RIBAMAR',
  'Francisco': 'FRANCISCO',
  'Alessandra Amorim': 'ALESSANDRA AMORIM',
  'Izabella': 'IZABELLA',
  'Mireya': 'MIREYA',
  'Willian Barbosa Filho': 'WILLIAN'
};


/************************************************************
 * REGRAS DE ATRIBUIÇÃO
 * Os mesmos termos valem para o assunto e para o corpo.
 * "corresponsavel" recebe também o seu marcador (atuação conjunta).
 ************************************************************/

function regraAtribuicao_(id, responsavel, prioridade, termos, corresponsavel) {
  return {
    id: id,
    responsavel: responsavel,
    corresponsavel: corresponsavel || null,
    prioridade: prioridade,
    assunto: termos,
    contexto: termos
  };
}

const REGRAS_ATRIBUICAO = [

  // Ana Paula: readmissão/retorno ao curso, codificação do segundo
  // ciclo e atualização de nome.
  regraAtribuicao_('READMISSAO', 'Ana Paula', 110,
    ['readmissao', 'retorno ao curso']),
  regraAtribuicao_('CODIFICACAO_SEGUNDO_CICLO', 'Ana Paula', 110,
    ['codificacao segundo ciclo', 'codificacao do segundo ciclo',
     'codificacao de segundo ciclo']),
  regraAtribuicao_('ATUALIZACAO_NOME', 'Ana Paula', 110,
    ['atualizacao do nome', 'atualizacao de nome']),

  // Mireya: transferência compulsória e andamento de processos
  // administrativos.
  regraAtribuicao_('TRANSFERENCIA_COMPULSORIA', 'Mireya', 109,
    ['transferencia compulsoria']),
  regraAtribuicao_('ANDAMENTO_PROCESSO', 'Mireya', 108,
    ['andamento do meu processo', 'andamento do processo',
     'andamento de meu processo', 'processo administrativo']),

  // Izabella: demandas judiciais. Com a Mireya nas demandas ligadas
  // à Ouvidoria e à Procuradoria Federal (as duas recebem marcador).
  // Esta regra vem antes de JUDICIAL: no empate, a primeira vence.
  regraAtribuicao_('OUVIDORIA_PROCURADORIA', 'Izabella', 107,
    ['ouvidoria', 'procuradoria federal'], 'Mireya'),
  regraAtribuicao_('JUDICIAL', 'Izabella', 107,
    ['demanda judicial', 'processo judicial', 'ordem judicial',
     'decisao judicial', 'determinacao judicial', 'mandado judicial',
     'oficio judicial']),

  // Alessandra Amorim: consultas e dados sobre cancelamento temporário.
  regraAtribuicao_('CANCELAMENTO_TEMPORARIO', 'Alessandra Amorim', 106,
    ['cancelamento temporario']),

  // Francisco: campi de Pinheiro, Chapadinha e Imperatriz.
  regraAtribuicao_('PINHEIRO', 'Francisco', 100, ['pinheiro']),
  regraAtribuicao_('CHAPADINHA', 'Francisco', 100, ['chapadinha']),
  regraAtribuicao_('IMPERATRIZ', 'Francisco', 100, ['imperatriz']),

  // Willian Barbosa Filho: campi de Balsas, Grajaú, Codó, Bacabal e
  // São Bernardo.
  regraAtribuicao_('BALSAS', 'Willian Barbosa Filho', 100, ['balsas']),
  regraAtribuicao_('GRAJAU', 'Willian Barbosa Filho', 100, ['grajau']),
  regraAtribuicao_('CODO', 'Willian Barbosa Filho', 100, ['codo']),
  regraAtribuicao_('BACABAL', 'Willian Barbosa Filho', 100, ['bacabal']),
  regraAtribuicao_('SAO_BERNARDO', 'Willian Barbosa Filho', 100,
    ['sao bernardo']),

  // Unidades acadêmicas do Campus São Luís.
  regraAtribuicao_('CCSO', 'Jorge Henrique', 90,
    ['ciencias sociais', 'ccso']),
  // "tecnologia" também cobre "tecnologias".
  regraAtribuicao_('CCET', 'Kellen', 90,
    ['ciencias exatas e tecnologia', 'ccet']),
  regraAtribuicao_('CCH', 'Keila', 90,
    ['ciencias humanas', 'cch']),
  regraAtribuicao_('CCBS', 'José de Ribamar', 90,
    ['ciencias da saude', 'ccbs']),

  // José de Ribamar: problemas relacionados ao SIGAA. Prioridade
  // menor para que campus e unidade prevaleçam; só termos de
  // problema, porque "SIGAA" sozinho aparece em quase toda consulta.
  regraAtribuicao_('SIGAA', 'José de Ribamar', 70,
    ['problema no sigaa', 'problemas no sigaa',
     'problema com o sigaa', 'problemas com o sigaa',
     'erro no sigaa', 'erro do sigaa', 'falha no sigaa',
     'nao consigo acessar o sigaa', 'acesso ao sigaa'])
];


/************************************************************
 * REGRAS DE ENCAMINHAMENTO PARA OUTROS SETORES
 ************************************************************/

const REGRAS_ENCAMINHAMENTO = [
  {
    setor: 'DIRED',
    email: 'dired.proen@ufma.br',
    termos: [
      'revalidacao de diploma', 'problema com registro de diploma',
      'registro de diploma', 'lista para colacao de grau',
      'declaracao de diploma estrangeiro'
    ]
  },
  {
    setor: 'AGETIC',
    email: 'sistemas.ti@ufma.br',
    termos: ['carteira de estudante', 'carteira estudante', 'carteirinha']
  },
  {
    setor: 'DIAC',
    email: 'diac.proen@ufma.br',
    termos: ['monitoria', 'consulta sobre monitoria']
  },
  {
    setor: 'DIAP',
    email: 'diap.proen@ufma.br',
    termos: [
      'estagio obrigatorio', 'estagio nao obrigatorio',
      'estagio curricular'
    ]
  },
  {
    setor: 'DIDEG',
    email: 'dideg.proen@ufma.br',
    termos: ['estrutura curricular', 'projeto pedagogico de curso', 'ppc']
  }
];


/************************************************************
 * MENSAGENS
 ************************************************************/

const MENSAGEM_RECEBIMENTO = [
  'Confirmamos o recebimento de sua consulta.',
  'O e-mail corporativo é destinado a consultas e orientações e não gera protocolo. Retornaremos o mais rápido possível.',
  'Solicitações que exijam formalização, análise de mérito ou alteração de situação acadêmica devem ser registradas pelo canal institucional adequado, como SEI, GLPI ou Atendimento PROEN no portal da UFMA.',
  'Atenciosamente,',
  CONFIG.ASSINATURA
].join('\n\n');

const MENSAGEM_RASCUNHO_AUDITORIA_DIOAC = [
  'Prezada(o),',
  'Acusamos o recebimento da solicitação. O caso depende de análise técnica e conferência nos registros oficiais pela unidade competente. Este retorno limita-se ao recebimento e não constitui decisão nem confirmação de informação acadêmica.',
  'A resposta conclusiva será preparada após a auditoria do técnico responsável e a validação por servidor autorizado.',
  'Atenciosamente,\n' + CONFIG.ASSINATURA
].join('\n\n');


/************************************************************
 * FUNÇÃO PRINCIPAL
 ************************************************************/

function processarDIOAC() {

  // Impede que duas execuções simultâneas respondam a mesma conversa.
  const trava = LockService.getScriptLock();

  if (!trava.tryLock(1000)) {
    Logger.log('Outra execução está em andamento. Encerrando.');
    return;
  }

  try {
    executarProcessamentoDIOAC_();
  } finally {
    trava.releaseLock();
  }
}

function executarProcessamentoDIOAC_() {

  CACHE_CONTROLE_DIOAC_ = null;

  Logger.log('==============================================');
  Logger.log('INÍCIO DO PROCESSAMENTO DIOAC');
  Logger.log('Modo simulação: ' + CONFIG.SIMULACAO_ONLY);
  Logger.log('Limite configurado: ' + CONFIG.LIMITE_THREADS);
  Logger.log('==============================================');

  // Manutenção não pode impedir a triagem: falha é só registrada.
  try {
    migrarControleAntigoDIOAC_();
    limparControleInternoAntigoDIOAC_();
  } catch (erro) {
    Logger.log(
      'Falha na manutenção do controle [' + nomeDoErroDIOAC_(erro) +
      ']. A triagem continua.'
    );
  }

  const threads = buscarThreadsPendentesDIOAC_(CONFIG.LIMITE_THREADS);

  Logger.log('Threads pendentes encontradas: ' + threads.length);

  const contagem = {};
  let erros = 0;

  for (let i = 0; i < threads.length; i++) {

    Logger.log('--- THREAD ' + (i + 1) + ' de ' + threads.length + ' ---');

    try {

      const resultado = processarThreadDIOAC_(threads[i]);
      const chave = typeof resultado === 'string'
        ? resultado
        : 'DESCONHECIDO';

      contagem[chave] = (contagem[chave] || 0) + 1;

    } catch (erro) {

      erros++;

      // Tipo do erro + ID opaco da conversa. A mensagem do erro não é
      // registrada porque pode conter endereço de e-mail.
      Logger.log(
        'Erro técnico [' + nomeDoErroDIOAC_(erro) + '] na conversa ' +
        idSeguroDaThreadDIOAC_(threads[i]) +
        '; conteúdo da mensagem não registrado.'
      );
    }
  }

  const rotulos = [
    ['ATRIBUIDA', 'Atribuídas'],
    ['ENCAMINHADA', 'Encaminhadas'],
    ['CONFIRMADA', 'Somente confirmação de recebimento'],
    ['AUDITORIA_TECNICA', 'Aguardando auditoria técnica'],
    ['SEM_ACAO', 'Sem ação automática'],
    ['IGNORADA', 'Ignoradas'],
    ['DESCONHECIDO', 'Resultado desconhecido']
  ];

  Logger.log('==============================================');
  Logger.log(
    CONFIG.SIMULACAO_ONLY
      ? 'RESUMO (SIMULAÇÃO: nada foi enviado nem alterado)'
      : 'RESUMO FINAL'
  );
  Logger.log('Threads analisadas nesta execução: ' + threads.length);

  rotulos.forEach(function(par) {
    Logger.log(par[1] + ': ' + (contagem[par[0]] || 0));
  });

  Logger.log('Erros: ' + erros);

  const registros = contarRegistrosDeControleDIOAC_();

  Logger.log('Registros no controle invisível: ' + registros);

  if (registros >= CONFIG.ALERTA_REGISTROS_CONTROLE) {
    Logger.log(
      'ATENÇÃO: o controle invisível está grande. As propriedades do ' +
      'script têm limite de espaço; reduza o prazo de retenção ou ' +
      'marque como lidas as conversas já resolvidas.'
    );
  }

  Logger.log('FIM DO PROCESSAMENTO');
  Logger.log('==============================================');
}

function nomeDoErroDIOAC_(erro) {
  return (erro && erro.name) ? String(erro.name) : 'Erro';
}

function idSeguroDaThreadDIOAC_(thread) {
  try {
    return thread.getId();
  } catch (e) {
    return '(id indisponível)';
  }
}


/************************************************************
 * BUSCA DE THREADS PENDENTES
 *
 * As conversas processadas continuam NÃO LIDAS, então a busca
 * percorre lotes e descarta as que já estão no controle interno.
 ************************************************************/

function buscarThreadsPendentesDIOAC_(limite) {

  const pendentes = [];
  const TAMANHO_LOTE = 50;
  const MAX_LOTES = 20;

  // Enquanto a migração não rodar (ela não roda em simulação), as
  // conversas com o marcador antigo já foram tratadas e ficam de fora.
  let consulta = 'in:inbox is:unread';

  if (GmailApp.getUserLabelByName(CONFIG.LABEL_PROCESSADO_ANTIGO)) {
    consulta += ' -label:' + CONFIG.LABEL_PROCESSADO_ANTIGO;
  }

  for (let lote = 0; lote < MAX_LOTES; lote++) {

    const threads = GmailApp.search(
      consulta,
      lote * TAMANHO_LOTE,
      TAMANHO_LOTE
    );

    if (!threads || threads.length === 0) break;

    for (let i = 0; i < threads.length; i++) {

      if (threadJaProcessadaDIOAC_(threads[i])) continue;

      pendentes.push(threads[i]);

      if (pendentes.length >= limite) return pendentes;
    }

    if (threads.length < TAMANHO_LOTE) break;
  }

  return pendentes;
}


/************************************************************
 * CONTROLE INTERNO INVISÍVEL
 *
 * As propriedades são lidas UMA vez por execução. Consultar uma
 * a uma custava até 1.000 chamadas por execução.
 ************************************************************/

let CACHE_CONTROLE_DIOAC_ = null;

function obterControleDIOAC_() {

  if (!CACHE_CONTROLE_DIOAC_) {
    CACHE_CONTROLE_DIOAC_ =
      PropertiesService.getScriptProperties().getProperties() || {};
  }

  return CACHE_CONTROLE_DIOAC_;
}

function existeNoControleDIOAC_(chave) {
  return Object.prototype.hasOwnProperty.call(
    obterControleDIOAC_(),
    chave
  );
}

function gravarNoControleDIOAC_(chave) {

  const valor = new Date().toISOString();

  PropertiesService.getScriptProperties().setProperty(chave, valor);
  obterControleDIOAC_()[chave] = valor;
}

function threadJaProcessadaDIOAC_(thread) {
  return existeNoControleDIOAC_(
    CONFIG.PREFIXO_CONTROLE_INTERNO + thread.getId()
  );
}

function registrarProcessamentoInternoDIOAC_(thread) {
  gravarNoControleDIOAC_(
    CONFIG.PREFIXO_CONTROLE_INTERNO + thread.getId()
  );
}

function contarRegistrosDeControleDIOAC_() {

  return Object.keys(obterControleDIOAC_()).filter(function(chave) {
    return (
      chave.indexOf(CONFIG.PREFIXO_CONTROLE_INTERNO) === 0 ||
      chave.indexOf(CONFIG.PREFIXO_CONTROLE_RASCUNHO) === 0
    );
  }).length;
}


/************************************************************
 * MIGRAÇÃO DO MARCADOR ANTIGO (uma única vez)
 ************************************************************/

function migrarControleAntigoDIOAC_() {

  if (CONFIG.SIMULACAO_ONLY) {
    Logger.log('Simulação: migração do marcador antigo não executada.');
    return;
  }

  const propriedades = PropertiesService.getScriptProperties();

  if (obterControleDIOAC_()[CONFIG.CHAVE_MIGRACAO] === 'OK') return;

  const labelAntigo = GmailApp.getUserLabelByName(
    CONFIG.LABEL_PROCESSADO_ANTIGO
  );

  if (!labelAntigo) {
    propriedades.setProperty(CONFIG.CHAVE_MIGRACAO, 'OK');
    obterControleDIOAC_()[CONFIG.CHAVE_MIGRACAO] = 'OK';
    Logger.log('Migração: marcador antigo não encontrado.');
    return;
  }

  // Limite de lotes: evita laço sem fim se a remoção do marcador
  // demorar a aparecer. O que sobrar é retomado na próxima execução.
  const MAX_LOTES = 30;
  let quantidade = 0;
  let concluida = false;

  for (let lote = 0; lote < MAX_LOTES; lote++) {

    const threads = labelAntigo.getThreads(0, 100);

    if (!threads || threads.length === 0) {
      concluida = true;
      break;
    }

    const agora = new Date().toISOString();
    const novos = {};

    threads.forEach(function(thread) {
      novos[CONFIG.PREFIXO_CONTROLE_INTERNO + thread.getId()] = agora;
    });

    // Grava o lote inteiro de uma vez e só depois remove o marcador.
    propriedades.setProperties(novos, false);

    Object.keys(novos).forEach(function(chave) {
      obterControleDIOAC_()[chave] = agora;
    });

    labelAntigo.removeFromThreads(threads);

    quantidade += threads.length;
  }

  if (concluida) {
    propriedades.setProperty(CONFIG.CHAVE_MIGRACAO, 'OK');
    obterControleDIOAC_()[CONFIG.CHAVE_MIGRACAO] = 'OK';
  }

  Logger.log(
    'Migração ' + (concluida ? 'concluída' : 'parcial (continua na ' +
    'próxima execução)') + '. Conversas migradas agora: ' + quantidade
  );
}


/************************************************************
 * LIMPEZA DO CONTROLE (no máximo uma vez por dia)
 ************************************************************/

function limparControleInternoAntigoDIOAC_() {

  if (CONFIG.SIMULACAO_ONLY) {
    Logger.log('Simulação: limpeza do controle interno não executada.');
    return;
  }

  const UM_DIA = 24 * 60 * 60 * 1000;
  const props = PropertiesService.getScriptProperties();
  const valores = obterControleDIOAC_();

  const ultima = Date.parse(valores[CONFIG.CHAVE_ULTIMA_LIMPEZA]);

  if (Number.isFinite(ultima) && Date.now() - ultima < UM_DIA) return;

  const prefixos = [
    CONFIG.PREFIXO_CONTROLE_INTERNO,
    CONFIG.PREFIXO_CONTROLE_RASCUNHO
  ];

  const limite =
    Date.now() - CONFIG.PRAZO_RETENCAO_CONTROLE_DIAS * UM_DIA;

  let removidas = 0;

  Object.keys(valores).forEach(function(chave) {

    const prefixo = prefixos.find(function(candidato) {
      return chave.indexOf(candidato) === 0;
    });

    if (!prefixo) return;

    const instante = Date.parse(valores[chave]);

    if (Number.isFinite(instante) && instante >= limite) return;

    // Conversa ainda não lida: o registro é conservado para evitar
    // reprocessamento e resposta duplicada. Conversa apagada ou
    // inacessível: o registro pode sair.
    let thread = null;

    try {
      thread = GmailApp.getThreadById(chave.substring(prefixo.length));
    } catch (e) {
      thread = null;
    }

    if (thread && thread.isUnread()) return;

    props.deleteProperty(chave);
    delete valores[chave];
    removidas++;
  });

  gravarNoControleDIOAC_(CONFIG.CHAVE_ULTIMA_LIMPEZA);

  Logger.log('Registros antigos de controle removidos: ' + removidas);
}


/************************************************************
 * TRIAGEM
 *
 * Verificações de segurança (mérito, pedido de ato, dado pessoal)
 * olham o texto INTEIRO, inclusive o histórico citado.
 * Gatilhos de ação (consulta procedimental) olham só o texto NOVO,
 * para que a pergunta antiga citada num "obrigado" não dispare
 * outra confirmação.
 ************************************************************/

function classificarFluxoTriagemDIOAC_(
  assuntoOriginal,
  corpoOriginal,
  temAnexo
) {

  const assunto = normalizarTexto_(assuntoOriginal);
  const textoCompleto =
    (assunto + ' ' + normalizarTexto_(corpoOriginal)).trim();
  const textoNovo = (
    assunto + ' ' +
    normalizarTexto_(removerCitacaoDIOAC_(corpoOriginal))
  ).trim();

  const temasDeMerito = [
    'veracidade documental', 'autenticidade documental', 'diploma',
    'historico escolar', 'alteracao de historico', 'vinculo academico',
    'decisao liminar', 'ordem judicial', 'mandado judicial',
    'transferencia compulsoria', 'readmissao',
    'desligamento', 'mudanca de vinculo',
    'fora do prazo', 'pedido extemporaneo',
    'alteracao de plano de estudos',
    'demanda judicial', 'processo judicial', 'ouvidoria', 'procuradoria'
  ];

  const termosDeAtoAcademico = [
    'solicito matricula', 'solicito cancelamento',
    'efetuar matricula', 'alterar minha matricula',
    'cancelar minha disciplina', 'corrigir meu historico',
    'alterar meu vinculo', 'regularizar minha situacao'
  ];

  const termosDeConsulta = [
    'como faco', 'como realizar', 'como solicitar',
    'orientacao sobre', 'duvida sobre', 'duvidas sobre', 'passo a passo',
    'quais documentos', 'prazo para inscricao',
    'como consultar no sigaa',
    'consulta sobre monitoria', 'orientacao sobre monitoria',
    'carteira de estudante', 'carteirinha',
    'estagio obrigatorio', 'estagio nao obrigatorio',
    'estagio curricular', 'estrutura curricular',
    'projeto pedagogico de curso', 'ppc'
  ];

  const dadoIdentificavel = detectarDadoPessoalDIOAC_(textoCompleto);

  if (
    contemAlgumTermo_(textoCompleto, temasDeMerito) ||
    contemAlgumTermo_(textoCompleto, termosDeAtoAcademico) ||
    temAnexo ||
    dadoIdentificavel
  ) {
    return {
      classe: 'AUDITORIA_TECNICA',
      requerAuditoria: true,
      dadoIdentificavel: dadoIdentificavel,
      temAnexo: Boolean(temAnexo),
      respostaAutomaticaPermitida: false
    };
  }

  if (contemAlgumTermo_(textoNovo, termosDeConsulta)) {
    return {
      classe: 'CONSULTA_PROCEDIMENTAL',
      requerAuditoria: false,
      dadoIdentificavel: false,
      temAnexo: false,
      respostaAutomaticaPermitida: true
    };
  }

  return {
    classe: 'REVISAO_MANUAL',
    requerAuditoria: true,
    dadoIdentificavel: false,
    temAnexo: false,
    respostaAutomaticaPermitida: false
  };
}

/*
 * Critério conservador: na dúvida, trata como dado identificável.
 * - CPF, com ou sem pontuação;
 * - palavra-chave (matrícula, CPF, RG...) seguida de número com 5+
 *   dígitos a até 25 caracteres ("minha matrícula é 2026123456");
 *   o mínimo de 5 dígitos evita confundir com "matrícula 2026.1";
 * - qualquer sequência de 9+ dígitos (matrícula, CPF, telefone).
 */
function detectarDadoPessoalDIOAC_(texto) {

  const conteudo = String(texto || '');

  const cpf = /\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b/;
  const identificador =
    /\b(?:matr[ií]cula|cpf|rg|passaporte|n[uú]mero de documento)\b\D{0,25}\d{5,}/i;
  const numeroLongo = /\b\d{9,}\b/;

  return (
    cpf.test(conteudo) ||
    identificador.test(conteudo) ||
    numeroLongo.test(conteudo)
  );
}

/*
 * Remove o histórico citado em respostas: linhas iniciadas por ">" e
 * tudo o que vem depois do cabeçalho de citação.
 */
function removerCitacaoDIOAC_(corpo) {

  const linhas = String(corpo || '').split(/\r?\n/);
  const novas = [];

  const inicioDeCitacao =
    /^\s*(?:em .{0,200}escreveu:|on .{0,200}wrote:|-{2,}\s*(?:mensagem original|original message)\s*-{2,})\s*$/i;

  for (let i = 0; i < linhas.length; i++) {

    if (inicioDeCitacao.test(linhas[i])) break;

    if (/^\s*>/.test(linhas[i])) continue;

    novas.push(linhas[i]);
  }

  return novas.join('\n');
}


/************************************************************
 * DECISÃO (função pura: não toca no Gmail)
 *
 * Devolve o plano de ação. A simulação e a execução real usam o
 * mesmo plano, então a simulação mostra o que de fato aconteceria.
 ************************************************************/

function decidirAcaoDIOAC_(
  triagem,
  atribuicao,
  encaminhamento,
  jaRespondidaPelaDIOAC
) {

  const plano = {
    resultado: 'SEM_ACAO',
    marcadores: [],
    marcadorSetor: null,
    rascunho: false,
    encaminharPara: null,
    confirmar: false
  };

  // Responsável e, se houver, corresponsável (atuação conjunta).
  const marcadoresResponsaveis = atribuicao
    ? [atribuicao.responsavel, atribuicao.corresponsavel]
        .filter(Boolean)
        .map(function(nome) { return MARCADORES_RESPONSAVEIS[nome]; })
        .filter(Boolean)
    : [];

  // Mérito, anexo ou dado identificável: sempre auditoria.
  // Demanda não reconhecida, mas com responsável definido: também.
  if (
    triagem.classe === 'AUDITORIA_TECNICA' ||
    (triagem.classe === 'REVISAO_MANUAL' && atribuicao)
  ) {

    plano.resultado = 'AUDITORIA_TECNICA';
    plano.marcadores = atribuicao
      ? marcadoresResponsaveis
      : [CONFIG.LABEL_EM_ANALISE];
    plano.rascunho = Boolean(
      atribuicao &&
      CONFIG.CRIAR_RASCUNHO_PARA_AUDITORIA &&
      !jaRespondidaPelaDIOAC
    );

    return plano;
  }

  if (triagem.classe === 'CONSULTA_PROCEDIMENTAL') {

    plano.marcadores = marcadoresResponsaveis;

    if (encaminhamento && CONFIG.ENCAMINHAR_AUTOMATICAMENTE) {
      plano.encaminharPara = encaminhamento.email;
      plano.marcadorSetor = encaminhamento.setor;
    }

    // Conversa que a DIOAC já respondeu está em atendimento humano:
    // não recebe nova confirmação automática.
    plano.confirmar = Boolean(
      CONFIG.ENVIAR_CONFIRMACAO_SIMPLES &&
      triagem.respostaAutomaticaPermitida &&
      !jaRespondidaPelaDIOAC
    );

    if (plano.encaminharPara) {
      plano.resultado = 'ENCAMINHADA';
    } else if (atribuicao) {
      plano.resultado = 'ATRIBUIDA';
    } else if (plano.confirmar) {
      plano.resultado = 'CONFIRMADA';
    }

    return plano;
  }

  // Demanda não reconhecida e sem responsável: permanece intacta.
  return plano;
}


/************************************************************
 * PROCESSAMENTO DA THREAD
 ************************************************************/

function processarThreadDIOAC_(thread) {

  if (threadJaProcessadaDIOAC_(thread)) return 'IGNORADA';

  const mensagens = thread.getMessages();

  if (!mensagens || mensagens.length === 0) return 'IGNORADA';

  const mensagem = mensagens[mensagens.length - 1];
  const remetente = mensagem.getFrom() || '';
  const assuntoOriginal = mensagem.getSubject() || '';
  const corpoOriginal = mensagem.getPlainBody() || '';

  // Não registra conteúdo, remetente ou assunto nos logs.

  if (
    ehMensagemAutomatica_(remetente, mensagem) ||
    ehMensagemDaDIOAC_(remetente)
  ) {
    if (!CONFIG.SIMULACAO_ONLY) {
      registrarProcessamentoInternoDIOAC_(thread);
    }
    return 'IGNORADA';
  }

  const jaRespondidaPelaDIOAC = mensagens.some(function(m) {
    return ehMensagemDaDIOAC_(m.getFrom() || '');
  });

  const assunto = normalizarTexto_(assuntoOriginal);
  const corpoNovo = normalizarTexto_(removerCitacaoDIOAC_(corpoOriginal));
  const nomeRemetente =
    normalizarTexto_(extrairNomeRemetente_(remetente));

  const anexos = mensagem.getAttachments({
    includeInlineImages: false,
    includeAttachments: true
  }) || [];

  const triagem = classificarFluxoTriagemDIOAC_(
    assuntoOriginal,
    corpoOriginal,
    anexos.length > 0
  );

  const encaminhamento = identificarEncaminhamento_(assunto, corpoNovo);
  const atribuicao =
    identificarAtribuicao_(assunto, corpoNovo, nomeRemetente);

  const plano = decidirAcaoDIOAC_(
    triagem,
    atribuicao,
    encaminhamento,
    jaRespondidaPelaDIOAC
  );

  Logger.log('Classe da triagem: ' + triagem.classe);
  Logger.log(
    'Regra de atribuição: ' + (atribuicao ? atribuicao.id : 'nenhuma')
  );
  Logger.log(
    'Regra de encaminhamento: ' +
    (encaminhamento ? encaminhamento.setor : 'nenhuma')
  );
  Logger.log(
    'Plano: ' + plano.resultado +
    ' | marcadores: ' + plano.marcadores.length +
    ' | rascunho: ' + (plano.rascunho ? 'sim' : 'não') +
    ' | encaminhar: ' + (plano.encaminharPara ? 'sim' : 'não') +
    ' | confirmar: ' + (plano.confirmar ? 'sim' : 'não')
  );

  if (atribuicao && !MARCADORES_RESPONSAVEIS[atribuicao.responsavel]) {
    Logger.log(
      'AVISO: responsável da regra ' + atribuicao.id +
      ' não tem marcador configurado.'
    );
  }

  if (CONFIG.SIMULACAO_ONLY) {
    Logger.log('Simulação: plano não executado.');
    return plano.resultado;
  }

  executarPlanoDIOAC_(thread, mensagem, assuntoOriginal, plano);

  return plano.resultado;
}

function executarPlanoDIOAC_(thread, mensagem, assuntoOriginal, plano) {

  // Sem ação: o Gmail não é tocado. Só o controle invisível.
  if (plano.resultado === 'SEM_ACAO') {
    if (CONFIG.REGISTRAR_SEM_ACAO) {
      registrarProcessamentoInternoDIOAC_(thread);
    }
    return;
  }

  plano.marcadores.forEach(function(nomeMarcador) {
    if (!adicionarMarcadorExistenteDIOAC_(thread, nomeMarcador)) {
      Logger.log('AVISO: um marcador previsto não existe no Gmail.');
    }
  });

  if (plano.encaminharPara) {
    mensagem.forward(plano.encaminharPara, {
      subject: '[DIOAC - Encaminhamento] ' + assuntoOriginal
    });
  }

  // Registrado ANTES do rascunho e da confirmação: se um deles falhar,
  // a conversa não volta à fila e nada é enviado em duplicidade.
  registrarProcessamentoInternoDIOAC_(thread);

  if (plano.marcadorSetor) {
    adicionarMarcadorExistenteDIOAC_(thread, plano.marcadorSetor);
  }

  if (plano.rascunho) {
    criarRascunhoAuditoriaDIOAC_(thread);
  }

  if (plano.confirmar) {
    thread.reply(MENSAGEM_RECEBIMENTO);
  }

  thread.markUnread();
}

function adicionarMarcadorExistenteDIOAC_(thread, nomeMarcador) {

  if (!nomeMarcador) return false;

  const label = GmailApp.getUserLabelByName(nomeMarcador);

  if (!label) return false;

  thread.addLabel(label);

  return true;
}

function criarRascunhoAuditoriaDIOAC_(thread) {

  const chave = CONFIG.PREFIXO_CONTROLE_RASCUNHO + thread.getId();

  if (existeNoControleDIOAC_(chave)) return false;

  // Rascunho simples, sem citar dados do titular e sem anexos.
  thread.createDraftReply(MENSAGEM_RASCUNHO_AUDITORIA_DIOAC);

  gravarNoControleDIOAC_(chave);

  return true;
}


/************************************************************
 * IDENTIFICA ENCAMINHAMENTO
 * Primeiro o assunto; só depois o corpo. Conflito -> nenhum.
 ************************************************************/

function identificarEncaminhamento_(assunto, corpo) {

  const textos = [assunto, corpo];

  for (let t = 0; t < textos.length; t++) {

    const encontradas = REGRAS_ENCAMINHAMENTO.filter(function(regra) {
      return contemAlgumTermo_(textos[t], regra.termos);
    });

    if (encontradas.length === 1) return encontradas[0];

    if (encontradas.length > 1) {
      Logger.log(
        'CONFLITO DE ENCAMINHAMENTO NO ' +
        (t === 0 ? 'ASSUNTO.' : 'CORPO.')
      );
      return null;
    }
  }

  return null;
}


/************************************************************
 * IDENTIFICA ATRIBUIÇÃO
 * Ordem: assunto -> unidade pelo nome do remetente -> corpo.
 ************************************************************/

function identificarAtribuicao_(assunto, corpo, remetenteNome) {

  const porAssunto = escolherRegraDeAtribuicao_(assunto, 'assunto');

  if (porAssunto.conflito) {
    Logger.log('CONFLITO NO ASSUNTO.');
    return null;
  }

  if (porAssunto.regra) return porAssunto.regra;

  const unidade = identificarUnidadePorRemetente_(remetenteNome);

  if (unidade) return unidade;

  const porCorpo = escolherRegraDeAtribuicao_(corpo, 'contexto');

  if (porCorpo.conflito) {
    Logger.log('CONFLITO NO CORPO.');
    return null;
  }

  return porCorpo.regra;
}

/*
 * Vence a maior prioridade. Empate entre responsáveis diferentes é
 * conflito e não gera atribuição.
 */
function escolherRegraDeAtribuicao_(texto, campo) {

  const candidatas = REGRAS_ATRIBUICAO.filter(function(regra) {
    return contemAlgumTermo_(texto, regra[campo]);
  });

  if (candidatas.length === 0) {
    return { regra: null, conflito: false };
  }

  const maior = Math.max.apply(null, candidatas.map(function(regra) {
    return regra.prioridade;
  }));

  const melhores = candidatas.filter(function(regra) {
    return regra.prioridade === maior;
  });

  if (obterResponsaveisUnicos_(melhores).length > 1) {
    return { regra: null, conflito: true };
  }

  return { regra: melhores[0], conflito: false };
}

function identificarUnidadePorRemetente_(remetenteNome) {

  const texto = normalizarTexto_(remetenteNome);

  const unidades = [
    ['CCSO', ['ciencias sociais', 'ccso']],
    ['CCET', ['ciencias exatas e tecnologia', 'ccet']],
    ['CCH', ['ciencias humanas', 'cch']],
    ['CCBS', ['ciencias da saude', 'ccbs']]
  ];

  for (let i = 0; i < unidades.length; i++) {
    if (contemAlgumTermo_(texto, unidades[i][1])) {
      return obterRegraPorId_(unidades[i][0]);
    }
  }

  return null;
}

function obterRegraPorId_(id) {

  for (let i = 0; i < REGRAS_ATRIBUICAO.length; i++) {
    if (REGRAS_ATRIBUICAO[i].id === id) return REGRAS_ATRIBUICAO[i];
  }

  return null;
}

function obterResponsaveisUnicos_(regras) {

  const responsaveis = [];

  (regras || []).forEach(function(regra) {
    if (
      regra.responsavel &&
      responsaveis.indexOf(regra.responsavel) === -1
    ) {
      responsaveis.push(regra.responsavel);
    }
  });

  return responsaveis;
}


/************************************************************
 * UTILITÁRIOS DE TEXTO
 ************************************************************/

function normalizarTexto_(texto) {

  return String(texto || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function contemAlgumTermo_(texto, termos) {

  if (!texto || !termos || termos.length === 0) return false;

  for (let i = 0; i < termos.length; i++) {

    const termo = normalizarTexto_(termos[i]);

    if (termo && contemTermoNoInicioDePalavra_(texto, termo)) return true;
  }

  return false;
}

/*
 * O termo precisa começar no início de uma palavra: "cch" casa com
 * "cch" e "/cch", mas não com "bacchus". O fim fica livre para aceitar
 * plurais ("diploma" casa com "diplomas").
 */
function contemTermoNoInicioDePalavra_(texto, termo) {

  let posicao = texto.indexOf(termo);

  while (posicao !== -1) {

    if (posicao === 0 || !/[a-z0-9]/.test(texto.charAt(posicao - 1))) {
      return true;
    }

    posicao = texto.indexOf(termo, posicao + 1);
  }

  return false;
}

/*
 * Devolve só o nome de apresentação. Quando o remetente vem sem nome
 * (apenas o endereço), devolve vazio: o endereço de e-mail nunca é
 * usado para classificar.
 */
function extrairNomeRemetente_(remetente) {

  const texto = String(remetente || '');
  const posicao = texto.indexOf('<');

  if (posicao !== -1) {
    return texto.substring(0, posicao).replace(/"/g, '').trim();
  }

  if (texto.indexOf('@') !== -1) return '';

  return texto.replace(/"/g, '').trim();
}


/************************************************************
 * MENSAGENS AUTOMÁTICAS E DA PRÓPRIA DIOAC
 ************************************************************/

function ehMensagemAutomatica_(remetente, mensagem) {

  const texto = String(remetente || '').toLowerCase();

  const indicadores = [
    'mailer-daemon', 'postmaster',
    'no-reply', 'noreply', 'no_reply',
    'do-not-reply', 'donotreply',
    'nao-responda', 'naoresponda', 'nao_responda',
    'calendar-notification', 'notifications@', 'notification@'
  ];

  for (let i = 0; i < indicadores.length; i++) {
    if (texto.indexOf(indicadores[i]) !== -1) return true;
  }

  // Cabeçalhos de resposta automática (ex.: aviso de férias). Sem
  // isto, dois respondedores automáticos podem ficar se respondendo.
  if (mensagem && typeof mensagem.getHeader === 'function') {

    try {

      const auto = String(
        mensagem.getHeader('Auto-Submitted') || ''
      ).toLowerCase().trim();

      if (auto && auto !== 'no') return true;

      const precedencia = String(
        mensagem.getHeader('Precedence') || ''
      ).toLowerCase().trim();

      if (/^(bulk|junk|auto_reply)$/.test(precedencia)) return true;

      if (
        mensagem.getHeader('X-Autoreply') ||
        mensagem.getHeader('X-Autorespond')
      ) {
        return true;
      }

    } catch (e) {
      // Cabeçalho indisponível: segue só com a regra do remetente.
    }
  }

  return false;
}

function ehMensagemDaDIOAC_(remetente) {

  const texto = String(remetente || '').toLowerCase();

  return Boolean(
    CONFIG.EMAIL_DIOAC &&
    texto.indexOf(CONFIG.EMAIL_DIOAC.toLowerCase()) !== -1
  );
}


/************************************************************
 * TESTES (nenhum deles envia e-mail ou altera o Gmail)
 ************************************************************/

/*
 * Casos críticos de atribuição. Remetentes fictícios: não manter
 * nome ou e-mail de pessoas reais no código.
 */
function testarCasosCriticosDIOAC() {

  const casos = [
    {
      numero: 1,
      assunto: 'Re: Solicitação de readmissão',
      remetente: 'Discente Fictício <discente1@exemplo.invalid>',
      corpo: 'Aluno do curso de Enfermagem.',
      esperado: 'ATRIBUIR:READMISSAO'
    },
    {
      numero: 2,
      assunto:
        'ORIENTAÇÃO SOBRE INSCRIÇÃO EM COMPONENTE CURRICULAR FORA DO PRAZO',
      remetente:
        'COORDENAÇÃO DO CURSO DE CIÊNCIAS SOCIAIS - BACHARELADO ' +
        'CCCSB/CCH <coordenacao@exemplo.invalid>',
      corpo: '',
      esperado: 'ATRIBUIR:CCSO'
    },
    {
      numero: 3,
      assunto:
        'Dúvidas sobre vaga remanescente de Enfermagem em Imperatriz ' +
        'e Transferência Interna',
      remetente: 'Discente Fictício <discente3@exemplo.invalid>',
      corpo: '',
      esperado: 'ATRIBUIR:IMPERATRIZ'
    },
    {
      numero: 4,
      assunto: 'Saber o andamento do meu processo.',
      remetente: 'Discente Fictício <discente4@exemplo.invalid>',
      corpo: '',
      esperado: 'ATRIBUIR:ANDAMENTO_PROCESSO'
    },
    {
      numero: 5,
      assunto: 'Processamento de matricula',
      remetente: 'Discente Fictício <discente5@exemplo.invalid>',
      corpo: '',
      esperado: 'SEM_ACAO'
    },
    {
      numero: 6,
      assunto: 'Informações',
      remetente: 'ccso@exemplo.invalid',
      corpo: '',
      esperado: 'SEM_ACAO'
    },
    {
      numero: 7,
      assunto: 'Codificação do segundo ciclo',
      remetente: 'Discente Fictício <discente7@exemplo.invalid>',
      corpo: '',
      esperado: 'ATRIBUIR:CODIFICACAO_SEGUNDO_CICLO'
    },
    {
      numero: 8,
      assunto: 'Manifestação da Ouvidoria',
      remetente: 'Setor Fictício <setor@exemplo.invalid>',
      corpo: '',
      esperado: 'ATRIBUIR:OUVIDORIA_PROCURADORIA+Mireya'
    },
    {
      numero: 9,
      assunto: 'Curso de Ciências Exatas e Tecnologia',
      remetente: 'Discente Fictício <discente9@exemplo.invalid>',
      corpo: '',
      esperado: 'ATRIBUIR:CCET'
    },
    {
      numero: 10,
      assunto: 'Dúvida do CCH',
      remetente: 'Discente Fictício <discente10@exemplo.invalid>',
      corpo: '',
      esperado: 'ATRIBUIR:CCH'
    },
    {
      numero: 11,
      assunto: 'Problema no SIGAA',
      remetente: 'Discente Fictício <discente11@exemplo.invalid>',
      corpo: '',
      esperado: 'ATRIBUIR:SIGAA'
    },
    {
      numero: 12,
      assunto: 'Vagas remanescentes',
      remetente: 'Discente Fictício <discente12@exemplo.invalid>',
      corpo: '',
      esperado: 'SEM_ACAO'
    }
  ];

  let falhas = 0;

  casos.forEach(function(caso) {

    const assunto = normalizarTexto_(caso.assunto);
    const corpo = normalizarTexto_(caso.corpo);
    const nome = normalizarTexto_(extrairNomeRemetente_(caso.remetente));

    const encaminhamento = identificarEncaminhamento_(assunto, corpo);
    const atribuicao = identificarAtribuicao_(assunto, corpo, nome);

    let obtido = 'SEM_ACAO';

    if (encaminhamento) {
      obtido = 'ENCAMINHAR:' + encaminhamento.setor;
    } else if (atribuicao) {
      obtido = 'ATRIBUIR:' + atribuicao.id +
        (atribuicao.corresponsavel ? '+' + atribuicao.corresponsavel : '');
    }

    const aprovado = obtido === caso.esperado;

    if (!aprovado) falhas++;

    Logger.log(
      (aprovado ? 'OK ' : 'FALHA ') + 'caso ' + caso.numero +
      ' | esperado: ' + caso.esperado + ' | obtido: ' + obtido
    );
  });

  if (falhas > 0) {
    throw new Error(falhas + ' caso(s) crítico(s) falharam.');
  }

  Logger.log('Todos os casos críticos passaram.');
}

function testarFluxoTriagemEmailDIOAC() {

  const casos = [
    {
      nome: 'consulta procedimental sem dados',
      assunto: 'Como consultar no SIGAA?',
      corpo: 'Qual o passo a passo para consultar minhas turmas?',
      anexo: false,
      esperado: 'CONSULTA_PROCEDIMENTAL'
    },
    {
      nome: 'validação documental',
      assunto: 'Solicitação de veracidade documental do diploma',
      corpo: 'Solicitamos confirmação de autenticidade.',
      anexo: true,
      esperado: 'AUDITORIA_TECNICA'
    },
    {
      nome: 'identificador acadêmico',
      assunto: 'Consulta de matrícula',
      corpo: 'Matrícula: 2026123456',
      anexo: false,
      esperado: 'AUDITORIA_TECNICA'
    },
    {
      nome: 'identificador em frase corrida',
      assunto: 'Dúvida sobre estágio obrigatório',
      corpo: 'Minha matrícula é 2026123456.',
      anexo: false,
      esperado: 'AUDITORIA_TECNICA'
    },
    {
      nome: 'período letivo não é dado pessoal',
      assunto: 'Dúvida sobre prazo de matrícula 2026.1',
      corpo: 'Como faço para saber o calendário?',
      anexo: false,
      esperado: 'CONSULTA_PROCEDIMENTAL'
    },
    {
      nome: 'agradecimento com pergunta antiga citada',
      assunto: 'Re: Informações',
      corpo: 'Obrigado!\n\n> Como faço para consultar minhas turmas?',
      anexo: false,
      esperado: 'REVISAO_MANUAL'
    },
    {
      nome: 'dado pessoal apenas no histórico citado',
      assunto: 'Re: Dúvida sobre monitoria',
      corpo: 'Como faço?\n\n> CPF 123.456.789-00',
      anexo: false,
      esperado: 'AUDITORIA_TECNICA'
    },
    {
      nome: 'demanda não reconhecida',
      assunto: 'Informações',
      corpo: 'Gostaria de tratar de um assunto acadêmico.',
      anexo: false,
      esperado: 'REVISAO_MANUAL'
    }
  ];

  const resultados = casos.map(function(caso) {

    const obtido = classificarFluxoTriagemDIOAC_(
      caso.assunto,
      caso.corpo,
      caso.anexo
    ).classe;

    return {
      caso: caso.nome,
      esperado: caso.esperado,
      obtido: obtido,
      aprovado: obtido === caso.esperado
    };
  });

  resultados.forEach(function(resultado) {
    Logger.log(
      (resultado.aprovado ? 'OK ' : 'FALHA ') + resultado.caso +
      ' | esperado: ' + resultado.esperado +
      ' | obtido: ' + resultado.obtido
    );
  });

  if (resultados.some(function(r) { return !r.aprovado; })) {
    throw new Error('Um ou mais casos do fluxo de triagem falharam.');
  }

  Logger.log('Todos os casos do fluxo de triagem passaram.');

  return resultados;
}

function testarEncaminhamentosDIOAC() {

  const exemplos = [
    'Solicitação de revalidação de diploma',
    'Problema com registro de diploma',
    'Registro de diploma',
    'Lista para colação de grau',
    'Declaração de diploma estrangeiro',
    'Carteira de estudante',
    'Carteirinha',
    'Consulta sobre monitoria',
    'Estágio obrigatório',
    'Estágio não obrigatório',
    'Estágio curricular',
    'Estrutura curricular',
    'Projeto pedagógico de curso',
    'PPC',
    'Processamento de matrícula'
  ];

  exemplos.forEach(function(exemplo) {

    const regra =
      identificarEncaminhamento_(normalizarTexto_(exemplo), '');

    Logger.log(
      exemplo + ' → ' +
      (regra ? regra.setor + ' → ' + regra.email : 'NÃO ENCAMINHAR')
    );
  });
}

/*
 * Confere se os marcadores usados pelo script existem no Gmail.
 * Só leitura.
 */
function testarMarcadoresDIOAC() {

  let ausentes = 0;

  Object.keys(MARCADORES_RESPONSAVEIS).forEach(function(responsavel) {

    const nomeMarcador = MARCADORES_RESPONSAVEIS[responsavel];
    const existe = Boolean(GmailApp.getUserLabelByName(nomeMarcador));

    if (!existe) ausentes++;

    Logger.log(
      (existe ? 'OK → ' : 'NÃO ENCONTRADO → ') +
      responsavel + ' → ' + nomeMarcador
    );
  });

  const emAnalise =
    Boolean(GmailApp.getUserLabelByName(CONFIG.LABEL_EM_ANALISE));

  if (!emAnalise) ausentes++;

  Logger.log(
    (emAnalise ? 'OK → ' : 'NÃO ENCONTRADO → ') + CONFIG.LABEL_EM_ANALISE
  );

  // Toda regra precisa apontar para um responsável com marcador.
  REGRAS_ATRIBUICAO.forEach(function(regra) {
    [regra.responsavel, regra.corresponsavel].forEach(function(nome) {
      if (nome && !MARCADORES_RESPONSAVEIS[nome]) {
        ausentes++;
        Logger.log('SEM MARCADOR CONFIGURADO → regra ' + regra.id);
      }
    });
  });

  Logger.log('Marcadores ausentes: ' + ausentes);

  return ausentes;
}

/*
 * Mostra a configuração em vigor e aponta combinações arriscadas.
 */
function verificarSegurancaDIOAC() {

  Logger.log('Modo simulação: ' + CONFIG.SIMULACAO_ONLY);
  Logger.log(
    'Confirmação automática (só consulta simples): ' +
    CONFIG.ENVIAR_CONFIRMACAO_SIMPLES
  );
  Logger.log(
    'Encaminhamento automático: ' + CONFIG.ENCAMINHAR_AUTOMATICAMENTE
  );
  Logger.log(
    'Rascunho para auditoria: ' + CONFIG.CRIAR_RASCUNHO_PARA_AUDITORIA
  );
  Logger.log('Limite por execução: ' + CONFIG.LIMITE_THREADS);
  Logger.log(
    'Mérito, dado identificável ou anexo: auditoria técnica, sem ' +
    'resposta automática'
  );
  Logger.log('Mensagens não reconhecidas: permanecem sem alteração');
  Logger.log('Controle de duplicidade: propriedades do script');

  if (!CONFIG.SIMULACAO_ONLY) {
    Logger.log('ATENÇÃO: execução REAL ativa.');
  }

  if (!CONFIG.SIMULACAO_ONLY && CONFIG.ENCAMINHAR_AUTOMATICAMENTE) {
    Logger.log(
      'ATENÇÃO: encaminhamento automático ativo em execução real. ' +
      'Confirme antes os e-mails de destino dos setores.'
    );
  }

  Logger.log('Marcadores ausentes: ' + testarMarcadoresDIOAC());
}
