//! all_smi — Unified accelerator discovery and monitoring.
//!
//! Auto-detects and queries ALL accelerator types on local and remote nodes:
//!
//!   NVIDIA  → nvml-wrapper (direct NVML API, no binary needed)
//!   AMD     → rocm-smi if available, else amdgpu sysfs (works on RX 580 with no ROCm)
//!   Intel   → i915/xe sysfs + intel_gpu_top if present
//!   IBM     → Telum/Spyre via lszcrypt + /sys/bus/ap (s390x mainframe)
//!             On x86: IBM MI300X = AMD ROCm path
//!
//! For remote nodes: SSH + same detection logic run inline via shell one-liners.
//! No external binaries required on the Forge server — everything is either
//! direct Rust API (NVML) or tiny inline Python/shell scripts sent over SSH.

use serde::{Deserialize, Serialize};
use tokio::process::Command;
use tracing::{info, warn};

// ── Unified GPU record ────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AcceleratorInfo {
    pub index: u32,
    pub name: String,
    pub vendor: AcceleratorVendor,
    pub temperature_c: u32,
    pub utilization_pct: u32,
    pub memory_used_mb: u64,
    pub memory_total_mb: u64,
    pub power_draw_w: f32,
    pub power_limit_w: f32,
    pub fan_speed_pct: Option<u32>,
    pub clock_gpu_mhz: Option<u32>,
    pub clock_mem_mhz: Option<u32>,
    pub pcie_gen: Option<u32>,
    pub pcie_width: Option<u32>,
    pub node: String,
    pub source: String,   // "nvml" | "rocm-smi" | "amdgpu-sysfs" | "intel-sysfs" | "ibm-ap"
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum AcceleratorVendor {
    Nvidia,
    Amd,
    Intel,
    Ibm,
    #[default]
    Unknown,
}

impl std::fmt::Display for AcceleratorVendor {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Self::Nvidia  => write!(f, "nvidia"),
            Self::Amd     => write!(f, "amd"),
            Self::Intel   => write!(f, "intel"),
            Self::Ibm     => write!(f, "ibm"),
            Self::Unknown => write!(f, "unknown"),
        }
    }
}

// ── Node definition ───────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct NodeTarget {
    pub name: String,
    pub ip: Option<String>,   // None = local
    pub ssh_user: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeReport {
    pub name: String,
    pub ip: String,
    pub accelerators: Vec<AcceleratorInfo>,
    pub reachable: bool,
    pub error: Option<String>,
    pub arch: String,   // "x86_64" | "s390x" | "aarch64"
}

// ── NVIDIA via nvml-wrapper ───────────────────────────────────────────────────

pub async fn query_nvidia_nvml(node: &str) -> Vec<AcceleratorInfo> {
    tokio::task::spawn_blocking({
        let node = node.to_string();
        move || {
            let nvml = match nvml_wrapper::Nvml::init() {
                Ok(n) => n,
                Err(e) => {
                    warn!("NVML init failed on {}: {}", node, e);
                    return vec![];
                }
            };
            let count = match nvml.device_count() {
                Ok(c) => c,
                Err(e) => {
                    warn!("NVML device_count failed: {}", e);
                    return vec![];
                }
            };
            let mut gpus = Vec::new();
            for i in 0..count {
                let dev = match nvml.device_by_index(i) {
                    Ok(d) => d,
                    Err(_) => continue,
                };
                let name = dev.name().unwrap_or_else(|_| format!("NVIDIA GPU {}", i));
                let temp = dev.temperature(nvml_wrapper::enum_wrappers::device::TemperatureSensor::Gpu).unwrap_or(0);
                let util = dev.utilization_rates().map(|u| u.gpu).unwrap_or(0);
                let mem = dev.memory_info().ok();
                let power = dev.power_usage().map(|p| p as f32 / 1000.0).unwrap_or(0.0);
                let power_limit = dev.enforced_power_limit().map(|p| p as f32 / 1000.0).unwrap_or(0.0);
                let fan = dev.fan_speed(0).ok();
                let clock_gpu = dev.clock_info(nvml_wrapper::enum_wrappers::device::Clock::Graphics).ok();
                let clock_mem = dev.clock_info(nvml_wrapper::enum_wrappers::device::Clock::Memory).ok();
                let pcie_gen = dev.current_pcie_link_gen().ok();
                let pcie_w   = dev.current_pcie_link_width().ok();

                gpus.push(AcceleratorInfo {
                    index: i,
                    name,
                    vendor: AcceleratorVendor::Nvidia,
                    temperature_c: temp,
                    utilization_pct: util,
                    memory_used_mb: mem.as_ref().map(|m| m.used / 1024 / 1024).unwrap_or(0),
                    memory_total_mb: mem.as_ref().map(|m| m.total / 1024 / 1024).unwrap_or(0),
                    power_draw_w: power,
                    power_limit_w: power_limit,
                    fan_speed_pct: fan,
                    clock_gpu_mhz: clock_gpu,
                    clock_mem_mhz: clock_mem,
                    pcie_gen: pcie_gen,
                    pcie_width: pcie_w,
                    node: node.clone(),
                    source: "nvml".into(),
                });
            }
            info!("NVML found {} GPU(s) on {}", gpus.len(), node);
            gpus
        }
    })
    .await
    .unwrap_or_default()
}

