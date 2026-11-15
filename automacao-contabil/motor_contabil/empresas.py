"""Dados separados por empresa.

Cada empresa cliente tem a sua pasta dentro da pasta de dados do escritório:

    dados/
      nx/
        empresa.json     nome, CNPJ, conta do banco, prefixo da marca, formato do plano
        plano.csv        plano de contas (exemplo do motor ou exportado do Fortes)
        regras.json      regras de classificação desta empresa
        motor.db         movimentos, lançamentos, lotes e trilha de auditoria
        arquivos/        extratos e planilhas recebidos, como chegaram (AAAA-MM/)
      outra-empresa/
        ...

O motor de uma empresa só abre os arquivos da pasta dela. Não há banco
compartilhado: um erro de consulta não tem como misturar dados de clientes.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .banco import BancoDeDados
from .motor import Motor
from .plano_contas import PlanoDeContas
from .regras import ConjuntoDeRegras

IDENTIFICADOR = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
FORMATOS_PLANO = ("fortes", "motor")
CONFIG = "empresa.json"


@dataclass
class Empresa:
    identificador: str
    nome: str
    cnpj: str
    conta_bancaria: str          # como o banco aparece nos extratos (ex.: reduzido 362)
    prefixo_marca: str
    formato_plano: str
    pasta: Path

    @property
    def caminho_banco(self) -> Path:
        return self.pasta / "motor.db"

    @property
    def caminho_plano(self) -> Path:
        return self.pasta / "plano.csv"

    @property
    def caminho_regras(self) -> Path:
        return self.pasta / "regras.json"

    @property
    def pasta_arquivos(self) -> Path:
        return self.pasta / "arquivos"

    def carregar_plano(self) -> PlanoDeContas:
        if self.formato_plano == "fortes":
            return PlanoDeContas.carregar_fortes(self.caminho_plano)
        return PlanoDeContas.carregar(self.caminho_plano)

    def abrir_motor(self, usuario: str, classificador=None) -> Motor:
        plano = self.carregar_plano()
        regras = ConjuntoDeRegras.carregar(self.caminho_regras)
        banco = BancoDeDados(self.caminho_banco)
        try:
            return Motor(banco, plano, regras, classificador=classificador, usuario=usuario)
        except Exception:
            banco.fechar()
            raise


def _so_digitos(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def _pasta_da_empresa(dados: Path, identificador: str) -> Path:
    if not IDENTIFICADOR.match(identificador or ""):
        raise ValueError(
            "identificador inválido: use de 2 a 40 letras minúsculas, números ou hífen, "
            "começando por letra ou número (ex.: nx, olavo-araujo)"
        )
    pasta = (dados / identificador).resolve()
    if pasta.parent != dados.resolve():
        raise ValueError("identificador inválido")
    return pasta


def validar_configuracao(plano: PlanoDeContas, regras: ConjuntoDeRegras) -> list[str]:
    """Problemas que impedem o uso: conta do banco ou das regras fora do plano."""
    problemas = []
    if erro := plano.problema(regras.conta_banco):
        problemas.append(f"conta do banco nas regras: {erro}")
    for regra in regras.regras:
        if erro := plano.problema(regra.conta):
            problemas.append(f"regra {regra.id}: {erro}")
    return problemas


def ler(pasta: str | Path) -> Empresa:
    pasta = Path(pasta)
    try:
        bruto = json.loads((pasta / CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise ValueError(f"{pasta.name}: configuração da empresa ilegível ({erro})") from erro
    if bruto.get("identificador") != pasta.name:
        raise ValueError(f"{pasta.name}: o identificador em {CONFIG} não corresponde à pasta")
    return Empresa(
        identificador=bruto["identificador"], nome=bruto["nome"], cnpj=bruto["cnpj"],
        conta_bancaria=bruto["conta_bancaria"], prefixo_marca=bruto["prefixo_marca"],
        formato_plano=bruto["formato_plano"], pasta=pasta,
    )


def listar(dados: str | Path) -> list[Empresa]:
    dados = Path(dados)
    if not dados.is_dir():
        return []
    return [ler(p) for p in sorted(dados.iterdir()) if p.is_dir() and (p / CONFIG).is_file()]


def abrir(dados: str | Path, identificador: str) -> Empresa:
    pasta = _pasta_da_empresa(Path(dados), identificador)
    if not (pasta / CONFIG).is_file():
        raise ValueError(f"empresa {identificador!r} não cadastrada em {dados}")
    return ler(pasta)


def cadastrar(dados: str | Path, identificador: str, nome: str, cnpj: str, conta_bancaria: str,
              prefixo_marca: str, formato_plano: str, plano: str | Path, regras: str | Path) -> Empresa:
    """Cria a pasta da empresa com cópia do plano e das regras, depois de validá-los."""
    dados = Path(dados)
    pasta = _pasta_da_empresa(dados, identificador)
    if pasta.exists():
        raise ValueError(f"já existe a pasta {pasta.name}; escolha outro identificador")
    if not nome.strip():
        raise ValueError("informe o nome da empresa")
    if len(_so_digitos(cnpj)) != 14:
        raise ValueError("informe o CNPJ com 14 dígitos")
    if formato_plano not in FORMATOS_PLANO:
        raise ValueError(f"formato do plano deve ser um de {FORMATOS_PLANO}")
    if not re.fullmatch(r"[A-Z0-9]{2,6}", prefixo_marca or ""):
        raise ValueError("o prefixo da marca deve ter de 2 a 6 letras maiúsculas ou números")
    if not conta_bancaria.strip():
        raise ValueError("informe a conta bancária (como ela será identificada nos extratos)")
    for outra in listar(dados):
        if _so_digitos(outra.cnpj) == _so_digitos(cnpj):
            raise ValueError(f"o CNPJ já está cadastrado na empresa {outra.identificador}")
        if outra.prefixo_marca == prefixo_marca:
            raise ValueError(f"o prefixo {prefixo_marca} já é usado pela empresa {outra.identificador}")

    carregar = PlanoDeContas.carregar_fortes if formato_plano == "fortes" else PlanoDeContas.carregar
    plano_lido = carregar(plano)
    regras_lidas = ConjuntoDeRegras.carregar(regras)
    if problemas := validar_configuracao(plano_lido, regras_lidas):
        raise ValueError("o plano e as regras não combinam:\n- " + "\n- ".join(problemas))

    provisoria = dados / f".{identificador}.novo"
    if provisoria.exists():
        shutil.rmtree(provisoria)
    try:
        (provisoria / "arquivos").mkdir(parents=True)
        shutil.copyfile(plano, provisoria / "plano.csv")
        shutil.copyfile(regras, provisoria / "regras.json")
        empresa = Empresa(identificador, nome.strip(), cnpj.strip(), conta_bancaria.strip(),
                          prefixo_marca, formato_plano, pasta)
        config = {k: v for k, v in asdict(empresa).items() if k != "pasta"}
        config["cadastrada_em"] = datetime.now().isoformat(timespec="seconds")
        (provisoria / CONFIG).write_text(json.dumps(config, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        provisoria.rename(pasta)
    except BaseException:
        shutil.rmtree(provisoria, ignore_errors=True)
        raise
    return empresa


def guardar_original(empresa: Empresa, nome: str, conteudo: bytes,
                     agora: datetime | None = None) -> tuple[Path, bool]:
    """Guarda o arquivo recebido como chegou. Devolve (caminho, já existia)."""
    resumo = hashlib.sha256(conteudo).hexdigest()
    for existente in empresa.pasta_arquivos.rglob(f"{resumo[:16]}_*"):
        if existente.is_file() and hashlib.sha256(existente.read_bytes()).hexdigest() == resumo:
            return existente, True
    seguro = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(nome).name)[:80] or "arquivo"
    pasta = empresa.pasta_arquivos / (agora or datetime.now()).strftime("%Y-%m")
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{resumo[:16]}_{seguro}"
    destino.write_bytes(conteudo)
    return destino, False


def empresas_com_o_arquivo(dados: str | Path, conteudo: bytes, exceto: str) -> list[str]:
    """Outras empresas que já receberam exatamente este arquivo (sinal de envio na empresa errada)."""
    resumo = hashlib.sha256(conteudo).hexdigest()
    achadas = []
    for empresa in listar(dados):
        if empresa.identificador == exceto:
            continue
        for existente in empresa.pasta_arquivos.rglob(f"{resumo[:16]}_*"):
            if existente.is_file() and hashlib.sha256(existente.read_bytes()).hexdigest() == resumo:
                achadas.append(empresa.identificador)
                break
    return achadas
