import json
from pathlib import Path
from django.core.management.base import BaseCommand
from core.models import Work


class Command(BaseCommand):
    help = 'Adiciona as 12 obras iniciais, sem contas, resenhas ou notas fictícias.'

    def handle(self, *args, **options):
        data = json.loads(Path(__file__).with_name('catalog.json').read_text())
        created = 0
        for row in data:
            fields = {k: row[k] for k in ['category', 'year', 'synopsis', 'creator', 'color']}
            _, new = Work.objects.get_or_create(title=row['title'], category=fields.pop('category'), defaults=fields)
            created += int(new)
        self.stdout.write(self.style.SUCCESS(f'{created} obras adicionadas.'))
