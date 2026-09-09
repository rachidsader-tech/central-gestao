# Central de Gestão — V3.1 pronta para Render

Versão oficial para operação real em Flask + Render + PostgreSQL.

## Infraestrutura definida
- Web service: `central-gestao-app-v31` — plano `free`
- PostgreSQL: `central-gestao-db-v31` — plano `0.1c-256mb` (menor plano pago)
- Login inicial por `ADMIN_EMAIL` e `ADMIN_PASSWORD`
- `SECRET_KEY` e `DAILY_IMPORT_TOKEN` gerados pelo Render

Os nomes `-v31` foram usados de propósito para evitar conflito com tentativas de Blueprint anteriores. Isso não altera o nome exibido do sistema.

## Upload no GitHub
Envie todo o conteúdo deste pacote para a raiz do repositório `rachidsader-tech/central-gestao`, sobrescrevendo os arquivos de mesmo nome.

Arquivos essenciais:
- `app.py`
- `render.yaml`
- `requirements.txt`
- `templates/index.html`
- `templates/login.html`
- `data/seed.json`

## Deploy
1. No Render, crie um novo Blueprint a partir de `rachidsader-tech/central-gestao`.
2. Use Blueprint Name `central-gestao-v31`.
3. Branch `main`.
4. Deixe Blueprint Path vazio.
5. Preencha `ADMIN_EMAIL` e `ADMIN_PASSWORD`.
6. Cadastre o cartão quando solicitado para o PostgreSQL pago.
7. Clique em Deploy Blueprint.

## Dados
A base inicial dos 7 projetos, Agenda e Notas é criada automaticamente quando o banco estiver vazio.
A V3.1 também inclui o botão **Importar backup** para migrar um Backup JSON produzido pela V2.0.

## Depois do deploy
O GitHub Pages não será mais o ambiente operacional. O endereço principal passa a ser o `onrender.com` do Web Service.
