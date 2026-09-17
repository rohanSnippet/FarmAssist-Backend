from django.db import models
from pgvector.django import VectorField

class PriorityTier(models.TextChoices):
    TIER_A = 'A', 'Tier A (National)'
    TIER_B = 'B', 'Tier B (Regional/Cash)'
    TIER_C = 'C', 'Tier C (Specialty/Spices)'

class AuthorityTier(models.TextChoices):
    TIER_1 = '1', 'Tier 1 (Legal/CIB&RC)'
    TIER_2 = '2', 'Tier 2 (Agronomic/ICAR)'
    TIER_3 = '3', 'Tier 3 (Regional/State Univ)'
    TIER_4 = '4', 'Tier 4 (Extension/KVK)'

class PathogenType(models.TextChoices):
    INSECT = 'INSECT', 'Insect Pest'
    FUNGUS = 'FUNGUS', 'Fungus'
    BACTERIA = 'BACTERIA', 'Bacteria'
    VIRUS = 'VIRUS', 'Virus'
    NEMATODE = 'NEMATODE', 'Nematode'
    WEED = 'WEED', 'Weed'
    OTHER = 'OTHER', 'Other'

class KnowledgeStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft / Unverified'
    UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    EXPIRED = 'EXPIRED', 'Expired / Superseded'
    CONFLICTING = 'CONFLICTING', 'Conflicting Evidence'

class Crop(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="Canonical English name (e.g. Tomato)")
    scientific_name = models.CharField(max_length=150, blank=True, null=True)
    priority_tier = models.CharField(max_length=1, choices=PriorityTier.choices, default=PriorityTier.TIER_B)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class GrowthStage(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class CropStageProfile(models.Model):
    crop = models.ForeignKey(
        Crop,
        on_delete=models.CASCADE,
        related_name="stage_profiles",
    )
    growth_stage = models.ForeignKey(
        GrowthStage,
        on_delete=models.CASCADE,
        related_name="crop_profiles",
    )
    stage_order = models.PositiveIntegerField()
    expected_age_min_days = models.PositiveIntegerField(null=True, blank=True)
    expected_age_max_days = models.PositiveIntegerField(null=True, blank=True)
    biological_description = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["crop", "growth_stage"],
                name="unique_crop_growth_stage",
            )
        ]

class Pathogen(models.Model):
    canonical_name = models.CharField(max_length=150, unique=True, help_text="e.g. helicoverpa_armigera")
    scientific_name = models.CharField(max_length=150, blank=True, null=True)
    pathogen_type = models.CharField(max_length=10, choices=PathogenType.choices, default=PathogenType.OTHER)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.canonical_name} ({self.get_pathogen_type_display()})"

class CropDiagnosis(models.Model):
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="diagnoses")
    pathogen = models.ForeignKey(Pathogen, on_delete=models.CASCADE, related_name="crop_diagnoses")
    diagnosis_name = models.CharField(max_length=150, help_text="e.g. Tomato Early Blight")
    symptoms_description = models.TextField(blank=True, null=True)
    
    class Meta:
        unique_together = ('crop', 'pathogen')
        verbose_name_plural = "Crop Diagnoses"

    def __str__(self):
        return f"{self.crop.name} - {self.diagnosis_name}"

class DiagnosisAlias(models.Model):
    alias = models.CharField(max_length=150, unique=True, help_text="e.g. Early_Blight_Tomato, Tamatar ka rog")
    canonical_diagnosis = models.ForeignKey(CropDiagnosis, on_delete=models.CASCADE, related_name="aliases")
    language = models.CharField(max_length=10, default='en')
    
    class Meta:
        verbose_name_plural = "Diagnosis Aliases"

    def __str__(self):
        return f"{self.alias} -> {self.canonical_diagnosis}"

class KnowledgeSource(models.Model):
    organization = models.CharField(max_length=200)
    authority_tier = models.CharField(max_length=1, choices=AuthorityTier.choices)
    url = models.URLField(blank=True, null=True)
    last_checked = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.organization} (Tier {self.authority_tier})"

