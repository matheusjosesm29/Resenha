import difflib
import re
import unicodedata
from html import unescape

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

        'cast': value('Actors', 2000), 'tags': '', 'poster': value('Poster', 1000),
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
        'cast': '',
        'tags': ', '.join(tag_names[:5])[:2000],
        'poster': value('background_image', '')[:1000],
        'rawg_id': game_id[:50],
    }


# ---------------------------------------------------------------------------
# Livros (Open Library + Google Books) e quadrinhos (Comic Vine)
# ---------------------------------------------------------------------------

USER_AGENT = 'Resenha/1.0 (catalogo de resenhas)'
LEADING_ARTICLES = {'the', 'a', 'an', 'o', 'os', 'as', 'um', 'uma', 'el', 'la', 'los', 'las', 'le', 'les', 'l'}


def fetch_json(url, provider, params=None):
    """GET com timeout, User-Agent identificado e mensagens de erro sem detalhes internos."""
    try:
        response = requests.get(url, params=params, headers={'User-Agent': USER_AGENT}, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        status = getattr(exc.response, 'status_code', None)
        if status in (401, 403):
            raise ValidationError(f'O {provider} recusou a chave de API configurada no servidor.') from None
        if status == 429:
            raise ValidationError(f'Limite de consultas do {provider} atingido. Tente novamente mais tarde.') from None
        raise ValidationError(f'Não foi possível consultar o {provider}. Tente novamente mais tarde.') from None
    except (requests.RequestException, ValueError):
        raise ValidationError(f'Não foi possível consultar o {provider}. Tente novamente mais tarde.') from None


def comparable(value):
    """Normaliza títulos para comparação: sem acentos, pontuação e artigo inicial."""
    value = unicodedata.normalize('NFKD', value if isinstance(value, str) else '')
    value = ''.join(c for c in value if not unicodedata.combining(c)).casefold()
    words = re.sub(r'[^\w\s]', ' ', value).split()
    if len(words) > 1 and words[0] in LEADING_ARTICLES:
        words = words[1:]
    return ' '.join(words)


def similarity(query, candidate):
    return difflib.SequenceMatcher(None, comparable(query), comparable(candidate)).ratio()


def clip(value, limit):
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit - 1].rsplit(' ', 1)[0].rstrip(' ,;:') + '…'


def tidy(value):
    paragraphs = (' '.join(p.split()) for p in re.split(r'\n\s*\n', value))
    return '\n\n'.join(p for p in paragraphs if p)


def html_to_text(value):
    if not isinstance(value, str):
        return ''
    # Tabelas, listas e títulos de seção costumam ser listas de edições, não sinopse.
    value = re.sub(r'(?is)<(table|figure|ul|ol|h[1-6]|script|style)\b.*?</\1>', '\n\n', value)
    value = re.sub(r'(?i)<br\s*/?>|</(p|div|li|blockquote)>', '\n\n', value)
    return tidy(unescape(strip_tags(value)))


def markdown_to_text(value):
    if isinstance(value, dict):
        value = value.get('value', '')
    if not isinstance(value, str):
        return ''
    # O Open Library separa a sinopse de listas como "Also contained in" com uma linha de traços.
    value = re.split(r'\n\s*-{3,}', value, maxsplit=1)[0]
    value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
    value = re.sub(r'\[([^\]]+)\]\[\d+\]', r'\1', value)
    value = re.sub(r'(?m)^\s*\[\d+\]:\s*\S+.*$', '', value)
    value = re.sub(r'(\*\*|\*)(?=\S)(.+?)(?<=\S)\1', r'\2', value)
    return tidy(value)


def parse_year(value):
    match = re.match(r'\s*(\d{4})', str(value or ''))
    year = int(match.group(1)) if match else 0
    return year if 1 <= year <= 2100 else 0


def normalize_isbn(value):
    isbn = re.sub(r'[\s-]', '', value if isinstance(value, str) else '').upper()
    if not re.fullmatch(r'\d{9}[\dX]|\d{13}', isbn):
        raise ValidationError('ISBN inválido. Informe 10 ou 13 dígitos.')
    return isbn


