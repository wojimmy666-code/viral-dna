import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ArrowUpRight, Check, Eye, List, LockSimple, Pause, Play, X } from "@phosphor-icons/react";
import { loginHref } from "../accounts/login-destination.js";
import "./home.css";

const IMAGE_SOURCES = {
  "hero-scene": { png: "/home/hero-scene.png", webp: "/home/hero-scene.webp" },
  "thumb-close": { png: "/home/thumb-close.png", webp: "/home/thumb-close.webp" },
  "thumb-scene": { png: "/home/thumb-scene.png", webp: "/home/thumb-scene.webp" },
  "thumb-motion": { png: "/home/thumb-motion.png", webp: "/home/thumb-motion.webp" },
};

export function SceneImage({ name, className = "", alt = "", eager = false }) {
  const [failure, setFailure] = useState(0);
  useEffect(() => setFailure(0), [name]);
  const source = IMAGE_SOURCES[name];
  return <picture className={className}>{failure >= 2 ? <span className="vd-image-unavailable" role="img" aria-label={alt || "展示图片暂时不可用"}>画面暂时不可用</span> : <>{failure === 0 && <source type="image/webp" srcSet={source.webp} />}<img src={source.png} alt={alt} width="1672" height="941" loading={eager ? "eager" : "lazy"} fetchPriority={eager && name === "hero-scene" ? "high" : "auto"} onError={() => setFailure(current => current + 1)} /></>}</picture>;
}

const SAMPLES = [
  { label: "产品特写", image: "hero-scene", thumbnail: "thumb-close", alt: "暖金侧光下，琥珀色玻璃瓶立于黑色岩石上", detail: "用材质、光线与细节，建立产品的第一印象。" },
  { label: "场景演绎", image: "thumb-scene", thumbnail: "thumb-scene", alt: "岩石峡谷中的琥珀色玻璃瓶，远处透入暖色光线", detail: "把产品放进有情绪的场景，让画面有了故事。" },
  { label: "运镜节奏", image: "thumb-motion", thumbnail: "thumb-motion", alt: "银色金属瓶盖与琥珀色瓶身的倾斜近景", detail: "通过景别变化与镜头衔接，组织成片的节奏。" },
];
const NAVIGATION = [["作品案例", "showcase"], ["创作流程", "workflow"], ["Skill", "skills"], ["团队协作", "team"]];
// Explicit public presentation list. Never populated from an account's assets,
// projects, provider credentials, or the authenticated Skill catalog.
const WORKFLOW = [
  { title: "确定创作方向", copy: "从参考视频里找到结构，或用 Skill 把想法整理成创作方案。", image: "thumb-scene", note: "创作方向", statement: "让产品从暗处出现，用光线讲述质感。" },
  { title: "把故事拆成分镜", copy: "先看清每一镜要表达什么，再安排景别、构图和画面衔接。", image: "thumb-close", note: "分镜规划", statement: "产品特写 → 环境展开 → 材质近景" },
  { title: "生成与采用画面", copy: "逐张调整画面要求，保留候选历史，采用你认可的那一张。", image: "thumb-close", note: "画面选择", statement: "选定画面，保留创作判断。" },
  { title: "让分镜动起来", copy: "沿用分镜图与提示词生成视频，再选择进入剪辑的片段。", image: "thumb-motion", note: "分镜视频", statement: "从光线切入，在细节处停留。" },
  { title: "剪辑与导出", copy: "调整片段顺序、节奏和声音，把已采用的片段组织成完整作品。", image: "thumb-scene", note: "剪辑输出", statement: "每一个片段，服务于同一个故事。" },
];

