# Central de Gestão — V3.0 Render/PostgreSQL

Aplicação real em Flask + PostgreSQL, preservando o layout da V2.0.

## Funcionalidades reais
- Login por e-mail/senha definidos por variáveis de ambiente.
- Projetos, frentes, pendências, notas, agenda e diário persistidos no PostgreSQL.
- Upload de arquivos reais armazenados no PostgreSQL (limite de 12 MB por arquivo nesta fase).
- Edição do estado do projeto e das frentes.
- Backup JSON.
- Endpoint protegido `/api/daily-import` já preparado para futura automação do fechamento diário vinda do ChatGPT.

## Deploy no Render
1. Suba este conteúdo no repositório GitHub `central-gestao`.
2. No Render, escolha **New → Blueprint** e conecte o repositório. O `render.yaml` cria o Web Service e o PostgreSQL.
3. No Web Service, defina `ADMIN_EMAIL` e `ADMIN_PASSWORD`.
4. Aguarde o deploy e abra a URL gerada pelo Render.

## Regra de infraestrutura
- GitHub = código e histórico.
- Render Web Service = aplicação.
- Render PostgreSQL = banco persistente.
- GitHub Pages deixa de ser o ambiente principal depois que a V3.0 estiver validada.