def names(items, limit, sort_by_count=False):
    """Extrai nomes de listas [{'name': ...}], opcionalmente pelos mais frequentes."""
    if not isinstance(items, list):
        return []
    valid = [i for i in items if isinstance(i, dict) and isinstance(i.get('name'), str) and i['name'].strip()]
    if sort_by_count:
        def count(item):
            try:
                return int(item.get('count') or 0)
            except (TypeError, ValueError):
                return 0
        valid.sort(key=count, reverse=True)
    return [i['name'].strip() for i in valid[:limit]]


def lookup_open_library(title='', isbn='', ol_id=''):
    """Busca um livro no Open Library (sem chave) e normaliza para o catálogo.

    A sinopse vem da obra (work), e o ano é o da primeira publicação, não da edição.
    Edições em português são preferidas para título e capa.
    """
    params = {
        'lang': 'por', 'limit': 10,
        'fields': 'key,title,author_name,first_publish_year,cover_i,edition_count,'
                  'editions,editions.title,editions.isbn,editions.cover_i,editions.language',
    }
    if ol_id:
        if not isinstance(ol_id, str) or not re.fullmatch(r'OL\d+W', ol_id):
            raise ValidationError('O identificador do Open Library é inválido (ex.: OL1003040W).')
        params['q'] = f'key:/works/{ol_id}'
    elif isbn:
        isbn = normalize_isbn(isbn)
        params['isbn'] = isbn
    else:
        if not isinstance(title, str) or not title.strip():
            raise ValidationError('Informe o título ou o ISBN do livro.')
        params['q'] = title.strip()

    data = fetch_json('https://openlibrary.org/search.json', 'Open Library', params)
    docs = [d for d in (data.get('docs') if isinstance(data, dict) else None) or []
            if isinstance(d, dict) and isinstance(d.get('key'), str) and d['key'].startswith('/works/')]
    if not docs:
        raise ValidationError('Livro não encontrado no Open Library.')

    def edition_of(doc):
        editions = doc.get('editions') if isinstance(doc.get('editions'), dict) else {}
        found = editions.get('docs') if isinstance(editions.get('docs'), list) else []
        return found[0] if found and isinstance(found[0], dict) else {}

    def rank(doc):
        # Busca por título: o mais parecido; em empate, a obra com mais edições
        # (o Open Library tem muitas duplicatas de uma só edição).
        query = title.strip() if not (isbn or ol_id) else ''
        best = max(similarity(query, doc.get('title', '')), similarity(query, edition_of(doc).get('title', ''))) if query else 0
        return round(best, 1), doc.get('edition_count') or 0

    book = docs[0] if (isbn or ol_id) else max(docs, key=rank)
    edition = edition_of(book)
    work_title = book.get('title') if isinstance(book.get('title'), str) else ''
    edition_title = edition.get('title') if isinstance(edition.get('title'), str) else ''
    languages = edition.get('language') if isinstance(edition.get('language'), list) else []
    use_edition = bool(edition_title) and (
        'por' in languages or (not ol_id and similarity(title or '', edition_title) > similarity(title or '', work_title))
    )
    chosen_title = (edition_title if use_edition else work_title).strip()

    year = parse_year(book.get('first_publish_year'))
    if not year:
        raise ValidationError('O Open Library não retornou um ano de publicação válido.')

    work_id = book['key'].rsplit('/', 1)[-1]
    details = fetch_json(f'https://openlibrary.org/works/{work_id}.json', 'Open Library')
    synopsis = markdown_to_text(details.get('description')) if isinstance(details, dict) else ''
    if not synopsis:
        raise ValidationError('O Open Library não tem sinopse para este livro. Cadastre a obra manualmente.')

    cover_id = (edition.get('cover_i') if use_edition else None) or book.get('cover_i')
    # O ISBN só faz sentido se a edição foi a usada para título e capa.
    edition_isbns = [i for i in edition.get('isbn') or [] if isinstance(i, str)] if use_edition else []
    isbn_value = isbn or next((i for i in edition_isbns if len(i) == 13), '') or next(iter(edition_isbns), '')
    authors = [a for a in book.get('author_name') or [] if isinstance(a, str)]

    return {
        'title': clip(chosen_title, 150),
        'category': 'Livros',
        'year': year,
        'synopsis': clip(synopsis, 3000),
        'creator': clip(', '.join(authors[:3]), 200) or 'Autoria não informada',
        'cast': '',
        'tags': '',
        'poster': f'https://covers.openlibrary.org/b/id/{int(cover_id)}-L.jpg' if str(cover_id or '').isdigit() else '',
        'ol_id': work_id[:50],
        'isbn': isbn_value[:20] or None,
    }