class KnowledgeDocument(models.Model):
    source = models.ForeignKey(KnowledgeSource, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=255)
    publication_date = models.DateField(blank=True, null=True)
    file_url = models.URLField(blank=True, null=True, help_text="Remote URL in Cloudinary/Firebase")
    
    def __str__(self):
        return self.title

class KnowledgeChunk(models.Model):
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    crop = models.ForeignKey(Crop, on_delete=models.SET_NULL, null=True, blank=True)
    diagnosis = models.ForeignKey(CropDiagnosis, on_delete=models.SET_NULL, null=True, blank=True)
    region = models.CharField(max_length=100, blank=True, null=True)
    
    chunk_text = models.TextField()
    page_number = models.IntegerField(blank=True, null=True)
    embedding = VectorField(dimensions=768, blank=True, null=True) # Assuming Gemini embeddings
    
    def __str__(self):
        return f"Chunk from {self.document.title[:30]}..."

class ManagementPractice(models.Model):
    class PracticeType(models.TextChoices):
        CULTURAL = 'CULTURAL', 'Cultural'
        MECHANICAL = 'MECHANICAL', 'Mechanical'
        BIOLOGICAL = 'BIOLOGICAL', 'Biological'
        BOTANICAL = 'BOTANICAL', 'Botanical'

    diagnosis = models.ForeignKey(CropDiagnosis, on_delete=models.CASCADE, related_name="management_practices")
    practice_type = models.CharField(max_length=15, choices=PracticeType.choices)
    description = models.TextField()
    region_applicability = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. Maharashtra, All India")
    source = models.ForeignKey(KnowledgeDocument, on_delete=models.SET_NULL, null=True, blank=True)
    
    applicable_stages = models.ManyToManyField(GrowthStage, related_name='applicable_management_practices', blank=True)
    prohibited_stages = models.ManyToManyField(GrowthStage, related_name='prohibited_management_practices', blank=True)
    
    def __str__(self):
        return f"[{self.get_practice_type_display()}] {self.diagnosis}"

class ChemicalTreatment(models.Model):
    diagnosis = models.ForeignKey(CropDiagnosis, on_delete=models.CASCADE, related_name="chemical_treatments")
    active_ingredient = models.CharField(max_length=255)
    formulation_type = models.CharField(max_length=100, help_text="e.g. 23% SC")
    trade_name_examples = models.CharField(max_length=255, blank=True, null=True)
    
    dose_per_hectare_min = models.FloatField(blank=True, null=True)
    dose_per_hectare_max = models.FloatField(blank=True, null=True)
    dose_unit = models.CharField(max_length=20, help_text="e.g. ml, g, kg")
    
    water_volume_per_hectare = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. 500 L")
    application_method = models.CharField(max_length=100, default="Foliar Spray")
    
    pre_harvest_interval_days = models.IntegerField(blank=True, null=True)
    waiting_period_days = models.IntegerField(blank=True, null=True)
    mode_of_action_group = models.CharField(max_length=50, blank=True, null=True, help_text="FRAC/IRAC codes")
    maximum_applications_per_season = models.IntegerField(blank=True, null=True)
    
    source = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE)
    status = models.CharField(max_length=15, choices=KnowledgeStatus.choices, default=KnowledgeStatus.APPROVED)
    
    applicable_stages = models.ManyToManyField(GrowthStage, related_name='applicable_chemical_treatments', blank=True)
    prohibited_stages = models.ManyToManyField(GrowthStage, related_name='prohibited_chemical_treatments', blank=True)
    
    def __str__(self):
        return f"{self.active_ingredient} for {self.diagnosis}"

class ChemicalExtractionDraft(models.Model):
    """
    Quarantine Zone for automated PDF/LLM extractions. 
    Must be reviewed and approved by an agronomist before moving to ChemicalTreatment.
    """
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE)
    raw_extracted_text = models.TextField()
    extracted_json = models.JSONField()
    status = models.CharField(max_length=15, choices=KnowledgeStatus.choices, default=KnowledgeStatus.UNDER_REVIEW)
    reviewer_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Draft from {self.document.title} [{self.get_status_display()}]"
