"""Integrações de livros (Open Library/Google Books) e quadrinhos (Comic Vine), com mocks."""
import json
from unittest.mock import Mock, patch
import requests
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from .models import User, Work


def reply(payload):
    return Mock(json=lambda: payload)


def http_error(status):
    error = requests.HTTPError(response=Mock(status_code=status))
    return Mock(raise_for_status=Mock(side_effect=error))


def ol_search(*docs):
    return reply({'docs': list(docs)})


def ol_doc(key, title, editions=1, edition=None, year=1899, cover=10):
    doc = {'key': f'/works/{key}', 'title': title, 'author_name': ['Machado de Assis'],
           'first_publish_year': year, 'cover_i': cover, 'edition_count': editions}
    if edition:
        doc['editions'] = {'docs': [edition]}
    return doc


CV_VOLUME = {
    'id': 3092, 'name': 'Watchmen', 'start_year': '1986',
    'description': '<p>Who watches the <b>Watchmen</b>? &amp; more.</p>'
                   '<h2>Collected Editions</h2><ul><li>Absolute Watchmen</li></ul>',
    'deck': 'Short deck', 'publisher': {'name': 'DC Comics'},
    'image': {'medium_url': 'https://comicvine.gamespot.com/a/uploads/scale_medium/watchmen.jpg'},
    'person_credits': [{'name': 'Letterer', 'count': '2'}, {'name': 'Alan Moore', 'count': '12'},
                       {'name': 'Dave Gibbons', 'count': '12'}, {'name': 'Colorist', 'count': '1'}],
    'character_credits': [{'name': 'Rorschach', 'count': '12'}, {'name': 'Ozymandias', 'count': '10'}],
}


