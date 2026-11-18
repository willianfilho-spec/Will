# Testes de navegador (Playwright)

Rodam contra o app em execução. Usam só os exemplos sintéticos.

```bash
# fluxo 1: primeira configuração, plano, regras, carga CSV e bloqueio de arquivo repetido
export CONCILIADOR_DATA_DIR=$(mktemp -d)
streamlit run app.py --server.headless true --server.port 8599 &
node tests/e2e/fluxo_primeira_configuracao.js

# fluxo 2: operadora classifica, revisor confirma, conferência, lote e retorno
export CONCILIADOR_DATA_DIR=$(mktemp -d)
python scripts/seed_demo.py
streamlit run app.py --server.headless true --server.port 8599 &
node tests/e2e/fluxo_demo_dois_usuarios.js
```

Variáveis opcionais: `E2E_URL` (padrão http://localhost:8599) e `E2E_OUT` (pasta das capturas de tela).
