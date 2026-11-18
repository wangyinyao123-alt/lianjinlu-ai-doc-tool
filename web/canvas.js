/* =========================================================================
   Topic 生成画布（色块版）— 由框架工坊「批量生成 Topic」唤起
   依赖 app.js 暴露的全局：state / request / pollJob / selectedSkillNames
   支持：横向树 / 纵向树、空白处拖动平移、滚轮（或触控板捏合）缩放
   ========================================================================= */
(function () {
  "use strict";
  if (window.__topicCanvasReady) return;
  window.__topicCanvasReady = true;

  const G = {
    // 横向树（根在左，章节向右展开）
    RX: 28, RW: 164, RH: 64, CX: 282, CHW: 184, SX: 546, SW: 204,
    SH: 38, SG: 6, CHH: 64, HD: 56, FT: 58, GAP: 40, CHGAP: 22,
    // 纵向树（根在上，章节向右平铺、节点向下展开）
    VX: 34, VW: 196, VROOT_Y: 28, VCH_TOP: 196, VCOLGAP: 30,
    VSH: 38, VSG: 6, VROW_TOP: 30, VHD: 56, VFT: 58,
  };
  const COLORS = ["#2fd884", "#cbbdf4", "#dcf8b6", "#aee0ff", "#ffcfa8"];
  const BLOBS = ["#fff07a", "#c9f28d", "#2fd884", "#aee0ff", "#ffcfa8"];
  const LB = { wait: "○ 排队", run: "● 生成中", ok: "✓ 完成", fail: "✕ 失败" };
  const FL = '<g style="fill:var(--bl)"><circle cx="40" cy="20" r="16"/><circle cx="60" cy="40" r="16"/><circle cx="40" cy="60" r="16"/><circle cx="20" cy="40" r="16"/><circle cx="40" cy="40" r="18"/></g>';
  const AS = '<g style="fill:var(--bl)"><rect x="34" y="4" width="12" height="72" rx="6"/><rect x="34" y="4" width="12" height="72" rx="6" transform="rotate(60 40 40)"/><rect x="34" y="4" width="12" height="72" rx="6" transform="rotate(120 40 40)"/></g>';
  const MIN_S = 0.25, MAX_S = 2;

  let root = null;
  let model = null;
  let dir = "h";                 // "h" 横向树 | "v" 纵向树
  let scale = 1, TX = 24, TY = 18;
  let CUR = null;                // 最近一次布局结果
  let WW = 0, WH = 0;
  let editingId = null, formColor = COLORS[0], formProfile = "";
  let gen = { playing: false, jobId: null };
  let toastTimer = null;

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const q = (sel) => root.querySelector(sel);
  const qa = (sel) => Array.from(root.querySelectorAll(sel));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  function toast(msg) {
    const t = q(".tc-toast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
  }

  /* ------------------------------ DOM ------------------------------ */
  function ensureRoot() {
    if (root) return root;
    root = document.createElement("div");
    root.id = "topic-canvas";
    root.innerHTML = `
      <div class="tc-shell">
        <header class="tc-appbar">
          <span class="tc-brand"><svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1l3 7 8 .9-6 5.2 1.8 7.9L12 17.8 5.2 22l1.8-7.9-6-5.2L9 8z" fill="currentColor"/></svg>炼金炉</span>
          <nav class="tc-tabs">
            <button class="tc-tab" data-jump="home-view">首页</button>
            <button class="tc-tab" data-jump="projects-view">项目工作台</button>
            <button class="tc-tab on" data-jump="analysis-view">框架工坊</button>
            <button class="tc-tab" data-jump="topic-view">Topic 工作台</button>
            <button class="tc-tab" data-jump="projects-view">质量巡检</button>
          </nav>
          <span class="tc-proj" id="tc-proj-name"></span>
          <button class="tc-b" id="tc-close" title="关闭画布（Esc）">关闭 ×</button>
        </header>
        <div class="tc-hero">
          <div><h1><i class="tc-badge">✱</i>生成画布<em>Topic Canvas</em></h1><p class="tc-sub" id="tc-sub">正在准备…</p></div>
          <div class="tc-tools">
            <button class="tc-b" id="tc-add">新增 Agent</button>
            <button class="tc-b" id="tc-gpbtn">全局 Prompt<i class="tc-gpdot" id="tc-gpdot" aria-hidden="true"></i></button>
            <button class="tc-b" id="tc-archbtn">模型档案 <span class="tc-n" id="tc-archn">0</span></button>
            <div class="tc-seg" id="tc-dir" role="group" aria-label="画布方向"><button type="button" data-dir="h" class="on">横向树</button><button type="button" data-dir="v">纵向树</button></div>
            <label class="tc-zm">缩放 <input id="tc-zoom" type="range" min="25" max="200" step="5" value="100"><output id="tc-zl">100%</output></label>
            <button class="tc-b" id="tc-fit" title="适应画布（快捷键 0）">适应画布</button>
            <button class="tc-go" id="tc-go">批量生成 Topic<i class="tc-ci">▶</i></button>
          </div>
        </div>
        <main class="tc-main">
          <div class="tc-vp"><div class="tc-stage"><div class="tc-world"></div></div></div>
          <div class="tc-legend">
            <div class="tc-tb"><span class="tc-ch ok" id="tc-lg-ok">已完成 0</span><span class="tc-ch run" id="tc-lg-run">生成中 0</span><span class="tc-ch fail" id="tc-lg-fail">失败 0</span><span class="tc-ch" id="tc-lg-wait">排队 0</span></div>
            <p class="tc-hint" id="tc-hint">拖卡片上/下缘按整章增减（大章节为单位），可一路接管相邻 Agent。空白处拖动平移，滚轮缩放。</p>
          </div>
          <div class="tc-empty" id="tc-empty"><div><h4>还没有可生成的节点</h4><p>请先在框架工坊生成并保存框架，再回到这里批量生成 Topic。</p></div></div>
          <div class="tc-mask" id="tc-mask"></div>
          <aside class="tc-cfg" id="tc-cfg" role="dialog" aria-modal="true" aria-labelledby="tc-cft">
            <header><div><h3 id="tc-cft"><span id="tc-ct">新增</span> <i>Agent</i></h3><p id="tc-cp">框住的章节就是这个 Agent 的职责范围</p></div><button class="tc-cx" id="tc-cx" aria-label="关闭">×</button></header>
            <div class="tc-body">
              <div class="tc-f"><label for="tc-nm">名称 <small>不填则自动命名为 A、B、C…</small></label><input id="tc-nm" placeholder="如：入门章节专员"></div>
              <div class="tc-f"><label>标识色 <small>卡片底色和进度条</small></label><div class="tc-sw" id="tc-swrow">
                <button data-c="1" style="--s:#2fd884" class="on" aria-label="色1"></button>
                <button data-c="2" style="--s:#cbbdf4" aria-label="色2"></button>
                <button data-c="3" style="--s:#dcf8b6" aria-label="色3"></button>
                <button data-c="4" style="--s:#aee0ff" aria-label="色4"></button>
                <button data-c="5" style="--s:#ffcfa8" aria-label="色5"></button>
                <input type="color" id="tc-cc" value="#2fd884" title="自定义颜色">
              </div></div>

              <div class="tc-f tc-full tc-mdzone">
                <label>AI 模型 <small id="tc-mdnote">未配置也能在这里直接建</small></label>
                <div class="tc-r">
                  <div class="tc-sel" id="tc-sel-md" data-ph="选择子 Agent 或主配置"></div>
                  <button type="button" class="tc-b tc-newbtn" id="tc-newprofile">＋ 新建子 Agent</button>
                </div>
                <div class="tc-plist" id="tc-plist"></div>
              </div>

              <div class="tc-reuse tc-full"><label>复用已有 Agent 的配置</label><div class="tc-sel" id="tc-sel-ru" data-ph="不复用，从零配置"></div><small>模型档案、Prompt、Skill、素材和标识色会一并带入</small></div>
              <div class="tc-f tc-full">
                <label for="tc-pr">Prompt <small>对本 Agent 管辖的全部章节生效</small></label>
                <div class="tc-seg tc-seg-sm" id="tc-pm" role="group" aria-label="Prompt 来源">
                  <button type="button" data-pm="global" class="on">复用全局</button>
                  <button type="button" data-pm="custom">自定义</button>
                </div>
                <textarea id="tc-pr" rows="3" placeholder="角色：资深 DITA 技术写作；统一术语；Task 步骤不少于 2 步；shortdesc 不超过 3 句"></textarea>
                <p class="tc-note" id="tc-prnote"></p>
              </div>
              <div class="tc-f tc-tile">
                <label>Skill 约束 <small id="tc-sk-count">已选 0 个</small></label>
                <div class="tc-skgroup">
                  <div class="tc-skhead"><b>① 需求分析时用的 Skill</b><span>默认全部继承</span></div>
                  <div class="tc-sklist" id="tc-sk-analysis"></div>
                </div>
                <div class="tc-skgroup">
                  <div class="tc-skhead"><b>② 从 Skill 库补充</b><input id="tc-sk-q" placeholder="筛选 Skill" aria-label="筛选 Skill"></div>
                  <div class="tc-sklist" id="tc-sk-library"></div>
                </div>
                <label class="tc-check"><input type="checkbox" id="tc-inherit" checked> 同时继承项目级 Skill（自动跟随项目变更）</label>
              </div>
              <div class="tc-f tc-tile">
                <label>素材 <small id="tc-mat-count">本次生成引用的研发素材</small></label>
                <div class="tc-sklist tc-matlist" id="tc-mats"></div>
              </div>
            </div>
            <div class="tc-acmask" id="tc-acmask"></div>
            <div class="tc-acard" id="tc-npf" role="dialog" aria-modal="true" aria-labelledby="np-title">
              <header class="tc-achead">
                <div>
                  <span class="tc-ackick" id="np-kick">子 AGENT / 独立凭据</span>
                  <h4 id="np-title">新建子 Agent</h4>
                  <p id="np-sub">用本账号的 API Key 建一个独立子 Agent，生成 Topic 时可直接选用</p>
                </div>
                <div class="tc-acheadr"><span class="tc-acbadge" id="np-badge">系统凭据</span><button type="button" class="tc-acx" id="np-x" aria-label="关闭">×</button></div>
              </header>
              <div class="tc-acbody">
                <div class="tc-acpair">
                  <label class="tc-acf">子 Agent 名称<input id="np-name" placeholder="例如：快速档 / 长文档专员"></label>
                  <div class="tc-acf"><span class="tc-acfl">服务类型</span>
                    <div class="tc-seg tc-seg-sm" id="np-prov" role="group" aria-label="服务类型">
                      <button type="button" data-p="openai-compatible" class="on">OpenAI 兼容</button>
                      <button type="button" data-p="anthropic">Anthropic</button>
                      <button type="button" data-p="local">本地</button>
                    </div>
                  </div>
                </div>
                <div class="tc-acpair">
                  <label class="tc-acf">接口地址<input id="np-url" placeholder="留空沿用主配置地址"></label>
                  <label class="tc-acf">模型名称<input id="np-model" placeholder="留空沿用主配置模型"></label>
                </div>
                <div class="tc-actrio">
                  <label class="tc-acf">API Key<input id="np-key" type="password" autocomplete="new-password" placeholder="留空 = 复制账号主 Key"></label>
                  <label class="tc-acf">Temperature<input id="np-temp" type="number" min="0" max="2" step="0.1" value="0.2"></label>
                  <label class="tc-acf">超时（秒）<input id="np-time" type="number" min="5" max="600" step="1" value="300"></label>
                </div>
                <p class="tc-acnote" id="np-kshint"></p>
                <div class="tc-acquick"><span>常用服务</span>
                  <button type="button" data-pre="workbuddy">WorkBuddy 账号</button>
                  <button type="button" data-pre="openai">OpenAI</button>
                  <button type="button" data-pre="deepseek">DeepSeek</button>
                  <button type="button" data-pre="dashscope">通义千问</button>
                  <button type="button" data-pre="moonshot">Kimi</button>
                  <button type="button" data-pre="zhipu">智谱 GLM</button>
                  <button type="button" data-pre="ollama">本地 Ollama</button>
                </div>
                <div class="tc-acfoot"><button type="button" class="tc-b" id="np-cancel">取消</button><button type="button" class="tc-go" id="np-save">保存子 Agent<i class="tc-ci">✓</i></button></div>
              </div>
            </div>
            <footer><button class="tc-b" id="tc-cancel">取消</button><button class="tc-b" id="tc-create">保存配置</button><button class="tc-go" id="tc-run">保存并执行<i class="tc-ci">▶</i></button></footer>
            <div class="tc-rsz" id="tc-rsz" title="拖动调整面板大小"></div>
          </aside>
          <div class="tc-gp" id="tc-gp" role="dialog" aria-modal="true" aria-labelledby="tc-gpt-title">
            <div class="tc-gpc">
              <header><h3 id="tc-gpt-title">全局 <i>Prompt</i></h3><button class="tc-cx" id="tc-gpx" aria-label="关闭">×</button></header>
              <p>画布上所有 Agent 的默认 prompt。Agent 配置卡里选「复用全局」就跟随这里，选「自定义」则各写各的。</p>
              <textarea id="tc-gpt" rows="7" placeholder="角色：资深 DITA 技术写作；统一术语与句式；Task 步骤不少于 2 步；shortdesc 不超过 3 句；不要虚构界面名称。"></textarea>
              <div class="tc-gpf"><span id="tc-gpn">0 字</span><button class="tc-b" id="tc-gpcancel">取消</button><button class="tc-go" id="tc-gpsave">保存<i class="tc-ci">✓</i></button></div>
            </div>
          </div>
          <div class="tc-toast"></div>
        </main>
      </div>`;
    document.body.appendChild(root);
    bindShell();
    return root;
  }

  /* ------------------------------ 数据 ------------------------------ */
  function buildModel(opts) {
    const nodes = (opts.nodes || []).filter((n) => String(n.title || "").trim());
    const buckets = new Map();
    nodes.forEach((n) => {
      const key = String(n.framework_node_key || "");
      const parts = key.replace(/^fw:/, "").split(" > ").map((s) => s.trim()).filter(Boolean);
      const chapTitle = parts.length >= 2 ? parts[1] : (String(n.parent_title || "").trim() || "未分章节点");
      if (!buckets.has(chapTitle)) buckets.set(chapTitle, []);
      buckets.get(chapTitle).push(n);
    });
    const chapters = Array.from(buckets.entries()).map(([title, list]) => ({ title, nodes: list }));
    const status = {};
    nodes.forEach((n) => { status[nodeId(n)] = "wait"; });
    return {
      projectId: opts.projectId || "",
      projectName: opts.projectName || "当前项目",
      nodes,
      chapters,
      agents: [],
      owner: new Array(chapters.length).fill(null),
      status,
      seq: 0,
      wAdj: {},
      globalPrompt: "",
    };
  }
  const nodeId = (n) => String(n.framework_node_key || n.title || "");
  const byId = (id) => model.agents.find((a) => a.id === id);
  const totalNodes = () => model.nodes.length;

  /* ---- Skill / 素材：复用 app.js 的全局 state ---- */
  // 需求分析时勾选的 Skill：优先读框架工坊里的复选框，读不到时退回项目级 Skill
  function analysisSkills() {
    let names = [];
    try {
      if (typeof selectedSkillNames === "function") names = selectedSkillNames("#analysis-skill-options") || [];
    } catch (err) { names = []; }
    if (!names.length) names = (state.selectedProject?.skills || []).slice();
    return Array.from(new Set(names.filter(Boolean)));
  }
  const librarySkills = () => (state.skills || []).slice();
  const skillOf = (name) => librarySkills().find((s) => s.name === name);
  const isRequiredSkill = (name) => Boolean(skillOf(name)?.required);

  function defaultMaterialIds() {
    const fw = state.currentFramework;
    if (fw && Array.isArray(fw.material_ids) && fw.material_ids.length) return fw.material_ids.map(String);
    return (state.projectMaterials || []).map((m) => String(m.id));
  }

  // 画布可能在 Skill / 素材还没加载完时打开，补齐后再刷新面板
  async function loadAssets() {
    const jobs = [];
    if (!(state.skills || []).length) {
      jobs.push(request("/api/skills").then((data) => { state.skills = data.skills || state.skills || []; }).catch(() => {}));
    }
    if (model?.projectId && !(state.projectMaterials || []).length) {
      jobs.push(request(`/api/projects/${encodeURIComponent(model.projectId)}/materials`)
        .then((data) => { state.projectMaterials = data.materials || state.projectMaterials || []; })
        .catch(() => {}));
    }
    if (typeof state.accountKeyConfigured !== "boolean") {
      jobs.push(request("/api/settings")
        .then((data) => { state.accountKeyConfigured = !!data.api_key_configured; })
        .catch(() => {}));
    }
    if (!jobs.length) return;
    await Promise.all(jobs);
    if (q("#tc-cfg")?.classList.contains("show")) { renderSkillGroups(); renderMaterialChips(); }
  }

  function groups() {
    const gs = [];
    let cur = null;
    for (let i = 0; i < model.chapters.length; i++) {
      const o = model.owner[i];
      if (!cur || cur.o !== o) { cur = { o, ch: [] }; gs.push(cur); }
      cur.ch.push(i);
    }
    return gs;
  }
  const grpOf = (a) => groups().find((g) => g.o === a.id);
  const rangeLabel = (ch) => (ch.length === 1 ? `第${ch[0] + 1}章` : `第${ch[0] + 1}–${ch[ch.length - 1] + 1}章`);
  const nodeTotalOf = (ch) => ch.reduce((s, i) => s + model.chapters[i].nodes.length, 0);

  function addAgent(o) {
    o = o || {};
    model.seq += 1;
    const id = model.seq;
    const a = {
      id,
      nm: String(o.nm || "").trim() || String.fromCharCode(64 + id),
      profileId: o.profileId || "",
      prompt: o.prompt || "",
      useGlobal: o.useGlobal !== false,
      skills: Array.isArray(o.skills) ? o.skills.slice() : analysisSkills(),
      inheritSkills: o.inheritSkills !== false,
      materialIds: Array.isArray(o.materialIds) ? o.materialIds.slice() : defaultMaterialIds(),
      color: o.color || COLORS[(id - 1) % COLORS.length],
      blob: BLOBS[(id - 1) % BLOBS.length],
    };
    model.agents.push(a);
    return a;
  }

  function defaultAgents() {
    const count = Math.min(2, Math.max(1, model.chapters.length));
    const profiles = (state.agentProfiles || []).slice(0, count);
    const agents = [];
    for (let k = 0; k < count; k++) {
      agents.push(addAgent({ profileId: profiles[k]?.id || "", color: COLORS[k % COLORS.length] }));
    }
    const chunk = Math.ceil(model.chapters.length / count);
    model.chapters.forEach((_, i) => {
      const idx = Math.min(agents.length - 1, Math.floor(i / chunk));
      model.owner[i] = agents[idx].id;
    });
  }

  /* ------------------------------ 布局 ------------------------------ */
  function cardWidth(a) {
    return G.SX + G.SW - G.CX + 36 + (model.wAdj[a.id] || 0);
  }

  // 横向树：根在左 → 章节竖排 → 节点再向右
  function layoutH() {
    let y = 32;
    const chaps = [], secs = [], agents = [];
    groups().forEach((g) => {
      const a = g.o ? byId(g.o) : null;
      if (a) y += G.HD;
      const t0 = y;
      g.ch.forEach((i, k) => {
        const cnt = model.chapters[i].nodes.length;
        const hh = Math.max(cnt * (G.SH + G.SG) - G.SG, G.SH);
        const cy = y + hh / 2;
        chaps[i] = { x: G.CX, y: cy - G.CHH / 2, w: G.CHW, h: G.CHH, cy, bottom: y + hh };
        model.chapters[i].nodes.forEach((nd, j) => {
          secs.push({ i, j, x: G.SX, y: y + j * (G.SH + G.SG), w: G.SW, h: G.SH });
        });
        y += hh + (k < g.ch.length - 1 ? G.CHGAP : 0);
      });
      if (a) {
        agents.push({ a, x: G.CX - 18, y: t0 - G.HD, w: cardWidth(a), h: y + G.FT - (t0 - G.HD), extend: "v" });
        y += G.FT;
      }
      y += G.GAP;
    });
    const cys = chaps.filter(Boolean).map((c) => c.cy);
    const ry = cys.length ? (Math.min(...cys) + Math.max(...cys)) / 2 - G.RH / 2 : 32;
    const maxR = Math.max(G.SX + G.SW + 40, ...agents.map((f) => f.x + f.w + 34));
    return {
      root: { x: G.RX, y: ry, w: G.RW, h: G.RH },
      chaps, secs, agents,
      w: maxR,
      h: Math.max(y - 12, 240),
    };
  }

  // 纵向树：根在上 → 章节横向平铺 → 节点在各自列向下展开
  function layoutV() {
    const n = model.chapters.length;
    const colW = G.VW;
    const totalW = Math.max(colW, n * colW + Math.max(0, n - 1) * G.VCOLGAP);
    const startX = G.VX;
    const chTop = G.VCH_TOP;
    const chaps = [], secs = [];
    let maxB = chTop;

    model.chapters.forEach((chap, i) => {
      const cx = startX + i * (colW + G.VCOLGAP);
      const sy = chTop + G.CHH + G.VROW_TOP;
      const cnt = chap.nodes.length;
      const hh = Math.max(cnt * (G.VSH + G.VSG) - G.VSG, G.VSH);
      chap.nodes.forEach((nd, j) => {
        secs.push({ i, j, x: cx, y: sy + j * (G.VSH + G.VSG), w: colW, h: G.VSH });
      });
      chaps[i] = { x: cx, y: chTop, w: colW, h: G.CHH, cy: chTop + G.CHH / 2, bottom: sy + hh };
      maxB = Math.max(maxB, sy + hh);
    });

    const agents = [];
    groups().forEach((g) => {
      const a = g.o ? byId(g.o) : null;
      if (!a) return;
      const i0 = g.ch[0], i1 = g.ch[g.ch.length - 1];
      const x = chaps[i0].x - 10;
      const right = chaps[i1].x + colW + 10;
      const bottom = Math.max(...g.ch.map((i) => chaps[i].bottom));
      const top = chTop - G.VHD - 16;
      agents.push({ a, x, y: top, w: right - x, h: bottom + G.VFT + 16 - top, extend: "h" });
    });

    return {
      root: { x: startX + totalW / 2 - G.RW / 2, y: G.VROOT_Y, w: G.RW, h: G.RH },
      chaps, secs, agents,
      w: Math.max(startX + totalW + 34, ...agents.map((f) => f.x + f.w + 34)),
      h: Math.max(maxB + 60, 260),
    };
  }

  /* ------------------------------ 渲染 ------------------------------ */
  function render() {
    const L = dir === "v" ? layoutV() : layoutH();
    CUR = L;
    WW = L.w; WH = L.h;
    const world = q(".tc-world");
    const horizontal = dir !== "v";
    const cvH = (x0, y0, x1, y1) => {
      const m = (x1 - x0) * 0.5;
      return `<path d="M${x0} ${y0}C${x0 + m} ${y0} ${x1 - m} ${y1} ${x1} ${y1}" stroke="var(--tc-edge)" stroke-width="1.6"/>`;
    };
    const cvV = (x0, y0, x1, y1) => {
      const m = (y1 - y0) * 0.5;
      return `<path d="M${x0} ${y0}C${x0} ${y0 + m} ${x1} ${y1 - m} ${x1} ${y1}" stroke="var(--tc-edge)" stroke-width="1.6"/>`;
    };
    const cv = horizontal ? cvH : cvV;

    let h = "";
    h += `<div class="tc-root" style="left:${L.root.x}px;top:${L.root.y}px;width:${L.root.w}px;height:${L.root.h}px"><b>${esc(model.projectName)}</b><span>${model.chapters.length} 章，${totalNodes()} 个节点</span></div>`;

    L.agents.forEach((f, k) => {
      const a = f.a, g = grpOf(a);
      if (!g) return;
      const n = nodeTotalOf(g.ch);
      const d = g.ch.reduce((s, i) => s + model.chapters[i].nodes.filter((x) => model.status[nodeId(x)] === "ok").length, 0);
      const profileName = profileLabel(a.profileId);
      h += `<div class="tc-agent${f.w < 380 ? " is-narrow" : ""}" data-id="${a.id}" style="left:${f.x}px;top:${f.y}px;width:${f.w}px;height:${f.h}px;--c:${a.color};--bl:${a.blob}">
        <div class="tc-ah"><span class="tc-sc">${rangeLabel(g.ch)}</span><b>${esc(a.nm)}</b><i class="tc-md">${esc(profileName)}</i>
        <span class="tc-ac"><button class="tc-runb" data-run="${a.id}" title="执行这个 Agent，只生成它范围内的章节">▶</button><button class="tc-cfgb" data-cfg="${a.id}"><i>⚙</i><span>配置</span></button><button class="tc-del" data-del="${a.id}" title="删除 Agent">×</button></span></div>
        <div class="tc-af"><span class="tc-nt">${n} 个节点</span><span class="tc-pb"><i style="width:${n ? (d / n) * 100 : 0}%"></i></span><span class="tc-cnt">${d}/${n} 完成</span></div>
        <span class="tc-grip"></span><span class="tc-blob"><svg viewBox="0 0 80 80" aria-hidden="true">${k % 2 ? AS : FL}</svg></span>
      </div>`;
    });

    // 拖拽把手单独渲染在最上层：卡片本体 z-index 低于章节/节点，把手放里面会被它们盖住点不到
    // data-mode: end 拖尾端 / start 拖首端 / widen 只调宽
    // 抓取带整条边贯通（旧版上缘只覆盖左半侧，右半侧抓不住）；只压进卡片 6px，避免吞掉配置/删除按钮
    const EDGE = 22, INNER = 6;
    let hit = "";
    L.agents.forEach((f) => {
      const id = f.a.id;
      if (horizontal) {
        hit += `<span class="tc-hit tc-hit-r" data-hr="${id}" data-mode="widen" style="left:${f.x + f.w - 24}px;top:${f.y + 58}px;width:24px;height:${Math.max(44, f.h - 58 - 58)}px"></span>`;
        hit += `<span class="tc-hit tc-hit-b" data-hr="${id}" data-mode="end" data-judge="y" style="left:${f.x}px;top:${f.y + f.h - INNER}px;width:${f.w}px;height:${EDGE}px"></span>`;
        hit += `<span class="tc-hit tc-hit-t" data-hr="${id}" data-mode="start" data-judge="y" style="left:${f.x}px;top:${f.y - (EDGE - INNER)}px;width:${f.w}px;height:${EDGE}px"></span>`;
      } else {
        hit += `<span class="tc-hit tc-hit-r" data-hr="${id}" data-mode="end" data-judge="x" style="left:${f.x + f.w - INNER}px;top:${f.y}px;width:${EDGE}px;height:${f.h}px"></span>`;
        hit += `<span class="tc-hit tc-hit-l" data-hr="${id}" data-mode="start" data-judge="x" style="left:${f.x - (EDGE - INNER)}px;top:${f.y}px;width:${EDGE}px;height:${f.h}px"></span>`;
      }
    });

    L.chaps.forEach((c, i) => {
      const chap = model.chapters[i];
      if (!c || !chap) return;
      const owned = !!model.owner[i];
      h += `<div class="tc-chap${owned ? "" : " free"}" id="tc-ch-${i}" style="left:${c.x}px;top:${c.y}px;width:${c.w}px;height:${c.h}px"><b title="${esc(chap.title)}">${esc(chap.title)}</b><span>${chap.nodes.length} 个节点${owned ? "" : "，未分配"}</span></div>`;
    });

    L.secs.forEach((s) => {
      const n = model.chapters[s.i]?.nodes[s.j];
      if (!n) return;
      const id = nodeId(n);
      const st = model.status[id] || "wait";
      const owned = !!model.owner[s.i];
      h += `<div class="tc-sec ${st}" id="tc-s-${s.i}-${s.j}" data-nid="${esc(id)}" style="left:${s.x}px;top:${s.y}px;width:${s.w}px;height:${s.h}px"><span class="tc-t" title="${esc(n.title)}">${esc(n.title)}</span><em>${owned ? LB[st] : "○ 未分配"}</em></div>`;
    });

    let e = "";
    L.chaps.forEach((c, i) => {
      if (!c) return;
      if (horizontal) {
        e += cv(L.root.x + L.root.w, L.root.y + L.root.h / 2, c.x, c.cy);
      } else {
        e += cv(L.root.x + L.root.w / 2, L.root.y + L.root.h, c.x + c.w / 2, c.y);
      }
    });
    L.secs.forEach((s) => {
      const c = L.chaps[s.i];
      if (!c) return;
      if (horizontal) e += cv(c.x + c.w, c.cy, s.x, s.y + s.h / 2);
      else e += cv(c.x + c.w / 2, c.y + c.h, s.x + s.w / 2, s.y);
    });

    world.innerHTML = `<svg class="tc-edges" width="${WW}" height="${WH}" style="width:${WW}px;height:${WH}px">${e}</svg>` + h + hit;
    world.style.width = WW + "px";
    world.style.height = WH + "px";
    q("#tc-hint").textContent = horizontal
      ? "拖卡片上/下缘按整章增减（大章节为单位，可一路接管相邻 Agent），右缘调宽。点卡片 ▶ 只跑这个 Agent，右上角「批量生成 Topic」跑全部。"
      : "拖卡片左/右缘按整章增减（大章节为单位，可一路接管相邻 Agent）。点卡片 ▶ 只跑这个 Agent，右上角「批量生成 Topic」跑全部。";
    bindNodes();
    refreshStats();
  }

  function profileLabel(pid) {
    if (!pid) return "主配置";
    const p = (state.agentProfiles || []).find((x) => x.id === pid);
    return p ? (p.model || p.name || "档案") : "主配置";
  }

  function bindNodes() {
    qa("[data-cfg]").forEach((b) => { b.onclick = (e) => { e.stopPropagation(); openCfg(Number(b.dataset.cfg)); }; });
    qa("[data-run]").forEach((b) => {
      b.onclick = (e) => { e.stopPropagation(); startGenerate(Number(b.dataset.run)); };
    });
    qa("[data-del]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const a = byId(Number(b.dataset.del));
        if (!a) return;
        model.owner = model.owner.map((o) => (o === a.id ? null : o));
        model.agents = model.agents.filter((x) => x.id !== a.id);
        render();
        toast(`已删除 ${a.nm}，其章节回到未分配`);
      };
    });
    // 把手统一绑定：data-mode = end(尾端) / start(首端) / widen(只调宽)
    qa("[data-hr]").forEach((el) => {
      const card = () => cardOf(el);
      el.addEventListener("pointerdown", (e) => {
        if (el.dataset.mode === "widen") startWiden(e, card());
        else startRange(e, card(), el.dataset.judge, el.dataset.mode);
      });
    });
  }

  function cardOf(el) {
    return root.querySelector(`.tc-agent[data-id="${el.dataset.hr}"]`);
  }

  /* ------------------------------ 视图（缩放 / 平移） ------------------------------ */
  // 用 CSS zoom 而不是 transform:scale —— transform 走合成层会按 1x 栅格化后放大，文字发虚；
  // zoom 是真实布局缩放，任意比例下文字都是矢量清晰的。
  const HAS_ZOOM = typeof document.documentElement.style.zoom !== "undefined";

  function applyView() {
    const world = q(".tc-world");
    if (world) {
      if (HAS_ZOOM) {
        world.style.transform = "";
        world.style.zoom = String(scale);
        // 注意：元素自身的 zoom 也会放大它的 left/top，所以这里要除以 scale 才是屏幕偏移
        world.style.left = TX / scale + "px";
        world.style.top = TY / scale + "px";
      } else {
        world.style.transform = `translate(${TX}px,${TY}px) scale(${scale})`;
      }
    }
    const slider = q("#tc-zoom");
    if (slider) slider.value = String(Math.round(clamp(scale, MIN_S, MAX_S) * 100));
    const label = q("#tc-zl");
    if (label) label.textContent = Math.round(scale * 100) + "%";
  }

  // 以视口内某个点（默认中心）为锚点缩放
  function setS(s, clientX, clientY) {
    const vp = q(".tc-vp");
    if (!vp) return;
    const r = vp.getBoundingClientRect();
    const px = clientX == null ? r.width / 2 : clientX - r.left;
    const py = clientY == null ? r.height / 2 : clientY - r.top;
    const ns = clamp(s, MIN_S, MAX_S);
    const wx = (px - TX) / scale;
    const wy = (py - TY) / scale;
    scale = ns;
    TX = px - wx * ns;
    TY = py - wy * ns;
    applyView();
  }

  function topLeft(s) {
    scale = clamp(s == null ? scale : s, MIN_S, MAX_S);
    TX = 24; TY = 18;
    applyView();
  }

  function fit() {
    const vp = q(".tc-vp");
    if (!vp) return;
    const r = vp.getBoundingClientRect();
    const ns = Math.min(1.2, (r.width - 56) / Math.max(WW, 1), (r.height - 56) / Math.max(WH, 1));
    scale = clamp(ns, MIN_S, MAX_S);
    TX = Math.round((r.width - WW * scale) / 2);
    TY = Math.round((r.height - WH * scale) / 2);
    applyView();
  }

  function toWorld(cx, cy) {
    const r = q(".tc-world").getBoundingClientRect();
    return { x: (cx - r.left) / scale, y: (cy - r.top) / scale };
  }

  /* ------------------------------ 拖拽 ------------------------------ */
  // judge: "x" 纵向树（按横坐标判定章节）| "y" 横向树（按纵坐标判定章节）
  // side:  "end" 拖尾端 | "start" 拖首端
  // 规则：以大章节为最小单位整章增减；两端都能自由越过相邻 Agent（整章接管），
  //       相邻 Agent 章节被清零后自动移除，不再出现「先缩小对方才能继续」的死锁。
  function startRange(e, cardEl, judge, side) {
    if (!cardEl) return;
    e.preventDefault(); e.stopPropagation();
    const a = byId(Number(cardEl.dataset.id));
    if (!a) return;
    const g = grpOf(a);
    if (!g) return;
    const n = model.chapters.length;
    const s0 = g.ch[0];
    const i1 = g.ch[g.ch.length - 1];
    const isEnd = side !== "start";
    // 尾端可一路吃到最后一章、首端可一路吃到第一章；但至少给自己留 1 章
    const lo = isEnd ? s0 : 0;
    const hi = isEnd ? n - 1 : i1;
    let cur = isEnd ? i1 : s0;

    cardEl.classList.add("dragging", "resizing");
    document.body.style.userSelect = "none";
    document.body.style.cursor = judge === "x" ? "ew-resize" : "ns-resize";

    const centerOf = (c) => (judge === "x" ? c.x + c.w / 2 : c.cy);
    const passed = (c, p) => (judge === "x" ? p.x >= centerOf(c) : p.y >= centerOf(c));
    const before = (c, p) => (judge === "x" ? p.x <= centerOf(c) : p.y <= centerOf(c));
    // 纵向树里卡片的左右沿 = 章节列；横向树里卡片的上下沿 = 章节栈
    const stackTop = (i) => {
      const hh = Math.max(model.chapters[i].nodes.length * (G.SH + G.SG) - G.SG, G.SH);
      return CUR.chaps[i].cy - hh / 2;
    };

    // 拖动时跟随指针的范围徽标（第 X–Y 章 · N 个节点）
    const badge = document.createElement("div");
    badge.className = "tc-badge-range";
    badge.style.display = "none";
    q(".tc-world").appendChild(badge);
    let ptr = null;

    const paint = () => {
      const iL = isEnd ? s0 : cur;
      const iR = isEnd ? cur : i1;
      for (let i = 0; i < n; i++) {
        const el = document.getElementById(`tc-ch-${i}`);
        if (!el) continue;
        const inRange = i >= iL && i <= iR;
        const mine = model.owner[i] === a.id;
        el.classList.toggle("preview", inRange && !mine);   // 将被纳入
        el.classList.toggle("dim", !inRange && mine);       // 将被让出
      }
      if (!CUR?.chaps?.[iL] || !CUR?.chaps?.[iR]) return;
      // 卡片外框实时跟着拖，所见即所得
      if (judge === "x") {
        const L = CUR.chaps[iL].x - 10;
        const R = CUR.chaps[iR].x + CUR.chaps[iR].w + 10;
        cardEl.style.left = L + "px";
        cardEl.style.width = Math.max(140, R - L) + "px";
      } else {
        const T = stackTop(iL) - G.HD;
        const B = CUR.chaps[iR].bottom + G.FT;
        cardEl.style.top = T + "px";
        cardEl.style.height = Math.max(160, B - T) + "px";
      }
      const chs = [];
      for (let i = iL; i <= iR; i++) chs.push(i);
      badge.textContent = `${a.nm} · ${rangeLabel(chs)} · ${nodeTotalOf(chs)} 个节点`;
      // 徽标跟着指针走，边缘拖到屏幕外也不会丢
      if (ptr) {
        badge.style.display = "block";
        badge.style.left = Math.round(ptr.x + 18) + "px";
        badge.style.top = Math.round(ptr.y + 14) + "px";
      }
      const sc = cardEl.querySelector(".tc-sc");
      if (sc) sc.textContent = rangeLabel(chs);
      const nt = cardEl.querySelector(".tc-nt");
      if (nt) nt.textContent = nodeTotalOf(chs) + " 个节点";
    };

    const move = (ev) => {
      const p = toWorld(ev.clientX, ev.clientY);
      ptr = p;
      let val = isEnd ? lo : hi;
      if (isEnd) {
        for (let i = lo; i <= hi; i++) {
          const c = CUR?.chaps?.[i];
          if (c && passed(c, p)) val = i;
        }
      } else {
        // 首端：取第一段"中心还没被指针越过"的章节（含等号，边界落在谁的中心就归谁）
        for (let i = lo; i <= hi; i++) {
          const c = CUR?.chaps?.[i];
          if (!c) continue;
          if (before(c, p)) { val = i; break; }
        }
      }
      if (val !== cur) { cur = val; paint(); }
      else if (ptr) {
        badge.style.display = "block";
        badge.style.left = Math.round(ptr.x + 18) + "px";
        badge.style.top = Math.round(ptr.y + 14) + "px";
      }
    };

    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      cardEl.classList.remove("dragging", "resizing");
      badge.remove();
      for (let i = 0; i < n; i++) {
        const el = document.getElementById(`tc-ch-${i}`);
        if (el) el.classList.remove("preview", "dim");
      }
      const from = isEnd ? s0 : cur;
      const to = isEnd ? cur : i1;
      const gone = setRange(a, from, to);
      const chs = [];
      for (let i = from; i <= to; i++) chs.push(i);
      toast(`${a.nm}：${rangeLabel(chs)} · ${nodeTotalOf(chs)} 个节点${gone.length ? ` · 已接管 ${gone.map((x) => x.nm).join("、")} 的全部章节` : ""}`);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    paint();
  }

  // 区间内归本 Agent；区间外原本属于它的章节退回「未分配」，不自动并给相邻 Agent。
  // 返回因章节被整段接管而清零、随即被移除的 Agent 列表。
  function setRange(a, s, eIdx) {
    model.owner = model.owner.map((o, i) => {
      if (i >= s && i <= eIdx) return a.id;
      if (o === a.id) return null;
      return o;
    });
    const gone = model.agents.filter((x) => x.id !== a.id && !grpOf(x));
    if (gone.length) {
      const ids = new Set(gone.map((x) => x.id));
      model.agents = model.agents.filter((x) => !ids.has(x.id));
      if (editingId && ids.has(editingId)) closeCfg();
    }
    render();
    return gone;
  }

  function startWiden(e, cardEl) {
    if (!cardEl) return;
    e.preventDefault(); e.stopPropagation();
    const a = byId(Number(cardEl.dataset.id));
    if (!a) return;
    const w0 = model.wAdj[a.id] || 0;
    const x0 = e.clientX;
    cardEl.classList.add("dragging", "resizing");
    document.body.style.userSelect = "none";
    const move = (ev) => {
      model.wAdj[a.id] = clamp(w0 + (ev.clientX - x0) / scale, -140, 460);
      cardEl.style.width = cardWidth(a) + "px";
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.userSelect = "";
      cardEl.classList.remove("dragging", "resizing");
      render();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  /* ------------------------------ 配置面板 ------------------------------ */
  // 表单草稿：只在面板里改，点「保存配置 / 保存并执行」才写回 model.agents
  let form = { skills: new Set(), inherit: true, mats: new Set(), mode: "global", custom: "" };

  // 手写下拉：原生 select 没法做两行结构，也压不住系统样式
  const SEL = { md: null, ru: null };

  function mountSelect(host, items, value, onPick) {
    host.innerHTML = `<button type="button" class="tc-selb" aria-haspopup="listbox"><span class="tc-selv"></span><i class="tc-selar">⌄</i></button><div class="tc-selp" role="listbox"></div>`;
    const valEl = host.querySelector(".tc-selv");
    const panel = host.querySelector(".tc-selp");
    const api = {
      items: items || [],
      value: value == null ? "" : String(value),
      paint() {
        const cur = api.items.find((it) => String(it.value) === api.value);
        valEl.innerHTML = cur
          ? `<b>${esc(cur.label)}</b>${cur.hint ? `<em>${esc(cur.hint)}</em>` : ""}`
          : `<span class="tc-selph">${esc(host.dataset.ph || "请选择")}</span>`;
        panel.innerHTML = api.items.length
          ? api.items.map((it) => `<button type="button" class="tc-opt${String(it.value) === api.value ? " on" : ""}" data-v="${esc(it.value)}" role="option"><span>${esc(it.label)}${it.hint ? `<em>${esc(it.hint)}</em>` : ""}</span><b class="tc-optck">✓</b></button>`).join("")
          : `<p class="tc-selnt">暂无可选项</p>`;
      },
      set(v) { api.value = v == null ? "" : String(v); api.paint(); },
      get() { return api.value; },
      setItems(next) {
        api.items = next || [];
        if (!api.items.some((it) => String(it.value) === api.value)) api.value = "";
        api.paint();
      },
      close() { host.classList.remove("open"); },
    };
    host.querySelector(".tc-selb").onclick = (e) => {
      e.stopPropagation();
      const willOpen = !host.classList.contains("open");
      qa(".tc-sel.open").forEach((n) => n.classList.remove("open"));
      host.classList.toggle("open", willOpen);
    };
    panel.onclick = (e) => {
      const b = e.target.closest("[data-v]");
      if (!b) return;
      api.value = b.dataset.v;
      api.paint();
      api.close();
      if (onPick) onPick(api.value);
    };
    api.paint();
    return api;
  }

  function keyHintOf(p) {
    if (!p) return "";
    if (p.key_source === "none") return " · 未配 Key";
    if (p.key_origin === "account") return " · 账号 Key";
    return " · 独立 Key";
  }

  function profileItems() {
    const list = state.agentProfiles || [];
    return [{ value: "", label: "主配置", hint: "沿用设置页的模型与 Key" }].concat(
      list.map((p) => ({
        value: p.id,
        label: p.name || p.id,
        hint: `${p.model || "主配置模型"}${keyHintOf(p)}`,
      }))
    );
  }

  function syncModelNote() {
    const note = q("#tc-mdnote");
    if (!note) return;
    const id = SEL.md ? SEL.md.get() : "";
    const p = (state.agentProfiles || []).find((x) => x.id === id);
    note.textContent = !id ? "沿用设置页主配置" : `${p?.model || "主配置模型"}${keyHintOf(p)}`;
  }

  function refreshModelSelect(selected) {
    if (!SEL.md) SEL.md = mountSelect(q("#tc-sel-md"), profileItems(), selected, () => { form.profileId = SEL.md.get(); syncModelNote(); renderProfileCards(); });
    else SEL.md.setItems(profileItems());
    SEL.md.set(selected || "");
    form.profileId = SEL.md.get();
    syncModelNote();
    renderProfileCards();
    const badge = q("#tc-archn");
    if (badge) badge.textContent = String((state.agentProfiles || []).length);
  }

  // 已保存的子 Agent 卡片：显示在配置卡下方，点「选用」即挂到当前 Agent 上，
  // 生成 Topic 时就用它的模型与 Key。
  function renderProfileCards() {
    const host = q("#tc-plist");
    if (!host) return;
    const list = state.agentProfiles || [];
    const cur = SEL.md ? SEL.md.get() : (form.profileId || "");
    if (!list.length) {
      host.innerHTML = `<p class="tc-plist-empty">还没有子 Agent。点上方「＋ 新建子 Agent」，用本账号 Key 建一个，保存后会出现在这里并可被选用。</p>`;
      return;
    }
    host.innerHTML = list.map((p) => {
      const hostName = String(p.base_url || "").replace(/^https?:\/\//i, "").split("/")[0] || "主配置地址";
      const on = p.id === cur;
      return `<div class="tc-pcard${on ? " on" : ""}" data-pid="${esc(p.id)}">
        <span class="tc-pdot${p.key_source === "none" ? " warn" : ""}" aria-hidden="true"></span>
        <div class="tc-ptx"><b>${esc(p.name || p.id)}</b><span>${esc(p.model || "主配置模型")} · ${esc(hostName)}${esc(keyHintOf(p))}</span></div>
        <div class="tc-pacts">
          <button type="button" data-act="use"${on ? ' class="on"' : ""}>${on ? "已选用" : "选用"}</button>
          <button type="button" data-act="edit">编辑</button>
          <button type="button" data-act="test">测试</button>
          <button type="button" data-act="del">删除</button>
        </div>
      </div>`;
    }).join("");
  }

  function refreshReuseSelect() {
    const items = [{ value: "", label: "不复用，从零配置", hint: "下面全部字段保持默认" }].concat(
      model.agents.filter((a) => a.id !== editingId).map((a) => {
        const g = grpOf(a);
        return { value: String(a.id), label: a.nm, hint: g ? rangeLabel(g.ch) : "未框选章节" };
      })
    );
    if (!SEL.ru) SEL.ru = mountSelect(q("#tc-sel-ru"), items, "", applyReuse);
    else SEL.ru.setItems(items);
    SEL.ru.set("");
  }

  // 复用已有 Agent：模型档案 + Prompt + Skill + 素材 + 标识色一起带过来
  function applyReuse(v) {
    const a = byId(Number(v));
    if (!a) return;
    SEL.md.set(a.profileId || "");
    form.profileId = SEL.md.get();
    syncModelNote();
    setColor(a.color);
    q("#tc-nm").value = a.nm + " 副本";
    form.skills = new Set(a.skills || []);
    form.inherit = a.inheritSkills !== false;
    form.mats = new Set((a.materialIds || []).map(String));
    form.mode = a.useGlobal === false ? "custom" : "global";
    form.custom = a.prompt || "";
    q("#tc-inherit").checked = form.inherit;
    setPromptMode(form.mode);
    renderSkillGroups();
    renderMaterialChips();
    toast(`已复用 ${a.nm} 的配置`);
  }

  /* ---- 子 Agent：用本账号 Key 直接建档，卡片式表单 ---- */
  let npProv = "openai-compatible";
  let editingProfileId = "";
  const PRESETS = {
    workbuddy: { p: "openai-compatible", url: "https://copilot.tencent.com/v2", model: "deepseek-v4.1-flash", name: "WorkBuddy 账号" },
    openai: { p: "openai-compatible", url: "https://api.openai.com/v1", model: "gpt-6-luna", name: "OpenAI" },
    deepseek: { p: "openai-compatible", url: "https://api.deepseek.com", model: "deepseek-flash", name: "DeepSeek" },
    dashscope: { p: "openai-compatible", url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus", name: "通义千问" },
    moonshot: { p: "openai-compatible", url: "https://api.moonshot.cn/v1", model: "kimi-k3", name: "Kimi" },
    zhipu: { p: "openai-compatible", url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4.6", name: "智谱 GLM" },
    ollama: { p: "local", url: "http://127.0.0.1:11434/v1", model: "qwen2.5:7b", name: "本地 Ollama" },
  };

  function accountKeyReady() {
    if (typeof state.accountKeyConfigured === "boolean") return state.accountKeyConfigured;
    return (state.agentProfiles || []).some((p) => p.account_key_configured);
  }

  function syncNpNote() {
    const hint = q("#np-kshint");
    if (!hint) return;
    const cur = editingProfileId ? (state.agentProfiles || []).find((x) => x.id === editingProfileId) : null;
    if (npProv === "local") hint.textContent = "本地模型通常不需要 Key，留空即可。";
    else if (cur && cur.key_configured) hint.textContent = "这个子 Agent 已持有自己的 Key；留空保持不变，填入则整体替换。";
    else if (accountKeyReady()) hint.textContent = "留空 = 把「AI 服务」里的账号主 Key 复制成这个子 Agent 的独立 Key，之后可以单独替换。";
    else hint.textContent = "设置页还没有账号主 Key，请在下面填一个这个子 Agent 专用的 Key。";
  }

  function setProv(p) {
    npProv = p || "openai-compatible";
    qa("#np-prov button").forEach((b) => b.classList.toggle("on", b.dataset.p === npProv));
    syncNpNote();
  }

  function openNpf(profile) {
    editingProfileId = profile ? profile.id : "";
    q("#np-title").textContent = profile ? "编辑子 Agent" : "新建子 Agent";
    q("#np-kick").textContent = profile ? "子 AGENT / 已保存" : "子 AGENT / 独立凭据";
    q("#np-sub").textContent = profile
      ? "只改这个子 Agent 的配置；Key 留空保持不变"
      : "用本账号的 API Key 建一个独立子 Agent，生成 Topic 时可直接选用";
    q("#np-badge").textContent = profile ? (profile.key_configured ? "独立 Key" : "待配 Key") : "系统凭据";
    q("#np-name").value = profile ? profile.name || "" : "";
    q("#np-url").value = profile ? profile.base_url || "" : "";
    q("#np-model").value = profile ? profile.model || "" : "";
    q("#np-key").value = "";
    q("#np-key").placeholder = profile && profile.key_configured ? "已配置，留空保持不变" : "留空 = 复制本账号主 Key";
    q("#np-temp").value = profile ? (profile.temperature ?? 0.2) : 0.2;
    q("#np-time").value = profile ? (profile.timeout_seconds ?? 300) : 300;
    q("#tc-npf").classList.add("show");
    q("#tc-acmask").classList.add("show");
    q("#tc-newprofile").classList.add("on");
    setProv(profile ? profile.provider : npProv);
    setTimeout(() => {
      q("#tc-npf").scrollIntoView({ block: "nearest", behavior: "smooth" });
      q("#np-name").focus();
    }, 80);
  }

  function closeNpf() {
    q("#tc-npf").classList.remove("show");
    q("#tc-acmask").classList.remove("show");
    q("#tc-newprofile").classList.remove("on");
    editingProfileId = "";
  }

  function applyPreset(k) {
    const p = PRESETS[k];
    if (!p) return;
    setProv(p.p);
    q("#np-url").value = p.url;
    q("#np-model").value = p.model;
    if (!q("#np-name").value.trim()) q("#np-name").value = p.name;
    if (k === "workbuddy") {
      q("#np-key").placeholder = "粘贴 pt_ 开头的 WorkBuddy Key";
      const hint = q("#np-kshint");
      if (hint) hint.textContent = "WorkBuddy 账号 Key 在「套餐与用量 → API 管理」创建，pt_ 开头；必须单独粘贴，留空会变成复制主 Key。";
    }
  }

  async function saveNewProfile() {
    const name = q("#np-name").value.trim();
    if (!name) { toast("先给这个子 Agent 起个名字"); q("#np-name").focus(); return; }
    const apiKey = q("#np-key").value.trim();
    const editing = Boolean(editingProfileId);
    const cur = editing ? (state.agentProfiles || []).find((x) => x.id === editingProfileId) : null;
    if (!apiKey && npProv !== "local" && !accountKeyReady() && !(cur && cur.key_configured)) {
      toast("还没有可复制的账号 Key，请先在下面填一个 Key");
      q("#np-key").focus();
      return;
    }
    const btn = q("#np-save");
    btn.disabled = true;
    btn.innerHTML = "保存中…";
    try {
      const payload = {
        id: editingProfileId || undefined,
        name,
        provider: npProv,
        base_url: q("#np-url").value.trim(),
        model: q("#np-model").value.trim(),
        temperature: Number(q("#np-temp").value) || 0.2,
        timeout_seconds: Number(q("#np-time").value) || 300,
        api_key: apiKey,
      };
      const prof = await request("/api/agent-profiles", { method: "POST", body: JSON.stringify(payload) });
      if (typeof loadAgentProfiles === "function") await loadAgentProfiles();
      else {
        const data = await request("/api/agent-profiles");
        state.agentProfiles = data.profiles || [];
      }
      refreshModelSelect(prof.id);
      closeNpf();
      toast(editing ? `已更新「${prof.name}」` : `已建好子 Agent「${prof.name}」，本 Agent 将用它生成`);
    } catch (error) {
      toast(`保存失败：${error.message}`);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '保存子 Agent<i class="tc-ci">✓</i>';
    }
  }
  function setColor(c) {
    formColor = c.toLowerCase();
    const idx = COLORS.findIndex((x) => x.toLowerCase() === formColor);
    qa("#tc-swrow button").forEach((b) => b.classList.toggle("on", Number(b.dataset.c) - 1 === idx));
    if (/^#[0-9a-f]{6}$/i.test(formColor)) q("#tc-cc").value = formColor;
  }

  function skillChip(name, required, disabled) {
    const on = required || form.skills.has(name);
    const cls = "tc-chip" + (on ? " on" : "") + (required ? " lock" : "");
    const tail = required ? " · 必选" : disabled ? " · 停用" : "";
    return `<button type="button" class="${cls}" data-sk="${esc(name)}"${required || disabled ? " disabled" : ""} title="${esc(name)}">${esc(name)}${tail}</button>`;
  }

  // ① 需求分析时勾选的 Skill（默认全继承）② Skill 库里补充的其他 Skill
  function renderSkillGroups() {
    const ana = new Set(analysisSkills());
    const all = librarySkills();
    const kw = String(q("#tc-sk-q")?.value || "").trim().toLowerCase();
    const listA = Array.from(ana);
    q("#tc-sk-analysis").innerHTML = listA.length
      ? listA.map((name) => skillChip(name, isRequiredSkill(name), skillOf(name)?.enabled === false)).join("")
      : `<span class="tc-skhint">需求分析还没勾选 Skill，可直接从下方 Skill 库挑。</span>`;
    const rest = all
      .filter((s) => !ana.has(s.name))
      .filter((s) => !kw || String(s.name).toLowerCase().includes(kw) || String(s.description || "").toLowerCase().includes(kw));
    q("#tc-sk-library").innerHTML = rest.length
      ? rest.map((s) => skillChip(s.name, Boolean(s.required), s.enabled === false)).join("")
      : `<span class="tc-skhint">${all.length ? (kw ? "没有匹配的 Skill。" : "库里的其他 Skill 都已包含在上方。") : "Skill 库为空，可在「配置 Skill」里新建。"}</span>`;
    refreshCfgCounts();
  }

  function renderMaterialChips() {
    const list = state.projectMaterials || [];
    q("#tc-mats").innerHTML = list.length
      ? list.map((m) => `<button type="button" class="tc-chip${form.mats.has(String(m.id)) ? " on" : ""}" data-mat="${esc(m.id)}" title="${esc(m.name)}">${esc(m.name)}</button>`).join("")
        + `<button type="button" class="tc-chip tc-chip-tool" data-mat-all="1">全选 / 清空</button>`
      : `<span class="tc-skhint">当前项目还没有素材，可在需求分析页上传后回来勾选。</span>`;
    refreshCfgCounts();
  }

  function refreshCfgCounts() {
    const sk = q("#tc-sk-count");
    if (sk) sk.textContent = `已选 ${form.skills.size} 个`;
    const mt = q("#tc-mat-count");
    if (mt) {
      const total = (state.projectMaterials || []).length;
      mt.textContent = total ? `已选 ${form.mats.size} / ${total} 项（不选则不带素材）` : "本次生成引用的研发素材";
    }
  }

  // 复用全局：textarea 只读展示全局 prompt；自定义：可编辑，留空则回退全局
  function setPromptMode(mode) {
    const ta = q("#tc-pr"), note = q("#tc-prnote");
    if (form.mode === "custom" && mode !== "custom") form.custom = ta.value;
    form.mode = mode === "custom" ? "custom" : "global";
    qa("#tc-pm button").forEach((b) => b.classList.toggle("on", b.dataset.pm === form.mode));
    if (form.mode === "global") {
      ta.readOnly = true;
      ta.value = model.globalPrompt || "";
      ta.placeholder = "尚未设置全局 Prompt —— 点右上角「全局 Prompt」填写，或切到「自定义」";
      note.textContent = model.globalPrompt
        ? `跟随画布右上角的全局 Prompt（${model.globalPrompt.length} 字），改一处即全卡生效。`
        : "全局 Prompt 为空，本次只按 Skill 与素材生成。";
    } else {
      ta.readOnly = false;
      ta.value = form.custom || "";
      ta.placeholder = "角色：资深 DITA 技术写作；统一术语；Task 步骤不少于 2 步；shortdesc 不超过 3 句";
      note.textContent = "仅对本 Agent 的章节生效；留空则回退到全局 Prompt。";
    }
  }

  function syncGlobalPrompt() {
    q("#tc-gpdot")?.classList.toggle("on", Boolean(model.globalPrompt));
    if (form.mode === "global" && q("#tc-cfg")?.classList.contains("show")) setPromptMode("global");
  }

  function openCfg(id) {
    editingId = id || null;
    const a = id ? byId(id) : null;
    const g = a ? grpOf(a) : null;
    q("#tc-ct").textContent = a ? "配置" : "新增";
    q("#tc-cp").textContent = a
      ? `正在配置：${a.nm}${g ? " · " + rangeLabel(g.ch) + " · " + nodeTotalOf(g.ch) + " 个节点" : " · 还没框选章节"}`
      : "框住的章节就是这个 Agent 的职责范围";
    q("#tc-nm").value = a ? a.nm : "";
    form = {
      profileId: a ? a.profileId || "" : "",
      skills: new Set(a ? a.skills || [] : analysisSkills()),
      inherit: a ? a.inheritSkills !== false : true,
      mats: new Set(a ? (a.materialIds || []).map(String) : defaultMaterialIds()),
      mode: a && a.useGlobal === false ? "custom" : "global",
      custom: a ? a.prompt || "" : "",
    };
    refreshModelSelect(form.profileId);
    refreshReuseSelect();
    closeNpf();
    q("#np-name").value = "";
    q("#np-url").value = "";
    q("#np-model").value = "";
    q("#np-key").value = "";
    setColor(a ? a.color : COLORS[model.agents.length % COLORS.length]);
    q("#tc-inherit").checked = form.inherit;
    q("#tc-sk-q").value = "";
    q("#tc-pr").value = form.mode === "custom" ? form.custom : (model.globalPrompt || "");
    setPromptMode(form.mode);
    q("#tc-create").textContent = a ? "保存配置" : "创建并框选章节";
    q("#tc-run").innerHTML = (a ? "保存并执行" : "创建并执行") + '<i class="tc-ci">▶</i>';
    renderSkillGroups();
    renderMaterialChips();
    q("#tc-cfg").classList.add("show");
    q("#tc-mask").classList.add("show");
    setTimeout(() => q("#tc-nm").focus(), 60);
    loadAssets();
  }
  function closeCfg() {
    q("#tc-cfg")?.classList.remove("show");
    q("#tc-mask")?.classList.remove("show");
    closeNpf();
  }

  // 表单 → model。返回 agent（新建时会自动分配 1 章，之后再拖边缘扩缩）
  function commitCfg() {
    const st = {
      nm: q("#tc-nm").value.trim(),
      profileId: SEL.md ? SEL.md.get() : (form.profileId || ""),
      useGlobal: form.mode !== "custom",
      prompt: form.mode === "custom" ? q("#tc-pr").value.trim() : "",
      skills: Array.from(form.skills),
      inheritSkills: q("#tc-inherit").checked,
      materialIds: Array.from(form.mats),
      color: formColor,
    };
    if (editingId) {
      const a = byId(editingId);
      if (!a) return null;
      a.nm = st.nm || a.nm;
      a.profileId = st.profileId;
      a.useGlobal = st.useGlobal;
      a.prompt = st.prompt;
      a.skills = st.skills;
      a.inheritSkills = st.inheritSkills;
      a.materialIds = st.materialIds;
      a.color = st.color;
      return a;
    }
    let s = -1;
    for (let i = 0; i < model.chapters.length; i++) { if (!model.owner[i]) { s = i; break; } }
    if (s < 0) {
      // 章节都被占满了：从章节最多的那个 Agent 手里切一章出来
      const blocks = groups().filter((x) => x.o);
      const big = blocks.slice().sort((x, y) => y.ch.length - x.ch.length)[0];
      if (!big || big.ch.length < 2) { toast("章节太少，无法再切分给新 Agent"); return null; }
      s = big.ch[big.ch.length - 1];
      model.owner[s] = null;
    }
    const a = addAgent(st);
    model.owner[s] = a.id;
    return a;
  }

  function toggleSkill(e) {
    const b = e.target.closest("[data-sk]");
    if (!b) return;
    const name = b.dataset.sk;
    if (isRequiredSkill(name)) { toast(`${name} 是必选 Skill，不能取消`); return; }
    if (form.skills.has(name)) form.skills.delete(name); else form.skills.add(name);
    renderSkillGroups();
  }
  function toggleMaterial(e) {
    if (e.target.closest("[data-mat-all]")) {
      const total = (state.projectMaterials || []).length;
      if (form.mats.size >= total) form.mats.clear();
      else (state.projectMaterials || []).forEach((m) => form.mats.add(String(m.id)));
      renderMaterialChips();
      return;
    }
    const b = e.target.closest("[data-mat]");
    if (!b) return;
    const id = b.dataset.mat;
    if (form.mats.has(id)) form.mats.delete(id); else form.mats.add(id);
    renderMaterialChips();
  }

  /* ------------------------------ 统计 ------------------------------ */
  function refreshStats() {
    let ok = 0, run = 0, fail = 0, wait = 0;
    model.chapters.forEach((chap, i) => {
      if (!model.owner[i]) return;
      chap.nodes.forEach((n) => {
        const s = model.status[nodeId(n)] || "wait";
        if (s === "ok") ok++; else if (s === "run") run++; else if (s === "fail") fail++; else wait++;
      });
    });
    q("#tc-lg-ok").textContent = `已完成 ${ok}`;
    q("#tc-lg-run").textContent = `生成中 ${run}`;
    q("#tc-lg-fail").textContent = `失败 ${fail}`;
    q("#tc-lg-wait").textContent = `排队 ${wait}`;
    const act = model.agents.filter((a) => grpOf(a)).length;
    q("#tc-sub").textContent = gen.playing
      ? `${act} 个 Agent 正在并行生成，已完成 ${ok} / ${totalNodes()} 个节点`
      : `${act} 个 Agent，共 ${totalNodes()} 个节点待生成`;
  }
  function refreshCard(a) {
    const g = grpOf(a);
    const el = root.querySelector(`.tc-agent[data-id="${a.id}"]`);
    if (!g || !el) return;
    const n = nodeTotalOf(g.ch);
    const d = g.ch.reduce((s, i) => s + model.chapters[i].nodes.filter((x) => model.status[nodeId(x)] === "ok").length, 0);
    el.querySelector(".tc-nt").textContent = n + " 个节点";
    el.querySelector(".tc-pb i").style.width = (n ? (d / n) * 100 : 0) + "%";
    el.querySelector(".tc-cnt").textContent = `${d}/${n} 完成`;
    if (dir !== "v" && staleCardWidth(a, el)) el.style.width = cardWidth(a) + "px";
  }
  function staleCardWidth(a, el) { return Math.abs(parseFloat(el.style.width) - cardWidth(a)) > 1; }

  function setStatus(nodeKey, st) {
    if (model.status[nodeKey] === st) return;
    model.status[nodeKey] = st;
    const el = root.querySelector(`.tc-sec[data-nid="${CSS.escape(nodeKey)}"]`);
    if (el && !el.closest(".free")) {
      el.className = "tc-sec " + st;
      const em = el.querySelector("em");
      if (em) em.textContent = LB[st];
    }
  }

  /* ------------------------------ 生成 ------------------------------ */
  // 公共默认：全局 Prompt + 分析时勾选的 Skill + 框架级素材；Agent 里显式选过的会覆盖它们
  function commonPayload() {
    return {
      generation_prompt: model.globalPrompt || "",
      skills: analysisSkills(),
      inherit_project_skills: true,
      material_ids: defaultMaterialIds(),
    };
  }

  function buildGroups(list) {
    return (list || model.agents).filter((a) => grpOf(a)).map((a) => {
      const g = grpOf(a);
      return {
        profile_id: a.profileId || null,
        // 复用全局时留空，后端回落到 common.generation_prompt
        generation_prompt: a.useGlobal === false ? (a.prompt || "") : "",
        skills: Array.isArray(a.skills) ? a.skills.slice() : [],
        inherit_project_skills: a.inheritSkills !== false,
        material_ids: Array.isArray(a.materialIds) ? a.materialIds.slice() : [],
        node_keys: g.ch.flatMap((ci) => model.chapters[ci].nodes.map((n) => nodeId(n))),
      };
    });
  }

  // onlyId 传了就只跑这一个 Agent（卡片上的 ▶ / 面板里的「保存并执行」）
  async function startGenerate(onlyId) {
    if (gen.playing) {
      if (onlyId) { toast("正在生成中，先等这批跑完或点「取消批次」"); return; }
      await cancelGenerate();
      return;
    }
    const targets = model.agents.filter((a) => grpOf(a) && (!onlyId || a.id === onlyId));
    const groupsPayload = buildGroups(targets);
    if (!groupsPayload.length) {
      toast(onlyId ? "这个 Agent 还没框选章节，先拖边缘框住章节" : "先新增一个 Agent 再开始生成");
      return;
    }
    if (!model.projectId) { toast("缺少项目信息，请重新打开画布"); return; }

    // 只重置本次要跑的范围，其他 Agent 的完成状态保留
    targets.flatMap((a) => grpOf(a).ch).forEach((i) => {
      model.chapters[i].nodes.forEach((n) => { model.status[nodeId(n)] = "wait"; });
    });
    render();

    gen.playing = true;
    const btn = q("#tc-go");
    btn.classList.add("running");
    btn.innerHTML = '取消批次<i class="tc-ci">■</i>';
    refreshStats();

    const body = {
      nodes: model.nodes,
      common: commonPayload(),
      groups: groupsPayload,
      workers: groupsPayload.length,
    };
    try {
      const queued = await request(`/api/projects/${encodeURIComponent(model.projectId)}/topics/batch-generate-parallel-async`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      gen.jobId = queued.job_id;
      const job = await pollJob(queued.job_id, {
        progress: (current) => {
          const p = current?.progress;
          if (!p) return;
          (p.running_keys || []).forEach((k) => setStatus(k, "run"));
          (p.completed_keys || []).forEach((k) => setStatus(k, "ok"));
          (p.failed_keys || []).forEach((k) => setStatus(k, "fail"));
          model.agents.forEach((a) => refreshCard(a));
          refreshStats();
        },
      }, "topic-canvas");
      if (job?.status === "success" && job.result) {
        (job.result.items || []).forEach((item) => {
          const k = item.framework_node_key || item.title;
          setStatus(k, item.status === "failed" ? "fail" : "ok");
        });
        model.agents.forEach((a) => refreshCard(a));
        const r = job.result;
        toast(`生成完成：成功 ${r.succeeded}/${r.total}${r.failed ? `，失败 ${r.failed}` : ""}`);
      } else if (job?.status === "cancelled") {
        toast("已取消，已完成的结果已保存");
      }
    } catch (error) {
      toast(`生成失败：${error.message}`);
    } finally {
      gen.playing = false;
      gen.jobId = null;
      const b = q("#tc-go");
      b.classList.remove("running");
      b.innerHTML = '重新生成<i class="tc-ci">↻</i>';
      refreshStats();
    }
  }

  async function cancelGenerate() {
    if (!gen.jobId) return;
    try { await request(`/api/jobs/${encodeURIComponent(gen.jobId)}/cancel`, { method: "POST", body: "{}" }); } catch (err) { /* ignore */ }
    if (state.jobPollResolvers?.["topic-canvas"]) state.jobPollResolvers["topic-canvas"]();
  }

  /* ------------------------------ 方向切换 ------------------------------ */
  function setDir(next, silent) {
    dir = next === "v" ? "v" : "h";
    root.classList.toggle("is-v", dir === "v");
    qa("#tc-dir button").forEach((b) => b.classList.toggle("on", b.dataset.dir === dir));
    render();
    topLeft(scale);
    if (!silent) toast(dir === "v" ? "已切换为纵向树：章节左右平铺，节点向下展开" : "已切换为横向树：章节纵向排列，节点向右展开");
  }

  /* ------------------------------ 外壳事件 ------------------------------ */
  function bindShell() {
    q("#tc-close").onclick = close;
    qa(".tc-tab[data-jump]").forEach((b) => {
      b.onclick = () => {
        const view = b.dataset.jump;
        close();
        if (typeof showView === "function") showView(view);
      };
    });
    q("#tc-add").onclick = () => openCfg(null);
    q("#tc-archbtn").onclick = () => {
      close();
      if (typeof showView === "function") showView("settings-view");
      setTimeout(() => { document.getElementById("profile-list")?.scrollIntoView({ block: "center", behavior: "smooth" }); }, 260);
    };
    q("#tc-cx").onclick = closeCfg;
    q("#tc-cancel").onclick = closeCfg;
    q("#tc-fit").onclick = fit;
    q("#tc-zoom").oninput = (e) => setS(e.target.value / 100);
    q("#tc-go").onclick = startGenerate;
    qa("#tc-dir button").forEach((b) => { b.onclick = () => { if (b.dataset.dir !== dir) setDir(b.dataset.dir); }; });

    // 滚轮 / 触控板捏合缩放（以指针位置为锚点）
    const vp = q(".tc-vp");
    vp.addEventListener("wheel", (e) => {
      if (!root.classList.contains("is-open")) return;
      e.preventDefault();
      const k = e.ctrlKey ? 0.01 : 0.0018;
      setS(scale * Math.exp(-e.deltaY * k), e.clientX, e.clientY);
    }, { passive: false });

    // 空白处拖动平移
    vp.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest(".tc-agent,.tc-chap,.tc-sec,.tc-hit,.tc-cfg,.tc-legend,.tc-empty,.tc-toast")) return;
      e.preventDefault();
      const ox = e.clientX - TX, oy = e.clientY - TY;
      vp.classList.add("panning");
      const move = (ev) => { TX = ev.clientX - ox; TY = ev.clientY - oy; applyView(); };
      const up = () => {
        vp.classList.remove("panning");
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
    vp.addEventListener("dblclick", (e) => {
      if (e.target.closest(".tc-agent,.tc-chap,.tc-sec,.tc-legend,.tc-cfg")) return;
      fit();
    });

    qa("#tc-swrow button").forEach((b) => { b.onclick = () => setColor(COLORS[Number(b.dataset.c) - 1]); });
    q("#tc-cc").oninput = (e) => setColor(e.target.value);

    // —— 复用已有 Agent：模型档案 + Prompt + Skill + 素材一起带过来（由 applyReuse 处理）
    // —— AI 模型：子 Agent 卡片式新建/编辑
    q("#tc-newprofile").onclick = () => {
      if (q("#tc-npf").classList.contains("show")) closeNpf(); else openNpf();
    };
    q("#np-cancel").onclick = closeNpf;
    q("#np-x").onclick = closeNpf;
    q("#tc-acmask").onclick = closeNpf;
    q("#np-save").onclick = saveNewProfile;
    qa("#np-prov button").forEach((b) => { b.onclick = () => setProv(b.dataset.p); });
    qa("[data-pre]").forEach((b) => { b.onclick = () => applyPreset(b.dataset.pre); });

    // 保存后显示在下方的子 Agent 卡片：选用 / 编辑 / 测试 / 删除
    q("#tc-plist").onclick = async (e) => {
      const card = e.target.closest("[data-pid]");
      if (!card) return;
      const pid = card.dataset.pid;
      const actBtn = e.target.closest("[data-act]");
      const act = actBtn ? actBtn.dataset.act : "use";
      const prof = (state.agentProfiles || []).find((x) => x.id === pid);
      if (act === "use") {
        if (SEL.md) SEL.md.set(pid);
        form.profileId = pid;
        syncModelNote();
        renderProfileCards();
        toast(`本 Agent 将使用「${prof?.name || pid}」生成`);
        return;
      }
      if (act === "edit") {
        if (prof) openNpf(prof);
        return;
      }
      if (act === "test") {
        actBtn.disabled = true;
        actBtn.textContent = "测试中";
        try {
          const r = await request(`/api/agent-profiles/${encodeURIComponent(pid)}/test`, { method: "POST", body: "{}" });
          toast(`「${prof?.name || pid}」连接成功：${r.endpoint}`);
        } catch (error) {
          toast(`连接失败：${error.message}`);
        } finally {
          actBtn.disabled = false;
          actBtn.textContent = "测试";
        }
        return;
      }
      if (act === "del") {
        if (!window.confirm(`删除子 Agent「${prof?.name || pid}」？它的配置和 Key 会一起移除。`)) return;
        try {
          await request(`/api/agent-profiles/${encodeURIComponent(pid)}/delete`, { method: "POST", body: "{}" });
        } catch (error) {
          toast(`删除失败：${error.message}`);
          return;
        }
        if (typeof loadAgentProfiles === "function") await loadAgentProfiles();
        else {
          const data = await request("/api/agent-profiles");
          state.agentProfiles = data.profiles || [];
        }
        const keep = form.profileId === pid ? "" : form.profileId;
        refreshModelSelect(keep);
        toast(`已删除「${prof?.name || pid}」`);
      }
    };

    // 点空白处收起所有手写下拉
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".tc-sel")) qa(".tc-sel.open").forEach((n) => n.classList.remove("open"));
    });

    // 拖右下角调整面板大小（居中面板：单边拖动 → 宽高按 2 倍变化）
    const cfgEl = q("#tc-cfg");
    try {
      const saved = JSON.parse(localStorage.getItem("tcCfgSize") || "null");
      if (saved && saved.w > 0 && saved.h > 0) {
        cfgEl.style.width = saved.w + "px";
        cfgEl.style.height = saved.h + "px";
      }
    } catch (err) { /* ignore */ }
    q("#tc-rsz").addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const box = cfgEl.getBoundingClientRect();
      const area = q(".tc-main").getBoundingClientRect();
      const maxW = area.width - 28, maxH = area.height - 28;
      const sx = e.clientX, sy = e.clientY, w0 = box.width, h0 = box.height;
      cfgEl.classList.add("resizing");
      const move = (ev) => {
        const w = Math.min(maxW, Math.max(520, w0 + (ev.clientX - sx) * 2));
        const h = Math.min(maxH, Math.max(420, h0 + (ev.clientY - sy) * 2));
        cfgEl.style.width = w + "px";
        cfgEl.style.height = h + "px";
      };
      const up = () => {
        cfgEl.classList.remove("resizing");
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        try { localStorage.setItem("tcCfgSize", JSON.stringify({ w: cfgEl.offsetWidth, h: cfgEl.offsetHeight })); } catch (err) { /* ignore */ }
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });

    // —— Prompt：复用全局 / 自定义
    qa("#tc-pm button").forEach((b) => { b.onclick = () => setPromptMode(b.dataset.pm); });

    // —— Skill / 素材选择
    q("#tc-sk-q").oninput = () => renderSkillGroups();
    q("#tc-inherit").onchange = (e) => { form.inherit = e.target.checked; };
    q("#tc-sk-analysis").onclick = toggleSkill;
    q("#tc-sk-library").onclick = toggleSkill;
    q("#tc-mats").onclick = toggleMaterial;

    // —— 全局 Prompt 弹层
    const openGp = () => {
      q("#tc-gpt").value = model.globalPrompt || "";
      q("#tc-gpn").textContent = (model.globalPrompt || "").length + " 字";
      q("#tc-gp").classList.add("show");
      setTimeout(() => q("#tc-gpt").focus(), 60);
    };
    const closeGp = () => q("#tc-gp").classList.remove("show");
    q("#tc-gpbtn").onclick = openGp;
    q("#tc-gpx").onclick = closeGp;
    q("#tc-gpcancel").onclick = closeGp;
    q("#tc-gpt").oninput = (e) => { q("#tc-gpn").textContent = e.target.value.trim().length + " 字"; };
    q("#tc-gpsave").onclick = () => {
      model.globalPrompt = q("#tc-gpt").value.trim();
      syncGlobalPrompt();
      closeGp();
      toast(model.globalPrompt ? "全局 Prompt 已保存，复用它生成" : "已清空全局 Prompt");
    };

    // —— 保存 / 保存并执行
    q("#tc-create").onclick = () => {
      const isNew = !editingId;
      const a = commitCfg();
      if (!a) return;
      closeCfg(); render();
      const g = grpOf(a);
      toast(isNew
        ? `已创建 ${a.nm}，默认管辖${g ? rangeLabel(g.ch) : "第 1 章"}；拖边缘可扩缩范围`
        : `已更新 ${a.nm}`);
    };
    q("#tc-run").onclick = () => {
      const isNew = !editingId;
      const a = commitCfg();
      if (!a) return;
      closeCfg(); render();
      toast(isNew ? `已创建 ${a.nm}，开始生成…` : `开始生成 ${a.nm} 的章节…`);
      startGenerate(a.id);
    };
    document.addEventListener("keydown", (e) => {
      if (!root.classList.contains("is-open")) return;
      if (e.key === "Escape") {
        if (q(".tc-sel.open")) qa(".tc-sel.open").forEach((n) => n.classList.remove("open"));
        else if (q("#tc-gp").classList.contains("show")) closeGp();
        else if (q("#tc-npf").classList.contains("show")) closeNpf();
        else if (q("#tc-cfg").classList.contains("show")) closeCfg();
        else close();
        return;
      }
      if (e.target.closest("input,textarea,select")) return;
      if (e.key === "+" || e.key === "=") { e.preventDefault(); setS(scale * 1.15); }
      else if (e.key === "-" || e.key === "_") { e.preventDefault(); setS(scale / 1.15); }
      else if (e.key === "0") { e.preventDefault(); fit(); }
      else if (e.key === "1") { e.preventDefault(); topLeft(1); }
    });
  }

  /* ------------------------------ 开关 ------------------------------ */
  function open(opts) {
    ensureRoot();
    const previousProject = model?.projectId;
    model = buildModel(opts);
    if (previousProject !== model.projectId) {
      gen.playing = false;
      gen.jobId = null;
    }
    q("#tc-proj-name").textContent = model.projectName;
    q("#tc-go").classList.remove("running");
    q("#tc-go").innerHTML = '批量生成 Topic<i class="tc-ci">▶</i>';
    closeCfg();
    q("#tc-gp")?.classList.remove("show");
    syncGlobalPrompt();
    defaultAgents();
    root.classList.add("is-open");
    document.body.style.overflow = "hidden";
    setDir(dir, true);
    topLeft(1);
    q("#tc-empty").classList.toggle("show", !model.nodes.length);
    refreshStats();
  }

  function close() {
    if (!root) return;
    root.classList.remove("is-open");
    document.body.style.overflow = "";
  }

  window.openTopicCanvas = open;
  window.closeTopicCanvas = close;
})();
