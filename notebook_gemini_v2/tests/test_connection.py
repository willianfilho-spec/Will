import json

import pytest

from nb import settings_store
from nb.config import load_settings
from nb.connection import check_key, pick_embedding, pick_generation


class _Model:
    def __init__(self, name, actions):
        self.name, self.supported_actions = name, actions


class _Client:
    def __init__(self, models=None, error=None):
        self._models, self._error, self.models = models or [], error, self

    def list(self):
        if self._error:
            raise self._error
        return iter(self._models)


KEY = "AIza" + "x" * 35
MODELS = [
    _Model("models/gemini-2.5-flash", ["generateContent"]),
    _Model("models/gemini-2.5-flash-preview-tts", ["generateContent"]),
    _Model("models/gemini-2.5-pro", ["generateContent", "countTokens"]),
    _Model("models/gemini-embedding-001", ["embedContent"]),
    _Model("models/text-embedding-004", ["embedContent"]),
    _Model("models/imagen-4", ["predict"]),
]


def test_chave_valida_lista_modelos_de_resposta_e_de_busca_sem_o_prefixo_models():
    r = check_key(KEY, lambda k: _Client(MODELS))
    assert r.ok and r.generation_models == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert r.embedding_models == ["gemini-embedding-001", "text-embedding-004"]


@pytest.mark.parametrize("chave", ["", "curta", "AIza com espaco " + "x" * 30])
def test_chave_obviamente_ruim_nem_chega_a_chamar_a_api(chave):
    chamou = []
    r = check_key(chave, lambda k: chamou.append(k))
    assert not r.ok and not chamou


def test_chave_recusada_pelo_google_vira_mensagem_clara():
    class Erro(Exception):
        code = 400

    r = check_key(KEY, lambda k: _Client(error=Erro("API key not valid. API_KEY_INVALID")))
    assert not r.ok and "recusou a chave" in r.message


def test_falha_de_rede_tem_mensagem_propria():
    r = check_key(KEY, lambda k: _Client(error=ConnectionError("sem rede")))
    assert not r.ok and "internet" in r.message


def test_conta_sem_modelo_de_embeddings_e_reportada():
    r = check_key(KEY, lambda k: _Client([MODELS[0]]))
    assert not r.ok and "embeddings" in r.message


def test_escolha_de_modelos_prefere_o_configurado_depois_o_estavel():
    assert pick_embedding(["text-embedding-004", "gemini-embedding-001"]) == "gemini-embedding-001"
    assert pick_embedding(["gemini-embedding-001", "gemini-embedding-exp"], "gemini-embedding-exp") == "gemini-embedding-exp"
    assert pick_embedding(["gemini-embedding-exp-03", "gemini-embedding-001"]) == "gemini-embedding-001"
    assert pick_generation(["gemini-2.5-pro", "gemini-2.5-flash"]) == "gemini-2.5-flash"
    assert pick_generation(["gemini-3-flash-preview", "gemini-2.5-flash"]) == "gemini-2.5-flash"
    assert pick_generation(["gemini-2.5-pro", "gemini-3-flash-preview"]) == "gemini-3-flash-preview"
    assert pick_embedding([]) is None and pick_generation([]) is None


def test_config_salva_pela_tela_vale_mais_que_o_env_e_preserva_outros_campos(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaDoEnv" + "y" * 30)
    s = load_settings()
    assert s.key_source == ".env" and s.gemini_api_key.startswith("AIzaDoEnv")
    settings_store.save(tmp_path, api_key=KEY)
    settings_store.save(tmp_path, embedding_model="gemini-embedding-001")
    s = load_settings()
    assert (s.key_source, s.gemini_api_key, s.embedding_model) == ("tela", KEY, "gemini-embedding-001")
    assert json.loads((tmp_path / "config.json").read_text())["api_key"] == KEY


def test_arquivo_de_config_corrompido_ou_com_campos_estranhos_e_ignorado(tmp_path):
    (tmp_path / "config.json").write_text("{quebrado", encoding="utf-8")
    assert settings_store.load(tmp_path) == {}
    (tmp_path / "config.json").write_text('{"api_key": 5, "outro": "x", "gemini_model": "m"}', encoding="utf-8")
    assert settings_store.load(tmp_path) == {"gemini_model": "m"}
    with pytest.raises(ValueError):
        settings_store.save(tmp_path, senha="x")


def test_mascara_nao_revela_a_chave_inteira():
    assert settings_store.mask_key(KEY).startswith("AIza…") and "xxxxx" not in settings_store.mask_key(KEY)
    assert settings_store.mask_key("") == "(nenhuma)"
