from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower


class User(AbstractUser):
    email = models.EmailField(unique=True)
    bio = models.CharField(max_length=300, blank=True)
    avatar = models.TextField(blank=True)  # Imagem validada e recodificada, em data URL.

    class Meta:
        constraints = [models.UniqueConstraint(Lower('email'), name='user_email_case_unique')]


class Work(models.Model):
    CATEGORIES = [(c, c) for c in ['Filmes', 'Séries', 'Animes', 'Mangás', 'Livros', 'Jogos']]
    title = models.CharField(max_length=150, db_index=True)
    category = models.CharField(max_length=20, choices=CATEGORIES, db_index=True)
    year = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(2100)])
    synopsis = models.TextField(max_length=3000)
    creator = models.CharField(max_length=200)
    cast = models.TextField(blank=True, max_length=2000)
    color = models.CharField(max_length=7, default='#3a4551')
    poster = models.URLField(blank=True, max_length=1000)
    imdb_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Review(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name='reviews')
    score = models.DecimalField(max_digits=3, decimal_places=1, validators=[MinValueValidator(0), MaxValueValidator(10)])
    text = models.TextField(max_length=5000)
    spoiler = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'work'], name='one_review_per_work'),
            models.CheckConstraint(condition=models.Q(score__gte=0, score__lte=10), name='review_score_0_10'),
        ]


class Comment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)


class Like(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='likes')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'review'], name='one_like_per_review')]


class LibraryEntry(models.Model):
    STATUSES = [(s, s) for s in ['Quero ver / ler', 'Consumindo', 'Finalizado', 'Abandonado']]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='library')
    work = models.ForeignKey(Work, on_delete=models.CASCADE)
    favorite = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUSES, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'work'], name='one_library_entry')]


class Report(models.Model):
    REASONS = [(s, s) for s in ['Ofensa', 'Spam', 'Spoiler sem aviso', 'Outro']]
    reporter = models.ForeignKey(User, on_delete=models.CASCADE)
    review = models.ForeignKey(Review, on_delete=models.SET_NULL, null=True, blank=True)
    comment = models.ForeignKey(Comment, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.CharField(max_length=30, choices=REASONS)
    context = models.CharField(max_length=1000, blank=True)
    snapshot = models.TextField(blank=True)
    resolved = models.BooleanField(default=False)
    action = models.CharField(max_length=20, blank=True)
    moderator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='moderated_reports')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True)
