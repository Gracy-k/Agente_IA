# CodeLocal — Agente de Codificação Local

Agente de programação com Flask, SQLite e Ollama. Interface em português, histórico persistente e salvamento protegido na pasta `workspace/`.

## Requisitos
- Python 3.10+
- Ollama instalado e em execução
- Modelo recomendado para computadores com pouca memória: `llama3.2:1b`

## Instalação

```bash
ollama pull llama3.2:1b
pip install -r requirements.txt
python app.py
```

Abra `http://127.0.0.1:5000`.

## Recursos
- Histórico de conversas em SQLite (`conversas.db`, criado automaticamente ao iniciar `app.py`).
- Resposta em fluxo: o texto aparece enquanto o modelo gera, em vez de esperar a resposta inteira.
- Tema claro/escuro, com preferência salva no navegador.
- Busca no histórico e exportação de conversas em Markdown.
- Botões para copiar a resposta, copiar blocos de código e salvar código.
- Salvamento dentro de `workspace/`, sem sobrescrever arquivos existentes.
- Histórico de contexto reduzido às últimas mensagens para economizar memória e acelerar o processamento.

## Desempenho
A geração depende do hardware e do modelo instalado. Em computadores com 4 GB de RAM, use `llama3.2:1b`, feche programas pesados e prefira pedidos objetivos. A transmissão em fluxo melhora a percepção de velocidade, mas não torna o modelo mais rápido no processamento interno.

## Histórico e backup
O banco `conversas.db` fica na mesma pasta de `app.py`. Faça uma cópia desse arquivo para preservar as conversas ao atualizar o projeto. Seus arquivos criados ficam em `workspace/`.

## Segurança
O agente não executa código nem lê automaticamente os arquivos do projeto. O salvamento aceita apenas caminhos relativos dentro de `workspace/` e recusa nomes já existentes.
