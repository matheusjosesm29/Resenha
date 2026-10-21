from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Work, Review, Comment, Like, LibraryEntry, Report

@admin.register(User)
class ResenhaUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Perfil', {'fields': ('bio',)}),)
    list_display = ('username', 'email', 'first_name', 'is_active', 'is_staff')

@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    search_fields = ('title',)
    list_filter = ('category',)
    list_display = ('title', 'category', 'year')

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('work', 'user', 'score', 'spoiler', 'created_at')
    list_filter = ('spoiler',)

admin.site.register([Comment, Like, LibraryEntry, Report])
