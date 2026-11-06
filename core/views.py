"""API da primeira versão; autorização e validação são feitas no servidor."""
import base64
import io
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from PIL import Image, UnidentifiedImageError
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import User, Work, Review, Comment, Like, LibraryEntry, Report
from .services import lookup_book, lookup_comicvine, lookup_omdb, lookup_rawg

# Identificadores externos usados para não importar a mesma obra duas vezes.
EXTERNAL_IDS = ['imdb_id', 'rawg_id', 'ol_id', 'google_books_id', 'isbn', 'comicvine_id']
IMPORT_LABELS = {'omdb': 'OMDb', 'rawg': 'RAWG', 'books': 'Open Library/Google Books', 'comicvine': 'Comic Vine'}


def response(data=None, status=200):
    return JsonResponse(data or {'ok': True}, status=status)


def fail(message, status=400):
    return response({'error': message}, status)


def display(user):
    return user.first_name or user.username


@ensure_csrf_cookie
def index(request):
    return render(request, 'index.html')


def profile_data(user):
    return {'id': user.pk, 'name': display(user), 'bio': user.bio, 'avatar': user.avatar,
            'staff': user.is_staff, 'email': user.email}


def serialize_work(w):
    return {'id': w.pk, 'title': w.title, 'category': w.category, 'year': w.year,
            'synopsis': w.synopsis, 'creator': w.creator, 'cast': w.cast, 'poster': w.poster,
            'color': w.color, 'score': float(w.average or 0), 'count': w.review_count,
            'imdb_id': w.imdb_id, 'rawg_id': w.rawg_id, 'ol_id': w.ol_id, 'isbn': w.isbn,
            'google_books_id': w.google_books_id, 'comicvine_id': w.comicvine_id}


def works_list(request):
    user = request.user
    works = Work.objects.annotate(
        average=Avg('reviews__score'),
        review_count=Count('reviews')
    )

    # Filtros
    category = request.GET.get('category')
    if category and category != 'Todos':
        works = works.filter(category=category)

    query = request.GET.get('query', '').strip()
    if query:
        works = works.filter(title__icontains=query)

    year_min = request.GET.get('year_min')
    if year_min:
        try:
            works = works.filter(year__gte=int(year_min))
        except ValueError:
            pass

    year_max = request.GET.get('year_max')
    if year_max:
        try:
            works = works.filter(year__lte=int(year_max))
        except ValueError:
            pass

    score_min = request.GET.get('score_min')
    if score_min:
        try:
            works = works.filter(average__gte=float(score_min))
        except ValueError:
            pass

    # Ordenações
    order = request.GET.get('order', 'score')
    now = timezone.now()
    if order == 'trending':
        cutoff = now - timedelta(days=14)
        works = works.annotate(
            recent_count=Count('reviews', filter=Q(reviews__created_at__gte=cutoff)),
            recent_likes=Count('reviews__likes', filter=Q(reviews__created_at__gte=cutoff)),
        ).order_by('-recent_likes', '-recent_count', '-average')
    elif order == 'popular':
        works = works.order_by('-review_count', '-average')
    elif order == 'year':
        works = works.order_by('-year', '-average')
    elif order == 'count':
        works = works.order_by('-review_count', '-average')
    else:  # score
        works = works.order_by('-average', '-review_count')

    # Paginação
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(100, max(1, int(request.GET.get('page_size', 24))))
    except (TypeError, ValueError):
        page_size = 24

    total = works.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    page_works = works[start:end]

    return response({
        'works': [serialize_work(w) for w in page_works],
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'has_next': end < total,
    })


