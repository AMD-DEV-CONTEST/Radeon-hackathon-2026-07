mod api_keys;
mod ast_editor;
mod bootstrap;
mod cicd;
mod companion_seeder;
mod compiler;
mod db;
mod first_gui_hive_ipc;
mod env_manager;
mod fs;
mod hardware;
mod ipc_benchmark;
mod ipc_bootstrap;
mod ipc_envelope;
mod ipc_health;
mod ipc_hive;
mod ipc_orchestrator;
mod memory_health;
mod model_puller;
mod oauth_github;
mod ollama_installer;
mod ollama_probe;
mod orchestrator;
mod proof_center_stats;
mod python_json;
mod registry;
mod sidecar;
mod telemetry_logger;
mod terminal;
mod pty_terminal;
mod threads;
mod todos;
mod vanguard_state;
mod vector_engine;
mod workspace_search;
// CLAUDE LANE — IDE repair bridge.
// Locked under: locks/sentinel/TAURI_LIB_RS_COMMAND_WIRING_LOCK_001.json
// IDE repair commands shell out to scripts/ide/_tauri_driver.py. No live
// model call, no source mutation, no training-eligibility change.
mod ide_repair_bridge;
mod git;
mod lsp;
mod project_audit;
mod onboarding;
mod local_model_config;
mod diff_staging;
mod evidence_feeds;
mod release_status;
mod rosetta;
mod agent_registry;
mod agent_chat;
mod passport;
mod toolchain_installer;
mod win_process;

use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::Manager;

#[derive(Debug)]
pub struct NetworkPolicyState(pub Mutex<String>);

pub const DEFAULT_NETWORK_POLICY: &str = "cloaked";

pub fn normalize_network_policy(policy: &str) -> Result<String, String> {
    match policy.trim().to_ascii_lowercase().as_str() {
        "offline" => Ok("offline".to_string()),
        "cloaked" => Ok("cloaked".to_string()),
        "online" => Ok("online".to_string()),
        other => Err(format!(
            "Invalid network policy '{other}'. Expected offline, cloaked, or online."
        )),
    }
}

