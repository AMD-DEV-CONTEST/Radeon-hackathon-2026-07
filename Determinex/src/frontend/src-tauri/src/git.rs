use std::process::Command;
use serde::{Deserialize, Serialize};
use crate::win_process::HideConsoleExt;

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GitFile {
    pub path: String,
    pub status: String,
    /// The raw two-character porcelain status code (e.g. "M ", "??", "AM"),
    /// trimmed for display -- so the UI can show the real status letter
    /// instead of a hardcoded one.
    pub code: String,
    pub original_content: Option<String>,
    pub current_content: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GitStatusResult {
    pub branch: String,
    /// The upstream remote/branch this branch tracks (e.g. "origin/main"),
    /// if any -- None when there is no upstream configured.
    pub upstream: Option<String>,
    pub files: Vec<GitFile>,
    pub ahead: u32,
    pub behind: u32,
}

#[tauri::command]
pub fn git_status(cwd: String) -> Result<GitStatusResult, String> {
    let output = Command::new("git").hide_console()
        .args(["status", "--porcelain", "-b"])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut files = Vec::new();
    let mut branch = String::from("unknown");
    let mut upstream: Option<String> = None;
    let mut ahead = 0;
    let mut behind = 0;

    for line in stdout.lines() {
        if line.starts_with("##") {
            // e.g. ## main...origin/main [ahead 1, behind 2]
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() > 1 {
                let branch_info = parts[1];
                let mut segments = branch_info.split("...");
                branch = segments.next().unwrap_or("unknown").to_string();
                if let Some(remote) = segments.next() {
                    upstream = Some(remote.to_string());
                }
            }
            if line.contains("ahead") {
                if let Some(a) = line.split("ahead ").nth(1).and_then(|s| s.split(|c: char| !c.is_numeric()).next()) {
                    ahead = a.parse().unwrap_or(0);
                }
            }
            if line.contains("behind") {
                if let Some(b) = line.split("behind ").nth(1).and_then(|s| s.split(|c: char| !c.is_numeric()).next()) {
                    behind = b.parse().unwrap_or(0);
                }
            }
        } else if line.len() > 3 {
            let status_code = &line[0..2];
            let path = &line[3..];
            let index_char = status_code.chars().next().unwrap_or(' ');
            let status = if status_code == "??" {
                "untracked"
            } else if matches!(status_code, "UU" | "AA" | "DD" | "AU" | "UA" | "UD" | "DU") {
                "conflicted"
            } else if index_char != ' ' {
                // Any non-space index column means it's staged, regardless of
                // whether the worktree column also has a further unstaged
                // change (e.g. "MM") -- matches real git semantics instead of
                // only recognizing "A " as staged.
                "staged"
            } else {
                "modified"
            };
            let mut original_content = None;
            let mut current_content = None;

            if status != "untracked" {
                if let Ok(show_out) = Command::new("git").hide_console()
                    .args(["show", &format!("HEAD:{}", path)])
                    .current_dir(&cwd)
                    .output()
                {
                    if show_out.status.success() {
                        original_content = Some(String::from_utf8_lossy(&show_out.stdout).to_string());
                    }
                }
            }

            if let Ok(content) = std::fs::read_to_string(std::path::Path::new(&cwd).join(path)) {
                current_content = Some(content);
            }

            files.push(GitFile {
                path: path.to_string(),
                status: status.to_string(),
                code: status_code.trim().to_string(),
                original_content,
                current_content,
            });
        }
    }

    Ok(GitStatusResult {
        branch,
        upstream,
        files,
        ahead,
        behind,
    })
}

#[tauri::command]
pub fn git_stage(cwd: String, path: String) -> Result<(), String> {
    let output = Command::new("git").hide_console()
        .args(["add", &path])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn git_unstage(cwd: String, path: String) -> Result<(), String> {
    let output = Command::new("git").hide_console()
        .args(["restore", "--staged", &path])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn git_stage_all(cwd: String) -> Result<(), String> {
    let output = Command::new("git").hide_console()
        .args(["add", "."])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn git_commit(cwd: String, message: String) -> Result<(), String> {
    let output = Command::new("git").hide_console()
        .args(["commit", "-m", &message])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn git_list_branches(cwd: String) -> Result<Vec<String>, String> {
    let output = Command::new("git").hide_console()
        .args(["branch", "--format=%(refname:short)"])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let branches: Vec<String> = stdout
        .lines()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();

    Ok(branches)
}

#[tauri::command]
pub fn git_create_branch(cwd: String, name: String) -> Result<(), String> {
    let output = Command::new("git").hide_console()
        .args(["checkout", "-b", &name])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn git_checkout_branch(cwd: String, name: String) -> Result<(), String> {
    let output = Command::new("git").hide_console()
        .args(["checkout", &name])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn git_push(cwd: String) -> Result<(), String> {
    let output = Command::new("git").hide_console()
        .args(["push"])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn git_pull(cwd: String) -> Result<(), String> {
    let output = Command::new("git").hide_console()
        .args(["pull"])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConflictSides {
    /// The common ancestor (merge-base) version, stage 1 in the index. None for some
    /// conflict types (e.g. add/add) where git never populates stage 1.
    pub base: Option<String>,
    /// "Our" version -- stage 2, the current branch's side.
    pub ours: Option<String>,
    /// "Their" version -- stage 3, the incoming branch's side.
    pub theirs: Option<String>,
    /// The raw working-tree file as git left it: real conflict markers
    /// (<<<<<<<< / ======== / >>>>>>>>) inline, ready to hand-edit into the resolution.
    pub current: Option<String>,
}

// Merge-conflict resolution: git_status() already detects conflicted files (the "UU"/"AA"/
// etc. status codes -> "conflicted"), but nothing extracted the actual three sides or let a
// user resolve one -- there was no merge-editor capability in the product at all. Reuses the
// same `git show :N:<path>` mechanism (N = index stage) git itself uses to expose the
// pre-merge blobs; :1 is the common ancestor, :2 is ours, :3 is theirs.
#[tauri::command]
pub fn git_conflict_sides(cwd: String, path: String) -> Result<ConflictSides, String> {
    let show_stage = |stage: &str| -> Option<String> {
        let out = Command::new("git").hide_console()
            .args(["show", &format!(":{}:{}", stage, path)])
            .current_dir(&cwd)
            .output()
            .ok()?;
        if out.status.success() {
            Some(String::from_utf8_lossy(&out.stdout).to_string())
        } else {
            None
        }
    };
    let current = std::fs::read_to_string(std::path::Path::new(&cwd).join(&path)).ok();
    Ok(ConflictSides {
        base: show_stage("1"),
        ours: show_stage("2"),
        theirs: show_stage("3"),
        current,
    })
}

#[tauri::command]
pub fn git_resolve_conflict(cwd: String, path: String, resolved_content: String) -> Result<(), String> {
    std::fs::write(std::path::Path::new(&cwd).join(&path), &resolved_content)
        .map_err(|e| e.to_string())?;
    let output = Command::new("git").hide_console()
        .args(["add", &path])
        .current_dir(&cwd)
        .output()
        .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

// Real `git clone` for ProjectHub's "Git Clone" add-project mode, which previously only
// stored the typed remote URL as text with no actual clone ever happening (localPath stayed
// the literal placeholder "Choose folder to bind" forever). Refuses to clone into an existing
// path -- never overwrites a directory that's already there, whether it's an unrelated folder
// or a previous clone attempt's leftovers.
#[tauri::command]
pub fn git_clone(remote_url: String, destination: String) -> Result<(), String> {
    let dest_path = std::path::Path::new(&destination);
    if dest_path.exists() {
        return Err(format!("destination already exists, refusing to overwrite: {destination}"));
    }
    let output = Command::new("git").hide_console()
        .args(["clone", &remote_url, &destination])
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Real-git integration tests.
//
// These drive actual `git` against a throwaway repo -- no simulated backend.
// Every function in this file shells out to git, so a mock would only assert
// that our own fake behaves like our own fake. That is not hypothetical: the
// frontend's gitService suite simulated staging in memory and, because its
// mock threw where the real transport swallowed, it passed for months while
// production silently reported success for every FAILED commit.
//
// Nothing here touches the user's workspace; each test gets its own tempdir.
// ---------------------------------------------------------------------------
#[cfg(test)]
mod git_integration_tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;
    use std::process::Command;

    /// A throwaway repo with identity configured and one initial commit, so
    /// HEAD exists (many git subcommands behave differently on an unborn
    /// branch).
    fn init_repo() -> (tempfile::TempDir, String) {
        let dir = tempfile::tempdir().expect("tempdir");
        let cwd = dir.path().to_string_lossy().to_string();
        let run = |args: &[&str]| {
            let out = Command::new("git")
                .args(args)
                .current_dir(&cwd)
                .output()
                .expect("git available on PATH");
            assert!(
                out.status.success(),
                "git {:?} failed: {}",
                args,
                String::from_utf8_lossy(&out.stderr)
            );
        };
        run(&["init"]);
        run(&["config", "user.email", "test@determinex.local"]);
        run(&["config", "user.name", "Determinex Test"]);
        // Deterministic branch name regardless of the host's init.defaultBranch.
        run(&["checkout", "-B", "main"]);
        fs::write(PathBuf::from(&cwd).join("seed.txt"), "seed\n").unwrap();
        run(&["add", "seed.txt"]);
        run(&["commit", "-m", "seed"]);
        (dir, cwd)
    }

    fn write(cwd: &str, name: &str, body: &str) {
        fs::write(PathBuf::from(cwd).join(name), body).unwrap();
    }

    #[test]
    fn status_reports_untracked_then_staged() {
        let (_d, cwd) = init_repo();
        write(&cwd, "a.txt", "hello\n");

        let st = git_status(cwd.clone()).expect("status");
        assert_eq!(st.branch, "main");
        let a = st.files.iter().find(|f| f.path == "a.txt").expect("a.txt listed");
        assert_eq!(a.status, "untracked");

        git_stage(cwd.clone(), "a.txt".into()).expect("stage");
        let st = git_status(cwd.clone()).expect("status");
        let a = st.files.iter().find(|f| f.path == "a.txt").expect("a.txt listed");
        assert_eq!(a.status, "staged");
    }

    #[test]
    fn unstage_returns_a_file_to_modified() {
        let (_d, cwd) = init_repo();
        write(&cwd, "seed.txt", "changed\n");
        git_stage(cwd.clone(), "seed.txt".into()).expect("stage");
        git_unstage(cwd.clone(), "seed.txt".into()).expect("unstage");

        let st = git_status(cwd.clone()).expect("status");
        let f = st.files.iter().find(|f| f.path == "seed.txt").expect("listed");
        assert_ne!(f.status, "staged", "unstaged file must not still read as staged");
    }

    #[test]
    fn stage_all_stages_every_change() {
        let (_d, cwd) = init_repo();
        write(&cwd, "a.txt", "a\n");
        write(&cwd, "b.txt", "b\n");
        git_stage_all(cwd.clone()).expect("stage_all");

        let st = git_status(cwd.clone()).expect("status");
        assert!(!st.files.is_empty());
        assert!(
            st.files.iter().all(|f| f.status == "staged"),
            "expected all staged, got {:?}",
            st.files.iter().map(|f| (&f.path, &f.status)).collect::<Vec<_>>()
        );
    }

    /// The case the frontend suite claimed to cover but never did against real
    /// git. An empty commit must be an Err, because the UI shows that message.
    #[test]
    fn commit_with_nothing_staged_is_an_error() {
        let (_d, cwd) = init_repo();
        let res = git_commit(cwd.clone(), "nothing staged".into());
        assert!(res.is_err(), "expected Err committing with an empty index");
    }

    #[test]
    fn commit_with_staged_changes_succeeds_and_clears_the_index() {
        let (_d, cwd) = init_repo();
        write(&cwd, "a.txt", "hello\n");
        git_stage(cwd.clone(), "a.txt".into()).expect("stage");
        git_commit(cwd.clone(), "add a".into()).expect("commit");

        let st = git_status(cwd.clone()).expect("status");
        assert!(
            !st.files.iter().any(|f| f.path == "a.txt"),
            "committed file should no longer be pending"
        );
    }

    #[test]
    fn branch_create_checkout_and_list_round_trip() {
        let (_d, cwd) = init_repo();
        git_create_branch(cwd.clone(), "feature/x".into()).expect("create");

        let branches = git_list_branches(cwd.clone()).expect("list");
        assert!(
            branches.iter().any(|b| b == "feature/x"),
            "new branch missing from {branches:?}"
        );

        git_checkout_branch(cwd.clone(), "main".into()).expect("checkout main");
        assert_eq!(git_status(cwd.clone()).expect("status").branch, "main");
        git_checkout_branch(cwd.clone(), "feature/x".into()).expect("checkout feature");
        assert_eq!(git_status(cwd.clone()).expect("status").branch, "feature/x");
    }

    #[test]
    fn operations_on_a_non_repo_path_report_errors() {
        let dir = tempfile::tempdir().expect("tempdir");
        let cwd = dir.path().to_string_lossy().to_string();
        // Not a git repo: these must surface an error rather than quietly
        // succeeding, which is what the UI's error paths depend on.
        assert!(git_status(cwd.clone()).is_err());
        assert!(git_stage_all(cwd.clone()).is_err());
        assert!(git_commit(cwd, "x".into()).is_err());
    }

    #[test]
    fn push_without_a_remote_is_an_error_not_a_silent_success() {
        let (_d, cwd) = init_repo();
        // No remote configured. GitPanel now surfaces this; before, the
        // frontend swallowed it and the user saw nothing at all.
        assert!(git_push(cwd).is_err(), "push with no remote must be an error");
    }

    #[test]
    fn clone_refuses_an_existing_destination() {
        let (_src, src) = init_repo();
        let dest_dir = tempfile::tempdir().expect("tempdir");
        let dest = dest_dir.path().to_string_lossy().to_string();
        // Destination already exists -> must refuse rather than clobber.
        assert!(git_clone(src, dest).is_err());
    }
}
