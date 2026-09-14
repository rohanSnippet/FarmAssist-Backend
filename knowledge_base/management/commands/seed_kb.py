import logging
from django.core.management.base import BaseCommand
from knowledge_base.models import (
    Crop, Pathogen, CropDiagnosis, DiagnosisAlias, 
    PriorityTier, PathogenType, KnowledgeSource, AuthorityTier
)

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Seeds the initial Indian Agriculture Knowledge Base with Tier A/B crops and pathogens"

    def handle(self, *args, **options):
        self.stdout.write("Starting KB Seeding...")

        # 1. Seed Authorities
        cibrc, _ = KnowledgeSource.objects.get_or_create(
            organization="Central Insecticides Board & Registration Committee (CIB&RC)",
            defaults={'authority_tier': AuthorityTier.TIER_1, 'url': 'http://cibrc.nic.in/'}
        )
        icar, _ = KnowledgeSource.objects.get_or_create(
            organization="Indian Council of Agricultural Research (ICAR)",
            defaults={'authority_tier': AuthorityTier.TIER_2, 'url': 'https://icar.org.in/'}
        )
        tnau, _ = KnowledgeSource.objects.get_or_create(
            organization="Tamil Nadu Agricultural University (TNAU)",
            defaults={'authority_tier': AuthorityTier.TIER_3, 'url': 'https://agritech.tnau.ac.in/'}
        )

        # 2. Seed Crops
        crops_data = [
            ("Tomato", "Solanum lycopersicum", PriorityTier.TIER_A),
            ("Cotton", "Gossypium", PriorityTier.TIER_A),
            ("Banana", "Musa", PriorityTier.TIER_A),
            ("Paddy", "Oryza sativa", PriorityTier.TIER_A),
            ("Maize", "Zea mays", PriorityTier.TIER_A),
            ("Potato", "Solanum tuberosum", PriorityTier.TIER_A),
            ("Sugarcane", "Saccharum officinarum", PriorityTier.TIER_A),
        ]
        
        crops = {}
        for name, sci_name, tier in crops_data:
            obj, _ = Crop.objects.get_or_create(name=name, defaults={'scientific_name': sci_name, 'priority_tier': tier})
            crops[name] = obj

        # 3. Seed Pathogens
        pathogens_data = [
            ("early_blight", "Alternaria solani", PathogenType.FUNGUS),
            ("late_blight", "Phytophthora infestans", PathogenType.FUNGUS),
            ("fall_armyworm", "Spodoptera frugiperda", PathogenType.INSECT),
            ("helicoverpa", "Helicoverpa armigera", PathogenType.INSECT),
            ("yellow_vein_mosaic", "Bhendi yellow vein mosaic virus", PathogenType.VIRUS),
            ("panama_wilt", "Fusarium oxysporum f. sp. cubense", PathogenType.FUNGUS),
        ]

        pathogens = {}
        for can_name, sci_name, ptype in pathogens_data:
            obj, _ = Pathogen.objects.get_or_create(
                canonical_name=can_name, 
                defaults={'scientific_name': sci_name, 'pathogen_type': ptype}
            )
            pathogens[can_name] = obj

        # 4. Create CropDiagnoses & Aliases
        diagnoses_data = [
            (crops["Tomato"], pathogens["early_blight"], "Tomato Early Blight", ["Early_Blight_Tomato", "early blight"]),
            (crops["Tomato"], pathogens["late_blight"], "Tomato Late Blight", ["Late_Blight_Tomato", "late blight"]),
            (crops["Potato"], pathogens["early_blight"], "Potato Early Blight", ["Early_Blight_Potato"]),
            (crops["Potato"], pathogens["late_blight"], "Potato Late Blight", ["Late_Blight_Potato"]),
            (crops["Maize"], pathogens["fall_armyworm"], "Maize Fall Armyworm", ["Fall_Armyworm", "FAW"]),
            (crops["Cotton"], pathogens["helicoverpa"], "Cotton Bollworm", ["American Bollworm", "Helicoverpa_Cotton"]),
            (crops["Banana"], pathogens["panama_wilt"], "Banana Panama Wilt", ["Panama Disease", "panama_wilt"]),
        ]

        for crop_obj, pathogen_obj, diag_name, aliases in diagnoses_data:
            diag_obj, _ = CropDiagnosis.objects.get_or_create(
                crop=crop_obj, pathogen=pathogen_obj,
                defaults={'diagnosis_name': diag_name}
            )
            for alias in aliases:
                DiagnosisAlias.objects.get_or_create(
                    alias=alias,
                    defaults={'canonical_diagnosis': diag_obj}
                )

        self.stdout.write(self.style.SUCCESS("Successfully seeded KB with Indian authorities, crops, pathogens, and aliases!"))
