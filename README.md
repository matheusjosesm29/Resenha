# Resenha — Django + frontend integrado

Primeira versão funcional do backend. A interface escura do grupo é servida pelo Django e usa sessões e dados do banco, sem o login simulado nem a persistência em localStorage da versão anterior.

## Executar no Linux (mais simples)

Abra o terminal na pasta que contém este README e `manage.py`. Antes de iniciar, copie `.env.example` para `.env` e preencha a chave OMDb somente no `.env`:

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_catalog
python manage.py createsuperuser
python manage.py runserver
```

Abra http://127.0.0.1:8000. Nesta opção, o banco SQLite é criado automaticamente em `db.sqlite3`. Não é necessário executar `http.server` nem entrar na pasta `dist`. Para parar, use Ctrl+C. Para iniciar novamente, ative `.venv` e execute `python manage.py runserver`.

Caso a criação do ambiente virtual indique que `ensurepip` está indisponível no Ubuntu/Debian, instale `python3-venv` pelo gerenciador de pacotes do sistema.

O comando `seed_catalog` adiciona as 12 obras dos modelos e pode ser repetido sem duplicá-las. Não cria usuários nem avaliações fictícias: notas começam em zero. Crie uma conta pela interface para testar resenhas. O superusuário criado no terminal acessa o painel da interface e o `/admin/` nativo do Django. A interface entra por e-mail; o admin nativo usa o nome de usuário escolhido em `createsuperuser`.

## Docker + PostgreSQL

```bash
cp .env.example .env
```

Edite `.env` e substitua os valores de exemplo de `DJANGO_SECRET_KEY` e `POSTGRES_PASSWORD`. Uma chave pode ser gerada com `python -c 'import secrets; print(secrets.token_urlsafe(64))'`.

```bash
docker compose up --build -d
docker compose exec web python manage.py seed_catalog
docker compose exec web python manage.py createsuperuser
```

Abra http://127.0.0.1:8000. O volume `postgres_data` mantém o banco após reiniciar os contêineres. `docker compose down` encerra os serviços; não use `down -v` se quiser preservar o banco. A porta do banco não é publicada.

## Funcionalidades

- Cadastro, login e logout reais com sessão Django, cookies HttpOnly e validação de senha.
- Perfil com nome, biografia e avatar validado e recodificado pelo servidor; histórico e favoritos públicos.
- Catálogo público com busca, categorias, ordenação e detalhes.
- Uma resenha por usuário/obra, nota de 0 a 10, média e distribuição calculadas com dados reais.
- Edição e exclusão apenas pelo autor; aviso e revelação de spoiler na interface.
- Curtidas únicas, sem curtir a própria resenha; respostas e exclusão de comentários próprios.
- Favoritos e status de consumo por usuário; listas privadas e favoritos públicos no perfil.
- Denúncias de resenhas e comentários; fila e decisões registradas; moderação e bloqueio de contas por administradores.
- Cadastro, edição e exclusão de obras; importação de filmes e séries do OMDb por administrador.
- Admin nativo do Django em `/admin/`.

A ocultação de spoiler é um recurso visual; o texto é público e está na resposta da API, como qualquer resenha pública.

## OMDb

Configure `OMDB_API_KEY` no servidor. Na execução direta, por exemplo:

```bash
export OMDB_API_KEY='SUA_CHAVE'
python manage.py runserver
```

No Docker, preencha `.env` e recrie o serviço `web`. O painel permite importar por título. A chave nunca é enviada ao navegador. A consulta usa HTTPS, timeout de 5 segundos e tratamento de falhas. `GET /api/omdb?title=...` oferece consulta pública sem gravar; a busca pública atual filtra o banco local. A importação automática em toda busca ainda não foi ativada.

## Recuperar senha

Em desenvolvimento, o link é escrito no terminal do servidor. Não há envio real de e-mail por padrão. Para SMTP, configure `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` e `DEFAULT_FROM_EMAIL`. Links usam tokens nativos do Django e deixam de funcionar após a troca de senha. A resposta pública não informa se o e-mail está cadastrado.

O Django e o Docker Compose carregam o arquivo `.env`. Na execução direta, variáveis já definidas no terminal têm prioridade sobre os valores do `.env`.

## Testar

```bash
python manage.py test core
python manage.py check
```

15 testes automatizados cobrem CSRF, autenticação, hash de senha, notas inválidas e médias, unicidade, autorização, curtidas, comentários, isolamento das listas, moderação, bloqueios, recuperação de senha e falhas/importação OMDb com respostas simuladas.

Os testes foram executados com SQLite. Docker/PostgreSQL e o envio por SMTP precisam de validação no ambiente do grupo; o OMDb foi testado com mock, sem uma chave real. A conferência visual desta versão integrada não foi concluída porque o ambiente de preview não dispõe do interpretador Python instalado para esta aplicação.

## Estrutura

- `config/`: configurações, URLs e entrada WSGI.
- `core/models.py`: entidades e restrições de integridade.
- `core/views.py`: API, validação e autorização.
- `core/services.py`: consulta ao OMDb.
- `core/migrations/`: esquema versionado do banco.
- `core/tests.py`: testes de integração.
- `templates/`: estrutura da interface e recuperação de senha.
- `static/resenha/app.js`: renderização das telas reaproveitadas.
- `static/resenha/api.js`: integração das interações com a API Django; é carregado depois de app.js.
- `static/resenha/style.css`: identidade visual responsiva, ainda em CSS próprio.

## Rotas da API

Todas as alterações exigem CSRF. Campos JSON são validados no servidor; a autorização não depende de botões ocultos.

| Método | Rota | Acesso |
|---|---|---|
| GET | `/api/state` | Público, dados privados limitados à sessão |
| GET | `/api/profiles/<id>` | Perfil público sem e-mail |
| POST | `/api/register`, `/api/login`, `/api/logout` | Contas |
| POST | `/api/password-reset` | Público com limitação de tentativas |
| PATCH | `/api/profile` | Próprio perfil |
| POST | `/api/reviews` | Usuário autenticado |
| PATCH, DELETE | `/api/reviews/<id>` | Autor |
| POST | `/api/reviews/<id>/like` | Usuário autenticado |
| POST | `/api/reviews/<id>/comments` | Usuário autenticado |
| DELETE | `/api/comments/<id>` | Autor ou administrador |
| PATCH | `/api/library/<work_id>` | Própria lista |
| POST | `/api/reports` | Usuário autenticado |
| GET | `/api/omdb?title=...` | Consulta pública |
| POST | `/api/admin/import` | Administrador |
| POST | `/api/admin/works` | Administrador |
| PATCH, DELETE | `/api/admin/works/<id>` | Administrador |
| PATCH | `/api/admin/users/<id>` | Administrador |
| POST | `/api/admin/reports/<id>` | Administrador |

## Próximas etapas antes de produção

Configurar domínio, HTTPS, SMTP, PostgreSQL gerenciado/backup e segredos na Azure; usar `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS` com os domínios reais, coletar estáticos e executar `python manage.py check --deploy`. A configuração fornece Gunicorn/WhiteNoise e cookies seguros, mas não cria certificados nem infraestrutura Azure.

O limite de tentativas usa cache local por processo; usar cache compartilhado ou limitação no proxy em produção. O endpoint de estado carrega o catálogo e as resenhas inteiros, adequado à primeira implementação; implementar paginação antes de crescer e medir o requisito de dois segundos com carga real. Não há garantia de disponibilidade de 99,9% nesta entrega. Os estilos ainda precisam da migração para Tailwind prevista no documento. Separar mudanças em branches e revisar via pull request no repositório do grupo.

Referência de autenticação: https://docs.djangoproject.com/en/5.2/topics/auth/default/


## Enviar ao GitHub

O `.gitignore` exclui `.env`, ambientes virtuais, caches, banco local, uploads e logs. O `.env.example` deve continuar sem chave OMDb nem credenciais reais. As migrations e o catálogo inicial devem ser versionados.

Antes de substituir arquivos de uma instalação que já possui uma chave no `.env.example`, copie essa chave para o seu `.env` privado. O pacote revisado não inclui chaves, usuários ou banco de dados. Preserve sua pasta `.venv` e seu `db.sqlite3` atuais ao atualizar o código.

Na pasta que contém `manage.py`:

```bash
git init
git branch -M main
git add .
git status
```

Confira a lista: `.env`, `.venv/` e `db.sqlite3` não podem estar entre os arquivos preparados. Em seguida, substitua o endereço abaixo pelo HTTPS do seu repositório:

```bash
git commit -m "Implementa frontend e backend inicial do Resenha"
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main
```

Se já executou `git add` para esses arquivos antes de configurar o `.gitignore`, remova-os apenas do índice, preservando os arquivos locais, com `git rm --cached --ignore-unmatch .env .env.example db.sqlite3` e `git rm -r --cached --ignore-unmatch .venv venv staticfiles`. Depois execute `git add .` novamente para incluir o `.env.example` já sem a chave. Se uma chave chegou a ser enviada ao GitHub, substitua-a no provedor; retirá-la do último commit não apaga o histórico.