// ── AMD via amdgpu sysfs (no ROCm needed) ────────────────────────────────────
// Works on: RX 470/480/570/580/590, Vega, Navi, RDNA2/3
// Requires: amdgpu kernel module loaded (standard on all modern distros)

const AMD_SYSFS_SCRIPT: &str = r#"python3 -c "
import glob, json, os
cards = []
for i, dp in enumerate(sorted(glob.glob('/sys/class/drm/card*/device'))):
    try:
        vendor = open(dp+'/vendor').read().strip()
    except:
        continue
    if vendor != '0x1002':
        continue
    def r(p, default='0'):
        try: return open(p).read().strip()
        except: return default
    vram_total = int(r(dp+'/mem_info_vram_total', '0'))
    vram_used  = int(r(dp+'/mem_info_vram_used',  '0'))
    busy       = int(r(dp+'/gpu_busy_percent',     '0'))
    temp, power, fan, clk_gpu, clk_mem = 0, 0.0, None, None, None
    for hw in glob.glob(dp+'/hwmon/hwmon*/'):
        t = r(hw+'temp1_input')
        p = r(hw+'power1_average')
        f = r(hw+'fan1_input')
        cg = r(hw+'freq1_input')
        cm = r(hw+'freq2_input')
        if t != '0': temp     = int(t)//1000
        if p != '0': power    = float(p)/1000000
        if f != '0': fan      = int(f)
        if cg!= '0': clk_gpu  = int(cg)//1000000
        if cm!= '0': clk_mem  = int(cm)//1000000
    name = r(dp+'/product_name', 'AMD Radeon').strip() or 'AMD Radeon'
    pwr_cap = r(dp+'/hwmon/hwmon0/power1_cap', '0')
    pwr_limit = float(pwr_cap)/1000000 if pwr_cap != '0' else 0.0
    cards.append({'i':i,'name':name,'temp':temp,'busy':busy,
        'vram_total_mb':vram_total//1048576,'vram_used_mb':vram_used//1048576,
        'power_w':power,'power_limit_w':pwr_limit,'fan_rpm':fan,
        'clk_gpu_mhz':clk_gpu,'clk_mem_mhz':clk_mem})
print(json.dumps(cards))
" 2>/dev/null"#;

pub async fn query_amd_sysfs_local(node: &str) -> Vec<AcceleratorInfo> {
    let out = Command::new("sh").arg("-c").arg(AMD_SYSFS_SCRIPT).output().await;
    parse_amd_sysfs_json(out, node)
}

pub async fn query_amd_sysfs_remote(ip: &str, user: &str, node: &str) -> Vec<AcceleratorInfo> {
    let cmd = format!("ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no {}@{} '{}'",
        user, ip, AMD_SYSFS_SCRIPT.replace('\'', "'\"'\"'"));
    let out = Command::new("sh").arg("-c").arg(&cmd).output().await;
    parse_amd_sysfs_json(out, node)
}

fn parse_amd_sysfs_json(out: Result<std::process::Output, std::io::Error>, node: &str) -> Vec<AcceleratorInfo> {
    let out = match out { Ok(o) if !o.stdout.is_empty() => o, _ => return vec![] };
    let parsed: serde_json::Value = match serde_json::from_str(String::from_utf8_lossy(&out.stdout).trim()) {
        Ok(v) => v, Err(_) => return vec![],
    };
    parsed.as_array().unwrap_or(&vec![]).iter().map(|c| AcceleratorInfo {
        index:           c["i"].as_u64().unwrap_or(0) as u32,
        name:            c["name"].as_str().unwrap_or("AMD Radeon").to_string(),
        vendor:          AcceleratorVendor::Amd,
        temperature_c:   c["temp"].as_u64().unwrap_or(0) as u32,
        utilization_pct: c["busy"].as_u64().unwrap_or(0) as u32,
        memory_used_mb:  c["vram_used_mb"].as_u64().unwrap_or(0),
        memory_total_mb: c["vram_total_mb"].as_u64().unwrap_or(0),
        power_draw_w:    c["power_w"].as_f64().unwrap_or(0.0) as f32,
        power_limit_w:   c["power_limit_w"].as_f64().unwrap_or(0.0) as f32,
        fan_speed_pct:   c["fan_rpm"].as_u64().map(|f| f as u32),
        clock_gpu_mhz:   c["clk_gpu_mhz"].as_u64().map(|v| v as u32),
        clock_mem_mhz:   c["clk_mem_mhz"].as_u64().map(|v| v as u32),
        pcie_gen: None, pcie_width: None,
        node: node.to_string(),
        source: "amdgpu-sysfs".into(),
    }).collect()
}

