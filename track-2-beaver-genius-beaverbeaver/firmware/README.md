# BeaverBeaver CoreS3 Firmware Source Package

Team: **Beaver Genius**  
Target: **M5Stack CoreS3 / ESP32-S3**  
Track: **AMD Radeon Hackathon 2026 — Track 2**

This directory is the minimal public firmware package used by the BeaverBeaver
demo. It does not duplicate the entire upstream `xiaozhi-esp32` repository.
Instead, it pins an exact public upstream commit and provides the complete patch
needed to reconstruct the BeaverBeaver CoreS3 firmware.

## Source baseline

- Upstream: <https://github.com/78/xiaozhi-esp32>
- Upstream commit: `417f52d7597b85f3dfc6f5283bdc66df34fbd5fe`
- Upstream commit date: 2026-05-14
- License: MIT; the original copyright and license are retained in `LICENSE`.

## What is included

- Background JPEG and WAV capture on M5Stack CoreS3;
- SD-card durable media queues;
- sequence IDs, boot/stream identity and SHA-256 metadata;
- authenticated upload to Beaver Memory;
- retry, backoff, ACK handling and restart recovery;
- CoreS3 camera/audio/display integration;
- Beaver interaction states and UI status;
- the common firmware changes required to compile this CoreS3 target.

The patch is located at:

```text
patches/0001-beaverbeaver-cores3.patch
```

## Intentionally not included

This is a **firmware component package**, not a claim that every BeaverBeaver
service is contained here. The following remain separate from this public
firmware package:

- the private LiveKit/agent bridge implementation;
- the Beaver Memory backend and private deployment state;
- Radeon API keys, device tokens and local network addresses;
- model weights and private inference credentials;
- experimental receivers, captured WAV/JPEG files and evaluation data;
- changes for hardware boards other than M5Stack CoreS3.

The competition's complete project submission must either publish the remaining
server components separately or clearly document them as external/private
services. Do not describe this directory alone as the complete BeaverBeaver
repository.

## Prerequisites

- Linux;
- Git;
- Python 3.12;
- ESP-IDF 5.5.2 or newer.

ESP-IDF downloads the managed components declared by the upstream
`main/idf_component.yml`; generated `managed_components/` and `build/`
directories are intentionally not bundled.

## Reconstruct the source tree

From this directory, run:

```bash
./prepare_firmware.sh /tmp/beaverbeaver-xiaozhi
cd /tmp/beaverbeaver-xiaozhi
```

The script clones the public upstream repository, checks out the pinned commit,
checks the patch, and applies it. It refuses to overwrite an existing target
directory.

## Configure the public placeholders

Before building, edit:

```text
main/boards/m5stack-core-s3/config.json
```

Replace these example values with the evaluator's deployment values:

```text
ws://beaver-bridge.local:8080
http://beaver-memory.local:8789
replace-with-device-token
```

Never commit a real API key or device token. For a production public repository,
prefer build-time configuration or an ignored local SDK configuration file.

## Build

Activate ESP-IDF, then build the CoreS3 release:

```bash
source "$IDF_PATH/export.sh"
python scripts/release.py m5stack-core-s3
```

To flash and monitor a connected device:

```bash
idf.py -p /dev/ttyACM0 flash monitor
```

Adjust the serial port as needed.

## Verify package integrity

The public patch should not contain development IP addresses, real or legacy
device tokens, API keys, private media or the private bridge source. Before every
release, run:

```bash
./verify_public_package.sh
```

## 中文说明

这个目录只公开能够重建 M5Stack CoreS3 参赛固件的必要修改，并通过固定上游
commit 加补丁的方式保证可复现。LiveKit bridge、Beaver Memory 服务端、模型密钥、
局域网地址、真实媒体和其他板卡实验代码不会包含在此固件包内。

需要注意：比赛要求完整项目源代码，因此最终提交时应把这个目录明确标注为
“Firmware component”，并另外提供可公开的 Memory Server/Radeon 部署部分，或在
报告中准确说明哪些能力是外部服务，不能把该固件包单独描述成整个项目源码。