def lookup_google_books(title='', isbn=''):
    """Busca um livro no Google Books. Exige GOOGLE_BOOKS_API_KEY: a cota anônima é zero."""
    if not settings.GOOGLE_BOOKS_API_KEY:
        raise ValidationError('A chave do Google Books ainda não foi configurada no servidor.')
    if isbn:
        isbn = normalize_isbn(isbn)
        query = f'isbn:{isbn}'
    else:
        if not isinstance(title, str) or not title.strip():
            raise ValidationError('Informe o título ou o ISBN do livro.')
        query = f'intitle:{title.strip()}'
    data = fetch_json('https://www.googleapis.com/books/v1/volumes', 'Google Books', {
        'q': query, 'maxResults': 10, 'printType': 'books', 'key': settings.GOOGLE_BOOKS_API_KEY,
    })
    items = [i for i in (data.get('items') if isinstance(data, dict) else None) or []
             if isinstance(i, dict) and isinstance(i.get('volumeInfo'), dict) and i.get('id')]
    if not items:
        raise ValidationError('Livro não encontrado no Google Books.')

    def rank(item):
        info = item['volumeInfo']
        return round(similarity(title, info.get('title', '')), 1) if not isbn else 0, bool(info.get('description'))

    item = max(items, key=rank)
    volume = item['volumeInfo']
    if volume.get('maturityRating') == 'MATURE':
        raise ValidationError('Livro recusado: classificado como conteúdo adulto explícito.')

    year = parse_year(volume.get('publishedDate'))
    if not year:
        raise ValidationError('O Google Books não retornou um ano de publicação válido.')
    synopsis = html_to_text(volume.get('description'))
    if not synopsis:
        raise ValidationError('O Google Books não tem sinopse para este livro. Cadastre a obra manualmente.')

    identifiers = {i.get('type'): i.get('identifier') for i in volume.get('industryIdentifiers') or [] if isinstance(i, dict)}
    images = volume.get('imageLinks') if isinstance(volume.get('imageLinks'), dict) else {}
    poster = (images.get('thumbnail') or images.get('smallThumbnail') or '').replace('http://', 'https://').replace('&edge=curl', '')
    authors = [a for a in volume.get('authors') or [] if isinstance(a, str)]

    return {
        'title': clip(volume.get('title') or '', 150),
        'category': 'Livros',
        'year': year,
        'synopsis': clip(synopsis, 3000),
        'creator': clip(', '.join(authors[:3]), 200) or 'Autoria não informada',
        'cast': '',
        'tags': '',
        'poster': poster[:1000],
        'google_books_id': str(item['id'])[:20],
        'isbn': (isbn or identifiers.get('ISBN_13') or identifiers.get('ISBN_10') or '')[:20] or None,
    }


def lookup_book(title='', isbn='', ol_id=''):
    """Open Library primeiro; Google Books como reserva quando a chave estiver configurada."""
    try:
        return lookup_open_library(title=title, isbn=isbn, ol_id=ol_id)
    except ValidationError as primary:
        if ol_id or not settings.GOOGLE_BOOKS_API_KEY:
            raise
        try:
            return lookup_google_books(title=title, isbn=isbn)
        except ValidationError:
            raise primary from None


