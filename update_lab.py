import os
import re

with open('forge/src/qualification_lab.rs', 'r') as f:
    content = f.read()

# Replace hardcoded paths and compare_payload
new_rs = re.sub(
    r'fn compare_payload\(\) -> Value \{.*?\n\}',
    '''fn compare_payload() -> Value {
    let base_dir = std::path::PathBuf::from("/home/cesarops/cesarops_push/reports/qualification/thomas-translator");
    let mut scorecards = Vec::new();
    
    if let Ok(entries) = std::fs::read_dir(base_dir) {
        for entry in entries.flatten() {
            let path = entry.path().join("latest").join("scorecard.json");
            if path.exists() {
                if let Ok(raw) = std::fs::read_to_string(&path) {
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&raw) {
                        scorecards.push(val);
                    }
                }
            }
        }
    }
    
    serde_json::json!({
        "ok": true,
        "scorecards": scorecards,
        "role": ROLE_ID
    })
}''', content, flags=re.DOTALL)

with open('forge/src/qualification_lab.rs', 'w') as f:
    f.write(new_rs)

with open('forge/src/qualification_lab.html', 'r') as f:
    html_content = f.read()

# Update the HTML to dynamically render a table of scorecards instead of fixed 2 columns
html_content = html_content.replace(
    'loadComparison()',
    'loadDynamicComparison()'
)

# We append the new JS function to the end of the script block
new_js = '''
        async function loadDynamicComparison() {
            try {
                const res = await fetch('/api/compare');
                const data = await res.json();
                
                if (!data.ok || !data.scorecards) {
                    document.getElementById('compare-table').innerHTML = `<tr><td colspan="5" class="error-box">Failed to load comparison</td></tr>`;
                    return;
                }
                
                const cards = data.scorecards;
                let thead = '<tr><th>Metric</th>';
                cards.forEach(c => {
                    thead += `<th>${c.model_name || "Unknown"}</th>`;
                });
                thead += '</tr>';
                
                let tbody = '';
                const fields = [
                    { label: "Provider", key: "provider", default: "Local" },
                    { label: "Backend", key: "runtime_backend", default: "unknown" },
                    { label: "Hardware", key: "hardware_worker_id", default: "unknown" },
                    { label: "Quantization", key: "quantization", default: "unknown" },
                    { label: "Qualification", key: "qualification_state", default: "Inconclusive" },
                    { label: "Ranking", key: "standard_suite_ranking_score", default: "N/A" },
                    { label: "Requirement Recall", key: "metrics.mean_requirement_recall", default: "0" },
                    { label: "Constraint Recall", key: "metrics.mean_hard_constraint_recall", default: "0" },
                    { label: "Outcome Accuracy", key: "metrics.mean_claim_disposition_accuracy", default: "0" },
                    { label: "Repeat Agreement", key: "metrics.inter_repeat_agreement", default: "0" },
                    { label: "Mean Latency (ms)", key: "metrics.mean_latency_ms", default: "0" },
                    { label: "P95 Latency (ms)", key: "metrics.p95_latency_ms", default: "0" },
                    { label: "Wall Time (s)", key: "metrics.wall_time_s", default: "0" }
                ];
                
                fields.forEach(f => {
                    tbody += `<tr><td><span class="metric-label">${f.label}</span></td>`;
                    cards.forEach(c => {
                        let val = c;
                        const parts = f.key.split('.');
                        for(const p of parts) { if(val) val = val[p]; }
                        if (c.qualification_state === 'Unqualified' && f.key.startsWith('metrics')) {
                            val = 'Invalid Run';
                        }
                        tbody += `<td><span class="metric-value">${val !== undefined ? val : f.default}</span></td>`;
                    });
                    tbody += '</tr>';
                });
                
                document.getElementById('compare-table').innerHTML = `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
            } catch (err) {
                console.error(err);
            }
        }
'''

html_content = html_content.replace('</script>', new_js + '\n</script>')

with open('forge/src/qualification_lab.html', 'w') as f:
    f.write(html_content)

print("Updated qualification_lab.rs and qualification_lab.html")
