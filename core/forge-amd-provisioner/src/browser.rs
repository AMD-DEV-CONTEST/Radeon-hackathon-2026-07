use std::process::{Child, Command};
use std::time::Duration;

pub struct BrowserVncBridge {
    xvfb: Option<Child>,
    x11vnc: Option<Child>,
    websockify: Option<Child>,
}

impl BrowserVncBridge {
    pub fn new() -> Self {
        Self {
            xvfb: None,
            x11vnc: None,
            websockify: None,
        }
    }

    pub fn start(&mut self) -> Result<(), String> {
        println!("[Browser] Spawning Xvfb on :99...");
        self.xvfb = Command::new("Xvfb")
            .args(&[":99", "-screen", "0", "1280x800x24"])
            .spawn()
            .ok();

        std::thread::sleep(Duration::from_millis(500));

        println!("[Browser] Spawning x11vnc on :99 (localhost only)...");
        self.x11vnc = Command::new("x11vnc")
            .args(&["-display", ":99", "-localhost", "-nopw", "-bg", "-quiet"])
            .spawn()
            .ok();

        std::thread::sleep(Duration::from_millis(500));

        println!("[Browser] Spawning websockify for MissionSpec noVNC on port 6080...");
        self.websockify = Command::new("websockify")
            .args(&["6080", "localhost:5900", "-D"])
            .spawn()
            .ok();

        if self.xvfb.is_none() || self.x11vnc.is_none() || self.websockify.is_none() {
            return Err(format!(
                "VNC bridge failed to start — xvfb={} x11vnc={} websockify={}",
                self.xvfb.is_some(),
                self.x11vnc.is_some(),
                self.websockify.is_some()
            ));
        }

        Ok(())

    }
}

impl Drop for BrowserVncBridge {
    fn drop(&mut self) {
        println!("[Browser] Cleaning up temporary browser session...");
        if let Some(mut child) = self.websockify.take() {
            let _ = child.kill();
        }
        if let Some(mut child) = self.x11vnc.take() {
            let _ = child.kill();
        }
        if let Some(mut child) = self.xvfb.take() {
            let _ = child.kill();
        }
    }
}
