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
