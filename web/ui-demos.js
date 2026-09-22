const directions = {
  atelier: {
    index: "01", name: "LINEN ATELIER", title: "一个更像编辑器的 AI 工作台。",
    copy: "让 AI 生成和人工审核成为两个清晰的动作，用米白纸张、珊瑚橙、柠檬黄和叶绿色建立轻快的工作节奏。",
    tags: ["AI FIRST", "REVIEWABLE", "LOCAL"],
    content: `
      <aside class="demo-rail">
        <div class="rail-heading"><span>WORKSPACE</span><span>⌘ 1</span></div>
        <button class="rail-item is-active"><span>01</span>需求分析</button><button class="rail-item"><span>02</span>文档框架</button><button class="rail-item"><span>03</span>Topic XML</button><button class="rail-item"><span>04</span>Skill 配置</button>
        <div class="rail-project"><small>ACTIVE PROJECT</small><b>CODESYS 运动控制<br />手册 / V1.0.0</b></div>
      </aside>
      <section class="atelier-center"><div class="center-head"><div><span class="demo-kicker">FRAMEWORK / LIVE MAP</span><h2>从材料到结构。</h2></div><p>已识别 126 个节点<br />最后保存：刚刚</p></div><div class="atelier-map"><div class="map-spine"></div><div class="map-node"><div><b>前言</b><small>背景、读者与适用范围</small></div></div><div class="map-node"><div><b>1. 快速入门</b><small>完成首次轴运动验证</small></div></div><div class="map-node"><div><b>2. 运动控制概念</b><small>系统架构与执行机制</small></div></div><div class="map-node"><div><b>3. 配置运动控制系统</b><small>网络、轴与限位配置</small></div></div><div class="map-node is-core"><div><b>文档框架</b><small>126 TOPICS</small></div></div></div></section>
      <aside class="atelier-inspector"><div class="inspector-block"><span class="tiny-label">AI OUTPUT</span><h3>框架生成状态</h3><div class="metric-row"><span>材料证据</span><strong>3 份</strong></div><div class="metric-row"><span>HIK Writing</span><strong>必选</strong></div><div class="metric-row"><span>未确认问题</span><strong>08</strong></div><div class="progress-track"><i></i></div></div><div class="inspector-block"><span class="tiny-label">REVIEW QUEUE</span><h3>审核清单</h3><div class="check-list"><span>标题层级已规范</span><span>Task / Concept 已标记</span><span>待补充图片占位符</span></div></div><div><span class="tiny-label">VERSION</span><div class="metric-row"><span>当前版本</span><strong>V1.2</strong></div></div></aside>`,
  },
  signal: {
    index: "02", name: "PAPER SIGNAL", title: "像一张精确、安静的技术图纸。",
    copy: "把 Markdown 和结构图放在同一个平面，降低装饰，让标题层级、编辑状态和证据来源成为视觉主角。",
    tags: ["CLEAR HIERARCHY", "LIVE EDIT", "EVIDENCE"],
    content: `<section class="signal-editor"><div class="signal-editor-head"><div><span class="demo-kicker">MARKDOWN / SOURCE</span><h2>文档框架</h2></div><span class="save-badge">● 已保存</span></div><div class="markdown-sheet"><h3># CODESYS 运动控制手册</h3><p>&gt; 本手册面向使用 CODESYS 对 VCP 进行 EtherCAT 运动控制的技术人员。<span class="sheet-cursor"></span></p><ul><li>## 前言</li><li>### 手册用途与适用对象</li><li>### 适用产品、软件与版本</li><li>## 1. 快速入门 [task]</li><li>### 运动控制工程准备</li><li>### 完成第一次轴运动</li></ul></div><div class="signal-toolbar"><span class="tiny-label">353 LINES / 126 NODES</span><button class="ghost-action">导出 Markdown</button></div></section><section class="signal-map"><div class="map-card-head"><strong>结构预览</strong><span>脑图 · 44%</span></div><div class="signal-map-canvas"><div class="signal-side left">缺料<br />08 items</div><div class="signal-side right">待确认<br />04 items</div><div class="signal-node"><div><b>前言</b><small>3 个章节</small></div></div><div class="signal-node is-focus"><div><b>文档框架</b><small>实时同步</small></div></div><div class="signal-node"><div><b>1. 快速入门</b><small>12 个 Topics</small></div></div><div class="signal-node"><div><b>2. 运动控制概念</b><small>18 个 Topics</small></div></div></div><div class="signal-actions"><button class="ghost-action">鱼骨图</button><button class="solid-action">适应画布</button></div></section>`,
  },
  archive: {
    index: "03", name: "SOLAR ARCHIVE", title: "让每一次生成，都留下可追溯的路径。",
    copy: "用暖色、纸张和档案标签表达版本与证据，适合强调本地资产、历史回溯和从需求到 XML 的完整链路。",
    tags: ["TRACEABLE", "VERSIONED", "HUMAN IN LOOP"],
    content: `<div class="archive-banner"><div><span class="demo-kicker">PROJECT / CODESYS MOTION CONTROL</span><h2>一条从需求材料通往可交付 XML 的路径。</h2></div><p>项目封面、需求材料、生成版本和审核结论，都在一个连续工作区里留下记录。</p></div><div class="archive-flow"><article class="archive-card"><span class="archive-card-index">01 / INPUT</span><h3>需求材料</h3><p>Word、PDF、Markdown 和历史 XML 集中进入本地项目。</p><div class="archive-card-footer"><span>03 MATERIALS</span><span>已导入</span></div></article><article class="archive-card"><span class="archive-card-index">02 / THINK</span><h3>需求分析</h3><p>AI 标记确认信息、缺料清单和待研发确认问题。</p><div class="archive-card-footer"><span>HIK WRITING</span><span>已完成</span></div></article><article class="archive-card is-current"><span class="archive-card-index">03 / SHAPE</span><h3>文档框架</h3><p>Markdown 与脑图同步编辑，结构关系清晰可见。</p><div class="archive-card-footer"><span>126 TOPICS</span><span>编辑中</span></div></article><article class="archive-card"><span class="archive-card-index">04 / CRAFT</span><h3>Topic XML</h3><p>逐 Topic 生成、人工润色、校验并导出交付。</p><div class="archive-card-footer"><span>TODO_IMAGE</span><span>待开始</span></div></article></div><div class="archive-lower"><section class="archive-lower-panel"><span class="demo-kicker">EVIDENCE LEDGER</span><h3>本次框架的依据</h3><div class="evidence-row"><i></i><span>需求材料 / 3 份 · 已提取</span></div><div class="evidence-row"><i></i><span>HIK Writing Skill · 必选</span></div><div class="evidence-row"><i></i><span>研发确认问题 / 4 条待处理</span></div></section><section class="archive-lower-panel"><span class="demo-kicker">LOCAL VERSION</span><h3>历史版本</h3><div class="version-mark"><strong>V1.2</strong><span>2026—09—14<br />本地保存</span></div></section></div>`,
  },
  meridian: {
    index: "04", name: "MERIDIAN EDITORIAL", title: "把复杂的需求，炼成清晰的结构。",
    copy: "以品牌编辑页的秩序感承载需求分析、框架生成与 Topic XML：大留白让内容呼吸，单一强调色提示下一步动作。",
    tags: ["EDITORIAL UI", "LOW NOISE", "LOCAL AI"],
    content: `<section class="meridian-hero"><div class="meridian-outline" aria-hidden="true">DOCUMENT<br />SYSTEM</div><div class="meridian-orb" aria-hidden="true"></div><div class="meridian-hero-grid"><div class="meridian-hero-copy"><span class="demo-kicker">ALCHEMY FURNACE / PROJECT 04</span><h2>从材料开始，<br /><em>让结构自然出现。</em></h2><p>需求分析、Markdown 框架与 Topic XML，在同一个连续工作区里被看见、被审核，也被保存。</p><div class="meridian-hero-actions"><button class="solid-action" data-demo-action="generate">生成下一步</button><button class="ghost-action" data-demo-action="save">保存项目</button></div></div><div class="meridian-status"><span class="tiny-label">CURRENT PROJECT</span><strong>CODESYS<br />运动控制手册</strong><div class="meridian-status-rule"></div><span class="tiny-label">ANALYSIS STATUS</span><b>结构已生成 / 82%</b><div class="meridian-status-meter"><i></i></div><small>最后保存 · 刚刚</small></div></div></section><div class="meridian-strip"><span>需求分析</span><i></i><span class="is-current">文档框架</span><i></i><span>Topic XML</span><i></i><span>审核交付</span><b>V1.2 / LOCAL</b></div><section class="meridian-workbench"><article class="meridian-panel meridian-materials"><div class="meridian-panel-head"><div><span class="tiny-label">01 / EVIDENCE</span><h3>材料与依据</h3></div><span>03 SOURCES</span></div><p>AI 将原始材料转成可追溯的章节证据，工程师只需要确认哪些内容可以进入文档。</p><div class="meridian-source"><span class="source-mark">DOC</span><div><b>产品需求说明.docx</b><small>已提取 · 36 个证据点</small></div><em>✓</em></div><div class="meridian-source"><span class="source-mark source-pdf">PDF</span><div><b>运动控制功能清单.pdf</b><small>已提取 · 18 个证据点</small></div><em>✓</em></div><div class="meridian-source"><span class="source-mark source-md">MD</span><div><b>历史版本框架.md</b><small>作为参考语料 · 已关联</small></div><em>↗</em></div><button class="meridian-text-action" data-demo-action="menu">查看全部材料 ↗</button></article><article class="meridian-panel meridian-structure"><div class="meridian-panel-head"><div><span class="tiny-label">02 / SHAPE</span><h3>文档框架</h3></div><span>126 TOPICS</span></div><div class="meridian-structure-intro"><strong>结构正在成形。</strong><span>Markdown 与脑图同步编辑</span></div><div class="meridian-structure-map"><div class="structure-line line-a"></div><div class="structure-line line-b"></div><div class="structure-line line-c"></div><div class="structure-node structure-root">文档框架<small>126 topics</small></div><div class="structure-node structure-a">前言<small>3 topics</small></div><div class="structure-node structure-b">快速入门<small>12 topics</small></div><div class="structure-node structure-c">运动控制概念<small>18 topics</small></div></div><button class="meridian-outline-button" data-demo-action="generate">打开框架编辑器 <span>→</span></button></article></section><section class="meridian-bottom"><div><span class="tiny-label">NEXT ACTION</span><strong>确认章节概述，然后开始生成 Topic XML。</strong></div><div class="meridian-next-meta"><span>HIK WRITING</span><span>HIK DITA RULE</span><span>TODO_IMAGE</span></div></section>`,
  },
};

