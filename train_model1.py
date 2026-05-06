import pandas as pd
import joblib
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report

# 1. Load Data
print("Loading data...")
df = pd.read_csv('Crop_recommendation.csv')

# 2. Prepare Features and Target
X = df.drop('label', axis=1)
y = df['label']

# 3. Split Data
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# 4. Train Model
print("Training model...")
# UPGRADE: Added class_weight='balanced' to penalize the model for ignoring minority crops
rf_model = RandomForestClassifier(n_estimators=200, random_state=42, class_weight='balanced', n_jobs=-1)
rf_model.fit(X_train, y_train)

# 5. Evaluate
print("Evaluating model...")
y_pred = rf_model.predict(X_test)
print(f"\nOverall Accuracy: {accuracy_score(y_test, y_pred) * 100:.2f}%\n")

# UPGRADE: Print the detailed report (Precision, Recall, F1-Score)
print("Classification Report:")
print(classification_report(y_test, y_pred))

# 6. Diagnostics: Feature Importance
# This is crucial for explaining WHY the model made a decision
feature_importances = pd.Series(rf_model.feature_importances_, index=X.columns).sort_values(ascending=False)
print("\nFeature Importances:")
print(feature_importances)

# 7. Diagnostics: Confusion Matrix Heatmap
print("\nGenerating Confusion Matrix...")
crop_labels = rf_model.classes_
cm = confusion_matrix(y_test, y_pred, labels=crop_labels)

plt.figure(figsize=(14, 12))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=crop_labels, yticklabels=crop_labels)
plt.xlabel('Predicted Crop')
plt.ylabel('Actual Crop')
plt.title('FarmAssist Crop Recommendation - Confusion Matrix')
plt.xticks(rotation=45)
plt.tight_layout()
# Save the plot so you have it for your project documentation
# plt.savefig('recommendation/ml_models/confusion_matrix.png') 
plt.show()

# 8. Save the Model
print("\nSaving model...")
joblib.dump(rf_model, 'recommendation/ml_models/crop_recommendation_model1.pkl')
print("Pipeline complete.")