def state(request):
    user = request.user
    # Primeira versão: carregamento completo do catálogo; paginação prevista para crescimento.
    works = Work.objects.annotate(average=Avg('reviews__score'), review_count=Count('reviews'))
    reviews = Review.objects.select_related('user', 'work').prefetch_related('comments__user', 'likes').order_by('created_at')
    data = {
        'works': [serialize_work(w) for w in works],
        'reviews': [{
            'id': str(r.pk), 'work': r.work_id, 'userId': r.user_id, 'name': display(r.user),
            'score': float(r.score), 'text': r.text, 'spoiler': r.spoiler,
            'date': int(r.created_at.timestamp() * 1000), 'own': user.is_authenticated and r.user_id == user.pk,
            'likes': r.likes.count(), 'liked': user.is_authenticated and any(l.user_id == user.pk for l in r.likes.all()),
            'comments': [{'id': c.pk, 'name': display(c.user), 'text': c.text, 'own': user.is_authenticated and c.user_id == user.pk} for c in r.comments.all()],
        } for r in reviews],
        'profile': profile_data(user) if user.is_authenticated else {'name': 'Visitante', 'bio': '', 'avatar': '', 'staff': False},
        'authenticated': user.is_authenticated, 'csrf': get_token(request),
        'favorites': [], 'statuses': {}, 'reports': [], 'users': [], 'blocked': [],
    }
    if user.is_authenticated:
        for entry in user.library.all():
            if entry.favorite:
                data['favorites'].append(entry.work_id)
            if entry.status:
                data['statuses'][entry.work_id] = entry.status
    if user.is_authenticated and user.is_staff:
        data['reports'] = [{
            'id': str(p.pk), 'review': str(p.review_id) if p.review_id else None,
            'comment': p.comment_id, 'reason': p.reason, 'context': p.context, 'snapshot': p.snapshot,
        } for p in Report.objects.filter(resolved=False)]
        data['users'] = [{'id': u.pk, 'name': display(u), 'active': u.is_active, 'staff': u.is_staff} for u in User.objects.all()]
    return response(data)


def text(data, key, maximum, required=True):
    value = data.get(key, '')
    if not isinstance(value, str):
        raise ValidationError(f'Campo {key} inválido.')
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise ValidationError(f'Preencha {key} com até {maximum} caracteres.')
    return value


def flag(data, key):
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise ValidationError(f'Campo {key} inválido.')
    return value


def score_value(data):
    try:
        score = Decimal(str(data.get('score')))
        if not score.is_finite() or not 0 <= score <= 10 or score != score.quantize(Decimal('0.1')):
            raise ValueError
        return score
    except (InvalidOperation, ValueError):
        raise ValidationError('Informe uma nota de 0 a 10, com até uma casa decimal.') from None


def throttle(request, scope, maximum=12):
    # Limite por processo no ambiente local; em produção use cache compartilhado (Redis).
    key = f'{scope}:{request.META.get("REMOTE_ADDR", "")}'
    count = cache.get(key, 0)
    if count >= maximum:
        return False
    cache.set(key, count + 1, 300)
    return True


def authenticated(request):
    return request.user.is_authenticated and request.user.is_active


