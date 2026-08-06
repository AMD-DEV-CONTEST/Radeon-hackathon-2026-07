// 动画预览 —— FRONTEND_PLAN_V2.md §1.2(b)
//
// 视频功能产出的是动画，网格视图和画布视图都看不了。
// **这是视频功能的验收界面**：没有它用户无法判断结果好不好。
//
// 只读。要改动画去 Aseprite 改完再导回来（§6 不做什么）。

export class AnimView {
  constructor({ img, meta, playBtn, prevBtn, nextBtn, speedSelect }) {
    this.img = img;
    this.meta = meta;
    this.playBtn = playBtn;
    this.frames = [];
    this.index = 0;
    this.playing = false;
    this.speed = 1;
    this.timer = null;
    this.scale = 4;

    playBtn?.addEventListener('click', () => this.toggle());
    prevBtn?.addEventListener('click', () => { this.pause(); this.step(-1); });
    nextBtn?.addEventListener('click', () => { this.pause(); this.step(1); });
    speedSelect?.addEventListener('change', (e) => {
      this.speed = Number(e.target.value) || 1;
      if (this.playing) { this.pause(); this.play(); }
    });
  }

  /** @param frames [{url,width,height,durationMs}] */
  load(frames) {
    this.pause();
    this.frames = frames ?? [];
    this.index = 0;
    // 整数倍放大，和画布视图同一套规则——不出现任意小数比例
    const first = this.frames[0];
    if (first) {
      const longest = Math.max(first.width, first.height);
      this.scale = Math.max(1, Math.floor(320 / Math.max(1, longest)));
    }
    this.render();
  }

  render() {
    const frame = this.frames[this.index];
    if (!frame) {
      this.img.removeAttribute('src');
      this.meta.textContent = '没有可播放的帧。用「视频转动帧」或选择一个多帧资产。';
      return;
    }
    this.img.src = frame.url;
    this.img.width = Math.max(1, frame.width * this.scale);
    this.img.height = Math.max(1, frame.height * this.scale);
    const fps = frame.durationMs ? Math.round(1000 / frame.durationMs) : '--';
    this.meta.textContent =
      `第 ${this.index + 1}/${this.frames.length} 帧 · ${frame.durationMs ?? '--'}ms · 约 ${fps} fps · ${this.scale}x`;
  }

  step(delta) {
    if (this.frames.length === 0) return;
    this.index = (this.index + delta + this.frames.length) % this.frames.length;
    this.render();
  }

  play() {
    if (this.frames.length <= 1) return;
    this.playing = true;
    if (this.playBtn) this.playBtn.textContent = '❚❚ 暂停';
    const tick = () => {
      if (!this.playing) return;
      this.step(1);
      const wait = (this.frames[this.index]?.durationMs ?? 120) / this.speed;
      this.timer = setTimeout(tick, Math.max(16, wait));
    };
    const wait = (this.frames[this.index]?.durationMs ?? 120) / this.speed;
    this.timer = setTimeout(tick, Math.max(16, wait));
  }

  pause() {
    this.playing = false;
    clearTimeout(this.timer);
    if (this.playBtn) this.playBtn.textContent = '▶ 播放';
  }

  toggle() {
    if (this.playing) this.pause(); else this.play();
  }
}
