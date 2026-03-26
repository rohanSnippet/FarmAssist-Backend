from typing import Dict, Any, List

import joblib
import pandas as pd


ARTIFACT_PATH = "recommendation/ml_models/crop_recommendation_model2.pkl"


class CropRecommender:
    def __init__(self, artifact_path: str = ARTIFACT_PATH):
        artifact = joblib.load(artifact_path)
        self.pipeline = artifact["model"]
        self.feature_columns = artifact["feature_columns"]
        self.feature_ranges = artifact["feature_ranges"]
        self.metrics = artifact["metrics"]

    def _validate_input(self, payload: Dict[str, Any]) -> List[str]:
        warnings = []

        missing = [col for col in self.feature_columns if col not in payload]
        if missing:
            raise ValueError(f"Missing input fields: {missing}")

        for col in self.feature_columns:
            value = payload[col]

            if not isinstance(value, (int, float)):
                raise ValueError(f"{col} must be numeric.")

            min_val = self.feature_ranges[col]["min"]
            max_val = self.feature_ranges[col]["max"]

            if value < min_val or value > max_val:
                warnings.append(
                    f"{col}={value} is outside training range [{min_val}, {max_val}]"
                )

        # Domain sanity checks
        if not (0 <= payload["humidity"] <= 100):
            raise ValueError("humidity must be between 0 and 100.")

        if payload["ph"] < 0 or payload["ph"] > 14:
            raise ValueError("ph must be between 0 and 14.")

        if payload["rainfall"] < 0:
            raise ValueError("rainfall cannot be negative.")

        return warnings

    def predict(self, payload: Dict[str, Any], top_k: int = 3) -> Dict[str, Any]:
        warnings = self._validate_input(payload)

        X = pd.DataFrame([payload], columns=self.feature_columns)

        probs = self.pipeline.predict_proba(X)[0]
        classes = self.pipeline.classes_

        ranked = sorted(
            zip(classes, probs),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]

        return {
            "top_predictions": [
                {
                    "crop": crop,
                    "confidence": round(float(prob), 4)
                }
                for crop, prob in ranked
            ],
            "warnings": warnings,
            "model_metrics": self.metrics,
        }


if __name__ == "__main__":
    recommender = CropRecommender()

    sample_input = {
        "N": 90,
        "P": 42,
        "K": 43,
        "temperature": 21.0,
        "humidity": 82.0,
        "ph": 6.5,
        "rainfall": 203.0,
    }

    result = recommender.predict(sample_input, top_k=3)
    print(result)