def change_work(data, instance=None):
    instance = instance or Work()
    for field, limit in [('title', 150), ('synopsis', 3000), ('creator', 200), ('cast', 2000)]:
        setattr(instance, field, text(data, field, limit, required=field in ['title', 'synopsis']))
    instance.category = text(data, 'category', 20)
    if instance.category not in dict(Work.CATEGORIES):
        raise ValidationError('Categoria inválida.')
    year = data.get('year')
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 2100:
        raise ValidationError('Ano inválido.')
    instance.year = year
    instance.color = data.get('color', '#3a4551')
    if not isinstance(instance.color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', instance.color):
        raise ValidationError('Cor inválida.')
    poster = data.get('poster', '')
    if not isinstance(poster, str):
        raise ValidationError('URL da imagem inválida.')
    poster = poster.strip()
    if len(poster) > 1000 or (poster and not re.match(r'^https?://', poster)):
        raise ValidationError('Informe uma URL de imagem http(s) válida, com até 1000 caracteres.')
    instance.poster = poster
    instance.full_clean()
    instance.save()
    return instance


def lookup_external(source, values):
    """Consulta uma fonte externa por título ou identificador, sem gravar no banco."""
    def optional(key, maximum):
        return text({key: values.get(key) or ''}, key, maximum, required=False)

    if source == 'books':
        isbn, ol_id = optional('isbn', 20), optional('ol_id', 50)
        if isbn or ol_id:
            return lookup_book(isbn=isbn, ol_id=ol_id)
        title = optional('title', 150)
        if not title:
            raise ValidationError('Informe o título ou o ISBN do livro.')
        return lookup_book(title=title)
    if source == 'comicvine':
        comicvine_id = optional('comicvine_id', 20)
        if comicvine_id:
            return lookup_comicvine(comicvine_id=comicvine_id)
        title = optional('title', 150)
        if not title:
            raise ValidationError('Informe o título ou o ID do Comic Vine.')
        return lookup_comicvine(title=title)
    title = text({'title': values.get('title', '')}, 'title', 150)
    return lookup_rawg(title=title) if source == 'rawg' else lookup_omdb(title=title)


def api(request, route):
    if request.method not in ['GET', 'POST', 'PATCH', 'DELETE']:
        return fail('Método não permitido.', 405)
    try:
        data = {}
        if request.body:
            data = json.loads(request.body)
            if not isinstance(data, dict):
                return fail('JSON inválido.')
        with transaction.atomic():
            return dispatch(request, route.strip('/'), data)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
        return fail('JSON inválido.')
    except ValidationError as exc:
        return fail(' '.join(exc.messages))
    except (Work.DoesNotExist, Review.DoesNotExist, Comment.DoesNotExist, User.DoesNotExist, Report.DoesNotExist):
        return fail('Registro não encontrado.', 404)
    except IntegrityError:
        return fail('O registro já existe ou entra em conflito com outro registro.', 409)


def dispatch(request, route, data):
    method = request.method
    parts = route.split('/')
    if route == 'state' and method == 'GET':
        return state(request)
    if route in ['register', 'login', 'password-reset'] and method == 'POST':
        if not throttle(request, route):
            return fail('Muitas tentativas. Aguarde alguns minutos.', 429)
        email = text(data, 'email', 254).lower()
        validate_email(email)
        if route == 'password-reset':
            form = PasswordResetForm({'email': email})
            if form.is_valid():
                try:
                    form.save(request=request, use_https=request.is_secure(), from_email=settings.DEFAULT_FROM_EMAIL)
                except Exception as exc:
                    # Não revelar existência de conta ou dados de SMTP na resposta.
                    import logging
                    logging.getLogger(__name__).error('Falha no envio de recuperação (%s).', type(exc).__name__)
            return response({'message': 'Se houver uma conta com esse e-mail, enviaremos as instruções.'})
        password = data.get('password', '')
        if not isinstance(password, str) or not password or len(password) > 128:
            raise ValidationError('Senha inválida.')
        if route == 'register':
            name = text(data, 'name', 80)
            if User.objects.filter(email__iexact=email).exists():
                return fail('Não foi possível cadastrar este e-mail.', 409)
            user = User(username=uuid.uuid4().hex, email=email, first_name=name)
            validate_password(password, user)
            user.set_password(password)
            user.full_clean()
            user.save()
        else:
            candidate = User.objects.filter(email__iexact=email).first()
            user = authenticate(request, username=candidate.username if candidate else 'invalid-user', password=password)
            if user is None:
                return fail('E-mail ou senha inválidos.', 401)
        login(request, user)
        return response({'profile': profile_data(user), 'csrf': get_token(request)})
    if route == 'logout' and method == 'POST':
        logout(request)
        return response({'csrf': get_token(request)})
    # Consulta externa pública sem gravação. Somente administradores importam no catálogo.
    if route == 'omdb' and method == 'GET':
        if not throttle(request, 'omdb', 20):
            return fail('Limite de consultas atingido. Tente novamente depois.', 429)
        title = text({'title': request.GET.get('title', '')}, 'title', 150)
        return response({'work': lookup_omdb(title=title)})
    if route == 'rawg' and method == 'GET':
        if not throttle(request, 'rawg', 20):
            return fail('Limite de consultas atingido. Tente novamente depois.', 429)
        rawg_id = request.GET.get('rawg_id', '')
        if rawg_id:
            imported = lookup_rawg(rawg_id=rawg_id)
        else:
            title = text({'title': request.GET.get('title', '')}, 'title', 150)
            imported = lookup_rawg(title=title)
        return response({'work': imported})
    if route in ['books', 'comicvine'] and method == 'GET':
        if not throttle(request, route, 20):
            return fail('Limite de consultas atingido. Tente novamente depois.', 429)
        return response({'work': lookup_external(route, request.GET)})
    if len(parts) == 2 and parts[0] == 'profiles' and parts[1].isdigit() and method == 'GET':
        target = User.objects.get(pk=parts[1])
        return response({'id': target.pk, 'name': display(target), 'bio': target.bio, 'avatar': target.avatar,
                         'favorites': list(target.library.filter(favorite=True).values_list('work_id', flat=True)),
                         'statuses': {str(e.work_id): e.status for e in target.library.exclude(status='')}})
    # Catálogo e busca públicos: qualquer visitante navega sem conta.
    # Apenas as ações de escrita (resenhas, curtidas, listas, denúncias) exigem login.
    if route == 'works' and method == 'GET':
        return works_list(request)
    if not authenticated(request):
        return fail('Entre na sua conta para continuar.', 401)
    user = request.user
    if route == 'profile' and method == 'PATCH':
        name, bio = text(data, 'name', 80), text(data, 'bio', 300, False)
        avatar = data.get('avatar', user.avatar)
        if avatar != user.avatar and avatar:
            if not isinstance(avatar, str) or not re.match(r'^data:image/(png|jpeg|webp);base64,', avatar) or len(avatar) > 1500000:
                raise ValidationError('Imagem inválida ou maior que 1 MB.')
            try:
                raw = base64.b64decode(avatar.split(',', 1)[1], validate=True)
                if len(raw) > 1048576:
                    raise ValueError
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > 16000000:
                        raise ValueError
                    image.thumbnail((400, 400))
                    output = io.BytesIO()
                    image.convert('RGB').save(output, 'JPEG', quality=85)
                    avatar = 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()
            except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
                raise ValidationError('Não foi possível processar a imagem.') from None
        if not isinstance(avatar, str):
            raise ValidationError('Avatar inválido.')
        user.first_name, user.bio, user.avatar = name, bio, avatar
        user.save(update_fields=['first_name', 'bio', 'avatar'])
        return response({'profile': profile_data(user)})
    if route == 'reviews' and method == 'POST':
        work = Work.objects.get(pk=data.get('work'))
        review = Review.objects.create(user=user, work=work, score=score_value(data), text=text(data, 'text', 5000), spoiler=flag(data, 'spoiler'))
        return response({'id': review.pk}, 201)
    if parts[0] == 'reviews' and len(parts) >= 2 and parts[1].isdigit():
        review = Review.objects.get(pk=parts[1])
        if len(parts) == 2 and method in ['PATCH', 'DELETE']:
            if review.user_id != user.pk:
                return fail('Você só pode alterar suas próprias resenhas.', 403)
            if method == 'DELETE':
                review.delete()
            else:
                review.score, review.text, review.spoiler = score_value(data), text(data, 'text', 5000), flag(data, 'spoiler')
                review.save()
            return response()
        if len(parts) == 3 and parts[2] == 'like' and method == 'POST':
            if review.user_id == user.pk:
                return fail('Você não pode curtir sua própria resenha.')
            with transaction.atomic():
                review = Review.objects.select_for_update().get(pk=review.pk)
                like, created = Like.objects.get_or_create(user=user, review=review)
                if not created:
                    like.delete()
            return response({'liked': created})
        if len(parts) == 3 and parts[2] == 'comments' and method == 'POST':
            comment = Comment.objects.create(user=user, review=review, text=text(data, 'text', 2000))
            return response({'id': comment.pk}, 201)
    if parts[0] == 'comments' and len(parts) == 2 and parts[1].isdigit() and method == 'DELETE':
        comment = Comment.objects.get(pk=parts[1])
        if comment.user_id != user.pk and not user.is_staff:
            return fail('Sem permissão para excluir este comentário.', 403)
        comment.delete()
        return response()
    if parts[0] == 'library' and len(parts) == 2 and parts[1].isdigit() and method == 'PATCH':
        work = Work.objects.get(pk=parts[1])
        with transaction.atomic():
            # Serializa alterações para impedir perda de atualização de favoritos/status.
            User.objects.select_for_update().get(pk=user.pk)
            entry, _ = LibraryEntry.objects.get_or_create(user=user, work=work)
            if 'favorite' in data:
                entry.favorite = flag(data, 'favorite')
            if 'status' in data:
                value = data['status']
                if value not in ['', *dict(LibraryEntry.STATUSES)]:
                    raise ValidationError('Status inválido.')
                entry.status = value
            entry.save()
        return response()
    if route == 'reports' and method == 'POST':
        reason = text(data, 'reason', 30)
        if reason not in dict(Report.REASONS):
            raise ValidationError('Motivo inválido.')
        if bool(data.get('review')) == bool(data.get('comment')):
            raise ValidationError('Selecione uma resenha ou um comentário.')
        target = Review.objects.get(pk=data['review']) if data.get('review') else Comment.objects.get(pk=data['comment'])
        field = 'review' if isinstance(target, Review) else 'comment'
        if Report.objects.filter(reporter=user, resolved=False, **{field: target}).exists():
            return fail('Você já denunciou este conteúdo.', 409)
        Report.objects.create(reporter=user, reason=reason, context=text(data, 'context', 1000, False), snapshot=target.text, **{field: target})
        return response(status=201)
    if parts[0] == 'admin':
        if not user.is_staff:
            return fail('Acesso restrito à administração.', 403)
        if route == 'admin/works' and method == 'POST':
            return response({'id': change_work(data).pk}, 201)
        if route == 'admin/import' and method == 'POST':
            source = data.get('source', 'omdb')
            if source not in IMPORT_LABELS:
                raise ValidationError('Fonte de importação inválida.')
            imported = lookup_external(source, data)
            # Vazio vira NULL: os campos são únicos e '' colidiria entre obras.
            ids = {field: imported.get(field) or None for field in EXTERNAL_IDS if field in imported}
            imported.update(ids)
            ids = {field: value for field, value in ids.items() if value}
            if not ids:
                raise ValidationError(f'{IMPORT_LABELS[source]} não retornou um identificador válido.')
            match = Q()
            for field, value in ids.items():
                match |= Q(**{field: value})
            instance = Work.objects.filter(match).first()
            created = instance is None
            if created:
                instance = Work(**imported)
                instance.full_clean()
                instance.save()
            return response({'id': instance.pk, 'created': created})
        if len(parts) == 3 and parts[1] == 'works' and parts[2].isdigit():
            instance = Work.objects.get(pk=parts[2])
            if method == 'PATCH':
                change_work(data, instance)
                return response()
            if method == 'DELETE':
                instance.delete()
                return response()
        if len(parts) == 3 and parts[1] == 'users' and parts[2].isdigit() and method == 'PATCH':
            target = User.objects.get(pk=parts[2])
            if target.pk == user.pk or target.is_staff or target.is_superuser:
                return fail('Contas administrativas não podem ser bloqueadas por esta tela.', 403)
            target.is_active = flag(data, 'active')
            target.save(update_fields=['is_active'])
            return response()
        if len(parts) == 3 and parts[1] == 'users' and parts[2].isdigit() and method == 'DELETE':
            target = User.objects.get(pk=parts[2])
            if target.pk == user.pk:
                return fail('Você não pode excluir a própria conta por esta tela.', 403)
            if target.is_staff or target.is_superuser:
                return fail('Contas administrativas não podem ser excluídas por esta tela.', 403)
            target.delete()
            return response()
        if len(parts) == 3 and parts[1] == 'reports' and parts[2].isdigit() and method == 'POST':
            action = data.get('action')
            if action not in ['keep', 'delete', 'block']:
                raise ValidationError('Ação inválida.')
            with transaction.atomic():
                report = Report.objects.select_for_update().get(pk=parts[2], resolved=False)
                target = report.comment or report.review
                if action == 'block' and target:
                    author = target.user
                    if author.is_staff or author.is_superuser or author.pk == user.pk:
                        return fail('Esta conta não pode ser bloqueada por esta tela.', 403)
                    author.is_active = False
                    author.save(update_fields=['is_active'])
                if action != 'keep' and target:
                    target.delete()
                report.refresh_from_db()
                report.resolved, report.action, report.moderator, report.resolved_at = True, action, user, timezone.now()
                report.save()
            return response()
    return fail('Endpoint ou método não encontrado.', 404)