#[tauri::command]
fn sync_network_policy(policy: String, state: tauri::State<'_, NetworkPolicyState>) -> Result<(), String> {
    let normalized = normalize_network_policy(&policy)?;
    if let Ok(mut current) = state.0.lock() {
        *current = normalized;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Vector engine does not need OS path context or AppHandle — init eagerly.
    let vector_state = if std::env::var("DETERMINEX_ENABLE_VECTOR_ENGINE").as_deref() == Ok("1") {
        match vector_engine::initialize_vector_engine_guarded() {
            Ok(model) => vector_engine::VectorState {
                model: Mutex::new(Some(model)),
                init_error: None,
            },
            Err(error) => {
                eprintln!("[Determinex] Vector engine disabled at startup: {error}");
                vector_engine::VectorState {
                    model: Mutex::new(None),
                    init_error: Some(error),
                }
            }
        }
    } else {
        vector_engine::VectorState {
            model: Mutex::new(None),
            init_error: Some(
                "vector engine disabled by default pending ONNX Runtime API alignment".to_string(),
            ),
        }
    };

    tauri::Builder::default()
        .manage(vector_state)
        // Network policy state (offline/cloaked/online)
        .manage(NetworkPolicyState(Mutex::new(DEFAULT_NETWORK_POLICY.to_string())))
        // Vanguard telemetry opt-in — disabled by default, toggled via IPC.
        .manage(vanguard_state::VanguardState::new())
        // Hive Mind DAG orchestrator process tracking.
        .manage(ipc_hive::HiveProcessMap::new())
        // Diff Staging for AI mutations
        .manage(diff_staging::DiffStagingStore { diffs: std::sync::Mutex::new(Vec::new()) })
        // Benchmark run process tracking.
        .manage(ipc_benchmark::BenchmarkProcessMap::new())
        // Embedded Python sidecar for local GGUF inference (Config E).
        .manage(sidecar::new_shared_sidecar())
        .manage(pty_terminal::PtyState::default())
        // The project the user actually opened, kept separate from WorkspaceRoot -- which is the
        // file BROWSER's root and is set to the system drive so the picker can reach any project.
        // Credential reads (env_manager) use this narrower root instead.
        .manage(env_manager::ProjectRoot::default())
        .manage(agent_chat::ChatState::default())
        .invoke_handler(tauri::generate_handler![
            agent_registry::list_coding_agents,
            agent_registry::run_coding_agent,
            agent_registry::agent_status_roster,
            agent_registry::agent_probe_test,
            agent_registry::list_ai_providers,
            toolchain_installer::list_toolchains,
            toolchain_installer::install_toolchain,
            agent_chat::agent_chat_create_session,
            agent_chat::agent_chat_send,
            agent_chat::agent_chat_list_sessions,
            agent_chat::agent_chat_get_transcript,
            agent_chat::agent_chat_get_plan,
            agent_chat::agent_chat_set_plan,
            agent_chat::agent_chat_resync_plan,
            agent_chat::agent_chat_cloak_status,
            agent_chat::agent_chat_set_model,
            agent_chat::agent_chat_apply_proposal,
            agent_chat::agent_chat_list_proposals,
            passport::passport_cli_login_status,
            passport::passport_connect,
            passport::passport_list,
            passport::passport_disconnect,
            passport::passport_usage_summary,
            passport::passport_cli_subscription_status,
            api_keys::get_api_key_status,
            api_keys::save_api_keys,
            api_keys::save_service_key,
            api_keys::get_ollama_base_url,
            api_keys::save_ollama_base_url,
            threads::get_threads,
            fs::get_file_system_tree,
            fs::get_build_artifacts,
            fs::get_workspace_files,
            evidence_feeds::get_flywheel_feed,
            evidence_feeds::get_cloak_audit_summary,
            fs::read_file_content,
            todos::fetch_todos,
            todos::create_todo,
            todos::toggle_todo,
            todos::delete_todo,
            registry::get_models_registry,
            registry::add_custom_registry_model,
            registry::get_tool_registry,
            vector_engine::generate_and_store_embedding,
            vector_engine::query_knowledge,
            vector_engine::store_to_collection,
            memory_health::get_memory_health,
            ipc_orchestrator::orchestrate_plan,
            ipc_orchestrator::orchestrate_codegen,
            ipc_orchestrator::orchestrate_audit,
            ipc_orchestrator::orchestrator_shutdown,
            ipc_bootstrap::initialize_system,
            ipc_bootstrap::check_docker_status,
            ipc_bootstrap::probe_hardware,
            fs::read_workspace_file,
            vanguard_state::toggle_vanguard_telemetry,
            ollama_probe::check_ollama_status,
            ollama_probe::get_ollama_models,
            ollama_probe::get_work_readiness,
            ollama_installer::ensure_ollama_installed,
            model_puller::pull_required_models,
            model_puller::check_determinex_models,
            model_puller::install_determinex_models,
            ipc_health::get_health_telemetry,
            ipc_hive::create_session,
            ipc_hive::generate_dag,
            ipc_hive::run_session,
            ipc_hive::start_session,
            ipc_hive::get_session_status,
            ipc_hive::get_session_log_path,
            ipc_hive::read_hive_workspace_file,
            ipc_hive::stream_session_log,
            ipc_hive::kill_session,
            ipc_hive::generate_spec,
            ipc_hive::refine_spec,
            ipc_hive::discover_idea,
            ipc_hive::assess_idea_context,
            ipc_hive::provider_setup_report,
            ipc_hive::provider_setup_verify,
            ipc_hive::user_profile_get,
            ipc_hive::user_profile_set,
            ipc_hive::converse_idea,
            ipc_hive::explore_workspace,
            ipc_hive::diagnose_workspace,
            ipc_hive::fix_workspace,
            ipc_hive::list_hive_sessions,
            ipc_hive::get_role_assignments,
            ipc_hive::set_role_assignments,
            ipc_hive::reveal_session_output,
            fs::write_spec_file,
            fs::write_file_content,
            fs::reveal_in_explorer,
            fs::create_path,
            fs::rename_path,
            fs::delete_path,
            ipc_benchmark::launch_benchmark_run,
            ipc_benchmark::stop_benchmark_run,
            ipc_benchmark::get_programbench_snapshot,
            first_gui_hive_ipc::record_first_gui_hive_ipc_evidence,
            rosetta::rosetta_status,
            rosetta::rosetta_fetch,
            sidecar::spawn_sidecar,
            sidecar::sidecar_load,
            sidecar::sidecar_infer,
            sidecar::sidecar_status,
            sidecar::shutdown_sidecar,
            terminal::run_terminal_command,
            pty_terminal::pty_spawn,
            pty_terminal::pty_write,
            pty_terminal::pty_resize,
            pty_terminal::pty_kill,
            pty_terminal::pty_is_alive,
            sync_network_policy,
            proof_center_stats::get_programbench_proof_stats,
            // CLAUDE LANE — IDE repair bridge (TAURI_LIB_RS_COMMAND_WIRING_LOCK_001).
            ide_repair_bridge::open_workspace,
            ide_repair_bridge::get_workspace_status,
            ide_repair_bridge::get_model_route_status,
            ide_repair_bridge::diagnose_dry_run,
            ide_repair_bridge::diagnose_live_opt_in,
            ide_repair_bridge::generate_patch_plan,
            ide_repair_bridge::verify_temp_patch,
            ide_repair_bridge::get_human_approval_packet,
            ide_repair_bridge::source_apply_dry_run,
            ide_repair_bridge::get_repair_flow_state,
            ide_repair_bridge::generate_llm_program_advisory,
            ide_repair_bridge::preview_idea_oracle,
            ide_repair_bridge::build_idea,
            ide_repair_bridge::repair_diagnose,
            ide_repair_bridge::get_governance_status,
            local_model_config::save_local_model_config,
            local_model_config::get_local_model_config,
            ide_repair_bridge::get_unified_product_navigation_model,
            ide_repair_bridge::get_idea_lab_workflow_state,
            ide_repair_bridge::get_repo_clinic_workflow_state,
            ide_repair_bridge::get_maintenance_bay_workflow_state,
            ide_repair_bridge::get_learning_studio_workflow_state,
            ide_repair_bridge::generate_learning_studio_content,
            ide_repair_bridge::run_maintenance_bay_scan,
            ide_repair_bridge::get_proof_operator_center_state,
            ide_repair_bridge::get_user_level_teaching_windows,
            ide_repair_bridge::get_unified_splash_demo_spec,
            ide_repair_bridge::get_idea_lab_verified_demo_status,
            ide_repair_bridge::get_repo_clinic_verified_demo_status,
            ide_repair_bridge::get_maintenance_bay_verified_demo_status,
            ide_repair_bridge::get_learning_studio_verified_demo_status,
            ide_repair_bridge::get_proof_operator_center_milestone_dashboard_status,
            ide_repair_bridge::query_corpus,
            ide_repair_bridge::get_runtime_capability_status,
            git::git_status,
            git::git_stage,
            git::git_unstage,
            git::git_stage_all,
            git::git_commit,
            git::git_list_branches,
            git::git_create_branch,
            git::git_checkout_branch,
            git::git_push,
            git::git_pull,
            git::git_clone,
            git::git_conflict_sides,
            git::git_resolve_conflict,
            lsp::get_lsp_diagnostics,
            lsp::get_lsp_symbols,
            ipc_hive::pause_session,
            ipc_hive::resume_session,
            ipc_hive::cancel_session,
            ipc_hive::replay_session,
            project_audit::run_project_audit,
            onboarding::analyze_workspace,
            cicd::list_ci_runs,
            env_manager::list_env_vars,
            env_manager::reveal_env_var,
            env_manager::set_project_root,
            oauth_github::github_device_start,
            oauth_github::github_device_poll,
            oauth_github::github_sign_out,
            oauth_github::github_open_verification,
            diff_staging::get_staged_diffs,
            diff_staging::apply_staged_diff,
            diff_staging::reject_staged_diff,
            diff_staging::stage_diff_for_review,
            workspace_search::find_in_files,
            release_status::get_release_gate_status,
        ])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                let app = window.app_handle().clone();

                // 1. Immediately abort all dangling background agent processes
                if let Some(hive_map) = app.try_state::<ipc_hive::HiveProcessMap>() {
                    hive_map.abort_all();
                }

                let arc = std::sync::Arc::clone(&*app.state::<sidecar::SharedSidecar>());

                // Spawn a dedicated thread so the event handler returns immediately.
                std::thread::spawn(move || {
                    // 2. Unload all Ollama models synchronously within this thread to free GPU VRAM
                    if let Ok(rt) = tokio::runtime::Runtime::new() {
                        rt.block_on(async {
                            let client = reqwest::Client::builder()
                                .timeout(std::time::Duration::from_secs(2))
                                .build()
                                .unwrap_or_default();

                            if let Ok(res) = client.get("http://localhost:11434/api/ps").send().await {
                                if let Ok(json) = res.json::<serde_json::Value>().await {
                                    if let Some(models) = json.get("models").and_then(|m| m.as_array()) {
                                        for m in models {
                                            if let Some(name) = m.get("name").and_then(|n| n.as_str()) {
                                                let _ = client.post("http://localhost:11434/api/generate")
                                                    .json(&serde_json::json!({
                                                        "model": name,
                                                        "keep_alive": 0
                                                    }))
                                                    .send()
                                                    .await;
                                            }
                                        }
                                    }
                                }
                            }
                        });
                    }

                    // 3. Retry try_lock for up to 2 seconds to handle in-flight sidecar IPC commands
                    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
                    loop {
                        match arc.try_lock() {
                            Ok(mut mgr) => {
                                if mgr.is_alive() {
                                    let _: Result<_, _> = mgr.request("quit", serde_json::json!({}));
                                }
                                mgr.kill();
                                return;
                            }
                            Err(std::sync::TryLockError::Poisoned(p)) => {
                                p.into_inner().kill();
                                return;
                            }
                            Err(std::sync::TryLockError::WouldBlock) => {
                                if std::time::Instant::now() >= deadline {
                                    eprintln!("[Determinex] Sidecar kill timed out after 2s — OS will reap orphan on process exit");
                                    return;
                                }
                                std::thread::sleep(std::time::Duration::from_millis(100));
                            }
                        }
                    }
                });
            }
        })
        .setup(|app| {
            // ── Database ──────────────────────────────────────────────────────────
            // Resolve the platform-specific application data directory.
            //   Windows : %APPDATA%\<bundle-id>\
            //   macOS   : ~/Library/Application Support/<bundle-id>/
            //   Linux   : ~/.local/share/<bundle-id>/
            let app_data_dir = std::env::var("DETERMINEX_APP_DATA_DIR")
                .map(PathBuf::from)
                .unwrap_or_else(|_| {
                    app.path().app_data_dir()
                        .unwrap_or_else(|e| {
                            eprintln!("[Determinex] Cannot resolve app data dir: {e}; using temp dir");
                            std::env::temp_dir().join("determinex_fallback")
                        })
                });

            let conn = match db::initialize_database(app_data_dir.clone()) {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("[Determinex] DB init failed ({e}); falling back to in-memory database — settings will not persist");
                    let mem = rusqlite::Connection::open_in_memory()
                        .expect("in-memory SQLite must always succeed");
                    db::apply_schema(&mem).expect("in-memory schema setup must succeed");
                    mem
                }
            };

            app.manage(db::DbState { conn: Mutex::new(conn) });

            // AppDataDir state — shared with registry.rs for models_registry.json
            app.manage(db::AppDataDir(app_data_dir.clone()));

            // ── Companion Skill auto-seeder ───────────────────────────────────────
            // Seeds COMPANION_*.md documents into the vector DB once at first boot.
            // Resolves docs/ relative to the Tauri resource directory so it works
            // in both `tauri dev` (repo layout) and production bundles.
            // Runs in a background thread — never blocks app startup.
            {
                let docs_dir = {
                    let resource_path = app.path().resource_dir()
                        .unwrap_or_else(|_| std::path::PathBuf::from("."));
                    // Tauri dev: resource_dir resolves to the src-tauri/ directory.
                    // Walk up two levels (src-tauri → frontend → repo root) then docs/
                    resource_path
                        .parent()            // frontend/
                        .and_then(|p| p.parent()) // repo root
                        .map(|p| p.join("docs"))
                        .unwrap_or_else(|| resource_path.join("docs"))
                };
                let docs_dir = resolve_companion_docs_dir(&docs_dir);
                let db_path = app_data_dir.join("determinex.sqlite");

                std::thread::spawn(move || {
                    if std::env::var("DETERMINEX_ENABLE_VECTOR_ENGINE").as_deref() != Ok("1") {
                        eprintln!(
                            "[CompanionSeeder] Vector engine disabled by default; skipping seed pending ONNX Runtime API alignment"
                        );
                        return;
                    }

                    // The seeder instantiates its own short-lived embedding model so it
                    // never contends with the main app's VectorState mutex.
                    // The model is dropped at the end of this thread, releasing memory.
                    match vector_engine::initialize_vector_engine_guarded() {
                        Ok(mut model) => {
                            companion_seeder::seed_if_needed(&docs_dir, &db_path, &mut model);
                        }
                        Err(e) => {
                            eprintln!("[CompanionSeeder] Failed to init embedding model: {e}");
                        }
                    }
                });
            }


            // ── Workspace root ────────────────────────────────────────────────────
            // File browser boundary for path traversal checks in fs.rs.
            // On Windows: use the system drive root (C:\) so the file browser can
            // open C:\Dev and other user directories. The AI-write sandbox is
            // enforced separately by ipc_hive.rs using session-scoped temp dirs.
            // On other platforms: home directory is sufficient.
            let workspace_root = if cfg!(target_os = "windows") {
                // Use the system drive root so the file browser can open C:\Dev and
                // other user directories. AI-directed writes are sandboxed separately
                // by ipc_hive.rs session temp dirs — not by this boundary.
                let drive = std::env::var("SystemDrive").unwrap_or_else(|_| "C:".to_string());
                std::path::PathBuf::from(format!("{}\\", drive))
            } else {
                app.path().home_dir()
                    .unwrap_or_else(|_| {
                        std::env::current_dir()
                            .unwrap_or_else(|_| std::path::PathBuf::from("."))
                    })
            };

            app.manage(fs::WorkspaceRoot::new(workspace_root));

            // ── Orchestrator ──────────────────────────────────────────────────────
            // Spawned here (inside setup) so the actor has a valid AppHandle from
            // the start — required for the "moa-telemetry" event emitter.
            let orchestrator_handle = orchestrator::OrchestratorHandle::spawn(
                16,
                app.handle().clone(),
            );
            app.manage(orchestrator_handle);

            // ── Logging (debug builds only) ───────────────────────────────────────
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            Ok(())
        })
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn resolve_companion_docs_dir(seed: &Path) -> PathBuf {
    for candidate in companion_docs_candidates(seed) {
        if contains_companion_docs(&candidate) {
            return candidate;
        }
    }
    seed.join("docs").join("companions")
}

fn companion_docs_candidates(seed: &Path) -> Vec<PathBuf> {
    let mut bases: Vec<PathBuf> = Vec::new();
    if let Ok(dir) = std::env::var("DETERMINEX_COMPANION_DOCS_DIR") {
        bases.push(PathBuf::from(dir));
    }
    bases.push(seed.to_path_buf());
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            bases.push(parent.to_path_buf());
        }
    }
    if let Ok(current) = std::env::current_dir() {
        bases.push(current);
    }
    bases.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")));

    let mut candidates = Vec::new();
    for base in bases {
        for ancestor in base.ancestors() {
            candidates.push(ancestor.join("docs").join("companions"));
            candidates.push(ancestor.join("companions"));
            candidates.push(ancestor.join("docs"));
        }
    }
    candidates
}

fn contains_companion_docs(path: &Path) -> bool {
    let Ok(entries) = std::fs::read_dir(path) else {
        return false;
    };
    entries.filter_map(Result::ok).any(|entry| {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        name.starts_with("COMPANION_") && name.ends_with(".md")
    })
}
