# Transformação KAZ

Sistema estratégico multiusuário derivado do MVP HTML validado em reunião.

## Stack
- Flask
- PostgreSQL
- Render
- Sessão + CSRF
- Estado estratégico versionado no PostgreSQL
- Arquivos binários armazenados separadamente no PostgreSQL

## Execução local
```bash
pip install -r requirements.txt
ADMIN_PASSWORD='defina-uma-senha' python app.py
```

Acesse `/admin/users` com o usuário `rachid` para ativar os demais participantes e definir senhas.