const stage = document.querySelector("#demo-stage");
const content = document.querySelector("#demo-content");
const toast = document.querySelector("#demo-toast");
const gallery = document.querySelector("#demo-gallery");
let activeStyle = "meridian";
let activeFont = "kaiti";
let activePalette = "apricot";
let toastTimer;

function galleryPreview(style) {
  if (style === "atelier") return `<div class="preview-atelier"><div class="preview-rail"><i></i><i></i><i class="is-on"></i><i></i></div><div class="preview-atelier-main"><div class="preview-title-line"><span></span><b>文档框架</b><em>126 TOPICS</em></div><div class="preview-map"><div class="preview-core">框架</div><i class="preview-card card-a">前言</i><i class="preview-card card-b">快速入门</i><i class="preview-card card-c">运动控制概念</i><i class="preview-card card-d">Topic XML</i></div></div></div>`;
  if (style === "signal") return `<div class="preview-signal"><div class="preview-sheet"><b># 文档框架</b><span>&gt; 章节概述：说明产品与目标。</span><i>## 前言</i><i>### 适用产品与版本</i><i>## 1. 快速入门</i><i>### 创建运动控制工程</i></div><div class="preview-signal-map"><div class="preview-dot dot-top"></div><div class="preview-dot dot-main">框架</div><div class="preview-dot dot-bottom"></div><div class="preview-side side-left">缺料<br />08</div><div class="preview-side side-right">待确认<br />04</div></div></div>`;
  if (style === "meridian") return `<div class="preview-meridian"><div class="preview-meridian-nav"><span>炼金炉</span><i></i><small>FRAMEWORK / 04</small></div><div class="preview-meridian-hero"><div><b>让结构<br /><em>自然出现。</em></b><small>PROJECT / CODESYS</small></div><div class="preview-orb"></div></div><div class="preview-meridian-row"><span>材料</span><i></i><strong>框架</strong><i></i><span>XML</span></div></div>`;
  return `<div class="preview-archive"><div class="preview-flow-card"><b>01</b><strong>材料</strong><small>03 份</small></div><div class="preview-flow-card"><b>02</b><strong>分析</strong><small>已完成</small></div><div class="preview-flow-card is-current"><b>03</b><strong>框架</strong><small>126 Topics</small></div><div class="preview-flow-card"><b>04</b><strong>XML</strong><small>待开始</small></div></div>`;
}

