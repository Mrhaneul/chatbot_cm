import os
import sys
import yaml

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FAQS_DIR = os.path.join(DATA_DIR, "faqs")
INSTRUCTIONS_DIR = os.path.join(DATA_DIR, "instructions")
PLATFORMS_CONFIG_PATH = os.path.join(PROJECT_ROOT, "app", "rag", "platforms.yaml")

# --- Helper Function ---
def validate_index_file(filepath: str, label: str) -> bool:
    """Checks if a file exists and has a size greater than 0."""
    if not os.path.exists(filepath):
        print(f"❌ FAIL: Missing {label} index file: {filepath}")
        return False
    if os.path.getsize(filepath) == 0:
        print(f"❌ FAIL: Empty {label} index file: {filepath}")
        return False
    print(f"✅ PASS: {label} index found and not empty: {filepath}")
    return True

# --- Main Validation Logic ---
def main():
    print("--- Validating FAISS Indexes ---")
    all_passed = True
    
    # 1. Validate FAQ index
    all_passed &= validate_index_file(os.path.join(FAQS_DIR, "faiss_index"), "FAQ")
    
    # 2. Validate general instructions index
    all_passed &= validate_index_file(os.path.join(INSTRUCTIONS_DIR, "faiss_index"), "General Instructions")
    
    # 3. Validate platform-specific indexes
    try:
        with open(PLATFORMS_CONFIG_PATH, "r", encoding="utf-8") as f:
            platforms_config = yaml.safe_load(f)
        platforms = platforms_config.get("platforms", [])
    except FileNotFoundError:
        print(f"❌ FAIL: platforms.yaml not found at {PLATFORMS_CONFIG_PATH}")
        sys.exit(1)
    except yaml.YAMLError:
        print(f"❌ FAIL: Error parsing platforms.yaml at {PLATFORMS_CONFIG_PATH}")
        sys.exit(1)

    if not platforms:
        print("⚠️ WARNING: No platforms defined in platforms.yaml. Skipping platform-specific index validation.")
        
    for platform in platforms:
        platform_key = platform["key"]
        platform_label = platform.get("display_name", platform_key)
        
        platform_index_path = os.path.join(INSTRUCTIONS_DIR, f"faiss_index_{platform_key}")
        all_passed &= validate_index_file(platform_index_path, f"{platform_label} (Platform)")
            
    if all_passed:
        print("
--- All FAISS indexes validated successfully! ---")
        sys.exit(0)
    else:
        print("
--- FAISS index validation FAILED! ---")
        sys.exit(1)

if __name__ == "__main__":
    main()
