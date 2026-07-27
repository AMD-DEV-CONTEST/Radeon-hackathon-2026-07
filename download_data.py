import os
from dotenv import load_dotenv
from roboflow import Roboflow

# Load environment variables from your local .env file
load_dotenv()

def run_download():
    # Grab your token securely from the local environment state
    api_key = os.getenv("ROBOFLOW_API_KEY")
    if not api_key:
        raise ValueError("❌ Missing ROBOFLOW_API_KEY. Please ensure it is declared in your system environment or a .env file.")
    
    rf = Roboflow(api_key=api_key)
    
    # Target local directory for raw assets
    target_dir = "./data/raw"
    os.makedirs(target_dir, exist_ok=True)
    os.chdir(target_dir)
    
    print("📥 Initiating dataset download from Roboflow Universe...")
    print(" -> Targeting workspace: waferdetection")
    print(" -> Fetching project: wafer-defect-detection-zfi8y")
    
    # Connect directly to your specific wafer dataset project and workspace
    wafer_project = rf.workspace("waferdetection").project("wafer-defect-detection-zfi8y")
    
    # Downloading the dataset version in folder/classification format
    wafer_project.version(1).download("folder")
    
    print(f"\n✅ Extraction complete! All wafer map classification assets are saved locally inside: {target_dir}")

if __name__ == "__main__":
    run_download()