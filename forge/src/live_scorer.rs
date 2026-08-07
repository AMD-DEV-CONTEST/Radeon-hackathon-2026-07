use std::fs;
use std::path::PathBuf;

pub fn update_live_scorecard(
    model_name: &str,
    run: forge_qualification_lab::scorecard::RunResult,
) {
    let report_dir = format!("../core/forge-qualification-lab/reports/qualification/thomas-translator/{}/latest", model_name);
    let scorecard_path = PathBuf::from(&report_dir).join("scorecard.json");

    if let Ok(content) = fs::read_to_string(&scorecard_path) {
        if let Ok(mut scorecard) = serde_json::from_str::<forge_qualification_lab::scorecard::Scorecard>(&content) {
            // Append the run
            let is_hard_failure = run.hard_failure;
            let is_outcome_match = run.expected_outcome_match;
            scorecard.runs.push(run.clone());
            
            // Recompute pass summary (simple version: just add the new run to first_pass)
            if run.pass_type == "mission_control_live" {
                scorecard.first_pass.total_runs += 1;
                if run.raw_json_valid { scorecard.first_pass.raw_json_valid += 1; }
                if run.validator_success { scorecard.first_pass.validator_success += 1; }
                if is_outcome_match { scorecard.first_pass.outcome_match += 1; }
                if is_hard_failure { scorecard.first_pass.hard_failures += 1; }
                
                let mut req = 0.0;
                let mut con = 0.0;
                let mut acc = 0.0;
                for r in &scorecard.runs {
                    if r.pass_type == "mission_control_live" || r.pass_type == "first_pass" {
                        req += r.requirement_recall;
                        con += r.hard_constraint_recall;
                        acc += r.claim_disposition_accuracy;
                    }
                }
                let total = scorecard.first_pass.total_runs as f64;
                if total > 0.0 {
                    scorecard.first_pass.mean_requirement_recall = req / total;
                    scorecard.first_pass.mean_hard_constraint_recall = con / total;
                    scorecard.first_pass.mean_claim_disposition_accuracy = acc / total;
                }
            }

            // Save it back
            if let Ok(new_content) = serde_json::to_string_pretty(&scorecard) {
                let _ = fs::write(&scorecard_path, new_content);
            }
        }
    }
}
