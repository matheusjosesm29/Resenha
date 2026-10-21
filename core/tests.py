import json
from unittest.mock import Mock, patch
import requests
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from .models import User, Work, Review, Comment, Like, LibraryEntry, Report


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='ana', email='ana@example.org', password='Strong123!Words', first_name='Ana')
        self.other = User.objects.create_user(username='bia', email='bia@example.org', password='Strong123!Words', first_name='Bia')
        self.staff = User.objects.create_user(username='admin', email='admin@example.org', password='Strong123!Words', is_staff=True)
        self.work = Work.objects.create(title='Obra', category='Livros', year=2024, synopsis='Sinopse', creator='Autora')
        self.client = Client(enforce_csrf_checks=True)
        self.client.get('/')

    def send(self, path, data=None, method='post', client=None, csrf=True):
        client = client or self.client
        headers = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value} if csrf else {}
        return getattr(client, method)('/api/'+path, json.dumps(data or {}), content_type='application/json', **headers)

    def sign_in(self, user=None):
        user = user or self.user
        self.client.force_login(user)
        self.client.get('/')

    def review(self, user=None):
        return Review.objects.create(work=self.work, user=user or self.user, score=8, text='Uma resenha.')

    def test_public_state_and_no_private_data(self):
        self.review()
        self.assertEqual(self.client.get('/api/state').status_code, 200)
        data = self.client.get('/api/state').json()
        self.assertEqual(data['works'][0]['score'], 8)
        self.assertNotIn('email', data['profile'])
        self.assertEqual(data['users'], [])
        public = self.client.get(f'/api/profiles/{self.user.pk}').json()
        self.assertEqual(public['name'], 'Ana')
        self.assertNotIn('email', public)

    def test_csrf_required_for_login_and_mutation(self):
        result = self.send('login', {'email': self.user.email, 'password': 'Strong123!Words'}, csrf=False)
        self.assertEqual(result.status_code, 403)
        self.sign_in()
        self.assertEqual(self.send('reviews', {'work': self.work.pk, 'score': 8, 'text': 'x'}, csrf=False).status_code, 403)

    def test_register_hashes_password_and_login_logout(self):
        result = self.send('register', {'email': 'NEW@example.org', 'name': 'Novo', 'password': 'A-secure-long-123!Pass'})
        self.assertEqual(result.status_code, 200, result.content)
        user = User.objects.get(email='new@example.org')
        self.assertNotEqual(user.password, 'A-secure-long-123!Pass')
        self.assertTrue(user.check_password('A-secure-long-123!Pass'))
        self.assertEqual(self.send('logout').status_code, 200)
        self.assertFalse(self.client.get('/api/state').json()['authenticated'])
        self.assertEqual(self.send('login', {'email': 'NEW@example.org', 'password': 'A-secure-long-123!Pass'}).status_code, 200)

    def test_invalid_and_duplicate_registration(self):
        self.assertEqual(self.send('register', {'email': 'invalid', 'name': 'X', 'password': '123'}).status_code, 400)
        self.assertEqual(self.send('register', {'email': self.user.email.upper(), 'name': 'X', 'password': 'Strong123!Words'}).status_code, 409)

    def test_anonymous_cannot_write(self):
        self.assertEqual(self.send('reviews', {'work': self.work.pk, 'score': 7, 'text': 'x'}).status_code, 401)

    def test_score_validation_unique_review_and_average(self):
        self.sign_in()
        for score in [-1, 11, 'NaN', 8.123, True]:
            self.assertEqual(self.send('reviews', {'work': self.work.pk, 'score': score, 'text': 'texto'}).status_code, 400)
        self.assertEqual(self.send('reviews', {'work': self.work.pk, 'score': 7.5, 'text': 'texto', 'spoiler': True}).status_code, 201)
        self.assertEqual(self.send('reviews', {'work': self.work.pk, 'score': 8, 'text': 'texto'}).status_code, 409)
        Review.objects.create(user=self.other, work=self.work, score=9.5, text='Outra')
        self.assertEqual(self.client.get('/api/state').json()['works'][0]['score'], 8.5)

    def test_only_owner_can_modify_review(self):
        r = self.review(self.other)
        self.sign_in()
        self.assertEqual(self.send(f'reviews/{r.pk}', {'score': 5, 'text': 'ataque'}, 'patch').status_code, 403)
        self.assertEqual(self.send(f'reviews/{r.pk}', method='delete').status_code, 403)
        self.sign_in(self.other)
        self.assertEqual(self.send(f'reviews/{r.pk}', {'score': 5, 'text': 'editado'}, 'patch').status_code, 200)

    def test_likes_toggle_and_prevent_self_vote(self):
        r = self.review(self.other)
        self.sign_in()
        self.assertEqual(self.send(f'reviews/{r.pk}/like').status_code, 200)
        self.assertEqual(Like.objects.count(), 1)
        self.send(f'reviews/{r.pk}/like')
        self.assertEqual(Like.objects.count(), 0)
        own = self.review()
        self.assertEqual(self.send(f'reviews/{own.pk}/like').status_code, 400)

    def test_comments_and_library_are_persistent_and_private(self):
        r = self.review(self.other)
        self.sign_in()
        self.assertEqual(self.send(f'reviews/{r.pk}/comments', {'text': '<script>alert(1)</script>'}).status_code, 201)
        self.assertEqual(Comment.objects.get().text, '<script>alert(1)</script>')
        self.assertEqual(self.send(f'library/{self.work.pk}', {'status': 'Finalizado', 'favorite': True}, 'patch').status_code, 200)
        self.assertTrue(LibraryEntry.objects.get().favorite)
        self.sign_in(self.other)
        self.assertEqual(self.client.get('/api/state').json()['favorites'], [])
        self.assertEqual(self.send(f'comments/{Comment.objects.get().pk}', method='delete').status_code, 403)

    def test_staff_gate_and_catalog_crud(self):
        self.sign_in()
        data = {'title': 'Novo', 'category': 'Jogos', 'year': 2025, 'synopsis': 'Texto', 'creator': 'Studio'}
        self.assertEqual(self.send('admin/works', data).status_code, 403)
        self.sign_in(self.staff)
        result = self.send('admin/works', data)
        self.assertEqual(result.status_code, 201, result.content)
        self.assertEqual(self.send('admin/works/'+str(result.json()['id']), method='delete').status_code, 200)

    def test_moderation_records_decision_and_blocks_user(self):
        r = self.review(self.other)
        self.sign_in()
        self.assertEqual(self.send('reports', {'review': r.pk, 'reason': 'Ofensa'}).status_code, 201)
        self.assertEqual(self.send('reports', {'review': r.pk, 'reason': 'Ofensa'}).status_code, 409)
        report = Report.objects.get()
        self.assertEqual(self.send(f'admin/reports/{report.pk}', {'action': 'block'}).status_code, 403)
        self.sign_in(self.staff)
        self.assertEqual(self.send(f'admin/reports/{report.pk}', {'action': 'block'}).status_code, 200)
        self.other.refresh_from_db()
        report.refresh_from_db()
        self.assertFalse(self.other.is_active)
        self.assertTrue(report.resolved)
        self.assertEqual(report.snapshot, 'Uma resenha.')
        self.assertFalse(Review.objects.filter(pk=r.pk).exists())

    def test_cannot_block_admin_and_blocked_session_cannot_write(self):
        self.sign_in(self.staff)
        self.assertEqual(self.send(f'admin/users/{self.staff.pk}', {'active': False}, 'patch').status_code, 403)
        self.sign_in()
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.send(f'library/{self.work.pk}', {'favorite': True}, 'patch').status_code, 401)

    def test_password_recovery_generic_response_and_valid_token(self):
        existing = self.send('password-reset', {'email': self.user.email})
        unknown = self.send('password-reset', {'email': 'unknown@example.org'})
        self.assertEqual(existing.json(), unknown.json())
        self.assertEqual(len(mail.outbox), 1)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        result = self.client.get(f'/accounts/reset/{uid}/{token}/')
        self.assertEqual(result.status_code, 302)
        page = self.client.get(result.url)
        self.assertContains(page, 'Salvar nova senha')
        result = self.client.post(result.url, {'new_password1': 'AnotherStrong123!Pass', 'new_password2': 'AnotherStrong123!Pass', 'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value})
        self.assertEqual(result.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('AnotherStrong123!Pass'))
        self.assertFalse(default_token_generator.check_token(self.user, token))

    @override_settings(OMDB_API_KEY='test-key')
    @patch('core.services.requests.get')
    def test_omdb_timeout_and_import(self, get):
        get.side_effect = requests.Timeout()
        result = self.client.get('/api/omdb?title=Obra')
        self.assertEqual(result.status_code, 400)
        get.assert_called_with('https://www.omdbapi.com/', params={'apikey': 'test-key', 'plot': 'full', 't': 'Obra'}, timeout=5)
        get.side_effect = None
        get.return_value = Mock(json=lambda: {'Response': 'True', 'Title': 'Filme', 'Type': 'movie', 'Year': '2024', 'Plot': 'Texto', 'Director': 'Diretor', 'Actors': 'Elenco', 'Poster': 'https://example.org/poster.jpg', 'imdbID': 'tt1234567'})
        self.sign_in(self.staff)
        for _ in range(2):
            self.assertEqual(self.send('admin/import', {'title': 'Filme'}).status_code, 200)
        self.assertEqual(Work.objects.filter(imdb_id='tt1234567').count(), 1)

    def test_invalid_input_does_not_crash(self):
        self.sign_in()
        self.assertEqual(self.send('reviews', {'work': 'invalid', 'score': 7, 'text': 'x'}).status_code, 400)
        self.assertEqual(self.send('profile', {'name': 'Novo', 'bio': '', 'avatar': 'data:image/png;base64,invalid'}, 'patch').status_code, 400)
        self.assertEqual(self.send(f'library/{self.work.pk}', {'status': 'invalid'}, 'patch').status_code, 400)