function CreationWorkflow() {
  const [step, setStep] = useState(0);
  const current = WORKFLOW[step];
  function moveTab(event, index) {
    const next = event.key === "ArrowDown" || event.key === "ArrowRight" ? (index + 1) % WORKFLOW.length
      : event.key === "ArrowUp" || event.key === "ArrowLeft" ? (index + WORKFLOW.length - 1) % WORKFLOW.length
        : event.key === "Home" ? 0 : event.key === "End" ? WORKFLOW.length - 1 : null;
    if (next === null) return;
    event.preventDefault(); setStep(next); document.getElementById(`vd-step-${next}`)?.focus();
  }
  return <section className="vd-workflow vd-section" id="workflow" aria-labelledby="vd-workflow-title">
    <div className="vd-section-heading"><h2 id="vd-workflow-title">一段影像，<br />每一步都由你决定。</h2><p>从想法到成片，不是一次碰运气。<br />把创作拆开，让选择留在你手里。</p></div>
    <div className="vd-workflow-layout">
      <div className="vd-workflow-tabs" role="tablist" aria-label="创作流程" aria-orientation="vertical">{WORKFLOW.map((item, index) => <button type="button" role="tab" id={`vd-step-${index}`} aria-controls="vd-workflow-panel" aria-selected={step === index} tabIndex={step === index ? 0 : -1} key={item.title} onKeyDown={event => moveTab(event, index)} onClick={() => setStep(index)}><span className="vd-step-number">{index + 1}</span><span>{item.title}</span><ArrowRight size={20} /></button>)}</div>
      <div className="vd-workflow-panel" role="tabpanel" id="vd-workflow-panel" aria-labelledby={`vd-step-${step}`} tabIndex={0}>
        <div className="vd-workflow-stage"><SceneImage name={current.image} alt={SAMPLES.find(item => item.thumbnail === current.image)?.alt || SAMPLES[0].alt} /><span className="vd-example-label">创作示意</span><div className="vd-shot-strip" aria-hidden="true">{SAMPLES.map(item => <SceneImage name={item.thumbnail} key={item.label} />)}</div></div>
        <div className="vd-workflow-description"><h3>{current.statement}</h3><p>{current.copy}</p><p className="vd-caption">示例画面与流程说明，不是实际项目数据。</p></div>
      </div>
    </div>
  </section>;
}

function SkillShowcase() {
  return <section className="vd-skills vd-section" id="skills" aria-labelledby="vd-skills-title">
    <div className="vd-section-heading"><h2 id="vd-skills-title">将创作方法，<br />变为可复用的 Skill。</h2><div><p>让创作从一套方法开始。<br />具体可用的 Skill，以登录后的列表为准。</p><Link className="vd-text-link" to={loginHref("/skills")}>进入 Skill 库<ArrowUpRight size={21} /></Link></div></div>
    <div className="vd-methods">{[
      { title: "产品叙事", image: "thumb-close", copy: "用镜头建立质感，让产品成为故事主角。" },
      { title: "场景演绎", image: "thumb-scene", copy: "从场景与情绪出发，寻找合适的表达。" },
      { title: "细节表达", image: "thumb-motion", copy: "围绕材质、光线和景别，形成视觉节奏。" },
    ].map(method => <article key={method.title}><Link className="vd-method-link" to={loginHref("/skills")} aria-label={`探索${method.title}创作方法`}><div className="vd-method-image"><SceneImage name={method.image} alt="" /><span>创作方向示意</span><ArrowUpRight size={24} /></div><h3>{method.title}</h3><p>{method.copy}</p></Link></article>)}</div>
  </section>;
}

function TeamSection() {
  return <section className="vd-team vd-section" id="team" aria-labelledby="vd-team-title">
    <div className="vd-team-copy"><h2 id="vd-team-title">让团队在同一个<br className="vd-mobile-break" />项目里，<br className="vd-team-desktop-break" />向前创作。</h2><p>企业成员分别登录，共享资产与项目。<br />一次只交给一位编辑者，让每次修改都有序发生。</p><ul><li><Check size={20} />企业成员共用资产与项目</li><li><Check size={20} />同一项目，一位编辑者</li><li><Check size={20} />其他成员可只读查看</li></ul><Link className="vd-text-link" to={loginHref()}>进入团队创作台<ArrowUpRight size={21} /></Link><p className="vd-caption">个人与企业使用独立账户；账户开通请联系管理员。</p></div>
    <div className="vd-team-example" aria-label="企业项目协作示意，非实际账户数据"><div className="vd-team-example-title"><span>产品故事 · 团队项目</span><span className="vd-caption">协作示意</span></div><div className="vd-team-project"><SceneImage name="thumb-close" alt="团队项目的产品画面示意" /><div><p>共享项目</p><h3>一支关于质感的短片</h3><span className="vd-caption">分镜、素材与创作记录，留在同一个项目。</span></div></div><div className="vd-collaborator"><span>成员 A</span><span><LockSimple size={17} />正在编辑</span></div><div className="vd-collaborator"><span>成员 B</span><span><Eye size={17} />只读查看</span></div><div className="vd-team-example-footer">示意状态 · 不读取真实成员或编辑锁</div></div>
  </section>;
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}

