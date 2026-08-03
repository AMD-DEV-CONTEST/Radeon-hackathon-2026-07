import { motion } from 'framer-motion';
import { Camera, Brain, Sparkles, FileImage } from 'lucide-react';

const STEPS = [
  {
    id: '01',
    code: 'Reality',
    zh: '上传真实素材',
    en: 'Real assets, not prompts.',
    desc: '人物、Logo、地点与参考图分别上传；当前版本准确保留文字与 Logo，人物条件化规划中。',
    icon: Camera,
  },
  {
    id: '02',
    code: 'AI Understanding',
    zh: '理解人物 / 音乐 / 场景',
    en: 'Perceive the source.',
    desc: '多模态模型读取人脸、Logo、场景与文本，判断谁能保留、谁要重新生成。',
    icon: Brain,
  },
  {
    id: '03',
    code: 'Visual Creation',
    zh: '生成视觉作品',
    en: 'Compose the stage.',
    desc: '在风格、节奏、空间结构上自由发挥，把真实素材放进主视觉构图。',
    icon: Sparkles,
  },
  {
    id: '04',
    code: 'Your Poster',
    zh: '输出可发布海报',
    en: 'Ship to the world.',
    desc: '1024 × 1536 · 300dpi · PNG / 印刷就绪。下一次演出，今晚就能挂出来。',
    icon: FileImage,
  },
] as const;

export default function WorkflowTimeline() {
  return (
    <section id="workflow" className="workflow-timeline">
      <header className="workflow-timeline-head">
        <div>
          <small>Workflow · 02</small>
          <h2>
            How Poster <span>Works</span>
          </h2>
        </div>
        <p>
          真实素材先于 AI 想象。
          <br />
          Poster 不是一个 prompt 工具，而是一个理解素材的视觉工作流。
        </p>
      </header>

      <ol className="workflow-timeline-track">
        {STEPS.map((s, i) => {
          const Icon = s.icon;
          return (
            <motion.li
              key={s.id}
              className="workflow-step"
              initial={{ opacity: 0, y: 36 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-80px' }}
              transition={{ duration: 0.7, delay: i * 0.14, ease: [0.2, 0.7, 0.2, 1] }}
            >
              <div className="workflow-step-rail" aria-hidden="true">
                <span className="workflow-step-rail-dot" />
                {i < STEPS.length - 1 && <span className="workflow-step-rail-line" />}
              </div>
              <div className="workflow-step-body">
                <div className="workflow-step-head">
                  <span className="workflow-step-id">{s.id}</span>
                  <span className="workflow-step-icon">
                    <Icon size={14} />
                  </span>
                </div>
                <div className="workflow-step-text">
                  <b className="workflow-step-en">{s.code}</b>
                  <span className="workflow-step-zh">{s.zh}</span>
                </div>
                <p className="workflow-step-desc">{s.desc}</p>
                <i className="workflow-step-en-tag">— {s.en}</i>
              </div>
            </motion.li>
          );
        })}
      </ol>
    </section>
  );
}
