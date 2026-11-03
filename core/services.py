import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags


def is_adult_focused_game(title, synopsis, tags, esrb_rating):
    """Reject games explicitly labeled as pornographic, not general mature titles."""
    explicit_tags = {'nsfw', 'hentai', 'eroge', 'erotic', 'porn', 'pornographic'}
    title_terms = (
        'porn', 'hentai', 'futanari', 'nymphomania', 'deepthroat',
        'pregnation', 'adult game', 'erotic game', 'sex simulator',
    )
    description_phrases = (
        'adult-only', 'adult only', 'adult scenes',
        'adult-oriented content', 'adult oriented content',
        'sex game', 'hentai', 'eroge', 'pornographic', 'sexually explicit',
        'explicit sex', 'h-scenes', 'h scenes',
    )

    normalized_tags = set()
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str):
                normalized_tags.add(tag.strip().casefold())
            elif isinstance(tag, dict):
                for value in (tag.get('name'), tag.get('slug')):
                    if isinstance(value, str):
                        normalized_tags.add(value.strip().casefold().replace('_', '-'))
    elif isinstance(tags, dict) and isinstance(tags.get('results'), list):
        return is_adult_focused_game(title, synopsis, tags['results'], esrb_rating)

    if normalized_tags & explicit_tags:
        return True

    if isinstance(esrb_rating, dict):
        rating = esrb_rating.get('slug') or esrb_rating.get('name') or ''
        if isinstance(rating, str) and rating.strip().casefold().replace('_', '-') in {
            'adults-only', 'adults only', 'ao',
        }:
            return True

    normalized_title = title.casefold() if isinstance(title, str) else ''
    normalized_synopsis = synopsis.casefold() if isinstance(synopsis, str) else ''
    return (
        any(term in normalized_title for term in title_terms)
        or any(phrase in normalized_synopsis for phrase in description_phrases)
    )