function DemoDialog({ onClose, initialScene }) {
  const dialog = useRef(null);
  const [scene, setScene] = useState(initialScene);
  useEffect(() => {
    const previousFocus = document.activeElement;
    const element = dialog.current;
    element.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { element.close(); document.body.style.overflow = previousOverflow; previousFocus?.focus(); };
  }, []);
  return <dialog ref={dialog} className="vd-demo" aria-labelledby="vd-demo-title" onCancel={event => { event.preventDefault(); onClose(); }} onClose={() => { if (!dialog.current?.open) onClose(); }} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); onClose(); } }} onClick={event => { if (event.target === dialog.current) onClose(); }}>
    <div className="vd-demo-heading"><h2 id="vd-demo-title">从一个产品，到一段故事</h2><button type="button" className="vd-icon-button" aria-label="关闭演示" onClick={onClose}><X size={24} /></button></div>
    <SceneImage name={SAMPLES[scene].thumbnail} alt={SAMPLES[scene].alt} className="vd-demo-image" eager />
    <div className="vd-demo-body"><p className="vd-caption">视觉示意 · 非真实案例 · 静态分镜演示</p><h3>{SAMPLES[scene].label}</h3><p>{SAMPLES[scene].detail}</p>
      <div className="vd-demo-steps" aria-label="选择演示分镜">{SAMPLES.map((item, index) => <button type="button" key={item.label} aria-pressed={scene === index} onClick={() => setScene(index)}>{item.label}</button>)}</div>
      <p className="vd-demo-explanation">在创作台中，你可以逐张生成和采用分镜图，再制作分镜视频，调整顺序并剪辑导出。这里展示的是画面组织方式，不会调用生成模型。</p>
      <Link className="vd-button vd-primary" to={loginHref("/projects/new")}>开始自己的创作<ArrowRight size={20} /></Link>
    </div>
  </dialog>;
}