@override_settings(GOOGLE_BOOKS_API_KEY='', COMICVINE_API_KEY='')
class BooksAndComicsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(username='admin', email='admin@example.org', password='Strong123!Words', is_staff=True)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.staff)
        self.client.get('/')

    def send(self, data):
        return self.client.post('/api/admin/import', json.dumps(data), content_type='application/json',
                                HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    # Livros -----------------------------------------------------------------

    @patch('core.services.requests.get')
    def test_open_library_import_prefers_canonical_work_and_portuguese_edition(self, get):
        get.side_effect = [
            ol_search(
                ol_doc('OL2W', 'O Pequeno Príncipe', editions=1, year=2020),
                ol_doc('OL1W', 'Le petit prince', editions=700, year=1943, edition={
                    'title': 'O pequeno príncipe', 'isbn': ['8522005230', '9788522005239'],
                    'cover_i': 99, 'language': ['por']}),
            ),
            reply({'description': {'type': '/type/text', 'value':
                   '**Le Petit Prince** é um [conto](https://x.org).\n\n----------\nAlso contained in: lista'}}),
        ]
        result = self.send({'source': 'books', 'title': 'O pequeno príncipe'})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(result.json()['created'])
        work = Work.objects.get(ol_id='OL1W')
        self.assertEqual((work.title, work.year, work.category), ('O pequeno príncipe', 1943, 'Livros'))
        self.assertEqual(work.synopsis, 'Le Petit Prince é um conto.')
        self.assertEqual(work.isbn, '9788522005239')
        self.assertEqual(work.poster, 'https://covers.openlibrary.org/b/id/99-L.jpg')
        self.assertEqual(get.call_args_list[0].kwargs['params']['lang'], 'por')
        self.assertIn('Resenha', get.call_args_list[0].kwargs['headers']['User-Agent'])
        get.assert_called_with('https://openlibrary.org/works/OL1W.json', params=None,
                               headers={'User-Agent': 'Resenha/1.0 (catalogo de resenhas)'}, timeout=5)

        # Reimportar a mesma obra não duplica.
        get.side_effect = [ol_search(ol_doc('OL1W', 'Le petit prince', editions=700, year=1943)),
                           reply({'description': 'Texto'})]
        again = self.send({'source': 'books', 'title': 'Le petit prince'})
        self.assertEqual(again.json(), {'id': work.pk, 'created': False})
        self.assertEqual(Work.objects.filter(category='Livros').count(), 1)

    @patch('core.services.requests.get')
    def test_books_without_isbn_do_not_collide_on_unique_field(self, get):
        get.side_effect = [ol_search(ol_doc('OL1W', 'Dom Casmurro')), reply({'description': 'Bentinho.'}),
                           ol_search(ol_doc('OL3W', 'Memórias Póstumas')), reply({'description': 'Brás Cubas.'})]
        self.assertEqual(self.send({'source': 'books', 'title': 'Dom Casmurro'}).status_code, 200)
        self.assertEqual(self.send({'source': 'books', 'title': 'Memórias Póstumas'}).status_code, 200)
        self.assertEqual(list(Work.objects.filter(ol_id__in=['OL1W', 'OL3W']).values_list('isbn', flat=True)), [None, None])

    @patch('core.services.requests.get')
    def test_isbn_is_validated_before_any_request(self, get):
        result = self.send({'source': 'books', 'isbn': '123'})
        self.assertEqual(result.status_code, 400)
        self.assertIn('ISBN inválido', result.json()['error'])
        get.assert_not_called()
        self.assertEqual(self.send({'source': 'books'}).json()['error'], 'Informe o título ou o ISBN do livro.')

    @patch('core.services.requests.get')
    def test_isbn_search_uses_isbn_parameter(self, get):
        get.side_effect = [ol_search(ol_doc('OL9W', 'Nineteen Eighty-Four', year=1949,
                                            edition={'title': '1984', 'language': ['por']})),
                           reply({'description': 'Distopia.'})]
        result = self.client.get('/api/books?isbn=978-85-359-1484-9')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(get.call_args_list[0].kwargs['params']['isbn'], '9788535914849')
        self.assertEqual(result.json()['work']['title'], '1984')
        self.assertEqual(result.json()['work']['isbn'], '9788535914849')
        self.assertFalse(Work.objects.filter(ol_id='OL9W').exists())

    @patch('core.services.requests.get')
    def test_ol_id_lookup_keeps_work_title_and_ignores_foreign_edition_isbn(self, get):
        get.side_effect = [ol_search(ol_doc('OL10263W', 'Le petit prince', year=1943, edition={
                               'title': 'El Principito', 'isbn': ['9788459912013'], 'language': ['spa']})),
                           reply({'description': 'Conto.'})]
        work = self.client.get('/api/books?ol_id=OL10263W').json()['work']
        self.assertEqual((work['title'], work['isbn']), ('Le petit prince', None))
        self.assertEqual(get.call_args_list[0].kwargs['params']['q'], 'key:/works/OL10263W')
        self.assertEqual(self.client.get('/api/books?ol_id=../../etc').status_code, 400)

    @patch('core.services.requests.get')
    def test_book_without_synopsis_is_refused_when_google_books_is_not_configured(self, get):
        get.side_effect = [ol_search(ol_doc('OL1W', 'Grande Sertão')), reply({'title': 'Grande Sertão'})]
        result = self.send({'source': 'books', 'title': 'Grande Sertão'})
        self.assertEqual(result.status_code, 400)
        self.assertIn('não tem sinopse', result.json()['error'])
        self.assertEqual(get.call_count, 2)
        self.assertFalse(Work.objects.filter(ol_id='OL1W').exists())

    @override_settings(GOOGLE_BOOKS_API_KEY='gb-key')
    @patch('core.services.requests.get')
    def test_google_books_is_the_fallback_when_configured(self, get):
        volume = {'id': 'abc123', 'volumeInfo': {
            'title': 'Grande Sertão: Veredas', 'authors': ['João Guimarães Rosa'], 'publishedDate': '2019-05-01',
            'description': '<p>Riobaldo narra sua vida &amp; seus amores.</p>', 'maturityRating': 'NOT_MATURE',
            'industryIdentifiers': [{'type': 'ISBN_13', 'identifier': '9788535932003'}],
            'imageLinks': {'thumbnail': 'http://books.google.com/books/content?id=abc123&edge=curl'}}}
        get.side_effect = [ol_search(), reply({'items': [volume]})]
        result = self.send({'source': 'books', 'title': 'Grande Sertão'})
        self.assertEqual(result.status_code, 200, result.content)
        work = Work.objects.get(google_books_id='abc123')
        self.assertEqual(work.synopsis, 'Riobaldo narra sua vida & seus amores.')
        self.assertEqual(work.poster, 'https://books.google.com/books/content?id=abc123')
        self.assertEqual((work.isbn, work.ol_id, work.year), ('9788535932003', None, 2019))
        self.assertEqual(get.call_args_list[1].kwargs['params']['key'], 'gb-key')

    @override_settings(GOOGLE_BOOKS_API_KEY='gb-key')
    @patch('core.services.requests.get')
    def test_google_books_refuses_mature_books(self, get):
        volume = {'id': 'x', 'volumeInfo': {'title': 'Livro', 'publishedDate': '2020', 'description': 'Texto',
                                             'maturityRating': 'MATURE'}}
        get.side_effect = [ol_search(), reply({'items': [volume]})]
        result = self.send({'source': 'books', 'title': 'Livro'})
        # A mensagem exibida é a da fonte principal; nada é gravado.
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Work.objects.filter(google_books_id='x').exists())

    @patch('core.services.requests.get')
    def test_rate_limit_and_network_failures_return_friendly_errors(self, get):
        get.return_value = http_error(429)
        self.assertIn('Limite de consultas do Open Library', self.send({'source': 'books', 'title': 'X'}).json()['error'])
        get.return_value = None
        get.side_effect = requests.Timeout
        self.assertIn('Não foi possível consultar o Open Library', self.send({'source': 'books', 'title': 'X'}).json()['error'])

    # Quadrinhos ---------------------------------------------------------------

    def test_comicvine_requires_api_key(self):
        result = self.send({'source': 'comicvine', 'title': 'Watchmen'})
        self.assertEqual(result.status_code, 400)
        self.assertIn('chave do Comic Vine', result.json()['error'])

    @override_settings(COMICVINE_API_KEY='cv-key')
    @patch('core.services.requests.get')
    def test_comicvine_import_picks_main_series_and_normalizes_volume(self, get):
        get.side_effect = [
            reply({'status_code': 1, 'results': [
                {'id': 111, 'name': 'Watchmen', 'start_year': '2009', 'count_of_issues': 1},
                {'id': 3092, 'name': 'Watchmen', 'start_year': '1986', 'count_of_issues': 12},
                {'id': 222, 'name': 'Before Watchmen: Rorschach', 'count_of_issues': 4},
            ]}),
            reply({'status_code': 1, 'results': CV_VOLUME}),
        ]
        result = self.send({'source': 'comicvine', 'title': 'Watchmen'})
        self.assertEqual(result.status_code, 200, result.content)
        work = Work.objects.get(comicvine_id='3092')
        self.assertEqual((work.title, work.year, work.category), ('Watchmen', 1986, 'Quadrinhos'))
        self.assertEqual(work.synopsis, 'Who watches the Watchmen? & more.')
        self.assertEqual(work.creator, 'Alan Moore, Dave Gibbons, Letterer')
        self.assertEqual(work.cast, '')
        self.assertEqual(work.tags, 'Rorschach, Ozymandias')
        self.assertTrue(work.poster.endswith('watchmen.jpg'))
        search, detail = get.call_args_list
        self.assertEqual(search.args[0], 'https://comicvine.gamespot.com/api/search/')
        self.assertEqual(search.kwargs['params']['resources'], 'volume')
        self.assertEqual(search.kwargs['params']['api_key'], 'cv-key')
        self.assertEqual(detail.args[0], 'https://comicvine.gamespot.com/api/volume/4050-3092/')
        self.assertIn('Resenha', detail.kwargs['headers']['User-Agent'])

    @override_settings(COMICVINE_API_KEY='cv-key')
    @patch('core.services.requests.get')
    def test_comicvine_lookup_by_id_skips_search_and_does_not_persist(self, get):
        volume = dict(CV_VOLUME, description='', image={'medium_url': 'https://cv.example/6373148-blank.png'})
        get.return_value = reply({'status_code': 1, 'results': volume})
        result = self.client.get('/api/comicvine?comicvine_id=4050-3092')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(result.json()['work']['synopsis'], 'Short deck')
        self.assertEqual(result.json()['work']['poster'], '')
        self.assertFalse(Work.objects.filter(comicvine_id='3092').exists())
        self.assertEqual(self.client.get('/api/comicvine?comicvine_id=abc').status_code, 400)

    @override_settings(COMICVINE_API_KEY='bad-key')
    @patch('core.services.requests.get')
    def test_comicvine_api_errors_are_translated(self, get):
        get.return_value = reply({'status_code': 100, 'error': 'Invalid API Key', 'results': []})
        self.assertIn('recusou a chave', self.send({'source': 'comicvine', 'title': 'X'}).json()['error'])
        get.return_value = reply({'status_code': 1, 'results': []})
        self.assertEqual(self.send({'source': 'comicvine', 'title': 'X'}).json()['error'], 'Quadrinho não encontrado no Comic Vine.')
        get.return_value = reply({'status_code': 1, 'results': dict(CV_VOLUME, start_year=None)})
        self.assertIn('ano de início', self.send({'source': 'comicvine', 'comicvine_id': '3092'}).json()['error'])

    def test_non_staff_cannot_import(self):
        user = User.objects.create_user(username='ana', email='ana@example.org', password='Strong123!Words')
        self.client.force_login(user)
        self.client.get('/')
        self.assertEqual(self.send({'source': 'books', 'title': 'Dom Casmurro'}).status_code, 403)
