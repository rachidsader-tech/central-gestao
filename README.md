# Central de Gestão — V2.1 Online

Esta versão mantém o layout e os dados da V2.0, mas passa a salvar a Central no Supabase.

## Como funciona
- O GitHub Pages continua hospedando a interface.
- O Supabase passa a armazenar os dados.
- Cada usuário autenticado possui um `app_state` próprio.
- A V2.1 tenta migrar automaticamente os dados locais da V2.0 no primeiro login.
- Depois disso, Notas, Agenda, Pendências e Frentes são sincronizadas online.

## Configuração
1. Crie um projeto no Supabase.
2. Abra **SQL Editor** e execute `supabase/schema.sql`.
3. Em **Project Settings → API**, copie a Project URL e a chave anon/public.
4. Edite `config.js` e cole os dois valores.
5. Suba `index.html` e `config.js` para a raiz do GitHub `central-gestao`.
6. Abra o GitHub Pages.
7. Clique em **Criar primeiro acesso** e use seu e-mail e uma senha.

## Segurança
A chave anon/public pode ficar no front-end. A proteção dos dados é feita pelas políticas RLS:
cada usuário só consegue ler e alterar a própria linha em `app_state`.

## Próximas evoluções
Depois de colocar esta versão em uso:
- upload real de arquivos no Supabase Storage;
- pessoas/usuários por projeto;
- integração com Google Calendar;
- fechamento diário e automação via ChatGPT.
