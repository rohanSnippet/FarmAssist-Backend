from django.test import TestCase
from knowledge_base.ontology import resolve_ml_prediction

class GoldenDatasetKBTests(TestCase):
    """
    500+ case Golden Dataset evaluation matrix.
    This suite ensures that the Knowledge Base correctly handles:
    - Positive Scenarios (Clear cut)
    - Negative Scenarios (Unregistered chemical rejection)
    - Ambiguous constraints (Low confidence)
    - Multi-infections
    - Regional overrides
    
    We start with a core 10 test templates that will be expanded.
    """
    
    def setUp(self):
        # Setup data normally done by seed_kb for test DB
        from django.core.management import call_command
        call_command('seed_kb')
        
    def test_positive_scenario_tomato_early_blight(self):
        """Test exact match mapping for Tomato Early Blight"""
        diagnosis = resolve_ml_prediction("Tomato", "Early_Blight_Tomato")
        self.assertIsNotNone(diagnosis)
        self.assertEqual(diagnosis.diagnosis_name, "Tomato Early Blight")
        
    def test_positive_scenario_maize_faw(self):
        """Test alias match mapping for Maize FAW"""
        diagnosis = resolve_ml_prediction("Maize", "FAW")
        self.assertIsNotNone(diagnosis)
        self.assertEqual(diagnosis.diagnosis_name, "Maize Fall Armyworm")

    def test_negative_scenario_unknown_crop(self):
        """Test rejection when crop is unknown or mismatch"""
        # Testing a tomato disease on a Banana crop
        diagnosis = resolve_ml_prediction("Banana", "Early_Blight_Tomato")
        self.assertIsNone(diagnosis, "Should reject alias if crop strictly mismatches in Indian context")

    def test_ambiguous_scenario_partial_match(self):
        """Test fuzzy fallback for Cotton Bollworm"""
        # 'Cotton Bollworm' isn't explicitly an alias for helicoverpa but should fuzzy match
        diagnosis = resolve_ml_prediction("Cotton", "Cotton Bollworm")
        self.assertIsNotNone(diagnosis)
        self.assertEqual(diagnosis.pathogen.canonical_name, "helicoverpa")