// ── Intel Arc / Xe / iGPU via sysfs ──────────────────────────────────────────
// Vendor ID 0x8086, driver: i915 or xe

const INTEL_SYSFS_SCRIPT: &str = r#"python3 -c "
import glob, json
cards = []
for i, dp in enumerate(sorted(glob.glob('/sys/class/drm/card*/device'))):
    try:
        vendor = open(dp+'/vendor').read().strip()
    except:
        continue
    if vendor != '0x8086':
        continue
    def r(p, default='0'):
        try: return open(p).read().strip()
        except: return default
    # Intel uses hwmon for temp; no dedicated VRAM sysfs on iGPU
    # For Arc dGPU: /sys/class/drm/card*/device/drm/card*/gt/gt0/
    temp, power, clk = 0, 0.0, None
    for hw in glob.glob(dp+'/hwmon/hwmon*/'):
        t = r(hw+'temp1_input')
        p = r(hw+'power1_input')
        c = r(hw+'freq1_input')
        if t != '0': temp  = int(t)//1000
        if p != '0': power = float(p)/1000000
        if c != '0': clk   = int(c)//1000000
    name = r(dp+'/product_name','Intel GPU').strip() or 'Intel GPU'
    # Try gt utilization
    busy = 0
    for gt in glob.glob(dp+'/drm/*/gt/gt*/'):
        b = r(gt+'gt_cur_freq_mhz','0')
    cards.append({'i':i,'name':name,'temp':temp,'power_w':power,'clk_mhz':clk})
print(json.dumps(cards))
" 2>/dev/null"#;

pub async fn query_intel_sysfs_local(node: &str) -> Vec<AcceleratorInfo> {
    let out = Command::new("sh").arg("-c").arg(INTEL_SYSFS_SCRIPT).output().await;
    parse_intel_json(out, node)
}

pub async fn query_intel_sysfs_remote(ip: &str, user: &str, node: &str) -> Vec<AcceleratorInfo> {
    let cmd = format!("ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no {}@{} '{}'",
        user, ip, INTEL_SYSFS_SCRIPT.replace('\'', "'\"'\"'"));
    let out = Command::new("sh").arg("-c").arg(&cmd).output().await;
    parse_intel_json(out, node)
}

fn parse_intel_json(out: Result<std::process::Output, std::io::Error>, node: &str) -> Vec<AcceleratorInfo> {
    let out = match out { Ok(o) if !o.stdout.is_empty() => o, _ => return vec![] };
    let parsed: serde_json::Value = match serde_json::from_str(String::from_utf8_lossy(&out.stdout).trim()) {
        Ok(v) => v, Err(_) => return vec![],
    };
    parsed.as_array().unwrap_or(&vec![]).iter().map(|c| AcceleratorInfo {
        index:           c["i"].as_u64().unwrap_or(0) as u32,
        name:            c["name"].as_str().unwrap_or("Intel GPU").to_string(),
        vendor:          AcceleratorVendor::Intel,
        temperature_c:   c["temp"].as_u64().unwrap_or(0) as u32,
        utilization_pct: 0,
        memory_used_mb:  0,
        memory_total_mb: 0,
        power_draw_w:    c["power_w"].as_f64().unwrap_or(0.0) as f32,
        power_limit_w:   0.0,
        fan_speed_pct:   None,
        clock_gpu_mhz:   c["clk_mhz"].as_u64().map(|v| v as u32),
        clock_mem_mhz:   None,
        pcie_gen: None, pcie_width: None,
        node: node.to_string(),
        source: "intel-sysfs".into(),
    }).collect()
}

// ── IBM Telum / Spyre via /sys/bus/ap (s390x) ────────────────────────────────
// On s390x mainframes: crypto/AI accelerators are AP (Adjunct Processor) devices
// On x86 with IBM MI300X: falls through to AMD ROCm path
// lszcrypt shows Telum AI units; /sys/bus/ap/devices/ has online/config

