//! Resolve Forge data paths (deploy dir vs local repo copy).

const DEPLOY_FORGE: &str = "/codebase/repos/wreckhunter2000-1/cesarops-forge-v2";
const LOCAL_FORGE: &str = "/home/cesarops/cesarops_push";

pub fn forge_dir() -> String {
    if std::path::Path::new(DEPLOY_FORGE).exists() {
        DEPLOY_FORGE.to_string()
    } else {
        LOCAL_FORGE.to_string()
    }
}

pub fn cluster_config_path() -> String {
    let deploy = format!("{}/cluster_config.toml", DEPLOY_FORGE);
    if std::path::Path::new(&deploy).exists() {
        deploy
    } else {
        format!("{}/forge_cluster_config.toml", LOCAL_FORGE)
    }
}

pub fn routing_state_path() -> String {
    format!("{}/routing_state.json", forge_dir())
}

pub fn lanes_state_path() -> String {
    format!("{}/lanes_state.json", forge_dir())
}

pub fn models_dir() -> String {
    "/mnt/raid0/models".to_string()
}

pub fn project_root() -> String {
    if std::path::Path::new("/codebase/wreckhunter2000-1").exists() {
        "/codebase/wreckhunter2000-1".to_string()
    } else {
        "/home/cesarops".to_string()
    }
}

pub fn model_scoreboard_path() -> String {
    format!("{}/.forge_v2/model_scoreboard.jsonl", forge_dir())
}
