# Central de Gestão — V3.2 Render/PostgreSQL

Correção do deploy no Render:
- driver PostgreSQL atualizado para `psycopg[binary]==3.3.5`;
- URI do PostgreSQL usa explicitamente o driver SQLAlchemy `postgresql+psycopg://`;
- removido `__pycache__` do pacote.

## Publicação
Suba todo o conteúdo deste pacote na raiz do repositório `central-gestao`, sobrescrevendo os arquivos existentes.

O serviço existente `central-gestao-app-v31` está conectado à branch `main`, então o commit deve disparar novo deploy automático. Não crie outro Blueprint nem outro banco.