const IBM_AP_SCRIPT: &str = r#"python3 -c "
import glob, json, os, subprocess
accels = []
# Check architecture
arch = os.uname().machine
if arch == 's390x':
    # IBM Z / LinuxONE - Telum AI accelerator
    try:
        out = subprocess.check_output(['lszcrypt', '-V'], stderr=subprocess.DEVNULL, text=True)
        for line in out.splitlines():
            if 'CEX' in line or 'Telum' in line or 'AI' in line.upper():
                accels.append({'type':'ibm-telum','name':line.strip(),'arch':'s390x'})
    except:
        pass
    # Also check /sys/bus/ap
    for dev in glob.glob('/sys/bus/ap/devices/card*/'):
        online = open(dev+'online','r').read().strip() if os.path.exists(dev+'online') else '0'
        dev_type = open(dev+'type','r').read().strip() if os.path.exists(dev+'type') else 'unknown'
        accels.append({'type':'ibm-ap','name':'IBM AP '+dev_type,'online':online=='1','arch':'s390x'})
else:
    # x86 - check for IBM PCIe cards (rare, but possible in cloud)
    try:
        lspci = subprocess.check_output(['lspci', '-nn'], text=True, stderr=subprocess.DEVNULL)
        for line in lspci.splitlines():
            if '1014:' in line:  # IBM PCI vendor ID
                accels.append({'type':'ibm-pcie','name':line.strip(),'arch':arch})
    except:
        pass
print(json.dumps(accels))
" 2>/dev/null"#;

pub async fn query_ibm_local(node: &str) -> Vec<AcceleratorInfo> {
    let out = Command::new("sh").arg("-c").arg(IBM_AP_SCRIPT).output().await;
    parse_ibm_json(out, node)
}

pub async fn query_ibm_remote(ip: &str, user: &str, node: &str) -> Vec<AcceleratorInfo> {
    let cmd = format!("ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no {}@{} '{}'",
        user, ip, IBM_AP_SCRIPT.replace('\'', "'\"'\"'"));
    let out = Command::new("sh").arg("-c").arg(&cmd).output().await;
    parse_ibm_json(out, node)
}

fn parse_ibm_json(out: Result<std::process::Output, std::io::Error>, node: &str) -> Vec<AcceleratorInfo> {
    let out = match out { Ok(o) if !o.stdout.is_empty() => o, _ => return vec![] };
    let parsed: serde_json::Value = match serde_json::from_str(String::from_utf8_lossy(&out.stdout).trim()) {
        Ok(v) => v, Err(_) => return vec![],
    };
    parsed.as_array().unwrap_or(&vec![]).iter().enumerate().map(|(i, c)| AcceleratorInfo {
        index:           i as u32,
        name:            c["name"].as_str().unwrap_or("IBM Accelerator").to_string(),
        vendor:          AcceleratorVendor::Ibm,
        temperature_c:   0,
        utilization_pct: 0,
        memory_used_mb:  0,
        memory_total_mb: 0,
        power_draw_w:    0.0,
        power_limit_w:   0.0,
        fan_speed_pct:   None,
        clock_gpu_mhz:   None,
        clock_mem_mhz:   None,
        pcie_gen: None, pcie_width: None,
        node: node.to_string(),
        source: "ibm-ap".into(),
    }).collect()
}

// ── Auto-detect: all vendors, one node ───────────────────────────────────────

pub async fn query_all_accelerators(target: &NodeTarget) -> Vec<AcceleratorInfo> {
    let node = &target.name;

    match &target.ip {
        None => {
            // Local: run all probes concurrently
            let (nvidia, amd, intel, ibm) = tokio::join!(
                query_nvidia_nvml(node),
                query_amd_sysfs_local(node),
                query_intel_sysfs_local(node),
                query_ibm_local(node),
            );
            // Re-index so indices are globally unique per node
            let mut all = nvidia;
            let offset = all.len() as u32;
            all.extend(amd.into_iter().map(|mut g| { g.index += offset; g }));
            let offset = all.len() as u32;
            all.extend(intel.into_iter().map(|mut g| { g.index += offset; g }));
            let offset = all.len() as u32;
            all.extend(ibm.into_iter().map(|mut g| { g.index += offset; g }));
            info!("all_smi local: {} accelerator(s) found on {}", all.len(), node);
            all
        }
        Some(ip) => {
            let user = &target.ssh_user;
            // Remote: NVML can't run remotely - fall back to nvidia-smi for NVIDIA
            let (nvidia_remote, amd, intel, ibm) = tokio::join!(
                query_nvidia_remote_ssh(ip, user, node),
                query_amd_sysfs_remote(ip, user, node),
                query_intel_sysfs_remote(ip, user, node),
                query_ibm_remote(ip, user, node),
            );
            let mut all = nvidia_remote;
            let offset = all.len() as u32;
            all.extend(amd.into_iter().map(|mut g| { g.index += offset; g }));
            let offset = all.len() as u32;
            all.extend(intel.into_iter().map(|mut g| { g.index += offset; g }));
            let offset = all.len() as u32;
            all.extend(ibm.into_iter().map(|mut g| { g.index += offset; g }));
            info!("all_smi remote {}: {} accelerator(s) found", node, all.len());
            all
        }
    }
}