def lookup_omdb(title='', imdb_id=''):
    if not settings.OMDB_API_KEY:
        raise ValidationError('A chave OMDb ainda não foi configurada no servidor.')
    params = {'apikey': settings.OMDB_API_KEY, 'plot': 'full'}
    params.update({'i': imdb_id} if imdb_id else {'t': title})
    try:
        response = requests.get('https://www.omdbapi.com/', params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise ValidationError('Não foi possível consultar o OMDb. Tente novamente mais tarde.') from None
    if not isinstance(data, dict) or data.get('Response') != 'True':
        raise ValidationError('Obra não encontrada no OMDb.')
    if data.get('Type') not in ['movie', 'series']:
        raise ValidationError('Este tipo de obra não é suportado pela importação.')
    def value(key, limit):
        return (data.get(key, '') if data.get(key) != 'N/A' else '')[:limit]
    try:
        year = int(data.get('Year', '')[:4])
    except ValueError:
        raise ValidationError('O OMDb retornou um ano inválido.') from None
    return {
        'title': value('Title', 150), 'category': 'Séries' if data['Type'] == 'series' else 'Filmes',
        'year': year, 'synopsis': value('Plot', 3000), 'creator': value('Director', 200) or value('Writer', 200),
        'cast': value('Actors', 2000), 'poster': value('Poster', 1000),
        'imdb_id': value('imdbID', 20),
    }


def lookup_rawg(title='', rawg_id=''):
    """Busca um jogo no RAWG e normaliza seus dados para o catálogo."""
    if not settings.RAWG_API_KEY:
        raise ValidationError('A chave RAWG ainda não foi configurada no servidor.')

    if rawg_id:
        if not isinstance(rawg_id, str) or not rawg_id.isdigit():
            raise ValidationError('O identificador RAWG é inválido.')
        detail_url = f'https://api.rawg.io/api/games/{rawg_id}'
    else:
        if not isinstance(title, str) or not title.strip():
            raise ValidationError('Informe o título do jogo para pesquisar no RAWG.')
        params = {'key': settings.RAWG_API_KEY, 'search': title.strip(), 'page_size': 1}
        try:
            response = requests.get('https://api.rawg.io/api/games', params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            raise ValidationError('Não foi possível consultar o RAWG. Tente novamente mais tarde.') from None
        if not isinstance(data, dict) or not isinstance(data.get('results'), list) or not data['results']:
            raise ValidationError('Jogo não encontrado no RAWG.')
        game = data['results'][0]
        if not isinstance(game, dict) or not str(game.get('id', '')).isdigit():
            raise ValidationError('O RAWG retornou um jogo inválido.')
        detail_url = f"https://api.rawg.io/api/games/{game['id']}"

    try:
        response = requests.get(detail_url, params={'key': settings.RAWG_API_KEY}, timeout=5)
        response.raise_for_status()
        details = response.json()
    except (requests.RequestException, ValueError):
        raise ValidationError('Não foi possível consultar o RAWG. Tente novamente mais tarde.') from None

    if not isinstance(details, dict) or not details.get('id'):
        raise ValidationError('Jogo não encontrado no RAWG.')
    game = details

    def value(key, default=''):
        result = game.get(key, default)
        return result if isinstance(result, str) else default

    try:
        year = int(value('released')[:4])
    except (TypeError, ValueError):
        raise ValidationError('O RAWG não retornou um ano de lançamento válido.') from None
    if not 1 <= year <= 2100:
        raise ValidationError('O RAWG não retornou um ano de lançamento válido.')

    synopsis = value('description_raw').strip() or strip_tags(value('description')).strip()
    if not synopsis:
        raise ValidationError('O RAWG não retornou uma descrição para este jogo.')

    developers = game.get('developers', [])
    developer_names = [
        item['name'] for item in developers
        if isinstance(item, dict) and isinstance(item.get('name'), str) and item['name'].strip()
    ] if isinstance(developers, list) else []
    tags = game.get('tags', [])
    tag_names = [
        item['name'] for item in tags
        if isinstance(item, dict) and isinstance(item.get('name'), str) and item['name'].strip()
    ] if isinstance(tags, list) else []
    title = value('name').strip()
    if is_adult_focused_game(title, synopsis, tags, game.get('esrb_rating')):
        raise ValidationError('Jogo recusado: foco em conteúdo adulto explícito.')

    game_id = str(game['id'])

    return {
        'title': title[:150],
        'category': 'Jogos',
        'year': year,
        'synopsis': synopsis[:3000],
        'creator': ', '.join(developer_names)[:200] or 'Desenvolvedor não informado',
        'cast': ', '.join(tag_names[:5])[:2000],
        'poster': value('background_image', '')[:1000],
        'rawg_id': game_id[:50],
    }


def lookup_google_books(title='', isbn=''):
    """Stub: consulta Google Books API para livros."""
    params = {'q': isbn if isbn else f'intitle:{title}', 'maxResults': 1}
    try:
        response = requests.get('https://www.googleapis.com/books/v1/volumes', params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise ValidationError('Não foi possível consultar o Google Books. Tente novamente mais tarde.') from None
    items = data.get('items', [])
    if not items:
        raise ValidationError('Livro não encontrado no Google Books.')
    volume = items[0].get('volumeInfo', {})
    def value(key, default=''):
        return volume.get(key, default) or default
    try:
        year = int(str(value('publishedDate', ''))[:4]) if value('publishedDate') else 0
    except ValueError:
        year = 0
    isbns = volume.get('industryIdentifiers', [])
    isbn_val = ''
    for ident in isbns:
        if ident.get('type') in ('ISBN_13', 'ISBN_10'):
            isbn_val = ident.get('identifier', '')
            break
    return {
        'title': value('title', '')[:150],
        'category': 'Livros',
        'year': year,
        'synopsis': value('description', '')[:3000],
        'creator': ', '.join(value('authors', []))[:200],
        'cast': value('publisher', '')[:2000],
        'poster': value('imageLinks', {}).get('thumbnail', '')[:1000].replace('http://', 'https://'),
        'isbn': isbn_val[:20],
    }


def lookup_open_library(title='', ol_id=''):
    """Stub: consulta Open Library API para livros (fallback gratuito)."""
    params = {'q': title, 'limit': 1}
    try:
        response = requests.get('https://openlibrary.org/search.json', params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise ValidationError('Não foi possível consultar o Open Library. Tente novamente mais tarde.') from None
    docs = data.get('docs', [])
    if not docs:
        raise ValidationError('Livro não encontrado no Open Library.')
    book = docs[0]
    def value(key, default=''):
        return book.get(key, default) or default
    try:
        year = int(value('first_publish_year', 0)) if value('first_publish_year') else 0
    except ValueError:
        year = 0
    return {
        'title': value('title', '')[:150],
        'category': 'Livros',
        'year': year,
        'synopsis': '',
        'creator': ', '.join(value('author_name', []))[:200],
        'cast': ', '.join(value('publisher', [])[:3])[:2000],
        'poster': f"https://covers.openlibrary.org/b/id/{book.get('cover_i')}-M.jpg" if book.get('cover_i') else '',
        'ol_id': value('key', '').replace('/works/', '')[:50],
    }