COMICVINE_URL = 'https://comicvine.gamespot.com/api'
COMICVINE_ERRORS = {
    100: 'O Comic Vine recusou a chave de API configurada no servidor.',
    101: 'Quadrinho não encontrado no Comic Vine.',
    107: 'Limite de consultas do Comic Vine atingido. Tente novamente mais tarde.',
}


def comicvine_get(path, params):
    data = fetch_json(f'{COMICVINE_URL}/{path}/', 'Comic Vine', {
        'api_key': settings.COMICVINE_API_KEY, 'format': 'json', **params,
    })
    if not isinstance(data, dict):
        raise ValidationError('O Comic Vine retornou uma resposta inválida.')
    if data.get('status_code') != 1:
        raise ValidationError(COMICVINE_ERRORS.get(data.get('status_code'), 'Não foi possível consultar o Comic Vine.'))
    return data.get('results')


def lookup_comicvine(title='', comicvine_id=''):
    """Busca uma série/encadernado (volume) no Comic Vine e normaliza para o catálogo."""
    if not settings.COMICVINE_API_KEY:
        raise ValidationError('A chave do Comic Vine ainda não foi configurada no servidor.')

    if comicvine_id:
        # Aceita "3092" ou o formato do site, "4050-3092".
        match = re.fullmatch(r'(?:4050-)?(\d+)', comicvine_id.strip() if isinstance(comicvine_id, str) else '')
        if not match:
            raise ValidationError('O identificador do Comic Vine é inválido (ex.: 4050-3092).')
        volume_id = match.group(1)
    else:
        if not isinstance(title, str) or not title.strip():
            raise ValidationError('Informe o título do quadrinho para pesquisar no Comic Vine.')
        results = comicvine_get('search', {
            'query': title.strip(), 'resources': 'volume', 'limit': 10,
            'field_list': 'id,name,start_year,count_of_issues',
        })
        candidates = [r for r in results or [] if isinstance(r, dict) and str(r.get('id', '')).isdigit()]
        if not candidates:
            raise ValidationError('Quadrinho não encontrado no Comic Vine.')

        def rank(volume):
            # O mais parecido; em empate, a série principal (mais edições) em vez de reimpressões.
            try:
                issues = int(volume.get('count_of_issues') or 0)
            except (TypeError, ValueError):
                issues = 0
            return round(similarity(title, volume.get('name', '')), 1), issues

        volume_id = str(max(candidates, key=rank)['id'])

    volume = comicvine_get(f'volume/4050-{volume_id}', {
        'field_list': 'id,name,start_year,deck,description,publisher,image,person_credits,character_credits',
    })
    if not isinstance(volume, dict) or not volume.get('id'):
        raise ValidationError('Quadrinho não encontrado no Comic Vine.')

    year = parse_year(volume.get('start_year'))
    if not year:
        raise ValidationError('O Comic Vine não retornou um ano de início válido.')
    synopsis = html_to_text(volume.get('description')) or tidy(unescape(strip_tags(volume.get('deck') or '')))
    if not synopsis:
        raise ValidationError('O Comic Vine não tem sinopse para este quadrinho. Cadastre a obra manualmente.')

    publisher = volume.get('publisher') if isinstance(volume.get('publisher'), dict) else {}
    creators = names(volume.get('person_credits'), 3, sort_by_count=True)
    image = volume.get('image') if isinstance(volume.get('image'), dict) else {}
    poster = image.get('medium_url') or image.get('original_url') or ''
    if not isinstance(poster, str) or poster.endswith('blank.png'):  # imagem padrão do Comic Vine
        poster = ''

    return {
        'title': clip(volume.get('name') or '', 150),
        'category': 'Quadrinhos',
        'year': year,
        'synopsis': clip(synopsis, 3000),
        'creator': clip(', '.join(creators), 200) or (publisher.get('name') or 'Autoria não informada')[:200],
        'cast': '',
        'tags': clip(', '.join(names(volume.get('character_credits'), 5, sort_by_count=True)), 2000),
        'poster': poster[:1000],
        'comicvine_id': str(volume['id'])[:20],
    }