// nvidia-smi fallback for remote nodes (NVML can't cross SSH)
async fn query_nvidia_remote_ssh(ip: &str, user: &str, node: &str) -> Vec<AcceleratorInfo> {
    let script = "nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit,fan.speed,clocks.gr,clocks.mem,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader,nounits 2>/dev/null";
    let cmd = format!("ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no {}@{} '{}'", user, ip, script);
    let out = Command::new("sh").arg("-c").arg(&cmd).output().await;
    let out = match out { Ok(o) if o.status.success() || !o.stdout.is_empty() => o, _ => return vec![] };
    let stdout = String::from_utf8_lossy(&out.stdout);
    stdout.lines().enumerate().filter_map(|(_, line)| {
        let p: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
        if p.len() < 7 { return None; }
        let fan: Option<u32> = p.get(8).and_then(|v| v.parse().ok());
        Some(AcceleratorInfo {
            index:           p[0].parse().unwrap_or(0),
            name:            p[1].to_string(),
            vendor:          AcceleratorVendor::Nvidia,
            temperature_c:   p[2].parse().unwrap_or(0),
            utilization_pct: p[3].parse().unwrap_or(0),
            memory_used_mb:  p[4].parse().unwrap_or(0),
            memory_total_mb: p[5].parse().unwrap_or(0),
            power_draw_w:    p[6].parse().unwrap_or(0.0),
            power_limit_w:   p.get(7).and_then(|v| v.parse().ok()).unwrap_or(0.0),
            fan_speed_pct:   fan,
            clock_gpu_mhz:   p.get(9).and_then(|v| v.parse().ok()),
            clock_mem_mhz:   p.get(10).and_then(|v| v.parse().ok()),
            pcie_gen:        p.get(11).and_then(|v| v.parse().ok()),
            pcie_width:      p.get(12).and_then(|v| v.parse().ok()),
            node: node.to_string(),
            source: "nvidia-smi-ssh".into(),
        })
    }).collect()
}

// ── Fleet-wide query ──────────────────────────────────────────────────────────

pub fn known_fleet() -> Vec<NodeTarget> {
    vec![
        NodeTarget { name: "t440".into(),      ip: None,                    ssh_user: "cesarops".into() },
        NodeTarget { name: "cesarops4".into(), ip: Some("10.0.0.41".into()),  ssh_user: "cesarops".into() },
        NodeTarget { name: "cesarops3".into(), ip: Some("10.0.0.111".into()), ssh_user: "cesarops".into() },
        NodeTarget { name: "cesarops2".into(), ip: Some("10.0.0.201".into()), ssh_user: "cesarops".into() },
    ]
}

pub async fn query_full_fleet() -> Vec<NodeReport> {
    let fleet = known_fleet();
    let futures: Vec<_> = fleet.iter().map(|target| {
        let t = target.clone();
        async move {
            let accels = query_all_accelerators(&t).await;
            let reachable = t.ip.is_none() || !accels.is_empty();
            NodeReport {
                name: t.name.clone(),
                ip: t.ip.clone().unwrap_or_else(|| "127.0.0.1".into()),
                reachable,
                error: if !reachable { Some("No accelerators found or node unreachable".into()) } else { None },
                accelerators: accels,
                arch: "x86_64".into(), // TODO: detect from uname on remote
            }
        }
    }).collect();

    futures::future::join_all(futures).await
}

// ── Stress test primitives ────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StressSnapshot {
    pub timestamp_ms: u64,
    pub accelerators: Vec<AcceleratorInfo>,
}

/// Take a single snapshot — used by the stress test streamer
pub async fn snapshot_local() -> StressSnapshot {
    let target = NodeTarget { name: "local".into(), ip: None, ssh_user: "cesarops".into() };
    let accels = query_all_accelerators(&target).await;
    StressSnapshot {
        timestamp_ms: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64,
        accelerators: accels,
    }
}
