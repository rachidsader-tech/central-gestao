# Central de Gestão — V3.3

Correção do seed inicial no PostgreSQL.

## O que foi corrigido
O deploy anterior conectava corretamente ao PostgreSQL, mas falhava ao inserir
`fronts` porque o PostgreSQL recebia registros filhos antes de os respectivos
`projects` estarem persistidos.

A V3.3:
- persiste/flush os projetos antes de frentes, tarefas e diário;
- torna o seed idempotente para permitir reinícios sem duplicar dados;
- preserva os mesmos serviços Render já criados;
- mantém psycopg 3.3.5 e a configuração atual do banco.

## Como atualizar
Suba todo o conteúdo deste pacote na raiz do repositório `central-gestao`,
sobrescrevendo os arquivos existentes, e faça commit na branch `main`.

Não crie novo Blueprint, novo Web Service ou novo banco. O serviço
`central-gestao-app-v31` deve fazer Auto-Deploy após o commit.
