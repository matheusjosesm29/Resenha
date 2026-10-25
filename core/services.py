import requests
from django.conf import settings
from django.core.exceptions import ValidationError


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
    """Stub: consulta RAWG API para jogos (requer API key)."""
    if not settings.RAWG_API_KEY:
        raise ValidationError('A chave RAWG ainda não foi configurada no servidor.')
    params = {'key': settings.RAWG_API_KEY, 'search': title}
    try:
        response = requests.get('https://api.rawg.io/api/games', params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise ValidationError('Não foi possível consultar o RAWG. Tente novamente mais tarde.') from None
    results = data.get('results', [])
    if not results:
        raise ValidationError('Jogo não encontrado no RAWG.')
    game = results[0]
    def value(key, default=''):
        return game.get(key, default) or default
    try:
        year = int(str(value('released', ''))[:4]) if value('released') else 0
    except ValueError:
        year = 0
    return {
        'title': value('name', '')[:150],
        'category': 'Jogos',
        'year': year,
        'synopsis': value('description_raw', '')[:3000],
        'creator': ', '.join([p.get('name', '') for p in value('developers', [])])[:200],
        'cast': ', '.join([t.get('name', '') for t in value('tags', [])[:5]])[:2000],
        'poster': value('background_image', '')[:1000],
        'rawg_id': str(game.get('id', ''))[:50],
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