function renderGallery() {
  if (!gallery) return;
  const displayNames = { atelier: "Linen Atelier", signal: "Paper Signal", archive: "Solar Archive", meridian: "Meridian Editorial" };
  gallery.innerHTML = Object.entries(directions).map(([style, direction]) => `<article class="gallery-card style-${style} ${style === activeStyle ? "is-selected" : ""}" data-gallery-style="${style}"><div class="gallery-card-head"><div><span>${direction.index} / ${direction.name}</span><h3>${displayNames[style]}</h3></div><button type="button" class="gallery-open" data-gallery-open="${style}">查看完整方案 ↘</button></div><div class="gallery-preview">${galleryPreview(style)}</div><div class="gallery-card-foot"><span>${direction.tags.join(" · ")}</span><b>${style === activeStyle ? "当前预览" : "选择查看"}</b></div></article>`).join("");
  gallery.querySelectorAll("[data-gallery-style]").forEach((card) => card.addEventListener("click", () => renderDirection(card.dataset.galleryStyle)));
}

function renderDirection(style) {
  const direction = directions[style];
  if (!direction) return;
  activeStyle = style;
  stage.className = `demo-stage style-${style}`;
  content.innerHTML = direction.content;
  document.querySelector("#direction-index").textContent = direction.index;
  document.querySelector("#direction-name").textContent = direction.name;
  document.querySelector("#note-title").textContent = direction.title;
  document.querySelector("#note-copy").textContent = direction.copy;
  document.querySelector("#note-tags").innerHTML = direction.tags.map((tag) => `<span>${tag}</span>`).join("");
  document.querySelectorAll(".direction-button").forEach((button) => button.classList.toggle("is-active", button.dataset.style === style));
  document.querySelectorAll("[data-gallery-style]").forEach((card) => card.classList.toggle("is-selected", card.dataset.galleryStyle === style));
  document.body.className = `body-${style} font-${activeFont} palette-${activePalette}`;
}

