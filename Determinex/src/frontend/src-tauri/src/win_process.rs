// Every subprocess this app spawns (git, python, cargo, ollama, the hive
// sidecar, ...) is a one-shot background call whose output is captured and
// rendered inside the app's own UI -- never meant to be an interactive
// visible console. Without CREATE_NO_WINDOW, Windows pops a real console
// window for each one whenever the parent has no console of its own, which
// is exactly the case for this app both packaged (GUI subsystem, no
// attached console at all) and in some dev-launch configurations. Found live
// 2026-07-21 (Ryan: "i keep getting a cmd pop up and cant see what its
// saying"): every one of the 74 Command::new call sites across this crate
// was vulnerable -- CREATE_NO_WINDOW was not used anywhere in the codebase
// (the two prior `creation_flags` call sites set CREATE_NEW_PROCESS_GROUP
// instead, a different flag for Ctrl+Break signal delivery, not window
// visibility).
//
// The interactive Terminal panel (pty_terminal.rs) is unaffected -- it uses
// portable_pty::CommandBuilder (ConPTY), a separate mechanism that already
// renders into the app's own terminal UI rather than a native window.

pub trait HideConsoleExt {
    /// Suppress the console window Windows would otherwise pop for this
    /// child process. No-op on other platforms. Chainable like the rest of
    /// `Command`'s builder methods.
    fn hide_console(&mut self) -> &mut Self;
}

impl HideConsoleExt for std::process::Command {
    #[cfg(target_os = "windows")]
    fn hide_console(&mut self) -> &mut Self {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        self.creation_flags(CREATE_NO_WINDOW)
    }

    #[cfg(not(target_os = "windows"))]
    fn hide_console(&mut self) -> &mut Self {
        self
    }
}

/// For the two call sites that also need CREATE_NEW_PROCESS_GROUP (killable
/// process groups via Ctrl+Break) -- both flags combined, not one replacing
/// the other.
pub trait HideConsoleNewGroupExt {
    fn hide_console_new_group(&mut self) -> &mut Self;
}

impl HideConsoleNewGroupExt for std::process::Command {
    #[cfg(target_os = "windows")]
    fn hide_console_new_group(&mut self) -> &mut Self {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
        self.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
    }

    #[cfg(not(target_os = "windows"))]
    fn hide_console_new_group(&mut self) -> &mut Self {
        self
    }
}

// tokio::process::Command is a separate type from std::process::Command (it
// wraps it, but exposes its own builder API) -- several async Tauri command
// handlers (bootstrap.rs, ipc_bootstrap.rs, model_puller.rs,
// ollama_installer.rs, terminal.rs, ipc_hive/session.rs) spawn through it
// instead, so it needs its own impl of the same extension trait.
impl HideConsoleExt for tokio::process::Command {
    #[cfg(target_os = "windows")]
    fn hide_console(&mut self) -> &mut Self {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        self.creation_flags(CREATE_NO_WINDOW)
    }

    #[cfg(not(target_os = "windows"))]
    fn hide_console(&mut self) -> &mut Self {
        self
    }
}
