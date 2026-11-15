# Instalação no computador do escritório (piloto interno)

Guia para rodar a fase 1 num computador Windows do escritório. Tudo roda
localmente: nenhum dado sai do computador, e a sugestão por IA fica desligada.
Este guia foi escrito sem ter sido executado num Windows; anote o que não
funcionar como descrito.

## 1. Preparar o computador

1. Use uma conta do Windows com senha, só para quem trabalha na contabilidade.
2. Ative a criptografia do disco (BitLocker ou "Criptografia do dispositivo",
   em Configurações > Privacidade e segurança). O computador vai guardar
   extratos e lançamentos de clientes.
3. Separe o dispositivo de backup: outro disco, pendrive ou unidade de rede,
   de preferência guardado fora da sala do computador.

## 2. Instalar o Python

1. Baixe o Python 3.12 em <https://www.python.org/downloads/windows/>.
2. Na instalação, marque **"Add python.exe to PATH"**.
3. Confira no Prompt de Comando: `python --version` deve mostrar 3.12.

## 3. Instalar o aplicativo

No Prompt de Comando:

```bat
mkdir C:\Contabil
cd C:\Contabil
git clone --branch fase1/exportador-fortes https://github.com/willianfilho-spec/Will.git codigo
cd codigo\automacao-contabil
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest
```

Sem o Git instalado, baixe o ZIP da branch no GitHub (botão "Code" >
"Download ZIP") e descompacte em `C:\Contabil\codigo`. Os testes devem
terminar com "passed" e nenhuma falha.

A pasta de dados fica **fora** da pasta do código, em `C:\Contabil\dados`.
Assim uma atualização do código nunca mexe nos dados.

## 4. Cadastrar a NX

Antes, exporte pelo Fortes o plano de contas atual da NX (CSV) e tenha em mãos
as regras revisadas pelo contador.

```bat
.venv\Scripts\python.exe -m motor_contabil.cli --dados C:\Contabil\dados cadastrar-empresa nx ^
  --nome "N X ARAUJO LTDA" --cnpj 62.064.868/0001-02 --conta 362 --prefixo NX ^
  --plano C:\caminho\plano_NX.csv --regras C:\caminho\regras_NX.json
```

Se o cadastro recusar com "não combinam", alguma regra aponta para uma conta
que não existe no plano: corrija a regra ou o plano. O cadastro também pode ser
feito pela barra lateral do aplicativo.

## 5. Abrir o aplicativo

Dê dois cliques em `iniciar_windows.bat`, na pasta `automacao-contabil`. O
navegador abre em `http://localhost:8501`. O aplicativo só aceita conexões
deste computador. Para fechar, feche a janela preta do Prompt.

## 6. Agendar o backup

No Prompt de Comando (ajuste a letra do disco de backup):

```bat
schtasks /Create /TN "Backup contabil" /SC DAILY /ST 18:00 /RL LIMITED ^
  /TR "C:\Contabil\codigo\automacao-contabil\.venv\Scripts\python.exe -m motor_contabil.backup fazer --dados C:\Contabil\dados --destino E:\backups"
```

Depois, no Agendador de Tarefas, abra a tarefa "Backup contabil":

- em **Ações > Editar**, preencha "Iniciar em" com
  `C:\Contabil\codigo\automacao-contabil`;
- em **Configurações**, marque "Executar a tarefa o mais cedo possível após
  uma inicialização agendada ter sido perdida".

Rode a tarefa uma vez à mão (botão direito > Executar) e teste a restauração:

```bat
.venv\Scripts\python.exe -m motor_contabil.backup testar --destino E:\backups
```

No aplicativo, informe `E:\backups` em "Pasta de backup": a barra lateral
avisa quando a última cópia tem mais de 26 horas. Repita o teste de
restauração a cada três meses.

## 7. Roteiro do piloto

1. Escolha um mês da NX que ainda **não** foi lançado no Fortes. Importar um
   mês já lançado duplica lançamentos no Fortes.
2. Anote a hora de início. Importe o extrato Itaú em PDF ou as planilhas do mês.
3. Revise os pendentes, aprove ou corrija, e exporte o lote no leiaute Fortes.
4. Importe o lote no Fortes com "Desconsiderar Identificador" e "Utilizar
   Código Reduzido" marcados. Anote se alguma linha foi rejeitada.
5. Na seção 4 do aplicativo, confira o extrato contra os arquivos importados.
   O resultado esperado é "Conciliado", com diferença zero em todos os meses.
6. Anote a hora de término e compare com o tempo do processo atual para o
   mesmo tipo de mês. A comparação só é justa a partir do segundo mês, quando
   as correções do primeiro já viraram regras.
