//! 测试夹具：构造典型板端 /sys /proc 数据，复用避免每个测试重复造数据。

use std::collections::HashMap;

use crate::common::fakes::{FakeHrutGateway, FakeProcReader, FakeSysfsReader};
use shared::protocol::{StateSnapshot, Thermal, ThermalZone};

/// 典型 sysfs：两个 thermal zone（52°C / 61°C）+ cpufreq policy0=1500000kHz。
pub fn make_fake_sysfs() -> FakeSysfsReader {
    let mut files = HashMap::new();
    files.insert("/sys/class/thermal/thermal_zone0/temp".into(), "52000".into());
    files.insert("/sys/class/thermal/thermal_zone0/type".into(), "thermal-cpu".into());
    files.insert("/sys/class/thermal/thermal_zone1/temp".into(), "61000".into());
    files.insert("/sys/class/thermal/thermal_zone1/type".into(), "thermal-ddr".into());
    files.insert("/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq".into(), "1500000".into());
    let mut dirs = HashMap::new();
    dirs.insert(
        "/sys/class/thermal".into(),
        vec!["thermal_zone0".into(), "thermal_zone1".into()],
    );
    dirs.insert(
        "/sys/devices/system/cpu/cpufreq".into(),
        vec!["policy0".into()],
    );
    FakeSysfsReader { files, dirs }
}

/// 典型 procfs：loadavg、meminfo、net/dev、mounts、uptime、stat。
pub fn make_fake_proc() -> FakeProcReader {
    let mut files = HashMap::new();
    files.insert(
        "/proc/loadavg".into(),
        "1.87 2.40 1.17 3/200 12345\n".into(),
    );
    files.insert(
        "/proc/meminfo".into(),
        "MemTotal:        7424344 kB\nMemFree:          1119498 kB\nMemAvailable:    4268000 kB\nSwapTotal:             0 kB\nSwapFree:              0 kB\n".into(),
    );
    files.insert(
        "/proc/net/dev".into(),
        "Inter-|   Receive                                                |  Transmit\n face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n    lo:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0\n  wlan0: 304664629       0    0    0    0     0          0         0  1410732       0    0    0    0     0       0          0\n".into(),
    );
    files.insert(
        "/proc/mounts".into(),
        "rootfs / rootfs rw 0 0\n/dev/root / ext4 rw,relatime 0 0\nproc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\ntmpfs /tmp tmpfs rw,nosuid,nodev,relatime 0 0\n".into(),
    );
    files.insert("/proc/uptime".into(), "56221.73 55000.00\n".into());
    files.insert(
        "/proc/stat".into(),
        "cpu  100 200 300 400 50 10 5 0 0 0\ncpu0 10 20 30 40 5 1 0 0 0 0\ncpu1 10 20 30 40 5 1 0 0 0 0\n".into(),
    );
    files.insert(
        "/proc/net/fib_trie".into(),
        "Local: 127.0.0.1\nLocal: 192.168.128.10\n".into(),
    );
    FakeProcReader { files }
}

/// 典型 hrut 输出：bpuinfo 含 30% 与 1500 freq，sensors 含 temp 55。
pub fn make_fake_hrut() -> FakeHrutGateway {
    let mut tools = HashMap::new();
    tools.insert("hrut_bpuinfo".into(), "BPU utilisation: 30%\nBPU freq: 1500\n".into());
    tools.insert("hrut_sensors".into(), "temp: 55.0\n".into());
    FakeHrutGateway { tools }
}

/// 一个超阈值的 thermal 快照（80°C），用于 alert 测试。
pub fn make_thermal_snap(temp: f64) -> StateSnapshot {
    StateSnapshot {
        thermal: Some(Thermal {
            zones: vec![ThermalZone { name: "thermal-cpu".into(), temp_c: temp }],
        }),
        ..Default::default()
    }
}
