from django.contrib import admin
from .models import (
    Crop, Pathogen, CropDiagnosis, DiagnosisAlias,
    KnowledgeSource, KnowledgeDocument, KnowledgeChunk,
    ManagementPractice, ChemicalTreatment, ChemicalExtractionDraft
)

@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ('name', 'scientific_name', 'priority_tier')
    list_filter = ('priority_tier',)
    search_fields = ('name', 'scientific_name')

@admin.register(Pathogen)
class PathogenAdmin(admin.ModelAdmin):
    list_display = ('canonical_name', 'pathogen_type')
    list_filter = ('pathogen_type',)
    search_fields = ('canonical_name', 'scientific_name')

@admin.register(CropDiagnosis)
class CropDiagnosisAdmin(admin.ModelAdmin):
    list_display = ('diagnosis_name', 'crop', 'pathogen')
    list_filter = ('crop', 'pathogen__pathogen_type')
    search_fields = ('diagnosis_name', 'crop__name', 'pathogen__canonical_name')

@admin.register(DiagnosisAlias)
class DiagnosisAliasAdmin(admin.ModelAdmin):
    list_display = ('alias', 'canonical_diagnosis', 'language')
    list_filter = ('language',)
    search_fields = ('alias', 'canonical_diagnosis__diagnosis_name')

@admin.register(KnowledgeSource)
class KnowledgeSourceAdmin(admin.ModelAdmin):
    list_display = ('organization', 'authority_tier', 'url')
    list_filter = ('authority_tier',)
    search_fields = ('organization',)

@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'publication_date')
    list_filter = ('source__organization',)
    search_fields = ('title',)

@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ('document', 'crop', 'diagnosis', 'page_number')
    list_filter = ('crop', 'document__source__organization')
    search_fields = ('chunk_text',)

@admin.register(ManagementPractice)
class ManagementPracticeAdmin(admin.ModelAdmin):
    list_display = ('diagnosis', 'practice_type', 'region_applicability')
    list_filter = ('practice_type', 'region_applicability', 'diagnosis__crop')
    search_fields = ('description', 'diagnosis__diagnosis_name')

@admin.register(ChemicalTreatment)
class ChemicalTreatmentAdmin(admin.ModelAdmin):
    list_display = ('active_ingredient', 'diagnosis', 'dose_per_hectare_min', 'dose_unit', 'status')
    list_filter = ('status', 'diagnosis__crop', 'mode_of_action_group')
    search_fields = ('active_ingredient', 'diagnosis__diagnosis_name', 'trade_name_examples')
    actions = ['mark_as_approved', 'mark_as_expired']

    def mark_as_approved(self, request, queryset):
        queryset.update(status='APPROVED')
    mark_as_approved.short_description = "Mark selected treatments as APPROVED"

    def mark_as_expired(self, request, queryset):
        queryset.update(status='EXPIRED')
    mark_as_expired.short_description = "Mark selected treatments as EXPIRED"

@admin.register(ChemicalExtractionDraft)
class ChemicalExtractionDraftAdmin(admin.ModelAdmin):
    list_display = ('document', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('raw_extracted_text', 'document__title')
    readonly_fields = ('created_at',)
    actions = ['approve_and_migrate']
    
    def approve_and_migrate(self, request, queryset):
        # This is where a human validates the draft.
        # In a real system, you would deserialize extracted_json 
        # and create a ChemicalTreatment automatically if validation passes.
        # For now, we just mark it.
        queryset.update(status='APPROVED')
    approve_and_migrate.short_description = "Approve and Migrate to Active Treatments"
