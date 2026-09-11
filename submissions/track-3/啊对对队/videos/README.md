# Demo video / 演示视频

[Public Bilibili video / Bilibili 公开视频](https://www.bilibili.com/video/BV1Qkun6qEKn/)

[Agent+v21 hybrid source videos](v21-agent-vla-hybrid-success/README.md) ·
[MP4](genesis_panda_8_success_reference_demo.mp4) · [source manifest](source_manifest.json) · [concat script](concat_raw_success_overviews.py)

The MP4 is the direct episode-order concatenation of successful overview
streams `0, 1, 2, 4, 6, 7, 8, 9`. It is H.264, 224x224, 10 fps, 456 frames,
and 45.6 seconds. FFmpeg used the concat demuxer with `-c:v copy`; no source
frames were cut, scaled, retimed, captioned, or re-encoded.

该 MP4 按 `0、1、2、4、6、7、8、9` 的 episode 顺序直接拼接成功 overview
视频。编码为 H.264，分辨率 224x224，10 fps，共 456 帧、45.6 秒。FFmpeg
使用 concat demuxer 与 `-c:v copy`；没有裁帧、缩放、变速、字幕或重新编码。

The controller is `ScriptedPickPlaceExpert + ClosedLoopSupervisor`; the video
is not a learned-policy result. SHA-256:
`9eb72630c22a53da3d6be105d8ab8f813260ac34643b9f2dcb5c5568cd9c11af`.

视频控制器为 `ScriptedPickPlaceExpert + ClosedLoopSupervisor`，不是学习策略结果。
SHA-256 同上。
