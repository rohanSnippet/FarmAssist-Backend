import pandas as pd
import joblib
from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
import warnings

# Suppress warnings for cleaner output
warnings.filterwarnings('ignore')

print("🌱 Starting Crop Intelligence Training Process...")

# 1. Load Data
try:
    df = pd.read_csv('Crop_recommendation.csv')
    print(f"✅ Successfully loaded dataset with {len(df)} records.")
except FileNotFoundError:
    print("❌ Error: Crop_recommendation.csv not found in the current directory.")
    exit()

# 2. Prepare Features and Target
# Ensure column names match exactly what you send from Django!
X = df.drop('label', axis=1)
y = df['label']

# 3. Split Data (Keep 20% completely unseen for the final test)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# 4. Define the Hyperparameter Grid
# This tests different structural combinations to find the smartest possible model
param_grid = {
    'n_estimators': [100, 200, 300],      # Number of decision trees
    'max_depth': [None, 15, 25],          # How deep the trees can think
    'min_samples_split': [2, 5],          # Strictness for splitting rules
    'class_weight': ['balanced', None]    # Helps if some crops have fewer examples
}

# 5. Run Grid Search (The AI finding the best settings for the AI)
print("🔍 Running Grid Search to find optimal hyperparameters (this may take a minute)...")
base_rf = RandomForestClassifier(random_state=42)
grid_search = GridSearchCV(estimator=base_rf, param_grid=param_grid, cv=5, n_jobs=-1, verbose=1)
grid_search.fit(X_train, y_train)

# Extract the champion model
best_model = grid_search.best_estimator_
print(f"🏆 Best Parameters Found: {grid_search.best_params_}")

# 6. Rigorous Cross-Validation
# Test the champion model 5 separate times on different cuts of the data
print("\n🔄 Running 5-Fold Cross Validation for true accuracy...")
cv_scores = cross_val_score(best_model, X, y, cv=5)
print(f"📊 True Average Accuracy: {cv_scores.mean() * 100:.2f}% (+/- {cv_scores.std() * 100:.2f}%)")

# 7. Final Holdout Evaluation
print("\n🎯 Evaluating on unseen test data...")
y_pred = best_model.predict(X_test)
final_accuracy = accuracy_score(y_test, y_pred)
print(f"✨ Final Test Accuracy: {final_accuracy * 100:.2f}%")

# (Optional) Print detailed report to see if specific crops are struggling
# print("\nDetailed Crop Report:")
# print(classification_report(y_test, y_pred))

# 8. Save the Champion Model
# Using compress=3 makes the .pkl file smaller and load faster in Django
model_path = 'recommendation/ml_models/crop_recommendation_model1.pkl'
joblib.dump(best_model, model_path, compress=3)
print(f"\n💾 Model successfully saved to: {model_path}")
print("🚀 Ready for deployment!")