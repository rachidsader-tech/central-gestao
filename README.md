# Central de Gestão — Projetos

Versão de teste para GitHub Pages.

## Publicar

1. Crie um repositório novo no GitHub, por exemplo `central-gestao`.
2. Faça upload de todo o conteúdo deste pacote para a branch `main`.
3. No GitHub, vá em **Settings → Pages**.
4. Em **Build and deployment / Source**, selecione **GitHub Actions**.
5. Abra a aba **Actions** e aguarde o workflow `Deploy GitHub Pages`.
6. O GitHub mostrará a URL pública do sistema.

## Dados

Esta versão já nasce com os projetos reais carregados. Os dados ficam em `localStorage` do navegador durante o teste.  
O próximo passo, após validar o uso em URL real, é conectar Supabase para login, multiusuário, arquivos reais e persistência centralizada.
