import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  ChevronRight,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import Brand from "../components/Brand";
import AssetUpload from "../components/AssetUpload";
import ProjectAssistant from "../components/ProjectAssistant";
import PosterLanguageToggle from "../components/PosterLanguageToggle";
import SiteLanguageToggle from "../components/SiteLanguageToggle";
import { demoProject, emptyProject, styles } from "../data/mock";
import { useStore } from "../store";
import type { Participant, PosterProject, SceneType } from "../types";
import {useSiteLanguage} from "../hooks/useSiteLanguage";
const scenes: [SceneType, string, string, string, string][] = [
  ["concert", "音乐演出", "乐队、Livehouse 与巡演", "Live Performance", "Bands, livehouses and tours"],
  ["festival", "音乐节", "多艺人、多舞台阵容", "Music Festival", "Multi-artist and multi-stage lineups"],
  ["lecture", "讲座", "主讲人、主题与机构", "Talk", "Speaker, topic and organizer"],
  ["competition", "比赛", "赛事、奖项与报名", "Competition", "Event, awards and registration"],
  ["commercial", "商业活动", "品牌、产品与转化", "Commercial Event", "Brand, product and conversion"],
  ["custom", "自定义", "保留核心四要素", "Custom", "Keep the four core facts"],
];
const styleEnglish: Record<string, {tagline: string; composition: string}> = {
  rock: {tagline: 'Dark · warm orange · grain · live energy', composition: 'Dual-subject tension · rough display type · stage backlight'},
  cyber: {tagline: 'Purple · cyan · digital noise · future live', composition: 'Central perspective · signal glitches · hard rim light'},
  editorial: {tagline: 'Restrained · modern · editorial', composition: 'Asymmetric grid · generous space · clear hierarchy'},
};
const Field = ({
  label,
  value,
  onChange,
  required = false,
  type = "text",
  error,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  type?: string;
  error?: string;
}) => (
  <label className="field">
    <span>
      {label}
      {required && <b> *</b>}
    </span>
    {type === "textarea" ? (
      <textarea value={value} onChange={(e) => onChange(e.target.value)} />
    ) : (
      <input
        data-error={!!error}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    )}{" "}
    {error && <small className="field-error">{error}</small>}
  </label>
);
export default function Create() {
  const {english} = useSiteLanguage();
  const t = (zh: string, en: string) => english ? en : zh;
  const [params] = useSearchParams();
  const { save, projects } = useStore();
  const [project, setProject] = useState<PosterProject>(() => {
    const projectId = params.get("project");
    if (projectId && projects[projectId]) return projects[projectId];
    return params.get("demo") ? demoProject() : emptyProject();
  });
  const [step, setStep] = useState(params.get("demo") || params.get("project") ? 1 : 0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const nav = useNavigate();
  const mainRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    save(project);
    if (params.get("project") !== project.id) {
      nav(`/create?project=${encodeURIComponent(project.id)}`, { replace: true });
    }
  }, [nav, params, project, save]);
  const set = <K extends keyof PosterProject>(
    key: K,
    value: PosterProject[K],
  ) => setProject((p) => ({ ...p, [key]: value }));
  const completion = useMemo(
    () =>
      Math.round(
        ([
          project.scene,
          project.title,
          project.theme,
          project.dateTime,
          project.venue,
          project.subject,
          project.styleId,
        ].filter(Boolean).length /
          7) *
          100,
      ),
    [project],
  );
  const validate = () => {
    const next: Record<string, string> = {};
    if (!project.scene) next.scene = t("请选择一个海报场景", "Choose a poster scenario");
    if (!project.title.trim()) next.title = t("请填写活动名称", "Enter the event title");
    if (!project.theme.trim()) next.theme = t("请填写活动主题", "Enter the event theme");
    if (!project.dateTime.trim()) next.dateTime = t("请填写日期和时间", "Enter the date and time");
    if (!project.venue.trim()) next.venue = t("请填写场地名称", "Enter the venue");
    if (!project.subject.trim()) next.subject = t("请填写活动主体", "Enter the event subject");
    if (project.scene === "concert" && !project.bands.length)
      next.bands = t("至少添加一支乐队", "Add at least one band");
    setErrors(next);
    if (Object.keys(next).length) {
      setStep(next.scene ? 0 : 1);
      setTimeout(
        () =>
          mainRef.current
            ?.querySelector('[data-error="true"],.error-anchor')
            ?.scrollIntoView({ behavior: "smooth", block: "center" }),
        30,
      );
      return false;
    }
    return true;
  };
  const generate = () => {
    if (!validate()) return;
    save(project);
    nav(`/generate/${project.id}`);
  };
  const addBand = () =>
    set("bands", [
      ...project.bands,
      { id: crypto.randomUUID(), name: "", genre: "" },
    ]);
  const updateBand = (id: string, patch: Partial<Participant>) =>
    set(
      "bands",
      project.bands.map((b) => (b.id === id ? { ...b, ...patch } : b)),
    );
  const removeBand = (id: string) =>
    set(
      "bands",
      project.bands.filter((b) => b.id !== id),
    );
  const recommend = () => {
    const text = (project.theme + " " + project.title).toLowerCase();
    const id =
      text.includes("科技") || text.includes("未来")
        ? "cyber"
        : project.scene === "lecture"
          ? "editorial"
          : "rock";
    set("styleId", id);
    setNotice(
      t(`Mock 建议：${styles.find((s) => s.id === id)?.name}，请确认后再生成。`, `Mock suggestion: ${styles.find((s) => s.id === id)?.name}. Confirm it before generation.`),
    );
  };
  return (
    <main className="workspace">
      <header className="workspace-top">
        <Brand />
        <span>NEW PROJECT / {project.id.slice(0, 8).toUpperCase()}</span>
        <div className="workspace-top-actions">
          <SiteLanguageToggle />
          <button className="ghost-button" onClick={() => nav("/")}>
            <ArrowLeft size={15} /> {english ? 'Home' : '返回首页'}
          </button>
        </div>
      </header>
      <div className="workspace-grid">
        <aside className="steps">
          <p className="eyebrow">CREATE FLOW</p>
          {(english ? ["Scenario", "Information & assets", "Visual direction", "Output"] : ["选择场景", "信息与素材", "视觉风格", "输出确认"]).map((x, i) => (
            <button
              key={x}
              className={i === step ? "active" : i < step ? "done" : ""}
              onClick={() => setStep(i)}
            >
              <b>{i < step ? <Check size={15} /> : i + 1}</b>
              <span>
                {x}
                <small>
                  {i === step ? t("当前步骤", "Current") : i < step ? t("已完成", "Complete") : t("等待中", "Waiting")}
                </small>
              </span>
              <ChevronRight />
            </button>
          ))}
          <div className="completion">
            <span>
              {t("项目完成度", "Project completion")} <b>{completion}%</b>
            </span>
            <i>
              <em style={{ width: `${completion}%` }} />
            </i>
          </div>
          <button
            className="ai-entry"
            onClick={() =>
              document
                .querySelector<HTMLTextAreaElement>("#project-assistant textarea")
                ?.focus()
            }
          >
            <Bot /> {t("AI 项目助理", "AI Project Assistant")}<small>{t("对话提取 · 确认后写入", "Extract in chat · write only after confirmation")}</small>
          </button>
        </aside>
        <section className="form-panel" ref={mainRef}>
          {notice && (
            <div className="notice">
              <Sparkles />
              {notice}
              <button onClick={() => setNotice("")}>×</button>
            </div>
          )}
          {step === 0 && (
            <div className="form-section">
              <p className="eyebrow">STEP 01 / SCENARIO</p>
              <h1>{t("这次要做什么海报？", "What are we creating?")}</h1>
              <p>{t("场景决定接下来出现的字段；核心信息始终由你确认。", "The scenario controls the next fields. You always confirm the core facts.")}</p>
              {errors.scene && (
                <p className="field-error error-anchor">{errors.scene}</p>
              )}
              <div className="scene-grid">
                {scenes.map(([id, nameZh, descZh, nameEn, descEn], i) => (
                  <button
                    key={id}
                    onClick={() => set("scene", id)}
                    className={project.scene === id ? "selected" : ""}
                  >
                    <small>0{i + 1}</small>
                    <b>{english ? nameEn : nameZh}</b>
                    <span>{english ? descEn : descZh}</span>
                    {project.scene === id && <Check />}
                  </button>
                ))}
              </div>
            </div>
          )}
          {step === 1 && (
            <div className="form-section">
              <p className="eyebrow">STEP 02 / INFORMATION & ASSETS</p>
              <h1>{t("准确的信息，独立的素材", "Accurate facts, independent assets")}</h1>
              <p>{t("人物、场地、Logo 与二维码承担不同职责，不会混在同一上传框。", "People, venues, logos and QR codes keep separate roles and upload slots.")}</p>
              <h2>{t("核心信息", "Core information")}</h2>
              <div className="fields two">
                <Field
                  label={t("活动名称", "Event title")}
                  value={project.title}
                  onChange={(v) => set("title", v)}
                  required
                  error={errors.title}
                />
                <Field
                  label={t("活动主体", "Subject / artist")}
                  value={project.subject}
                  onChange={(v) => set("subject", v)}
                  required
                  error={errors.subject}
                />
                <Field
                  label={t("活动主题", "Theme")}
                  value={project.theme}
                  onChange={(v) => set("theme", v)}
                  required
                  error={errors.theme}
                />
                <Field
                  label={t("日期和时间", "Date and time")}
                  value={project.dateTime}
                  onChange={(v) => set("dateTime", v)}
                  required
                  error={errors.dateTime}
                />
                <Field
                  label={t("城市", "City")}
                  value={project.city}
                  onChange={(v) => set("city", v)}
                />
                <Field
                  label={t("场地名称", "Venue")}
                  value={project.venue}
                  onChange={(v) => set("venue", v)}
                  required
                  error={errors.venue}
                />
              </div>
              <h2>{t("英文主视觉文案", "English poster copy")} <small className="optional-copy">{t("可选 · 留空时沿用中文原文", "Optional · falls back to Chinese when blank")}</small></h2>
              <div className="fields two bilingual-fields">
                <Field label="活动名称 / TITLE" value={project.titleEn ?? ""} onChange={(v) => set("titleEn", v)} />
                <Field label="活动主体 / SUBJECT" value={project.subjectEn ?? ""} onChange={(v) => set("subjectEn", v)} />
                <Field label="活动主题 / TAGLINE" value={project.themeEn ?? ""} onChange={(v) => set("themeEn", v)} />
                <Field label="城市 / CITY" value={project.cityEn ?? ""} onChange={(v) => set("cityEn", v)} />
                <Field label="地点 / VENUE" value={project.venueEn ?? ""} onChange={(v) => set("venueEn", v)} />
                <Field label="票务说明 / TICKET INFO" value={project.ticketInfoEn ?? ""} onChange={(v) => set("ticketInfoEn", v)} />
              </div>
              <div className="uploads two">
                <AssetUpload
                  label={t("场地照片", "Venue photo")}
                  kind="venue"
                  value={project.assets.venue}
                  onChange={(v) =>
                    set("assets", { ...project.assets, venue: v })
                  }
                />
                <AssetUpload
                  label={t("添加参考海报（可选）", "Add reference poster (optional)")}
                  kind="reference"
                  value={project.assets.reference}
                  onChange={(v) =>
                    set("assets", { ...project.assets, reference: v })
                  }
                />
              </div>
              {project.scene === "concert" && (
                <>
                  <div className="section-title">
                    <div>
                      <h2>{t("乐队列表", "Band lineup")}</h2>
                      <p>{t("每支乐队的名称、Logo 与人物素材保持绑定。", "Each band keeps its name, logo and people assets bound together.")}</p>
                    </div>
                    <button className="ghost-button" onClick={addBand}>
                      <Plus /> {t("添加乐队", "Add band")}
                    </button>
                  </div>
                  {errors.bands && (
                    <p className="field-error error-anchor">{errors.bands}</p>
                  )}
                  <div className="bands">
                    {project.bands.map((b, i) => (
                      <article key={b.id}>
                        <header>
                          <b>{t("乐队", "Band")} 0{i + 1}</b>
                          <button onClick={() => removeBand(b.id)}>
                            <Trash2 />
                          </button>
                        </header>
                        <div className="fields two">
                          <Field
                            label={t("乐队名称", "Band name")}
                            value={b.name}
                            onChange={(v) => updateBand(b.id, { name: v })}
                          />
                          <Field
                            label={t("音乐风格", "Music genre")}
                            value={b.genre}
                            onChange={(v) => updateBand(b.id, { genre: v })}
                          />
                          <Field
                            label="乐队英文名 / BAND NAME"
                            value={b.nameEn ?? ""}
                            onChange={(v) => updateBand(b.id, { nameEn: v })}
                          />
                          <Field
                            label="英文音乐风格 / GENRE"
                            value={b.genreEn ?? ""}
                            onChange={(v) => updateBand(b.id, { genreEn: v })}
                          />
                        </div>
                        <div className="uploads three">
                          <AssetUpload
                            label={t("原始 Logo", "Original logo")}
                            kind="logo"
                            value={b.logo}
                            onChange={(v) => updateBand(b.id, { logo: v })}
                          />
                          <AssetUpload
                            label={t("成员合照", "Band photo")}
                            kind="person"
                            value={b.groupPhoto}
                            onChange={(v) =>
                              updateBand(b.id, { groupPhoto: v })
                            }
                          />
                          <AssetUpload
                            label={t("关键成员照片", "Key member photo")}
                            kind="person"
                            value={b.keyPhoto}
                            onChange={(v) => updateBand(b.id, { keyPhoto: v })}
                          />
                        </div>
                      </article>
                    ))}
                  </div>
                  <h2>{t("票务信息", "Ticketing")}</h2>
                  <div className="fields two">
                    <Field
                      label={t("票价", "Ticket price")}
                      value={project.price}
                      onChange={(v) => set("price", v)}
                    />
                    <Field
                      label={t("购票说明", "Ticket instructions")}
                      value={project.ticketInfo}
                      onChange={(v) => set("ticketInfo", v)}
                    />
                  </div>
                  <AssetUpload
                    label={t("购票二维码", "Ticket QR code")}
                    kind="qr"
                    value={project.assets.qr}
                    onChange={(v) =>
                      set("assets", { ...project.assets, qr: v })
                    }
                  />
                </>
              )}
              {project.scene === "lecture" && (
                <>
                  <h2>{t("讲座信息", "Talk information")}</h2>
                  <div className="fields two">
                    <Field
                      label={t("主讲人姓名", "Speaker")}
                      value={project.speakerName}
                      onChange={(v) => set("speakerName", v)}
                    />
                    <Field
                      label={t("主办单位", "Organizer")}
                      value={project.organizer}
                      onChange={(v) => set("organizer", v)}
                    />
                    <Field
                      label={t("主讲人简介", "Speaker bio")}
                      type="textarea"
                      value={project.speakerBio}
                      onChange={(v) => set("speakerBio", v)}
                    />
                  </div>
                  {errors.speaker && (
                    <p className="field-error error-anchor">{errors.speaker}</p>
                  )}
                  <div className="uploads two">
                    <AssetUpload
                      label={t("主讲人照片", "Speaker photo")}
                      kind="person"
                      value={project.assets.speaker}
                      onChange={(v) =>
                        set("assets", { ...project.assets, speaker: v })
                      }
                    />
                    <AssetUpload
                      label={t("主办方 Logo", "Organizer logo")}
                      kind="logo"
                      value={project.assets.organizerLogo}
                      onChange={(v) =>
                        set("assets", { ...project.assets, organizerLogo: v })
                      }
                    />
                  </div>
                </>
              )}
            </div>
          )}
          {step === 2 && (
            <div className="form-section">
              <p className="eyebrow">STEP 03 / VISUAL LANGUAGE</p>
              <h1>{t("选择主视觉方向", "Choose a visual direction")}</h1>
              <p>{t("风格只改变主视觉；真实文字与 Logo 仍由独立图层合成。", "Style affects the key visual only; verified copy and logos stay on deterministic layers.")}</p>
              <p className="workflow-truth-note"><b>{t("Prompt 视觉方向", "Prompt visual direction")}</b> · {t("当前真实 GPU 生成统一使用", "Real GPU generation currently uses the")} <code>metal-gothic-v1</code> {t("工作流，预设用于构图、色彩和材质提示。", "workflow; presets guide composition, color and material prompts.")}</p>
              <button className="ai-recommend" onClick={recommend}>
                <Sparkles /> {t("AI 帮我推荐", "Recommend with AI")} <small>{t("Mock 规则", "Mock rule")}</small>
              </button>
              <div className="style-list">
                {styles.map((s) => (
                  <button
                    key={s.id}
                    className={project.styleId === s.id ? "selected" : ""}
                    onClick={() => set("styleId", s.id)}
                  >
                    <div className={`style-thumb style-${s.id}`}>
                      <i />
                      <i />
                      <span>POSTER</span>
                    </div>
                    <div>
                      <h3>{s.name}</h3>
                      <p>{english ? styleEnglish[s.id]?.tagline : s.tagline}</p>
                      <small>{english ? styleEnglish[s.id]?.composition : s.composition}</small>
                      <div className="swatches">
                        {s.colors.map((c) => (
                          <i key={c} style={{ background: c }} />
                        ))}
                      </div>
                    </div>
                    {project.styleId === s.id && <Check />}
                  </button>
                ))}
              </div>
            </div>
          )}
          {step === 3 && (
            <div className="form-section">
              <p className="eyebrow">STEP 04 / OUTPUT</p>
              <h1>{t("选择要交付的内容", "Choose the deliverables")}</h1>
              <PosterLanguageToggle
                value={project.posterLanguage ?? "en"}
                onChange={(language) => set("posterLanguage", language)}
              />
              <div className="outputs">
                <label className="selected">
                  <input type="checkbox" checked readOnly />
                  <span>
                    <b>{t("静态竖版海报", "Static portrait poster")}</b>
                    <small>P0 · 1024 × 1536 · PNG</small>
                  </span>
                  <em>{t("默认", "Default")}</em>
                </label>
                <label className={project.outputs.teaser ? "selected" : ""}>
                  <input
                    type="checkbox"
                    checked={project.outputs.teaser}
                    onChange={(e) =>
                      set("outputs", {
                        ...project.outputs,
                        teaser: e.target.checked,
                      })
                    }
                  />
                  <span>
                    <b>{t("5–8 秒宣传片", "5–8 second teaser")}</b>
                    <small>{t("P1 · 规划中 · 会增加生成时间", "P1 · Planned · increases generation time")}</small>
                  </span>
                  <em>{t("需主动选择", "Opt in")}</em>
                </label>
                <label className="disabled">
                  <input type="checkbox" disabled />
                  <span>
                    <b>{t("VJ 动态视觉", "VJ motion visual")}</b>
                    <small>{t("P2 · 后续版本", "P2 · Later release")}</small>
                  </span>
                  <em>{t("暂不可用", "Unavailable")}</em>
                </label>
              </div>
              <div className="preflight">
                <Check />
                <div>
                  <b>{t("确定性信息图层", "Deterministic information layer")}</b>
                  <p>
                    {t("标题、时间、地点、Logo、二维码将使用你的原始数据合成，不由 AI 重画。", "Title, time, venue, logo and QR code are composed from your verified data, never redrawn by AI.")}
                  </p>
                </div>
              </div>
            </div>
          )}
          <div className="form-actions">
            <button
              className="ghost-button"
              disabled={step === 0}
              onClick={() => setStep((s) => s - 1)}
            >
              <ArrowLeft /> {t("上一步", "Back")}
            </button>
            {step < 3 ? (
              <button className="button" onClick={() => setStep((s) => s + 1)}>
                {t("继续", "Continue")} <ArrowRight />
              </button>
            ) : (
              <button className="button" onClick={generate}>
                {t("提交 W7900 真实生成", "Submit real W7900 generation")} <Sparkles />
              </button>
            )}
          </div>
        </section>
        <ProjectAssistant
          project={project}
          onApply={(draft) => {
            setProject((current) => ({ ...current, ...draft }));
            setNotice(t("AI 候选信息已按你的确认写入表单；请继续检查并补充素材。", "Confirmed AI suggestions were written to the form. Review them and add optional assets."));
            setStep(1);
          }}
        />
      </div>
    </main>
  );
}
