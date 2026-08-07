use forge_qualification_lab::adapter::OpenAiAdapter;
use forge_qualification_lab::harness::QualifyHarness;
use forge_qualification_lab::policy::QualificationPolicy;
use std::env;
use std::fs;
use std::path::Path;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 5 {
        eprintln!("Usage: {} <base_url> <model_id> <backend> <quantization> <worker_id> [display_name]", args[0]);
        std::process::exit(1);
    }

    let base_url = &args[1];
    let model_name = &args[2];  // actual model ID sent to API (may be a full path)
    let backend = &args[3];
    let quantization = &args[4];
    let worker_id = if args.len() > 5 { &args[5] } else { "local" };
    // display_name is used for report dir naming; falls back to basename of model_name
    let display_name = if args.len() > 6 {
        args[6].clone()
    } else {
        Path::new(model_name)
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| model_name.clone())
    };

    let adapter = OpenAiAdapter::new(base_url, model_name);
    let policy = QualificationPolicy::default(); // v1 policy
    let harness = QualifyHarness::new(&display_name, "forge-artifact", quantization, backend, worker_id);

    let scorecard = harness.run(&policy, &adapter).await;
    
    // Save to reports/
    let model_slug = display_name.replace("/", "_").replace(":", "_");
    let timestamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
    let report_dir = format!("reports/qualification/thomas-translator/{}/run_{}", model_slug, timestamp);
    fs::create_dir_all(&report_dir)?;

    let scorecard_path = format!("{}/scorecard.json", report_dir);
    fs::write(&scorecard_path, serde_json::to_string_pretty(&scorecard)?)?;

    println!("Qualification complete. Scorecard saved to {}", scorecard_path);
    Ok(())
}