export default function HomePage() {
  const reduced = useReducedMotion();
  const [sample, setSample] = useState(0);
  const [playing, setPlaying] = useState(() => !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [active, setActive] = useState(true);
  const [visible, setVisible] = useState(!document.hidden);
  const [interacting, setInteracting] = useState(false);
  const [menu, setMenu] = useState(false);
  const [demo, setDemo] = useState(false);
  const hero = useRef(null), menuButton = useRef(null);
  const rotating = playing && !reduced && active && visible && !interacting && !menu && !demo;
  useEffect(() => {
    document.title = "ViralDNA · 看懂好视频，把创意做成片";
    const observer = new IntersectionObserver(entries => setActive(entries[0].isIntersecting), { threshold: 0.15 });
    observer.observe(hero.current);
    const visibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", visibility);
    return () => { observer.disconnect(); document.removeEventListener("visibilitychange", visibility); };
  }, []);
  useEffect(() => {
    if (!rotating) return;
    const timer = setInterval(() => setSample(current => (current + 1) % SAMPLES.length), 7000);
    return () => clearInterval(timer);
  }, [rotating, sample]);
  useEffect(() => {
    if (!menu) return;
    const escape = event => { if (event.key === "Escape") { setMenu(false); menuButton.current?.focus(); } };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [menu]);
  return <div className="vd-home">
    <a className="vd-skip" href="#home-content">跳至主要内容</a>
    <header className="vd-navigation">
      <Link className="vd-brand" to="/" aria-label="ViralDNA 首页"><img src="/favicon.svg" alt="" width="40" height="40" /><span>ViralDNA</span></Link>
      <nav className={menu ? "vd-nav-links is-open" : "vd-nav-links"} aria-label="官网导航" id="vd-main-navigation">{NAVIGATION.map(([label, id]) => <a href={`#${id}`} key={id} onClick={() => setMenu(false)}>{label}</a>)}</nav>
      <Link className="vd-button vd-primary vd-nav-cta" to={loginHref()}>进入创作台</Link>
      <button ref={menuButton} className="vd-icon-button vd-menu-toggle" type="button" aria-label={menu ? "关闭导航" : "打开导航"} aria-controls="vd-main-navigation" aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? <X size={24} /> : <List size={24} />}</button>
    </header>
    <main id="home-content">
      <section ref={hero} className={`vd-hero${rotating ? " is-playing" : ""}${sample ? " is-alternate" : ""}`} id="showcase" aria-label="作品视觉示意">
        <SceneImage key={sample} name={SAMPLES[sample].image} alt={SAMPLES[sample].alt} className="vd-hero-image" eager />
        <div className="vd-hero-copy"><h1>看懂好视频，<br />把创意做成片。</h1><p>从原视频分析或 Skill 出发，连接分镜、图像、视频与剪辑，<br className="vd-desktop-break" />让每一步创作都清晰可控。</p>
          <div className="vd-hero-actions"><Link className="vd-button vd-primary" to={loginHref()}>进入创作台<ArrowRight size={25} /></Link><button className="vd-button vd-secondary" type="button" onClick={() => setDemo(true)}><Play size={24} weight="fill" />观看演示</button></div>
        </div>
        <div className="vd-sample-dock" onMouseEnter={() => setInteracting(true)} onMouseLeave={() => setInteracting(false)} onFocus={() => setInteracting(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setInteracting(false); }}>
          <p className="vd-sample-note">视觉示意 · 非真实案例</p>
          <div className="vd-sample-controls"><div className="vd-samples" aria-label="切换示意画面">{SAMPLES.map((item, index) => <button type="button" key={item.label} className="vd-sample" aria-label={`查看${item.label}`} aria-pressed={sample === index} onClick={() => { setSample(index); setPlaying(false); }}><SceneImage name={item.thumbnail} alt="" eager /><span>{item.label}</span></button>)}</div>
            <button className="vd-icon-button vd-play-toggle" type="button" aria-label={playing && !reduced ? "暂停画面轮播" : "播放画面轮播"} disabled={reduced} title={reduced ? "已遵循系统减少动态效果设置，可手动切换画面" : undefined} onClick={() => setPlaying(!playing)}>{playing && !reduced ? <Pause size={24} weight="fill" /> : <Play size={24} weight="fill" />}</button>
          </div>
        </div>
      </section>
      <section className="vd-paths" aria-label="两种创作方式">
        <article><h2>有参考，就从分析开始。</h2><p>理解视频，拆解亮点，找到可复用的创意方法。</p><Link className="vd-text-link" to={loginHref("/projects/new")}>分析一条视频<ArrowUpRight size={21} /></Link></article>
        <article><h2>有想法，就从 Skill 开始。</h2><p>用自然语言描述你的想法，让创意有迹可循。</p><Link className="vd-text-link" to={loginHref("/skills")}>探索创作 Skill<ArrowUpRight size={21} /></Link></article>
      </section>
      <CreationWorkflow />
      <SkillShowcase />
      <TeamSection />
      <section className="vd-closing vd-section"><h2>灵感，不必停留在脑海。</h2><p>从一条参考视频，或一个想法开始。</p><Link className="vd-button vd-primary" to={loginHref()}>进入创作台<ArrowRight size={24} /></Link></section>
    </main>
    <footer className="vd-footer"><Link className="vd-brand" to="/" aria-label="返回 ViralDNA 首页"><img src="/favicon.svg" alt="" width="32" height="32" /><span>ViralDNA</span></Link><p>看懂好视频，把创意做成片。</p><a href="#workflow">创作流程</a><Link to={loginHref()}>账户登录</Link><small>本页影像为 AI 视觉示意，非真实客户案例。</small></footer>
    {demo && <DemoDialog initialScene={sample} onClose={() => setDemo(false)} />}
  </div>;
}