function renderFont(font) {
  activeFont = font;
  document.body.className = `body-${activeStyle} font-${font} palette-${activePalette}`;
  document.querySelectorAll(".font-option").forEach((button) => button.classList.toggle("is-selected", button.dataset.font === font));
}

function renderPalette(palette) {
  activePalette = palette;
  document.body.className = `body-${activeStyle} font-${activeFont} palette-${palette}`;
  document.querySelectorAll(".palette-option").forEach((button) => button.classList.toggle("is-selected", button.dataset.palette === palette));
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 1900);
}

document.querySelectorAll(".direction-button").forEach((button) => button.addEventListener("click", () => renderDirection(button.dataset.style)));
document.querySelectorAll(".font-option").forEach((button) => button.addEventListener("click", () => renderFont(button.dataset.font)));
document.querySelectorAll(".palette-option").forEach((button) => button.addEventListener("click", () => renderPalette(button.dataset.palette)));
document.addEventListener("click", (event) => {
  const action = event.target.closest("[data-demo-action]");
  if (!action) return;
  const messages = { save: "本地版本已保存 · V1.3", generate: "已打开 Topic 生成入口", menu: "更多项目操作" };
  showToast(messages[action.dataset.demoAction] || "已执行");
});

// Lightweight local canvas atmosphere; no CDN dependency, suitable for desktop packaging.
const canvas = document.querySelector("#ambient-canvas");
const ctx = canvas.getContext("2d");
let particles = [];
function resizeCanvas() { const ratio = Math.min(window.devicePixelRatio || 1, 2); canvas.width = innerWidth * ratio; canvas.height = innerHeight * ratio; ctx.setTransform(ratio, 0, 0, ratio, 0, 0); particles = Array.from({ length: Math.min(62, Math.floor(innerWidth / 22)) }, (_, index) => ({ x: (index * 137) % innerWidth, y: (index * 83) % innerHeight, r: 1 + index % 3, vx: -.08 + (index % 5) * .04, vy: -.05 + (index % 4) * .03 })); }
function drawAtmosphere(time = 0) { ctx.clearRect(0, 0, innerWidth, innerHeight); const color = activeStyle === "atelier" ? "239,111,81" : activeStyle === "signal" ? "8,127,120" : "185,85,61"; particles.forEach((p, index) => { p.x += p.vx; p.y += p.vy; if (p.x < -20) p.x = innerWidth + 20; if (p.x > innerWidth + 20) p.x = -20; if (p.y < -20) p.y = innerHeight + 20; if (p.y > innerHeight + 20) p.y = -20; const alpha = .035 + .02 * Math.sin(time / 900 + index); ctx.fillStyle = `rgba(${color},${alpha})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill(); }); requestAnimationFrame(drawAtmosphere); }
window.addEventListener("resize", resizeCanvas);
resizeCanvas();
requestAnimationFrame(drawAtmosphere);
renderGallery();
renderDirection("meridian");
