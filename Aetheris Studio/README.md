<div align="center">
  <img src="assets/earth_pixelated.svg" alt="Aetheris Logo" />
  <h1>✨ Aetheris ✨</h1>
  <p><b>Seu Assistente de IA de Programação Autônoma com Interface (CLI + GUI)</b></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version" />
    <img src="https://img.shields.io/badge/Status-Em_Desenvolvimento-yellow.svg" alt="Status" />
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License" />
  </p>
</div>

<hr/>

## 🌌 O que é o Aetheris?

O **Aetheris** é uma ferramenta poderosa de Inteligência Artificial para programação autônoma. Inspirado por sistemas avançados como *GPT Codex* e *Trae*, ele atua como um verdadeiro parceiro de engenharia de software na sua máquina.

Em vez de apenas gerar código isolado, o Aetheris conta com uma **Interface Gráfica (GUI) integrada e ferramentas de Linha de Comando (CLI)**, permitindo:

- Criação e modificação de sistemas complexos.
- Análise de código e documentação.
- Automação do fluxo de trabalho diário.

---

## Principais Funcionalidades

- ** Inteligência Autônoma:** Entende contextos inteiros de projetos e sugere arquiteturas, refatorações e correções.
- ** CLI & GUI Integradas:** Pode ser usado tanto pelo terminal para máxima produtividade, quanto pela interface visual elegante e rica (desenvolvida com Flet) para melhor organização.
- ** Suporte a Modelos Locais (Ollama):** Integra-se com modelos hospedados localmente para garantir privacidade e alta disponibilidade (ex: Qwen, Llama).
- ** Indexação Inteligente:** Utiliza ferramentas como ChromaDB para buscas vetoriais super-rápidas no seu código, trazendo contexto cirúrgico.
- ** Fluxos Customizados:** Ferramentas sob medida para gerenciar tarefas, inspecionar painéis de chat e rodar tarefas em background.

---

## Instalação e Configuração

### 1. Pré-requisitos
- Python 3.10 ou superior
- Git
- Ollama (caso queira rodar modelos locais)

### 2. Passo a Passo

```bash
# Clone o repositório
git clone git@github.com:kyuubyN/aetherys.git
cd aetherys

# Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate  # No Linux/macOS
# No Windows use: .venv\Scripts\activate

# Instale as dependências
pip install -r requirements.txt
```

---

## Como Usar

Com o ambiente ativado, você pode rodar a interface principal ou o CLI:

```bash
# Para iniciar a interface visual
python app.py
```

Na interface, você pode selecionar suas pastas de projeto, escolher o modelo de IA que deseja usar e começar a dar comandos complexos para a IA agir na sua base de código.

---

## Arquitetura do Projeto

- **`core/`**: Backend (FastAPI, agente, ferramentas, banco de dados) e a integração com o motor de inferência VTE.
- **`aetheris_ui/`**: Cliente desktop nativo (Flutter).

---

<div align="center">
  <i>"Transforme sua maneira de programar com a força do cosmos."</i> 🌠
</div>
