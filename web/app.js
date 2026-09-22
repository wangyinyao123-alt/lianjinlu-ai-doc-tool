const state = {
  projects: [],
  projectModeFilter: "all",
  selectedProject: null,
  selectedAsset: null,
  coverSelection: null,
  currentTopic: null,
  projectTopics: [],
  skills: [],
  currentSkillId: null,
  skillAttachments: [],
  outlineItems: [],
  projectMaterials: [],
  currentAnalysis: null,
  analysisVersions: [],
  currentFramework: null,
  frameworkNodes: [],
  frameworkView: "map",
  frameworkPanel: "none",
  frameworkLayout: "mindmap",
  frameworkDebounce: null,
  frameworkPan: { x: 0, y: 0, scale: 1 },
  frameworkWorld: null,
  frameworkNeedsFit: true,
  frameworkPointers: new Map(),
  frameworkGesture: null,
  frameworkDrag: null,
  frameworkMapResizeObserver: null,
  frameworkClickTimer: null,
  frameworkPreviewNodeId: null,
  frameworkTopicNode: null,
  frameworkTopic: null,
  frameworkTopicOpenPromise: null,
  frameworkTopicOpenToken: 0,
  frameworkTopicLoading: false,
  topicInheritProjectSkills: true,
  topicDraftSkills: null,
  frameworkTopicDraftSkills: null,
  frameworkShowSummaries: false,
  frameworkPresentationStep: 0,
  frameworkPresentationOpen: false,
  frameworkPresentationPan: { x: 0, y: 0, scale: 1 },
  frameworkPresentationDrag: null,
  frameworkPresentationWasDragged: false,
  frameworkTheme: "poster",
};

const FRAMEWORK_THEME_PALETTES = {
  poster: {
    canvas: "#efe9d9",
    canvasGrid: "rgba(15,15,15,.09)",
    root: { bg: "#0f0f0f", fg: "#efe9d9", line: "#0f0f0f" },
    branches: [
      { bg: "#1f8a4c", fg: "#efe9d9", line: "#1f8a4c", light: "#c8edd9", lighter: "#e2f5ec" },
      { bg: "#f06ca8", fg: "#0f0f0f", line: "#d14e8b", light: "#fad0e5", lighter: "#fde8f2" },
      { bg: "#e85a1f", fg: "#efe9d9", line: "#e85a1f", light: "#f8d0bc", lighter: "#fce8da" },
      { bg: "#f5c518", fg: "#0f0f0f", line: "#c9a000", light: "#fdf0a0", lighter: "#fef8d0" },
    ],
  },
  pastel: {
    canvas: "#f7fbef",
    canvasGrid: "rgba(64,104,76,.10)",
    root: { bg: "#2f4b43", fg: "#f7fbef", line: "#2f4b43" },
    branches: [
      { bg: "#4d9b7c", fg: "#ffffff", line: "#3d8065", light: "#d6eee2", lighter: "#edf8f1" },
      { bg: "#d6768a", fg: "#ffffff", line: "#b85e72", light: "#f5dce2", lighter: "#fbedf0" },
      { bg: "#df9360", fg: "#ffffff", line: "#bf7546", light: "#f7e4d3", lighter: "#fcf3e9" },
      { bg: "#d4a83f", fg: "#3a3020", line: "#b78e29", light: "#f6ebc5", lighter: "#fcf8e8" },
      { bg: "#7186c9", fg: "#ffffff", line: "#596fae", light: "#dde4f7", lighter: "#eff3fc" },
      { bg: "#9c78b5", fg: "#ffffff", line: "#805d99", light: "#e9ddf1", lighter: "#f5eff8" },
    ],
  },
};

function frameworkThemePalette(theme = state.frameworkTheme, index = 0) {
  const palette = FRAMEWORK_THEME_PALETTES[theme] || FRAMEWORK_THEME_PALETTES.poster;
  return palette.branches[index % palette.branches.length];
}

const $ = (selector) => document.querySelector(selector);

let editorialAssets = [];

const editorialAssetUrl = (file) => `/static/assets/editorial/${encodeURIComponent(file)}`;

function assetUrl(asset) {
  return asset?.url || editorialAssetUrl(asset?.file || "");
}

function showMessage(selector, message, kind = "") {
  const node = $(selector);
  node.textContent = message;
  node.className = `inline-message ${kind}`.trim();
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function selectEditorialAsset(asset) {
  if (!asset) return;
  state.selectedAsset = asset;
  const hero = $("#hero-art");
  const heroLabel = $("#hero-art-label");
  if (hero) {
    hero.src = assetUrl(asset);
    hero.alt = `${asset.label} 编辑素材卡片`;
  }
  if (heroLabel) heroLabel.textContent = asset.label;
  document.querySelectorAll("[data-asset-file]").forEach((node) => {
    node.classList.toggle("is-selected", node.dataset.assetFile === asset.file);
  });
}

function renderGallery() {
  const gallery = $("#material-gallery");
  if (!gallery) return;
  if (!editorialAssets.length) {
    gallery.innerHTML = `<div class="empty-state material-empty"><div><div class="empty-icon">＋</div><p>素材墙为空</p><p>请将图片放入 web/assets/editorial 文件夹。</p></div></div>`;
    return;
  }
  gallery.innerHTML = editorialAssets.map((asset) => `
    <button class="material-card" type="button" data-asset-file="${escapeHtml(asset.file)}" aria-label="查看 ${escapeHtml(asset.label)} 素材">
      <img src="${escapeHtml(assetUrl(asset))}" alt="${escapeHtml(asset.label)} 编辑素材卡片" loading="lazy" />
      <span class="material-caption"><b>${escapeHtml(asset.label)}</b><span>${escapeHtml(asset.note)}</span></span>
    </button>
  `).join("");
  gallery.querySelectorAll("[data-asset-file]").forEach((node) => {
    node.addEventListener("click", () => {
      const asset = editorialAssets.find((item) => item.file === node.dataset.assetFile);
      if (asset) selectEditorialAsset(asset);
    });
    node.querySelector("img").addEventListener("error", () => {
      node.classList.add("is-broken");
    });
  });
  selectEditorialAsset(state.selectedAsset || editorialAssets[0]);
}

async function loadEditorialAssets() {
  const data = await request("/api/assets");
  editorialAssets = data.assets || [];
  if (!editorialAssets.some((asset) => asset.file === state.selectedAsset?.file)) {
    state.selectedAsset = editorialAssets[0] || null;
  }
  renderGallery();
}

function resetCoverSelection() {
  state.coverSelection = editorialAssets[0] ? { type: "asset", file: editorialAssets[0].file } : null;
  const input = $("#project-cover-file");
  if (input) input.value = "";
  renderCoverPicker();
}

function selectCoverAsset(file) {
  const asset = editorialAssets.find((item) => item.file === file);
  if (!asset) return;
  state.coverSelection = { type: "asset", file: asset.file };
  const input = $("#project-cover-file");
  if (input) input.value = "";
  renderCoverPicker();
}

function renderCoverPicker() {
  const gallery = $("#project-cover-gallery");
  const preview = $("#project-cover-preview");
  const fileName = $("#project-cover-file-name");
  if (!gallery || !preview || !fileName) return;
  const selection = state.coverSelection;
  if (selection?.type === "upload") {
    preview.src = selection.data_url;
    preview.alt = `本地上传封面：${selection.name}`;
    fileName.textContent = `已上传：${selection.name}`;
  } else {
    const asset = editorialAssets.find((item) => item.file === selection?.file) || editorialAssets[0];
    if (asset) {
      preview.src = assetUrl(asset);
      preview.alt = `项目封面：${asset.label}`;
      fileName.textContent = `当前封面：${asset.label}`;
    } else {
      preview.removeAttribute("src");
      preview.alt = "尚未选择项目封面";
      fileName.textContent = "暂无素材，请先放入素材墙或上传图片";
    }
  }
  preview.onclick = selection ? () => openCoverPreview(preview.src, fileName.textContent) : null;
  preview.classList.toggle("is-zoomable", Boolean(selection));
  gallery.innerHTML = editorialAssets.length
    ? editorialAssets.map((asset) => `
      <button class="cover-option ${selection?.type === "asset" && selection.file === asset.file ? "is-selected" : ""}" type="button" data-cover-file="${escapeHtml(asset.file)}" aria-label="使用 ${escapeHtml(asset.label)} 作为项目封面">
        <img src="${escapeHtml(assetUrl(asset))}" alt="${escapeHtml(asset.label)}" loading="lazy" />
        <span>${escapeHtml(asset.label)}</span>
      </button>
    `).join("")
    : `<p class="cover-empty">素材墙暂无图片</p>`;
  gallery.querySelectorAll("[data-cover-file]").forEach((node) => {
    node.addEventListener("click", () => selectCoverAsset(node.dataset.coverFile));
    node.querySelector("img")?.addEventListener("click", (event) => {
      event.stopPropagation();
      const asset = editorialAssets.find((item) => item.file === node.dataset.coverFile);
      if (asset) openCoverPreview(assetUrl(asset), asset.label);
    });
  });
}

function openCoverPreview(src, label = "") {
  const dialog = $("#cover-preview-dialog");
  const image = $("#cover-preview-large");
  const caption = $("#cover-preview-large-label");
  if (!dialog || !image || !src) return;
  image.src = src;
  image.alt = label || "封面放大预览";
  if (caption) caption.textContent = label || "封面预览";
  dialog.showModal();
}

function handleCoverUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    showMessage("#project-message", "项目封面必须是图片文件。", "error");
    event.target.value = "";
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    showMessage("#project-message", "项目封面大小不能超过 8 MB。", "error");
    event.target.value = "";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    state.coverSelection = { type: "upload", name: file.name, data_url: reader.result };
    renderCoverPicker();
    showMessage("#project-message", "本地封面已选择，提交项目后保存到本地。", "success");
  };
  reader.onerror = () => showMessage("#project-message", "读取封面失败，请重新选择图片。", "error");
  reader.readAsDataURL(file);
}

function renderProjects() {
  const list = $("#project-list");
  const filter = state.projectModeFilter || "all";
  const projects = filter === "all" ? state.projects : state.projects.filter((project) => project.mode === filter);
  $("#project-count").textContent = projects.length;
  if (!projects.length) {
    list.innerHTML = `<div class="empty-state"><div><div class="empty-icon">＋</div><p>${filter === "all" ? "还没有项目" : `${({new:"全新开发",update:"版本更新",optimize:"Topic 优化"}[filter] || "该模式")}暂无项目`}</p><p>先创建一个文档项目。</p></div></div>`;
    return;
  }
  list.innerHTML = projects.map((project) => `
    <button class="project-card ${state.selectedProject?.id === project.id ? "is-selected" : ""}" data-project-id="${project.id}">
      <div class="project-card-body">
        <div class="project-card-copy">
          <h4>${escapeHtml(project.name)}</h4>
          <div class="project-meta"><span>${escapeHtml(project.product || "未填写产品")}</span><span>${escapeHtml(project.version || "未填写版本")}</span></div>
          <div class="project-stage">${escapeHtml(project.mode_label || "全新开发")} · ${escapeHtml(project.stage)} · ${formatDate(project.updated_at)}</div>
          <div class="project-stage">语料库 ${project.corpus?.project_count || 0} 个项目 · ${project.corpus?.topic_count || 0} 个 Topic</div>
        </div>
        ${project.cover_url ? `<img class="project-cover-thumb" src="${escapeHtml(project.cover_url)}" alt="${escapeHtml(project.name)} 项目封面" />` : `<span class="project-cover-thumb cover-placeholder"><img class="cover-placeholder-image" src="/static/assets/alchemy-furnace-pixel.png" alt="" /></span>`}
      </div>
    </button>
  `).join("");
  list.querySelectorAll("[data-project-id]").forEach((node) => {
    node.addEventListener("click", () => selectProject(node.dataset.projectId));
  });
}

function renderProjectCreationOptions() {
  const base = $("#project-base-project");
  const references = $("#project-reference-projects");
  const projects = state.projects || [];
  if (base) {
    const current = base.value;
    base.innerHTML = `<option value="">不选择基线项目</option>${projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}${project.version ? ` · ${escapeHtml(project.version)}` : ""}</option>`).join("")}`;
    if (projects.some((project) => project.id === current)) base.value = current;
  }
  if (references) {
    renderReferenceProjectTree(references, checkedReferenceProjectIds(references));
  }
}

const PROJECT_MODE_LABELS = { new: "全新开发", update: "版本更新", optimize: "Topic 优化" };
const PROJECT_MODE_ORDER = ["new", "update", "optimize"];

function checkedReferenceProjectIds(containerOrSelector) {
  const container = typeof containerOrSelector === "string" ? $(containerOrSelector) : containerOrSelector;
  return [...(container?.querySelectorAll("input[data-reference-project-id]:checked") || [])].map((input) => input.dataset.referenceProjectId);
}

function renderReferenceProjectTree(container, selectedIds = [], excludeProjectId = "") {
  if (!container) return;
  const selected = new Set((selectedIds || []).map((id) => String(id)));
  const projects = (state.projects || []).filter((project) => project.id !== excludeProjectId);
  if (!projects.length) {
    container.innerHTML = `<div class="reference-tree-empty">暂无可引用的其他项目。</div>`;
    return;
  }
  container.innerHTML = PROJECT_MODE_ORDER.map((mode) => {
    const items = projects.filter((project) => (project.mode || "new") === mode);
    const rows = items.length
      ? items.map((project) => `<label class="reference-project-check"><input type="checkbox" data-reference-project-id="${escapeHtml(project.id)}" ${selected.has(String(project.id)) ? "checked" : ""} /><span class="reference-project-check-body"><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(project.product || "未填写产品")} · ${escapeHtml(project.version || "未填写版本")} · ${project.topic_count || 0} Topic · ${project.material_count || 0} 份素材 · 最后保存 ${escapeHtml(formatDate(project.updated_at))}</small></span><em>LIVE</em></label>`).join("")
      : `<div class="reference-mode-empty">暂无${PROJECT_MODE_LABELS[mode]}项目</div>`;
    return `<details class="reference-mode-group" open><summary><span><i class="reference-mode-dot mode-${mode}"></i>${PROJECT_MODE_LABELS[mode]}</span><b>${items.length}</b></summary><div class="reference-mode-items">${rows}</div></details>`;
  }).join("");
}

function toggleProjectModeFields() {
  const mode = $("#project-mode")?.value || "new";
  $("#project-base-fields")?.classList.toggle("is-hidden", mode === "new");
  const hints = {
    new: "从需求材料开始搭建新的文档框架。",
    update: "复制上版本框架和 Topic 作为基线，再结合新材料分析变化。",
    optimize: "复制目标项目的 Topic，专注优化语言、结构和术语表达。",
  };
  if ($("#project-mode-hint")) $("#project-mode-hint").textContent = hints[mode] || hints.new;
}

function renderReferenceProjectOptions() {
  const container = $("#detail-reference-projects");
  if (!container || !state.selectedProject) return;
  const referenceIds = new Set(state.selectedProject.reference_project_ids || []);
  renderReferenceProjectTree(container, [...referenceIds], state.selectedProject.id);
}

function renderProjectSkillOptions() {
  const container = $("#project-skill-options");
  if (!container) return;
  if (!state.skills.length) {
    container.innerHTML = `<div class="field-hint">暂无可用 Skill，请先在“配置 Skill”中添加。</div>`;
    return;
  }
  const selected = new Set(state.selectedProject?.skills || ["HIK Writing Skill", "HIK DITA Rule"]);
  container.innerHTML = state.skills.map((skill) => {
    const checked = skill.required || selected.has(skill.name);
    const disabled = skill.required || !skill.enabled;
    return `<label class="skill-choice ${disabled && !skill.required ? "is-disabled" : ""}"><input type="checkbox" data-project-skill-name="${escapeHtml(skill.name)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} /> <span><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description || (skill.required ? "必选规范 Skill" : "项目级生成约束"))}</small></span>${skill.required ? "<em>必选</em>" : skill.enabled ? "" : "<em>已停用</em>"}</label>`;
  }).join("");
}

async function saveProjectSkills() {
  if (!state.selectedProject) return;
  const selected = [...document.querySelectorAll("#project-skill-options input[data-project-skill-name]:checked")].map((node) => node.dataset.projectSkillName);
  try {
    const project = await request(`/api/projects/${encodeURIComponent(state.selectedProject.id)}`, {
      method: "PUT",
      body: JSON.stringify({ skills: ["HIK Writing Skill", ...selected.filter((name) => name !== "HIK Writing Skill")] }),
    });
    state.selectedProject = project;
    await loadProjects();
    renderProjectSkillOptions();
    renderSkillOptions("#analysis-skill-options");
    renderSkillOptions();
    showMessage("#project-skill-message", "项目级 Skill 已保存；继承中的 Topic 会自动使用最新配置。", "success");
  } catch (error) {
    showMessage("#project-skill-message", error.message, "error");
  }
}

async function saveReferenceProjects() {
  if (!state.selectedProject) return;
  const ids = checkedReferenceProjectIds("#detail-reference-projects");
  try {
    const project = await request(`/api/projects/${encodeURIComponent(state.selectedProject.id)}`, { method: "PUT", body: JSON.stringify({ reference_project_ids: ids }) });
    state.selectedProject = project;
    await loadProjects();
    showMessage("#corpus-message", "参考语料库已保存，后续生成会读取最新内容。", "success");
  } catch (error) {
    showMessage("#corpus-message", error.message, "error");
  }
}

function renderProjectDetail() {
  const panel = $("#project-detail");
  const project = state.selectedProject;
  if (!project) {
    panel.innerHTML = `<div class="empty-detail"><div><div class="empty-icon">✦</div><h3>选择一个项目</h3><p>项目数据会保存在本地 data/projects 目录中。</p></div></div>`;
    return;
  }
  panel.innerHTML = `
    <div class="detail-header">
      <div class="detail-copy">
        <p class="section-kicker">PROJECT DETAIL</p>
        <h2>${escapeHtml(project.name)}</h2>
        <div class="detail-description">${escapeHtml(project.description || "暂无项目备注")}</div>
      </div>
      <div class="detail-cover-wrap">
        ${project.cover_url ? `<img class="detail-cover" src="${escapeHtml(project.cover_url)}" alt="${escapeHtml(project.name)} 项目封面" />` : `<div class="detail-cover cover-placeholder"><img class="cover-placeholder-image" src="/static/assets/alchemy-furnace-pixel.png" alt="" /></div>`}
        <span class="count-badge">${escapeHtml(project.mode_label || "全新开发")} · ${escapeHtml(project.stage)}</span>
      </div>
    </div>
    <div class="detail-facts">
      <div class="fact"><div class="fact-label">产品 / 模块</div><div class="fact-value">${escapeHtml(project.product || "—")}</div></div>
      <div class="fact"><div class="fact-label">版本</div><div class="fact-value">${escapeHtml(project.version || "—")}</div></div>
      <div class="fact"><div class="fact-label">项目模式</div><div class="fact-value">${escapeHtml(project.mode_label || "全新开发")}</div></div>
      <div class="fact"><div class="fact-label">参考语料</div><div class="fact-value">${project.corpus?.project_count || 0} 个项目 / ${project.corpus?.topic_count || 0} 个 Topic</div></div>
    </div>
    <div class="topic-tree-block"><div class="topic-tree-heading"><div><p class="section-kicker">TOPIC TREE / DRAG TO RESTRUCTURE</p><strong>项目 Topic</strong></div><span class="panel-note">仅显示标题</span></div><div id="topic-tree" class="topic-tree"><div class="tree-empty">正在读取 Topic…</div></div><p class="tree-hint">拖动标题调整顺序；向右拖动可设置为下一级。单击标题展开 XML Code。</p></div>
    <div class="detail-tools-grid">
      <section class="detail-tool-panel corpus-manager"><div class="topic-tree-heading"><div><p class="section-kicker">REFERENCE CORPUS / LIVE LINK</p><strong>参考项目语料库</strong></div><span class="panel-note">实时读取最后保存内容</span></div><div class="reference-picker-layout"><div id="detail-reference-projects" class="reference-project-tree" aria-label="参考项目语料库项目列表"></div></div><div class="field-hint corpus-detail-note">按模式勾选；生成时读取项目最新框架、XML 和素材。</div><div class="form-actions"><button type="button" class="secondary-button compact-button" id="save-reference-projects">保存语料库</button></div><div class="inline-message" id="corpus-message" role="status"></div></section>
      <section class="detail-tool-panel project-skill-manager"><div class="topic-tree-heading"><div><p class="section-kicker">PROJECT SKILL ROUTE / INHERITABLE</p><strong>项目级 Skill</strong></div><span class="panel-note">需求分析、框架和批量 Topic 默认使用</span></div><div id="project-skill-options" class="skill-options"><div class="tree-empty">正在读取 Skill…</div></div><div class="form-actions"><button type="button" class="secondary-button compact-button" id="save-project-skills">保存项目 Skill</button></div><div class="inline-message" id="project-skill-message" role="status"></div></section>
    </div>
    <div id="topic-expanded-editor" class="topic-expanded-editor is-hidden"></div>
    <div class="detail-actions"><button type="button" class="primary-button" data-open-analysis="${escapeHtml(project.id)}">进入文档框架</button><span class="detail-skill-note">${escapeHtml((project.skills || ["HIK Writing Skill"]).join(" · "))}</span></div>
  `;
  panel.querySelector("[data-open-analysis]")?.addEventListener("click", () => openAnalysisForProject(project.id));
  renderTopicTree();
  renderReferenceProjectOptions();
  panel.querySelector("#save-reference-projects")?.addEventListener("click", saveReferenceProjects);
  renderProjectSkillOptions();
  panel.querySelector("#save-project-skills")?.addEventListener("click", saveProjectSkills);
  loadProjectTopics(project.id);
}

async function openAnalysisForProject(projectId) {
  await selectProject(projectId);
  showView("analysis-view");
  $("#analysis-project").value = projectId;
  await Promise.all([loadProjectMaterials(projectId), loadProjectAnalysis(projectId), loadProjectFramework(projectId)]);
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

async function loadProjects() {
  const data = await request("/api/projects");
  state.projects = data.projects || [];
  if (state.selectedProject) {
    state.selectedProject = state.projects.find((item) => item.id === state.selectedProject.id) || null;
  }
  renderProjects();
  renderProjectDetail();
  renderProjectCreationOptions();
  renderTopicProjects();
  renderAnalysisProjects();
}

async function loadProjectTopics(projectId) {
  try {
    const data = await request(`/api/projects/${encodeURIComponent(projectId)}/topics`);
    if (state.selectedProject?.id !== projectId) return;
    state.projectTopics = data.topics || [];
    renderTopicTree();
    renderTopicTargetOptions();
  } catch (error) {
    const tree = $("#topic-tree");
    if (tree) tree.innerHTML = `<div class="tree-empty tree-error">${escapeHtml(error.message)}</div>`;
  }
}

function renderTopicTree() {
  const tree = $("#topic-tree");
  if (!tree) return;
  if (!state.projectTopics.length) {
    tree.innerHTML = `<div class="tree-empty">还没有 Topic，先新建一个 Topic。</div>`;
    return;
  }
  let branchIndex = -1;
  tree.innerHTML = state.projectTopics.map((topic) => {
    const level = Math.max(1, Math.min(3, Number(topic.level || topic.heading_level || 1)));
    if (level === 1) branchIndex += 1;
    const branch = Math.max(0, branchIndex) % 4;
    return `
    <button type="button" class="topic-tree-item" draggable="true" data-topic-id="${escapeHtml(topic.id)}" data-level="${level}" data-branch="${branch}">
      <span class="drag-handle" aria-hidden="true">⋮⋮</span><span class="topic-tree-title">${escapeHtml(topic.title)}</span>
    </button>
  `;
  }).join("");
  const nodes = [...tree.querySelectorAll(".topic-tree-item")];
  nodes.forEach((node) => {
    node.addEventListener("click", () => expandTopicXml(state.selectedProject?.id, node.dataset.topicId));
    node.addEventListener("dragstart", (event) => {
      state.draggedTopicId = node.dataset.topicId;
      node.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", state.draggedTopicId);
    });
    node.addEventListener("dragend", () => {
      state.draggedTopicId = null;
      nodes.forEach((item) => item.classList.remove("is-dragging", "is-drop-target"));
    });
    node.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (node.dataset.topicId !== state.draggedTopicId) node.classList.add("is-drop-target");
      event.dataTransfer.dropEffect = "move";
    });
    node.addEventListener("dragleave", () => node.classList.remove("is-drop-target"));
    node.addEventListener("drop", async (event) => {
      event.preventDefault();
      node.classList.remove("is-drop-target");
      if (!state.draggedTopicId || state.draggedTopicId === node.dataset.topicId) return;
      const rect = node.getBoundingClientRect();
      const insertAfter = event.clientY > rect.top + rect.height / 2;
      const targetIndex = state.projectTopics.findIndex((item) => item.id === node.dataset.topicId);
      const dragged = state.projectTopics.find((item) => item.id === state.draggedTopicId);
      if (!dragged || targetIndex < 0) return;
      const next = state.projectTopics.filter((item) => item.id !== dragged.id);
      let insertionIndex = next.findIndex((item) => item.id === node.dataset.topicId);
      if (insertAfter) insertionIndex += 1;
      const dropLevel = Math.max(1, Math.min(3, Math.round((event.clientX - rect.left - 12) / 24) + 1));
      next.splice(insertionIndex, 0, { ...dragged, level: dropLevel, heading_level: dropLevel });
      try {
        const data = await request(`/api/projects/${encodeURIComponent(state.selectedProject.id)}/topics/order`, {
          method: "PUT",
          body: JSON.stringify({ topics: next.map((item, index) => ({ id: item.id, order: index, level: item.id === dragged.id ? dropLevel : item.level || 1 })) }),
        });
        state.projectTopics = data.topics || next;
        renderTopicTree();
      } catch (error) {
        showMessage("#topic-message", error.message, "error");
      }
    });
  });
}

async function selectProject(projectId) {
  state.selectedProject = await request(`/api/projects/${encodeURIComponent(projectId)}`);
  state.projectTopics = [];
  renderProjects();
  renderProjectDetail();
  renderTopicProjects();
  renderAnalysisProjects();
  if (document.querySelector("#analysis-view")?.classList.contains("is-visible")) {
    await Promise.all([loadProjectMaterials(projectId), loadProjectAnalysis(projectId), loadProjectFramework(projectId)]);
  }
  if (document.querySelector("#topic-view")?.classList.contains("is-visible")) {
    await loadProjectMaterials(projectId);
    renderTopicTargetOptions();
    renderTopicMaterialOptions();
  }
}

function showView(viewId) {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === viewId));
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("is-visible", view.id === viewId));
  const labels = { "projects-view": "项目工作台", "analysis-view": "需求分析", "topic-view": "新建 Topic", "skills-view": "配置 Skill", "settings-view": "AI 服务配置" };
  $("#breadcrumb-view").textContent = labels[viewId] || "项目工作台";
  if (viewId === "analysis-view") {
    renderAnalysisProjects();
    renderSkillOptions("#analysis-skill-options");
    const projectId = state.selectedProject?.id || $("#analysis-project")?.value;
    if (projectId) {
      $("#analysis-project").value = projectId;
      if (state.selectedProject?.id !== projectId) selectProject(projectId);
      else Promise.all([loadProjectMaterials(projectId), loadProjectAnalysis(projectId), loadProjectFramework(projectId)]);
    }
    window.requestAnimationFrame(() => { if (state.frameworkWorld) updateFrameworkMapViewport(); });
  }
  if (viewId === "topic-view") {
    renderTopicProjects();
    renderSkillOptions();
    const projectId = state.selectedProject?.id || $("#topic-project")?.value;
    if (projectId) {
      $("#topic-project").value = projectId;
      if (state.selectedProject?.id !== projectId) {
        selectProject(projectId).then(() => {
          renderTopicTargetOptions();
          renderTopicMaterialOptions();
        });
      } else {
        loadProjectTopics(projectId);
        loadProjectMaterials(projectId);
      }
    }
  }
  if (viewId === "skills-view") renderSkillList();
}

function renderTopicProjects() {
  const select = $("#topic-project");
  if (!select) return;
  const currentValue = state.selectedProject?.id || select.value;
  select.innerHTML = state.projects.length
    ? state.projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`).join("")
    : `<option value="">请先创建项目</option>`;
  if (currentValue && state.projects.some((project) => project.id === currentValue)) select.value = currentValue;
}

function renderTopicTargetOptions() {
  const select = $("#topic-target");
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">请选择已有 Topic</option>${state.projectTopics.map((topic) => `<option value="${escapeHtml(topic.id)}">${"　".repeat(Math.max(0, (topic.level || topic.heading_level || 1) - 1))}${escapeHtml(topic.title)}</option>`).join("")}`;
  if (state.projectTopics.some((topic) => topic.id === current)) select.value = current;
}

function renderTopicMaterialOptions() {
  const select = $("#topic-materials");
  if (!select) return;
  const selected = new Set([...select.selectedOptions].map((option) => option.value));
  select.innerHTML = state.projectMaterials.map((material) => `<option value="${escapeHtml(material.id)}" ${selected.has(material.id) ? "selected" : ""}>${escapeHtml(material.name)} · ${escapeHtml(formatAnalysisStatus(material.extract_status))}</option>`).join("") || `<option value="" disabled>当前项目暂无研发素材</option>`;
}

function renderFrameworkTopicMaterialOptions(selectedIds = null) {
  const select = $("#framework-topic-materials");
  if (!select) return;
  const selected = selectedIds == null
    ? new Set([...select.selectedOptions].map((option) => option.value))
    : new Set((selectedIds || []).map((item) => String(item)));
  select.innerHTML = state.projectMaterials.map((material) => `<option value="${escapeHtml(material.id)}" ${selected.has(String(material.id)) ? "selected" : ""}>${escapeHtml(material.name)} · ${escapeHtml(formatAnalysisStatus(material.extract_status))}</option>`).join("") || `<option value="" disabled>当前项目暂无研发素材</option>`;
}

function toggleTopicMode() {
  const optimize = $("#topic-mode")?.value === "optimize";
  $("#topic-target-label")?.classList.toggle("is-hidden", !optimize);
  $("#topic-optimization-label")?.classList.toggle("is-hidden", !optimize);
  renderTopicTargetOptions();
  if (optimize) renderTopicMaterialOptions();
}

function applyTopicTarget(topicId) {
  const topic = state.projectTopics.find((item) => item.id === topicId);
  if (!topic) return;
  state.topicInheritProjectSkills = topic.inherit_project_skills !== false;
  state.topicDraftSkills = [...(topic.skills || [])];
  $("#topic-type").value = topic.topic_type || "concept";
  $("#topic-heading-level").value = String(topic.heading_level || topic.level || 1);
  $("#topic-title").value = topic.title || "";
  $("#topic-shortdesc").value = topic.shortdesc || "";
  $("#topic-brief").value = topic.brief || topic.chapter_summary || "";
  $("#topic-optimization-prompt").value = topic.generation_prompt || "只优化语言和结构，不改变业务事实；尽量保留原有 XML 标签结构。";
  state.outlineItems = (topic.outline || []).map((item) => ({ title: item.title || "", level: Number(item.level) || 1 }));
  renderOutlineBuilder();
  renderSkillOptions();
  toggleTopicFields();
}

function renderAnalysisProjects() {
  const select = $("#analysis-project");
  const currentValue = state.selectedProject?.id || select?.value || "";
  if (select) {
    select.innerHTML = state.projects.length
      ? state.projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`).join("")
      : `<option value="">请先创建项目</option>`;
    if (currentValue && state.projects.some((project) => project.id === currentValue)) select.value = currentValue;
  }
  renderAnalysisProjectTree();
}

function renderAnalysisProjectTree() {
  const container = $("#analysis-project-tree");
  if (!container) return;
  const projects = state.projects || [];
  if (!projects.length) {
    container.innerHTML = `<div class="tree-empty">暂无项目，请先创建项目。</div>`;
    return;
  }
  container.innerHTML = PROJECT_MODE_ORDER.map((mode) => {
    const items = projects.filter((project) => (project.mode || "new") === mode);
    if (!items.length) return "";
    const rows = items.map((project) => `
      <button type="button" class="analysis-project-link ${state.selectedProject?.id === project.id ? "is-selected" : ""}" data-analysis-project-id="${escapeHtml(project.id)}" title="打开项目：${escapeHtml(project.name)}">
        <span class="analysis-project-dot mode-${escapeHtml(mode)}" aria-hidden="true"></span>
        <span class="analysis-project-copy"><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(project.stage || "待开始")} · ${project.topic_count || 0} Topic</small></span>
      </button>
    `).join("");
    return `<details class="analysis-project-group" open><summary><span><i class="reference-mode-dot mode-${escapeHtml(mode)}"></i>${PROJECT_MODE_LABELS[mode]}</span><b>${items.length}</b></summary><div class="analysis-project-group-items">${rows}</div></details>`;
  }).join("") || `<div class="tree-empty">暂无项目。</div>`;
  container.querySelectorAll("[data-analysis-project-id]").forEach((button) => button.addEventListener("click", async () => {
    const projectId = button.dataset.analysisProjectId;
    if (!projectId) return;
    await selectProject(projectId);
    showView("analysis-view");
  }));
}

function renderSkillOptions(containerSelector = "#topic-skill-options") {
  const container = $(containerSelector);
  if (!container) return;
  if (!state.skills.length) {
    container.innerHTML = `<div class="field-hint">暂无可用 Skill，请先配置 Skill。</div>`;
    return;
  }
  const projectSkills = [...new Set([...(state.selectedProject?.skills || ["HIK Writing Skill", "HIK DITA Rule"])])];
  const topicScoped = ["#topic-skill-options", "#framework-topic-skill-options"].includes(containerSelector);
  const currentTopic = containerSelector === "#framework-topic-skill-options" ? state.frameworkTopic : state.currentTopic;
  const inherit = topicScoped
    ? (currentTopic ? currentTopic.inherit_project_skills !== false : state.topicInheritProjectSkills !== false)
    : false;
  let selectedNames = projectSkills;
  if (containerSelector === "#framework-topic-skill-options") selectedNames = currentTopic?.skills || state.frameworkTopicDraftSkills || projectSkills;
  if (containerSelector === "#topic-skill-options") selectedNames = currentTopic?.skills || state.topicDraftSkills || projectSkills;
  const selected = new Set(selectedNames);
  const inheritanceMarkup = topicScoped ? `<div class="skill-inheritance-row"><label class="check-row"><input type="checkbox" data-skill-inherit ${inherit ? "checked" : ""} /> 继承项目 Skill</label><span>项目级配置变化后，继承中的 Topic 会自动跟随。</span></div>` : "";
  container.innerHTML = `${inheritanceMarkup}${state.skills.map((skill) => {
    const inherited = topicScoped && inherit && projectSkills.includes(skill.name) && !skill.required;
    const checked = skill.required || selected.has(skill.name) || inherited;
    const disabled = skill.required || !skill.enabled || inherited;
    const origin = inherited ? " · 项目继承" : skill.required ? " · 全局必选" : "";
    return `<label class="skill-choice ${disabled && !skill.required ? "is-disabled" : ""}"><input type="checkbox" data-skill-name="${escapeHtml(skill.name)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} /> <span><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description || (skill.required ? "必选规范 Skill" : "自定义生成约束"))}${origin}</small></span>${skill.required ? '<em>必选</em>' : inherited ? '<em>继承</em>' : skill.enabled ? "" : '<em>已停用</em>'}</label>`;
  }).join("")}`;
}

async function loadSkills() {
  const data = await request("/api/skills");
  state.skills = data.skills || [];
  renderSkillOptions();
  renderSkillOptions("#analysis-skill-options");
  renderSkillOptions("#framework-topic-skill-options");
  renderProjectSkillOptions();
  renderSkillList();
}

function skillInheritanceEnabled(containerSelector = "#topic-skill-options") {
  const input = $(`${containerSelector} input[data-skill-inherit]`);
  return input ? input.checked : true;
}

function selectedSkillNames(containerSelector = "#topic-skill-options") {
  const selected = [...document.querySelectorAll(`${containerSelector} input[data-skill-name]:checked`)].map((node) => node.dataset.skillName);
  return ["HIK Writing Skill", ...selected.filter((name) => name !== "HIK Writing Skill")];
}

function formatAnalysisStatus(status) {
  return { success: "已提取", unsupported: "待解析", failed: "提取失败" }[status] || "处理中";
}

function renderAnalysisMaterials() {
  const list = $("#analysis-material-list");
  const count = $("#analysis-material-count");
  if (!list || !count) return;
  count.textContent = `${state.projectMaterials.length} 份`;
  const summary = $("#analysis-material-summary-text");
  if (summary) summary.textContent = state.projectMaterials.length ? "已保存到当前项目" : "尚未导入材料";
  if (!state.projectMaterials.length) {
    list.innerHTML = `<span class="field-hint">还没有材料，请使用右侧“添加材料”。</span>`;
    return;
  }
  list.innerHTML = state.projectMaterials.map((material) => `
    <div class="analysis-material-item">
      <span class="material-file-mark">${escapeHtml((material.extension || "FILE").replace(".", "").slice(0, 4).toUpperCase())}</span>
      <span class="material-file-copy"><a href="${escapeHtml(material.download_url)}" target="_blank" rel="noreferrer">${escapeHtml(material.name)}</a><small>${escapeHtml(formatFileSize(material.size))} · ${escapeHtml(material.extract_message || "")}</small></span>
      <span class="material-file-status status-${escapeHtml(material.extract_status)}">${escapeHtml(formatAnalysisStatus(material.extract_status))}</span>
      ${[".txt", ".md", ".markdown", ".csv", ".yaml", ".yml", ".json", ".xml"].includes((material.extension || "").toLowerCase()) ? `<button type="button" class="mini-button" data-edit-material="${escapeHtml(material.id)}">编辑</button>` : ""}<button type="button" class="icon-button is-danger" data-delete-material="${escapeHtml(material.id)}" aria-label="删除材料">×</button>
    </div>
  `).join("");
  list.querySelectorAll("[data-delete-material]").forEach((button) => button.addEventListener("click", () => deleteAnalysisMaterial(button.dataset.deleteMaterial)));
  list.querySelectorAll("[data-edit-material]").forEach((button) => button.addEventListener("click", () => editAnalysisMaterial(button.dataset.editMaterial)));
}

async function editAnalysisMaterial(materialId) {
  const projectId = $("#analysis-project")?.value;
  const material = state.projectMaterials.find((item) => item.id === materialId);
  if (!projectId || !material) return;
  try {
    const result = await request(`/api/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(materialId)}/content`);
    const text = window.prompt(`编辑材料：${material.name}\n\n提示：请直接修改文本，点击“确定”保存。`, result.text || "");
    if (text === null) return;
    await request(`/api/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(materialId)}`, { method: "PUT", body: JSON.stringify({ text }) });
    await loadProjectMaterials(projectId);
    showMessage("#analysis-message", "材料内容已保存。", "success");
  } catch (error) { showMessage("#analysis-message", error.message, "error"); }
}

async function loadProjectMaterials(projectId) {
  if (!projectId) {
    state.projectMaterials = [];
    renderAnalysisMaterials();
    return;
  }
  try {
    const data = await request(`/api/projects/${encodeURIComponent(projectId)}/materials`);
    if (state.selectedProject?.id !== projectId && $("#analysis-project")?.value !== projectId) return;
    state.projectMaterials = data.materials || [];
    renderAnalysisMaterials();
    renderTopicMaterialOptions();
  } catch (error) {
    const list = $("#analysis-material-list");
    if (list) list.innerHTML = `<div class="tree-empty tree-error">${escapeHtml(error.message)}</div>`;
  }
}

async function deleteAnalysisMaterial(materialId) {
  const material = state.projectMaterials.find((item) => item.id === materialId);
  if (!material || !state.selectedProject) return;
  if (!window.confirm(`确定删除“${material.name}”吗？原始文件和提取文本都会被删除。`)) return;
  try {
    await request(`/api/projects/${encodeURIComponent(state.selectedProject.id)}/materials/${encodeURIComponent(materialId)}`, { method: "DELETE" });
    await loadProjectMaterials(state.selectedProject.id);
    showMessage("#analysis-message", "材料已删除。", "success");
  } catch (error) {
    showMessage("#analysis-message", error.message, "error");
  }
}

async function handleAnalysisMaterialFiles(event) {
  const files = [...(event.target.files || [])];
  event.target.value = "";
  const projectId = $("#analysis-project")?.value;
  if (!projectId) {
    showMessage("#analysis-message", "请先选择项目，再上传材料。", "error");
    return;
  }
  const button = $("#run-analysis-button");
  if (button) button.disabled = true;
  try {
    for (const file of files) {
      if (file.size > 48 * 1024 * 1024) {
        showMessage("#analysis-message", `材料“${file.name}”不能超过 48 MB。`, "error");
        continue;
      }
      showMessage("#analysis-message", `正在保存材料：${file.name}…`);
      const dataUrl = await readFileAsDataUrl(file);
      await request(`/api/projects/${encodeURIComponent(projectId)}/materials`, {
        method: "POST",
        body: JSON.stringify({ name: file.name, mime_type: file.type, data_url: dataUrl }),
      });
    }
    await loadProjectMaterials(projectId);
    await loadProjects();
    showMessage("#analysis-message", files.length ? "材料已保存。请检查提取状态后开始 AI 分析。" : "", files.length ? "success" : "");
  } catch (error) {
    showMessage("#analysis-message", error.message, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function savePastedMaterial() {
  const projectId = $("#analysis-project")?.value;
  const text = $("#analysis-pasted-text")?.value.trim();
  if (!projectId) return showMessage("#analysis-message", "请先选择项目。", "error");
  if (!text) return showMessage("#analysis-message", "请先粘贴文本。", "error");
  const name = `粘贴文本-${new Date().toISOString().slice(0,19).replace(/[T:]/g, "-")}.txt`;
  const dataUrl = `data:text/plain;base64,${btoa(unescape(encodeURIComponent(text)))}`;
  try {
    await request(`/api/projects/${encodeURIComponent(projectId)}/materials`, { method: "POST", body: JSON.stringify({ name, mime_type: "text/plain", data_url: dataUrl }) });
    $("#analysis-pasted-text").value = "";
    $("#analysis-pasted-text").classList.add("is-hidden"); $("#save-pasted-material").classList.add("is-hidden");
    await loadProjectMaterials(projectId); showMessage("#analysis-message", "粘贴文本已保存为材料。", "success");
  } catch (error) { showMessage("#analysis-message", error.message, "error"); }
}

async function importFrameworkExcel(event) {
  const file = event.target.files?.[0]; event.target.value = "";
  const projectId = $("#analysis-project")?.value;
  if (!file || !projectId) return showMessage("#analysis-message", "请先选择项目和 Excel 文件。", "error");
  try {
    const result = await request(`/api/projects/${encodeURIComponent(projectId)}/framework/import-excel`, { method: "POST", body: JSON.stringify({ name: file.name, mime_type: file.type, data_url: await readFileAsDataUrl(file) }) });
    $("#framework-markdown").value = result.markdown || ""; handleFrameworkMarkdownInput();
    showMessage("#analysis-message", `已读取“${result.sheet_name || "框架"}”页签并填充 Editor。`, "success");
  } catch (error) { showMessage("#analysis-message", error.message, "error"); }
}

function parseFrameworkMarkdown(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const nodes = [];
  const stack = [];
  let activeNode = null;
  lines.forEach((raw, lineIndex) => {
    const heading = raw.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (heading) {
      let title = heading[2].trim();
      const isTask = /\s+\[task\]\s*$/i.test(title);
      title = title.replace(/\s+\[task\]\s*$/i, "").trim();
      const level = heading[1].length;
      while (stack.length && stack[stack.length - 1].level >= level) stack.pop();
      const node = { id: `framework_node_${nodes.length + 1}`, title, level, topic_type: isTask ? "task" : "concept", summary: "", body: [], lineIndex, parentId: stack.length ? stack[stack.length - 1].id : null, is_document_title: false };
      nodes.push(node);
      stack.push(node);
      activeNode = node;
      return;
    }
    if (activeNode && /^\s*>\s*/.test(raw)) {
      const summary = raw.replace(/^\s*>\s*/, "").replace(/^章节概述\s*[:：]\s*/, "").trim();
      if (summary) activeNode.summary = summary;
      return;
    }
    if (activeNode && raw.trim() && !/^\s*```/.test(raw)) {
      const body = raw.trim().replace(/^[-*•]\s+/, "").replace(/^\d+[.)、]\s+/, "").trim();
      if (body && !/^---+$/.test(body)) activeNode.body.push(body);
    }
  });
  const first = nodes[0];
  if (first?.level === 1) {
    const hasOtherH1 = nodes.some((node, index) => index > 0 && node.level === 1);
    const hasChild = nodes.some((node) => node.parentId === first.id);
    first.is_document_title = !hasOtherH1 || hasChild;
  }
  return nodes;
}

function frameworkHeadingFromPlainLine(line, hasDocumentTitle = false) {
  const value = String(line || "").replace(/\u00a0/g, " ").trim();
  if (!value) return null;
  const chapter = value.match(/^第\s*[0-9一二三四五六七八九十百千万]+\s*(章|篇|部分)\s*[:：.、]?\s*(.*)$/);
  if (chapter) return { level: 1 + (hasDocumentTitle ? 1 : 0), title: chapter[2] || chapter[0] };
  const section = value.match(/^第\s*[0-9一二三四五六七八九十百千万]+\s*节\s*[:：.、]?\s*(.*)$/);
  if (section) return { level: 2 + (hasDocumentTitle ? 1 : 0), title: section[1] || section[0] };
  const chinese = value.match(/^(（?[一二三四五六七八九十百千万]+[）)、.．]|\([一二三四五六七八九十百千万]+\))\s*(.*)$/);
  if (chinese) {
    const bracketed = /^[（(]/.test(chinese[1]);
    return { level: (bracketed ? 2 : 1) + (hasDocumentTitle ? 1 : 0), title: chinese[2] || chinese[0] };
  }
  const numbered = value.match(/^(\d+(?:\.\d+){0,4})[、.)．]?\s*(.+)$/);
  if (numbered) return { level: Math.min(6, numbered[1].split(".").length + (hasDocumentTitle ? 1 : 0)), title: numbered[2] };
  return null;
}

function convertPlainFrameworkToMarkdown(rawText) {
  const source = String(rawText || "").replace(/\r\n?/g, "\n").replace(/\u00a0/g, " ").trim();
  if (!source) return "";
  const sourceLines = source.split("\n");
  // 已经是 Markdown 时保留原文，避免重复转换用户手写的层级和正文。
  if (sourceLines.some((line) => /^\s{0,3}#{1,6}\s+/.test(line))) return `${source}\n`;
  const meaningful = sourceLines.map((line) => line.trim()).filter(Boolean);
  const hasStructuredHeading = meaningful.some((line) => frameworkHeadingFromPlainLine(line, false));
  const firstLooksLikeHeading = Boolean(frameworkHeadingFromPlainLine(meaningful[0], false));
  const hasDocumentTitle = !firstLooksLikeHeading && hasStructuredHeading;
  const output = [];
  let current = null;
  if (hasDocumentTitle) {
    output.push(`# ${meaningful[0]}`, "");
  }
  sourceLines.forEach((rawLine) => {
    const trimmed = rawLine.trim();
    if (!trimmed) {
      if (current && output[output.length - 1] !== "") output.push("");
      return;
    }
    if (hasDocumentTitle && trimmed === meaningful[0] && !current) {
      current = { summary: false };
      return;
    }
    const indent = Math.max(0, rawLine.search(/\S|$/));
    const detected = frameworkHeadingFromPlainLine(trimmed, hasDocumentTitle);
    if (detected) {
      const title = detected.title.replace(/\s+\[(task|concept)\]\s*$/i, "").trim();
      const type = /\[task\]\s*$/i.test(detected.title) ? " [task]" : "";
      output.push(`${"#".repeat(Math.max(1, detected.level))} ${title}${type}`);
      current = { summary: false, level: detected.level };
      return;
    }
    if (!current) {
      const level = Math.min(6, 1 + Math.floor(indent / 2));
      output.push(`${"#".repeat(level)} ${trimmed}`);
      current = { summary: false, level };
      return;
    }
    const clean = trimmed.replace(/^(?:[-*•]|\d+[.)、])\s*/, "").trim();
    if (!clean) return;
    output.push(`${current.summary ? "> " : "> 章节概述："}${clean}`);
    current.summary = true;
  });
  return output.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

function insertFrameworkClipboardText(editor, rawText) {
  if (!editor || !String(rawText || "").trim()) return;
  const converted = convertPlainFrameworkToMarkdown(rawText);
  const start = Number(editor.selectionStart || 0);
  const end = Number(editor.selectionEnd || 0);
  editor.value = `${editor.value.slice(0, start)}${converted}${editor.value.slice(end)}`;
  const cursor = start + converted.length;
  editor.setSelectionRange(cursor, cursor);
  editor.dispatchEvent(new Event("input", { bubbles: true }));
}

async function pasteFrameworkFromClipboard(editor = $("#framework-markdown")) {
  if (!editor) return;
  try {
    const text = await navigator.clipboard.readText();
    if (!text.trim()) throw new Error("剪切板中没有可读取的文本。");
    insertFrameworkClipboardText(editor, text);
    showMessage("#analysis-message", "已从剪切板粘贴并转换为 Markdown。", "success");
  } catch (error) {
    showMessage("#analysis-message", `读取剪切板失败：${error.message || "请使用 Ctrl/Cmd + V 粘贴"}`, "error");
  }
}

function handleFrameworkMarkdownPaste(event) {
  const editor = event.currentTarget;
  const text = event.clipboardData?.getData("text/plain") || "";
  if (!text.trim()) return;
  event.preventDefault();
  insertFrameworkClipboardText(editor, text);
}

function renderFrameworkMarkdownFocusPreview() {
  const preview = $("#framework-markdown-focus-preview");
  if (!preview) return;
  const focusEditor = $("#framework-markdown-focus-editor");
  const source = focusEditor ? focusEditor.value : $("#framework-markdown")?.value || "";
  renderFrameworkOutlinePreview(preview, source);
}

function renderFrameworkOutlinePreview(target = $("#framework-outline-preview"), source = $("#framework-markdown")?.value || "") {
  if (!target) return;
  const nodes = parseFrameworkMarkdown(source);
  if (!nodes.length) {
    target.innerHTML = `<div class="tree-empty">输入 Markdown 后显示章节预览。</div>`;
    $("#framework-outline-count") && ($("#framework-outline-count").textContent = "0 个章节");
    return;
  }
  target.innerHTML = nodes.map((node, index) => {
    const level = Math.max(1, Math.min(6, Number(node.level) || 1));
    const body = (node.body || []).map((paragraph) => `<p class="framework-outline-preview-body">${escapeHtml(paragraph)}</p>`).join("");
    const selected = state.frameworkPreviewNodeId === node.id ? " is-selected" : "";
    const topicHint = node.is_document_title ? "" : " · 双击打开 Topic 编辑器";
    return `<article class="framework-outline-preview-item level-${level}${selected}" style="--outline-depth:${Math.max(0, level - 1)}" data-framework-preview-node="${escapeHtml(node.id)}" data-framework-preview-line="${node.lineIndex}" tabindex="0" role="button" aria-label="${escapeHtml(node.title)}${escapeHtml(topicHint)}"><span class="framework-outline-preview-index">${String(index + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(node.title)}</strong>${node.summary ? `<p class="framework-outline-preview-summary">${escapeHtml(node.summary)}</p>` : ""}${body}</div></article>`;
  }).join("");
  $("#framework-outline-count") && ($("#framework-outline-count").textContent = `${nodes.length} 个章节`);
  bindFrameworkOutlinePreviewInteractions(target, nodes);
}

function frameworkPreviewEditorFor(target) {
  return target?.id === "framework-markdown-focus-preview"
    ? $("#framework-markdown-focus-editor")
    : $("#framework-markdown");
}

function frameworkPreviewTargets() {
  return [$("#framework-outline-preview"), $("#framework-markdown-focus-preview")].filter(Boolean);
}

function markFrameworkPreviewNode(nodeId, scroll = false) {
  state.frameworkPreviewNodeId = nodeId || null;
  frameworkPreviewTargets().forEach((preview) => {
    preview.querySelectorAll("[data-framework-preview-node]").forEach((item) => {
      item.classList.toggle("is-selected", item.dataset.frameworkPreviewNode === state.frameworkPreviewNodeId);
    });
    if (scroll && nodeId) {
      const selected = [...preview.querySelectorAll("[data-framework-preview-node]")].find((item) => item.dataset.frameworkPreviewNode === nodeId);
      if (selected && selected.offsetParent !== null) selected.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  });
}

function frameworkEditorLineRange(editor, lineIndex) {
  const lines = String(editor?.value || "").split(/\r?\n/);
  const index = Math.max(0, Math.min(lines.length - 1, Number(lineIndex) || 0));
  let start = 0;
  for (let i = 0; i < index; i += 1) start += lines[i].length + 1;
  return { start, end: start + lines[index].length };
}

function focusFrameworkEditorNode(node, editor) {
  if (!node || !editor) return;
  const range = frameworkEditorLineRange(editor, node.lineIndex);
  editor.focus({ preventScroll: true });
  editor.setSelectionRange(range.start, range.end);
  const lineHeight = Number.parseFloat(window.getComputedStyle(editor).lineHeight) || 24;
  editor.scrollTop = Math.max(0, (Number(node.lineIndex) || 0) * lineHeight - editor.clientHeight * .35);
  markFrameworkPreviewNode(node.id, true);
}

function frameworkNodeAtEditorCursor(editor) {
  if (!editor) return null;
  const nodes = parseFrameworkMarkdown(editor.value);
  if (!nodes.length) return null;
  const lineIndex = String(editor.value || "").slice(0, editor.selectionStart || 0).split(/\r?\n/).length - 1;
  return [...nodes].reverse().find((node) => node.lineIndex <= lineIndex) || nodes[0];
}

function syncFrameworkPreviewSelectionFromEditor(editor) {
  const node = frameworkNodeAtEditorCursor(editor);
  if (node) markFrameworkPreviewNode(node.id, true);
}

function bindFrameworkOutlinePreviewInteractions(target, nodes) {
  target.querySelectorAll("[data-framework-preview-node]").forEach((item) => {
    const getNode = () => nodes.find((node) => node.id === item.dataset.frameworkPreviewNode);
    item.addEventListener("click", () => {
      const node = getNode();
      if (node) focusFrameworkEditorNode(node, frameworkPreviewEditorFor(target));
    });
    item.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const node = getNode();
      if (!node) return;
      markFrameworkPreviewNode(node.id, true);
      if (!node.is_document_title) openFrameworkTopicEditor(node);
    });
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        const node = getNode();
        if (node) focusFrameworkEditorNode(node, frameworkPreviewEditorFor(target));
      }
    });
  });
}

function openFrameworkMarkdownFullscreen() {
  const focus = $("#framework-markdown-focus");
  const mainEditor = $("#framework-markdown");
  const focusEditor = $("#framework-markdown-focus-editor");
  if (!focus || !mainEditor || !focusEditor) return;
  focusEditor.value = mainEditor.value;
  focus.classList.add("is-open");
  focus.setAttribute("aria-hidden", "false");
  document.body.classList.add("is-markdown-focus-open");
  renderFrameworkMarkdownFocusPreview();
  updateFrameworkFocusLineCount();
  window.requestAnimationFrame(() => focusEditor.focus());
}

function closeFrameworkMarkdownFullscreen() {
  const focus = $("#framework-markdown-focus");
  const focusEditor = $("#framework-markdown-focus-editor");
  const mainEditor = $("#framework-markdown");
  if (!focus || !focusEditor || !mainEditor) return;
  if (mainEditor.value !== focusEditor.value) {
    mainEditor.value = focusEditor.value;
    handleFrameworkMarkdownInput();
  }
  focus.classList.remove("is-open");
  focus.setAttribute("aria-hidden", "true");
  document.body.classList.remove("is-markdown-focus-open");
}

function updateFrameworkFocusLineCount() {
  const editor = $("#framework-markdown-focus-editor");
  const target = $("#framework-focus-line-count");
  if (editor && target) target.textContent = `${editor.value.split(/\r?\n/).length} 行 · ${parseFrameworkMarkdown(editor.value).length} 个章节`;
}

function frameworkMarkdownFromOutline(outline, projectName = "文档") {
  const lines = [`# ${projectName}`, ""];
  (outline || []).forEach((item) => {
    const title = String(item.title || "").trim();
    if (!title) return;
    const level = Math.max(1, Math.min(5, Number(item.level) || 1));
    const task = String(item.type || "").toLowerCase() === "task" ? " [task]" : "";
    lines.push(`${"#".repeat(level + 1)} ${title}${task}`);
    if (item.shortdesc) lines.push("", `> 章节概述：${String(item.shortdesc).trim()}`);
    lines.push("");
  });
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

function updateFrameworkStatus(message, kind = "") {
  const node = $("#framework-save-state");
  if (!node) return;
  node.textContent = message;
  node.className = `framework-save-state ${kind}`.trim();
}

function frameworkDisplayLines(value, maxWidth, maxLines = 4, fontSize = 12) {
  const text = String(value || "").trim();
  if (!text) return [];
  const lines = [];
  const visualWidth = (value) => [...String(value)].reduce((total, char) => {
    if (/\s/.test(char)) return total + fontSize * 0.34;
    if (/[\u3000-\u9fff\uff00-\uffef]/.test(char)) return total + fontSize;
    if (/[A-Z0-9]/.test(char)) return total + fontSize * 0.68;
    return total + fontSize * 0.56;
  }, 0);
  String(text).split(/\r?\n/).forEach((part) => {
    let line = "";
    [...part].forEach((char) => {
      if (line && visualWidth(line + char) > maxWidth) {
        lines.push(line);
        line = char;
      } else {
        line += char;
      }
    });
    if (line || !lines.length) lines.push(line);
  });
  if (lines.length > maxLines) {
    lines.length = maxLines;
    let last = lines[maxLines - 1];
    while (last && visualWidth(`${last}…`) > maxWidth) last = [...last].slice(0, -1).join("");
    lines[maxLines - 1] = `${last || "…"}…`;
  }
  return lines;
}

function frameworkNodePositions(nodes, layout) {
  const positions = new Map();
  const children = new Map(nodes.map((node) => [node.id, []]));
  nodes.forEach((node) => {
    if (node.parentId && children.has(node.parentId)) children.get(node.parentId).push(node);
  });
  const roots = nodes.filter((node) => !node.parentId);
  const isLargeMap = nodes.length > 36;
  const isVeryLargeMap = nodes.length > 80;
  const sizes = new Map(nodes.map((node) => {
    const level = Number(node.level) || 1;
    const w = node.is_document_title
      ? (isLargeMap ? 224 : 248)
      : level === 2
        ? (isLargeMap ? 188 : 210)
        : level === 3
          ? (isLargeMap ? 176 : 196)
          : (isLargeMap ? 164 : 184);
    // TASK 标签独立显示在标题上方，不再占用标题右侧宽度。
    const titleWidth = w - 24;
    const titleLines = frameworkDisplayLines(node.title, titleWidth, isLargeMap ? 3 : 4, isLargeMap ? 11 : 12);
    const hasSummary = Boolean(String(node.summary || "").trim());
    const expanded = state.frameworkShowSummaries;
    const summaryLines = hasSummary && expanded ? frameworkDisplayLines(node.summary, w - 26, isLargeMap ? 2 : 3, 9) : [];
    const summaryHeight = hasSummary && expanded ? 22 + summaryLines.length * 13 : 0;
    const height = Math.max(isLargeMap ? 54 : 58, 26 + titleLines.length * (isLargeMap ? 16 : 17) + summaryHeight);
    return [node.id, { w, h: height, titleLines, summaryLines, hasSummary, expanded }];
  }));
  const gap = isVeryLargeMap ? 9 : isLargeMap ? 12 : 18;
  const columnGap = isVeryLargeMap ? 24 : isLargeMap ? 32 : 48;
  const subtreeHeights = new Map();
  const measure = (node) => {
    if (subtreeHeights.has(node.id)) return subtreeHeights.get(node.id);
    const own = sizes.get(node.id).h;
    const childHeight = (children.get(node.id) || []).reduce((total, child, index) => total + measure(child) + (index ? gap : 0), 0);
    const value = Math.max(own, childHeight);
    subtreeHeights.set(node.id, value);
    return value;
  };
  roots.forEach(measure);

  if (layout === "fishbone") {
    const fishboneSpines = [];
    const fishboneBranches = [];
    const branchGap = isVeryLargeMap ? 34 : isLargeMap ? 44 : 54;
    const spineMargin = isVeryLargeMap ? 22 : isLargeMap ? 26 : 34;
    const sectionGap = isVeryLargeMap ? 42 : isLargeMap ? 52 : 72;
    const branchLead = isVeryLargeMap ? 72 : isLargeMap ? 80 : 92;
    let sectionTop = 24;

    const placeTree = (node, depth, top) => {
      const size = sizes.get(node.id);
      const subtreeHeight = measure(node);
      const childList = children.get(node.id) || [];
      const childTotal = childList.reduce((total, child, index) => total + measure(child) + (index ? gap : 0), 0);
      const childStart = top + Math.max(0, (subtreeHeight - childTotal) / 2);
      positions.set(node.id, { ...size, x: 24 + depth * (size.w + columnGap), y: top + Math.max(0, (subtreeHeight - size.h) / 2) });
      let childCursor = childStart;
      childList.forEach((child) => {
        placeTree(child, depth + 1, childCursor);
        childCursor += measure(child) + gap;
      });
    };

    const subtreeBounds = (node) => {
      const own = positions.get(node.id);
      const bounds = { minX: own.x, minY: own.y, maxX: own.x + own.w, maxY: own.y + own.h };
      (children.get(node.id) || []).forEach((child) => {
        const childBounds = subtreeBounds(child);
        bounds.minX = Math.min(bounds.minX, childBounds.minX);
        bounds.minY = Math.min(bounds.minY, childBounds.minY);
        bounds.maxX = Math.max(bounds.maxX, childBounds.maxX);
        bounds.maxY = Math.max(bounds.maxY, childBounds.maxY);
      });
      return bounds;
    };

    const shiftSubtree = (node, dx, dy) => {
      const current = positions.get(node.id);
      positions.set(node.id, { ...current, x: current.x + dx, y: current.y + dy });
      (children.get(node.id) || []).forEach((child) => shiftSubtree(child, dx, dy));
    };

    roots.forEach((root) => {
      const rootChildren = children.get(root.id) || [];
      // 鱼骨的同侧分支沿主骨横向展开，高度只需要容纳最高的那一支；
      // 将所有分支高度相加会把主骨无意义地推到画布底部。
      const topExtent = Math.max(...rootChildren.filter((_, index) => index % 2 === 0).map((child) => measure(child)), 0);
      const bottomExtent = Math.max(...rootChildren.filter((_, index) => index % 2 === 1).map((child) => measure(child)), 0);
      const spineY = sectionTop + Math.max(150, topExtent + 62);
      const rootSize = sizes.get(root.id);
      positions.set(root.id, { ...rootSize, x: 24, y: spineY - rootSize.h / 2 });
      const cursor = { top: rootSize.w + 24 + 148, bottom: rootSize.w + 24 + 148 };
      let sectionBottom = positions.get(root.id).y + rootSize.h;

      rootChildren.forEach((child, index) => {
        const side = index % 2 === 0 ? "top" : "bottom";
        placeTree(child, 0, 0);
        const initial = subtreeBounds(child);
        const dx = cursor[side] - initial.minX;
        const dy = side === "top"
          ? spineY - spineMargin - initial.maxY
          : spineY + spineMargin - initial.minY;
        shiftSubtree(child, dx, dy);
        const placed = subtreeBounds(child);
        cursor[side] = placed.maxX + branchGap;
        sectionBottom = Math.max(sectionBottom, placed.maxY);
        fishboneBranches.push({ nodeId: child.id, joinX: positions.get(child.id).x - branchLead, spineY, side });
      });

      const spineEnd = Math.max(rootSize.w + 24 + 42, cursor.top - branchGap + 28, cursor.bottom - branchGap + 28);
      fishboneSpines.push({ x1: 24 + rootSize.w, y: spineY, x2: spineEnd });
      sectionTop = sectionBottom + sectionGap;
    });

    const allBounds = [...positions.values()];
    const width = Math.max(720, 48 + Math.max(...allBounds.map((item) => item.x + item.w), 0));
    const height = Math.max(360, sectionTop + 24);
    return { positions, width, height, fishboneSpines, fishboneBranches };
  }

  const totalHeight = Math.max(360, 48 + roots.reduce((total, root, index) => total + measure(root) + (index ? gap : 0), 0));
  let rootCursor = 24;
  const place = (node, depth, top) => {
    const size = sizes.get(node.id);
    const subtreeHeight = measure(node);
    const childList = children.get(node.id) || [];
    const childTotal = childList.reduce((total, child, index) => total + measure(child) + (index ? gap : 0), 0);
    const childStart = top + Math.max(0, (subtreeHeight - childTotal) / 2);
    positions.set(node.id, { ...size, x: 24 + depth * (size.w + columnGap), y: top + Math.max(0, (subtreeHeight - size.h) / 2) });
    let childCursor = childStart;
    childList.forEach((child) => {
      place(child, depth + 1, childCursor);
      childCursor += measure(child) + gap;
    });
  };
  roots.forEach((root) => {
    place(root, 0, rootCursor);
    rootCursor += measure(root) + gap;
  });
  const maxX = Math.max(...[...positions.values()].map((item) => item.x + item.w), 0);
  return { positions, width: Math.max(720, maxX + 24), height: totalHeight };
}

function frameworkMapViewportSize() {
  const container = $("#framework-map");
  return { width: Math.max(1, container?.clientWidth || 960), height: Math.max(1, container?.clientHeight || 520) };
}

function clampFrameworkPan() {
  if (!state.frameworkWorld) return;
  const { width, height } = frameworkMapViewportSize();
  const scale = state.frameworkPan.scale;
  const viewWidth = width / scale;
  const viewHeight = height / scale;
  const margin = 24;
  const worldWidth = state.frameworkWorld.width;
  const worldHeight = state.frameworkWorld.height;
  if (worldWidth <= viewWidth) state.frameworkPan.x = (worldWidth - viewWidth) / 2;
  else {
    const minX = -margin;
    const maxX = worldWidth - viewWidth + margin;
    state.frameworkPan.x = Math.min(maxX, Math.max(minX, state.frameworkPan.x));
  }
  if (worldHeight <= viewHeight) state.frameworkPan.y = (worldHeight - viewHeight) / 2;
  else {
    const minY = -margin;
    const maxY = worldHeight - viewHeight + margin;
    state.frameworkPan.y = Math.min(maxY, Math.max(minY, state.frameworkPan.y));
  }
}

function updateFrameworkMapViewport() {
  const svg = $("#framework-map .framework-map-svg");
  if (!svg || !state.frameworkWorld) return;
  const { width, height } = frameworkMapViewportSize();
  clampFrameworkPan();
  svg.setAttribute("viewBox", `${state.frameworkPan.x} ${state.frameworkPan.y} ${width / state.frameworkPan.scale} ${height / state.frameworkPan.scale}`);
  const scaleNode = $("#framework-map-scale");
  if (scaleNode) scaleNode.textContent = `${Math.round(state.frameworkPan.scale * 100)}%`;
}

function fitFrameworkMap() {
  if (!state.frameworkWorld) return;
  const { width, height } = frameworkMapViewportSize();
  const availableWidth = Math.max(1, width - 32);
  const availableHeight = Math.max(1, height - 32);
  const scale = Math.min(2.5, Math.max(0.08, Math.min(availableWidth / state.frameworkWorld.width, availableHeight / state.frameworkWorld.height)));
  state.frameworkPan.scale = scale;
  state.frameworkPan.x = (state.frameworkWorld.width - width / scale) / 2;
  state.frameworkPan.y = (state.frameworkWorld.height - height / scale) / 2;
  updateFrameworkMapViewport();
}

function setFrameworkScaleAt(nextScale, screenX, screenY) {
  if (!state.frameworkWorld) return;
  const { width, height } = frameworkMapViewportSize();
  const x = Math.min(width, Math.max(0, Number(screenX) || width / 2));
  const y = Math.min(height, Math.max(0, Number(screenY) || height / 2));
  const scale = Math.min(2.5, Math.max(0.08, nextScale));
  const worldX = state.frameworkPan.x + x / state.frameworkPan.scale;
  const worldY = state.frameworkPan.y + y / state.frameworkPan.scale;
  state.frameworkPan.scale = scale;
  state.frameworkPan.x = worldX - x / scale;
  state.frameworkPan.y = worldY - y / scale;
  updateFrameworkMapViewport();
}

function frameworkMapScreenPoint(event) {
  const rect = $("#framework-map").getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function updateFrameworkLayoutControls() {
  const select = $("#framework-layout-select");
  if (select) select.value = state.frameworkLayout;
  document.querySelectorAll("[data-framework-layout]").forEach((item) => item.classList.toggle("is-active", item.dataset.frameworkLayout === state.frameworkLayout));
  const title = $("#framework-map-title");
  if (title) title.textContent = state.frameworkLayout === "fishbone" ? "FISHBONE PREVIEW" : "MINDMAP PREVIEW";
  const summaryButton = $("#framework-summary-toggle");
  if (summaryButton) summaryButton.textContent = state.frameworkShowSummaries ? "收起概述" : "展开概述";
  if (summaryButton) summaryButton.classList.toggle("is-active", state.frameworkShowSummaries);
}

function updateFrameworkViewControls() {
  const isOutline = state.frameworkView === "outline";
  $("#framework-map")?.classList.toggle("is-hidden", isOutline);
  $("#framework-outline-preview-pane")?.classList.toggle("is-hidden", !isOutline);
  document.querySelectorAll("#framework-map-pane .framework-map-tools").forEach((node) => node.classList.toggle("is-hidden", isOutline));
  $("#framework-summary-toggle")?.classList.toggle("is-hidden", isOutline);
  $("#framework-summary-toggle")?.setAttribute("aria-hidden", isOutline ? "true" : "false");
  $("#framework-map-hint")?.classList.toggle("is-hidden", isOutline);
  $("#framework-outline-hint")?.classList.toggle("is-hidden", !isOutline);
  document.querySelectorAll("[data-framework-view]").forEach((button) => {
    const active = button.dataset.frameworkView === state.frameworkView;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  const mapTitle = $("#framework-map-title");
  if (mapTitle) mapTitle.textContent = isOutline ? "章节预览" : state.frameworkLayout === "fishbone" ? "FISHBONE PREVIEW" : "MINDMAP PREVIEW";
  if (isOutline) renderFrameworkOutlinePreview($("#framework-outline-preview"));
}

function setFrameworkView(view) {
  state.frameworkView = view === "outline" ? "outline" : "map";
  updateFrameworkViewControls();
  if (state.frameworkView === "map") window.requestAnimationFrame(updateFrameworkMapViewport);
}

function updateFrameworkPanelControls() {
  const mapOpen = state.frameworkPanel === "map";
  const topicOpen = state.frameworkPanel === "topic";
  const body = $("#framework-workbench-body");
  const mapButton = $("#framework-toggle-map");
  const topicButton = $("#framework-toggle-topic");
  body?.classList.toggle("is-map-open", mapOpen);
  mapButton?.classList.toggle("is-active", mapOpen);
  topicButton?.classList.toggle("is-active", topicOpen);
  mapButton?.setAttribute("aria-expanded", mapOpen ? "true" : "false");
  topicButton?.setAttribute("aria-expanded", topicOpen ? "true" : "false");
  if (mapOpen && state.frameworkWorld) {
    window.requestAnimationFrame(() => {
      state.frameworkNeedsFit = true;
      fitFrameworkMap();
    });
  }
}

function setFrameworkPanel(panel) {
  const requested = ["map", "topic"].includes(panel) ? panel : "none";
  const dialog = $("#framework-topic-dialog");
  if (requested === "topic" && !state.frameworkTopicNode) {
    showMessage("#analysis-message", "请先单击一个框架节点，再打开 Topic 编辑器。", "error");
    return false;
  }
  if (requested !== "topic" && dialog?.open) {
    dialog.close();
    dialog.classList.remove("is-drawer");
  }
  state.frameworkPanel = requested;
  updateFrameworkPanelControls();
  return true;
}

async function toggleFrameworkTopicPanel() {
  const dialog = $("#framework-topic-dialog");
  if (state.frameworkPanel === "topic" && dialog?.open) {
    dialog.close();
    return;
  }
  // 节点内容仍在异步加载时，避免一次点击启动第二个请求并让两个结果
  // 互相覆盖。节点入口会继续允许切换到另一个节点。
  if (state.frameworkTopicLoading) return;
  if (!state.frameworkTopicNode) {
    showMessage("#analysis-message", "请先单击一个框架节点，再打开 Topic 编辑器。", "error");
    return;
  }
  await openFrameworkTopicEditor(state.frameworkTopicNode);
}

function updateFrameworkThemeControls() {
  const select = $("#framework-theme-select");
  if (select) select.value = state.frameworkTheme;
  document.querySelectorAll("[data-framework-theme]").forEach((button) => button.classList.toggle("is-active", button.dataset.frameworkTheme === state.frameworkTheme));
}

function applyFrameworkTheme(theme, persist = true) {
  if (!FRAMEWORK_THEME_PALETTES[theme]) return;
  state.frameworkTheme = theme;
  if (persist) {
    try { localStorage.setItem("hik-framework-theme", theme); } catch (error) { /* 本地存储不可用时不影响主题切换 */ }
  }
  updateFrameworkThemeControls();
  renderFrameworkMap();
  if (state.frameworkPresentationOpen) window.requestAnimationFrame(renderFrameworkPresentation);
}

function toggleFrameworkSummaries() {
  state.frameworkShowSummaries = !state.frameworkShowSummaries;
  state.frameworkNeedsFit = true;
  renderFrameworkMap();
  if (state.frameworkPresentationOpen) window.requestAnimationFrame(renderFrameworkPresentation);
}

function updateFrameworkFullscreenLabel() {
  const button = $("#framework-map-fullscreen");
  const isFullscreen = document.fullscreenElement === $("#framework-map-pane") || $("#framework-map-pane")?.classList.contains("is-map-fullscreen");
  if (button) button.textContent = isFullscreen ? "退出全屏" : "全屏";
}

async function toggleFrameworkFullscreen() {
  const pane = $("#framework-map-pane");
  if (!pane) return;
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if (pane.requestFullscreen) await pane.requestFullscreen();
    else pane.classList.toggle("is-map-fullscreen");
  } catch (error) {
    pane.classList.toggle("is-map-fullscreen");
  }
  updateFrameworkFullscreenLabel();
  window.setTimeout(() => { if (state.frameworkWorld) updateFrameworkMapViewport(); }, 80);
}

function setupFrameworkMapGestures() {
  const container = $("#framework-map");
  if (!container || container.dataset.gesturesReady === "true") return;
  container.dataset.gesturesReady = "true";

  container.addEventListener("pointerdown", (event) => {
    if (event.target.closest?.(".framework-map-node, .framework-map-tools, .framework-map-hint")) return;
    container.setPointerCapture?.(event.pointerId);
    state.frameworkPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (state.frameworkPointers.size >= 2) {
      const points = [...state.frameworkPointers.values()];
      const rect = container.getBoundingClientRect();
      const center = { x: (points[0].x + points[1].x) / 2 - rect.left, y: (points[0].y + points[1].y) / 2 - rect.top };
      const distance = Math.max(1, Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y));
      state.frameworkGesture = { distance, scale: state.frameworkPan.scale, worldX: state.frameworkPan.x + center.x / state.frameworkPan.scale, worldY: state.frameworkPan.y + center.y / state.frameworkPan.scale };
      state.frameworkDrag = null;
    } else {
      state.frameworkDrag = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, panX: state.frameworkPan.x, panY: state.frameworkPan.y };
    }
    container.classList.add("is-panning");
  });

  container.addEventListener("pointermove", (event) => {
    if (!state.frameworkPointers.has(event.pointerId)) return;
    state.frameworkPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const rect = container.getBoundingClientRect();
    if (state.frameworkPointers.size >= 2 && state.frameworkGesture) {
      const points = [...state.frameworkPointers.values()];
      const center = { x: (points[0].x + points[1].x) / 2 - rect.left, y: (points[0].y + points[1].y) / 2 - rect.top };
      const distance = Math.max(1, Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y));
      const scale = Math.min(2.5, Math.max(0.05, state.frameworkGesture.scale * distance / state.frameworkGesture.distance));
      state.frameworkPan.scale = scale;
      state.frameworkPan.x = state.frameworkGesture.worldX - center.x / scale;
      state.frameworkPan.y = state.frameworkGesture.worldY - center.y / scale;
      updateFrameworkMapViewport();
      event.preventDefault();
      return;
    }
    const drag = state.frameworkDrag;
    if (!drag || drag.pointerId !== event.pointerId) return;
    state.frameworkPan.x = drag.panX - (event.clientX - drag.startX) / state.frameworkPan.scale;
    state.frameworkPan.y = drag.panY - (event.clientY - drag.startY) / state.frameworkPan.scale;
    updateFrameworkMapViewport();
    event.preventDefault();
  });

  const endPointer = (event) => {
    state.frameworkPointers.delete(event.pointerId);
    if (state.frameworkPointers.size < 2) state.frameworkGesture = null;
    if (state.frameworkPointers.size === 0) {
      state.frameworkDrag = null;
      container.classList.remove("is-panning");
    }
  };
  container.addEventListener("pointerup", endPointer);
  container.addEventListener("pointercancel", endPointer);
  container.addEventListener("wheel", (event) => {
    const point = frameworkMapScreenPoint(event);
    setFrameworkScaleAt(state.frameworkPan.scale * (event.deltaY > 0 ? 0.9 : 1.1), point.x, point.y);
    event.preventDefault();
  }, { passive: false });
}

function setupFrameworkMapResizeObserver() {
  const container = $("#framework-map");
  if (!container || state.frameworkMapResizeObserver || !window.ResizeObserver) return;
  state.frameworkMapResizeObserver = new ResizeObserver(() => {
    if (!state.frameworkWorld) return;
    window.requestAnimationFrame(() => {
      if (state.frameworkNeedsFit) fitFrameworkMap();
      else updateFrameworkMapViewport();
    });
  });
  state.frameworkMapResizeObserver.observe(container);
}

function renderFrameworkMap() {
  const container = $("#framework-map");
  if (!container) return;
  container.classList.remove("framework-theme-poster", "framework-theme-pastel");
  container.classList.add(`framework-theme-${state.frameworkTheme}`);
  const nodes = state.frameworkNodes;
  if (!nodes.length) {
    container.innerHTML = `<div class="framework-map-empty">生成或输入 Markdown 后显示图形。</div>`;
    state.frameworkWorld = null;
    updateFrameworkViewControls();
    return;
  }
  const layout = frameworkNodePositions(nodes, state.frameworkLayout);
  const shouldFit = state.frameworkNeedsFit || !state.frameworkWorld || state.frameworkWorld.layout !== state.frameworkLayout;
  state.frameworkWorld = { width: layout.width, height: layout.height, layout: state.frameworkLayout };
  updateFrameworkLayoutControls();
  const esc = (value) => escapeHtml(value);
  const rootNode = nodes.find((node) => node.is_document_title) || null;
  const branchMap = new Map();
  const nodeChildren = new Map(nodes.map((node) => [node.id, []]));
  nodes.forEach((node) => {
    if (node.parentId && nodeChildren.has(node.parentId)) nodeChildren.get(node.parentId).push(node);
  });
  // 导入的 Markdown 可能包含多个 H1 根节点。除文档标题的直属子节点外，
  // 也要把其他根节点作为独立分支，否则它们会全部落到 branch 0，显示成同一种颜色。
  const branchRoots = [];
  if (rootNode) (nodeChildren.get(rootNode.id) || []).forEach((node) => branchRoots.push(node));
  nodes.filter((node) => !node.parentId && node.id !== rootNode?.id).forEach((node) => branchRoots.push(node));
  const assignBranch = (node, index) => {
    branchMap.set(node.id, index);
    (nodeChildren.get(node.id) || []).forEach((child) => assignBranch(child, index));
  };
  branchRoots.forEach((node, index) => assignBranch(node, index));
  if (rootNode) branchMap.set(rootNode.id, -1);
  const branchIndexFor = (node) => {
    const index = branchMap.get(node.id);
    return index == null || index < 0 ? 0 : index;
  };
  const branchStyleFor = (node) => {
    const palette = frameworkThemePalette(state.frameworkTheme, branchIndexFor(node));
    const line = node?.is_document_title ? "#0f0f0f" : Number(node?.level) === 2 ? palette.bg : palette.line;
    return `--framework-line:${line};`;
  };
  const lines = [];
  if (state.frameworkLayout === "fishbone") {
    const fishboneBranchByNode = new Map((layout.fishboneBranches || []).map((item) => [item.nodeId, item]));
    nodes.forEach((node) => {
      const to = layout.positions.get(node.id);
      const fishboneBranch = fishboneBranchByNode.get(node.id);
      if (!to || !fishboneBranch) return;
      lines.push(`<path class="framework-map-branch framework-map-fish-branch framework-branch-${branchIndexFor(node)} level-${Math.min(6, Math.max(1, Number(node.level) || 1))}" style="${branchStyleFor(node)}" data-framework-parent="${esc(node.parentId || "")}" data-framework-child="${esc(node.id)}" d="M ${fishboneBranch.joinX} ${fishboneBranch.spineY} C ${fishboneBranch.joinX + 18} ${fishboneBranch.spineY}, ${to.x - 18} ${to.y + to.h / 2}, ${to.x} ${to.y + to.h / 2}" />`);
    });
  } else {
    // XMind 风格：一个父节点只引出一条主干，子节点从主干分叉，避免所有连接线直接挤在父节点上。
    nodes.forEach((parent) => {
      const childList = nodeChildren.get(parent.id) || [];
      if (!childList.length) return;
      const from = layout.positions.get(parent.id);
      const childPositions = childList.map((child) => ({ node: child, pos: layout.positions.get(child.id) })).filter((item) => item.pos);
      if (!from || !childPositions.length) return;
      const parentY = from.y + from.h / 2;
      const trunkX = from.x + from.w + 24;
      const childYs = childPositions.map((item) => item.pos.y + item.pos.h / 2);
      const edgeLevel = Math.min(6, Math.max(1, Number(childPositions[0].node.level) || 1));
      const branchClass = `framework-map-branch framework-map-tree-edge framework-branch-${branchIndexFor(parent)} level-${edgeLevel}`;
      const branchStyle = `style="${branchStyleFor(parent)}"`;
      lines.push(`<path class="${branchClass} framework-map-parent-link" ${branchStyle} data-framework-parent="${esc(parent.id)}" d="M ${from.x + from.w} ${parentY} C ${from.x + from.w + 10} ${parentY}, ${trunkX - 10} ${parentY}, ${trunkX} ${parentY}" />`);
      if (childYs.length > 1) lines.push(`<path class="${branchClass} framework-map-trunk" ${branchStyle} data-framework-parent="${esc(parent.id)}" d="M ${trunkX} ${Math.min(...childYs)} L ${trunkX} ${Math.max(...childYs)}" />`);
      childPositions.forEach(({ node, pos }) => {
        const childY = pos.y + pos.h / 2;
        const childLevel = Math.min(6, Math.max(1, Number(node.level) || 1));
        lines.push(`<path class="framework-map-branch framework-map-tree-edge framework-branch-${branchIndexFor(node)} level-${childLevel} framework-map-child-link" style="${branchStyleFor(node)}" data-framework-parent="${esc(parent.id)}" data-framework-child="${esc(node.id)}" d="M ${trunkX} ${childY} C ${trunkX + 10} ${childY}, ${pos.x - 10} ${childY}, ${pos.x} ${childY}" />`);
      });
    });
  }
  if (state.frameworkLayout === "fishbone") {
    (layout.fishboneSpines || []).forEach((spine) => lines.unshift(`<line class="framework-map-spine" x1="${spine.x1}" y1="${spine.y}" x2="${spine.x2}" y2="${spine.y}" />`));
  }
  const boxes = nodes.map((node) => {
    const pos = layout.positions.get(node.id);
    const isTask = node.topic_type === "task";
    const titleBlockHeight = pos.titleLines.length * 17;
    const summaryBlockHeight = pos.summaryLines.length ? 8 + pos.summaryLines.length * 13 : 0;
    const titleY = isTask ? 31 : Math.max(18, (pos.h - titleBlockHeight - summaryBlockHeight) / 2 + 12);
    const centerX = pos.w / 2;
    const centeredText = node.is_document_title || Number(node.level) === 2;
    const textX = centeredText ? centerX : 12;
    const textAnchor = centeredText ? "middle" : "start";
    const alignClass = centeredText ? "" : " is-left-aligned";
    const titleMarkup = `<text class="framework-map-title-text" text-anchor="${textAnchor}" x="${textX}" y="${titleY}">${pos.titleLines.map((line, index) => `<tspan x="${textX}" dy="${index ? 17 : 0}">${esc(line)}</tspan>`).join("")}</text>`;
    const typeMarkup = isTask ? `<text class="framework-map-type" text-anchor="${textAnchor}" x="${textX}" y="15">TASK</text>` : "";
    const summaryY = titleY + titleBlockHeight + 8;
    const summaryMarkup = pos.hasSummary && pos.expanded
      ? `<text class="framework-map-summary" text-anchor="${textAnchor}" x="${textX}" y="${summaryY}">${pos.summaryLines.map((line, index) => `<tspan x="${textX}" dy="${index ? 13 : 0}">${esc(line)}</tspan>`).join("")}</text>`
      : "";
    const levelClass = `level-${Math.min(6, Math.max(1, Number(node.level) || 1))}`;
    const branchIndex = branchIndexFor(node);
    const palette = node.is_document_title ? FRAMEWORK_THEME_PALETTES[state.frameworkTheme].root : frameworkThemePalette(state.frameworkTheme, branchIndex);
    const shadowColor = node.is_document_title || Number(node.level) === 2 ? "#0f0f0f" : Number(node.level) === 3 ? palette.line : "transparent";
    const shadowMarkup = node.is_document_title
      ? `<rect class="framework-map-node-shadow" x="6" y="6" width="${pos.w}" height="${pos.h}" style="fill:#0f0f0f;stroke:none;filter:none" opacity=".18"></rect>`
      : Number(node.level) === 2
        ? `<rect class="framework-map-node-shadow" x="5" y="5" width="${pos.w}" height="${pos.h}" style="fill:#0f0f0f;stroke:none;filter:none"></rect>`
        : Number(node.level) === 3
          ? `<rect class="framework-map-node-shadow" x="3" y="3" width="${pos.w}" height="${pos.h}" style="fill:${palette.line};stroke:none;filter:none"></rect>`
          : "";
    return `<g class="framework-map-node ${levelClass} framework-branch-${branchIndex}${alignClass} ${isTask ? "is-task" : ""} ${node.is_document_title ? "is-document-title is-root" : "is-topic"}" style="--framework-branch-bg:${palette.bg};--framework-branch-fg:${palette.fg};--framework-branch-line:${palette.line};--framework-branch-light:${palette.light || palette.bg};--framework-branch-lighter:${palette.lighter || palette.light || palette.bg};--framework-shadow-color:${shadowColor};" data-framework-branch="${branchIndex}" data-framework-node="${esc(node.id)}" transform="translate(${pos.x} ${pos.y})">${shadowMarkup}<rect width="${pos.w}" height="${pos.h}" rx="0"></rect>${titleMarkup}${typeMarkup}${summaryMarkup}</g>`;
  }).join("");
  container.innerHTML = `<svg class="framework-map-svg" width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" role="img" aria-label="文档框架${state.frameworkLayout === "fishbone" ? "鱼骨图" : "脑图"}">${lines.join("")}${boxes}</svg>`;
  updateFrameworkViewControls();
  if (shouldFit) {
    state.frameworkPan = { x: 0, y: 0, scale: 1 };
    state.frameworkNeedsFit = false;
    window.requestAnimationFrame(fitFrameworkMap);
  } else {
    updateFrameworkMapViewport();
  }
  container.querySelectorAll("[data-framework-node]").forEach((node) => {
    node.addEventListener("click", (event) => {
      clearTimeout(state.frameworkClickTimer);
      const target = state.frameworkNodes.find((item) => item.id === node.dataset.frameworkNode);
      if (!target || target.is_document_title) return;
      // 单击先落地选中状态，双击判断只延迟“打开编辑器”这一步。
      // 这样用户单击节点后立即点击顶部 Topic 编辑器按钮时，不会因为
      // 220ms 的双击判定窗口而被误判为未选择节点。
      state.frameworkTopicNode = target;
      state.frameworkClickTimer = setTimeout(() => {
        openFrameworkTopicEditor(target);
      }, 220);
    });
    node.addEventListener("dblclick", () => {
      clearTimeout(state.frameworkClickTimer);
      const target = state.frameworkNodes.find((item) => item.id === node.dataset.frameworkNode);
      if (!target) return;
      const next = window.prompt("编辑章节标题", target.title);
      if (next == null || !next.trim()) return;
      const lines = $("#framework-markdown").value.split(/\r?\n/);
      const raw = lines[target.lineIndex] || "";
      const prefix = raw.match(/^\s*#{1,6}\s+/)?.[0] || `${"#".repeat(target.level)} `;
      const suffix = target.topic_type === "task" ? " [task]" : "";
      lines[target.lineIndex] = `${prefix}${next.trim()}${suffix}`;
      $("#framework-markdown").value = lines.join("\n");
      handleFrameworkMarkdownInput();
    });
  });
}

function frameworkPresentationViewport() {
  const stage = $("#framework-presentation-stage");
  return { width: Math.max(1, stage?.clientWidth || window.innerWidth), height: Math.max(1, stage?.clientHeight || window.innerHeight - 146) };
}

function updateFrameworkPresentationViewport() {
  const world = $("#framework-presentation-world");
  if (!world) return;
  const pan = state.frameworkPresentationPan;
  world.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${pan.scale})`;
  const indicator = $("#framework-presentation-zoom");
  if (indicator) indicator.textContent = `${Math.round(pan.scale * 100)}%`;
}

function frameworkPresentationSvgSize() {
  const svg = $("#framework-presentation-world .framework-presentation-svg");
  if (!svg) return { width: 1, height: 1 };
  return { width: Number(svg.getAttribute("width")) || 1, height: Number(svg.getAttribute("height")) || 1 };
}

function fitFrameworkPresentation() {
  const { width, height } = frameworkPresentationViewport();
  const size = frameworkPresentationSvgSize();
  const scale = Math.min(1.35, Math.max(.08, Math.min((width - 70) / size.width, (height - 70) / size.height)));
  state.frameworkPresentationPan.scale = scale;
  state.frameworkPresentationPan.x = (width - size.width * scale) / 2;
  state.frameworkPresentationPan.y = (height - size.height * scale) / 2;
  updateFrameworkPresentationViewport();
}

function setFrameworkPresentationScale(nextScale, screenX, screenY) {
  const { width, height } = frameworkPresentationViewport();
  const pan = state.frameworkPresentationPan;
  const x = Math.min(width, Math.max(0, Number(screenX) || width / 2));
  const y = Math.min(height, Math.max(0, Number(screenY) || height / 2));
  const scale = Math.min(2.8, Math.max(.08, nextScale));
  const worldX = (x - pan.x) / pan.scale;
  const worldY = (y - pan.y) / pan.scale;
  pan.scale = scale;
  pan.x = x - worldX * scale;
  pan.y = y - worldY * scale;
  updateFrameworkPresentationViewport();
  $("#framework-presentation-zoom")?.classList.add("is-visible");
  clearTimeout(state.frameworkPresentationZoomTimer);
  state.frameworkPresentationZoomTimer = setTimeout(() => $("#framework-presentation-zoom")?.classList.remove("is-visible"), 1100);
}

function focusFrameworkPresentationNode(nodeId, animated = true) {
  const node = [...document.querySelectorAll("#framework-presentation-world [data-framework-node]")].find((element) => element.dataset.frameworkNode === nodeId);
  if (!node) return;
  const pan = state.frameworkPresentationPan;
  // 大型框架整体适配时会得到较小缩放；演示聚焦节点时提升到可读比例，
  // 避免节点虽然居中但文字仍然无法辨认。
  if (pan.scale < .62) pan.scale = .62;
  const centerNodeInStage = () => {
    const stage = $("#framework-presentation-stage");
    if (!stage) return;
    const stageRect = stage.getBoundingClientRect();
    const nodeRect = node.getBoundingClientRect();
    pan.x += stageRect.left + stageRect.width / 2 - (nodeRect.left + nodeRect.width / 2);
    pan.y += stageRect.top + stageRect.height / 2 - (nodeRect.top + nodeRect.height / 2);
    updateFrameworkPresentationViewport();
  };
  const world = $("#framework-presentation-world");
  if (animated && world) {
    world.style.transition = "transform .45s cubic-bezier(.22,1,.36,1)";
    centerNodeInStage();
    window.setTimeout(() => { world.style.transition = ""; }, 500);
  } else centerNodeInStage();
}

function updateFrameworkPresentationReveal() {
  const nodes = state.frameworkNodes;
  const current = Math.min(nodes.length - 1, Math.max(0, state.frameworkPresentationStep));
  state.frameworkPresentationStep = current;
  const revealed = new Set(nodes.slice(0, current + 1).map((node) => node.id));
  const world = $("#framework-presentation-world");
  if (!world) return;
  world.querySelectorAll("[data-framework-node]").forEach((element) => {
    const visible = revealed.has(element.dataset.frameworkNode);
    element.classList.toggle("is-presentation-hidden", !visible);
    element.classList.toggle("is-presentation-active", visible && element.dataset.frameworkNode === nodes[current]?.id);
  });
  world.querySelectorAll(".framework-map-branch[data-framework-parent]").forEach((element) => {
    const parentVisible = revealed.has(element.dataset.frameworkParent);
    const childVisible = element.dataset.frameworkChild
      ? revealed.has(element.dataset.frameworkChild)
      : nodes.some((node) => node.parentId === element.dataset.frameworkParent && revealed.has(node.id));
    element.classList.toggle("is-presentation-hidden", !(parentVisible && childVisible));
  });
  const currentLabel = $("#framework-presentation-current");
  const totalLabel = $("#framework-presentation-total");
  const range = $("#framework-presentation-range");
  if (currentLabel) currentLabel.textContent = String(current + 1);
  if (totalLabel) totalLabel.textContent = String(nodes.length || 1);
  if (range) { range.max = String(Math.max(0, nodes.length - 1)); range.value = String(current); }
  $("#framework-presentation-prev")?.toggleAttribute("disabled", current <= 0);
  $("#framework-presentation-next")?.toggleAttribute("disabled", current >= nodes.length - 1);
  focusFrameworkPresentationNode(nodes[current]?.id, true);
}

function renderFrameworkPresentation() {
  const world = $("#framework-presentation-world");
  const source = $("#framework-map .framework-map-svg");
  if (!world || !source || !state.frameworkNodes.length) return;
  const overlay = $("#framework-presentation");
  overlay?.classList.remove("framework-theme-poster", "framework-theme-pastel");
  overlay?.classList.add(`framework-theme-${state.frameworkTheme}`);
  const clone = source.cloneNode(true);
  clone.classList.add("framework-presentation-svg");
  // 主脑图当前可能处于局部缩放 viewBox；演示必须恢复完整世界坐标，否则文字会被压缩成模糊小块。
  clone.setAttribute("viewBox", `0 0 ${state.frameworkWorld?.width || clone.getAttribute("width")} ${state.frameworkWorld?.height || clone.getAttribute("height")}`);
  world.replaceChildren(clone);
  $("#framework-presentation-title").textContent = state.frameworkNodes.find((node) => node.is_document_title)?.title || "文档框架";
  updateFrameworkPresentationReveal();
}

function openFrameworkPresentation() {
  if (!state.frameworkNodes.length) return;
  const overlay = $("#framework-presentation");
  if (!overlay) return;
  state.frameworkPresentationOpen = true;
  state.frameworkPresentationStep = 0;
  state.frameworkPresentationPan = { x: 0, y: 0, scale: 1 };
  overlay.classList.add("is-open");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("is-presentation-open");
  renderFrameworkMap();
  window.requestAnimationFrame(renderFrameworkPresentation);
}

function closeFrameworkPresentation() {
  const overlay = $("#framework-presentation");
  if (!overlay) return;
  state.frameworkPresentationOpen = false;
  overlay.classList.remove("is-open");
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("is-presentation-open");
}

function setFrameworkPresentationStep(step) {
  if (!state.frameworkPresentationOpen || !state.frameworkNodes.length) return;
  state.frameworkPresentationStep = Math.max(0, Math.min(state.frameworkNodes.length - 1, Number(step) || 0));
  updateFrameworkPresentationReveal();
}

function setupFrameworkPresentation() {
  $("#framework-map-presentation")?.addEventListener("click", openFrameworkPresentation);
  $("#framework-presentation-close")?.addEventListener("click", closeFrameworkPresentation);
  $("#framework-presentation-prev")?.addEventListener("click", () => setFrameworkPresentationStep(state.frameworkPresentationStep - 1));
  $("#framework-presentation-next")?.addEventListener("click", () => setFrameworkPresentationStep(state.frameworkPresentationStep + 1));
  $("#framework-presentation-range")?.addEventListener("input", (event) => setFrameworkPresentationStep(event.target.value));
  $("#framework-presentation-fit")?.addEventListener("click", fitFrameworkPresentation);
  $("#framework-presentation-summary")?.addEventListener("click", () => {
    state.frameworkShowSummaries = !state.frameworkShowSummaries;
    $("#framework-presentation-summary").textContent = state.frameworkShowSummaries ? "收起概述" : "展开概述";
    renderFrameworkMap();
    window.requestAnimationFrame(renderFrameworkPresentation);
  });
  const stage = $("#framework-presentation-stage");
  stage?.addEventListener("pointerdown", (event) => {
    if (event.target.closest?.("[data-framework-node]")) return;
    stage.setPointerCapture?.(event.pointerId);
    state.frameworkPresentationWasDragged = false;
    state.frameworkPresentationDrag = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, panX: state.frameworkPresentationPan.x, panY: state.frameworkPresentationPan.y };
    stage.classList.add("is-panning");
  });
  stage?.addEventListener("pointermove", (event) => {
    const drag = state.frameworkPresentationDrag;
    if (!drag || drag.pointerId !== event.pointerId) return;
    state.frameworkPresentationWasDragged = true;
    state.frameworkPresentationPan.x = drag.panX + event.clientX - drag.startX;
    state.frameworkPresentationPan.y = drag.panY + event.clientY - drag.startY;
    updateFrameworkPresentationViewport();
  });
  const endDrag = () => { state.frameworkPresentationDrag = null; stage?.classList.remove("is-panning"); };
  stage?.addEventListener("pointerup", endDrag);
  stage?.addEventListener("pointercancel", endDrag);
  stage?.addEventListener("wheel", (event) => {
    if (!state.frameworkPresentationOpen) return;
    const rect = stage.getBoundingClientRect();
    setFrameworkPresentationScale(state.frameworkPresentationPan.scale * (event.deltaY > 0 ? .9 : 1.1), event.clientX - rect.left, event.clientY - rect.top);
    event.preventDefault();
  }, { passive: false });
  stage?.addEventListener("click", (event) => {
    if (state.frameworkPresentationWasDragged) { state.frameworkPresentationWasDragged = false; return; }
    const node = event.target.closest?.("[data-framework-node]");
    if (!node) {
      setFrameworkPresentationStep(state.frameworkPresentationStep + 1);
      return;
    }
    const index = state.frameworkNodes.findIndex((item) => item.id === node.dataset.frameworkNode);
    if (index < 0) return;
    // 点击当前已展示的节点继续出现下一个框；点击其他已展示节点则聚焦该节点。
    setFrameworkPresentationStep(index === state.frameworkPresentationStep ? index + 1 : index);
  });
  document.addEventListener("keydown", (event) => {
    if (!state.frameworkPresentationOpen) return;
    if (event.key === "Escape") { event.preventDefault(); closeFrameworkPresentation(); }
    else if (event.key === "ArrowRight" || event.key === "ArrowDown" || event.key === "PageDown") { event.preventDefault(); setFrameworkPresentationStep(state.frameworkPresentationStep + 1); }
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp" || event.key === "PageUp") { event.preventDefault(); setFrameworkPresentationStep(state.frameworkPresentationStep - 1); }
    else if (event.key === "+" || event.key === "=") { event.preventDefault(); const { width, height } = frameworkPresentationViewport(); setFrameworkPresentationScale(state.frameworkPresentationPan.scale * 1.15, width / 2, height / 2); }
    else if (event.key === "-") { event.preventDefault(); const { width, height } = frameworkPresentationViewport(); setFrameworkPresentationScale(state.frameworkPresentationPan.scale * .87, width / 2, height / 2); }
    else if (event.key === "0") { event.preventDefault(); fitFrameworkPresentation(); }
  });
}

function handleFrameworkMarkdownInput() {
  const editor = $("#framework-markdown");
  if (!editor) return;
  state.frameworkNodes = parseFrameworkMarkdown(editor.value);
  $("#framework-line-count").textContent = `${editor.value.split(/\r?\n/).length} 行 · ${state.frameworkNodes.length} 个节点`;
  const focusEditor = $("#framework-markdown-focus-editor");
  if (focusEditor && document.activeElement !== focusEditor) focusEditor.value = editor.value;
  updateFrameworkFocusLineCount();
  renderFrameworkMarkdownFocusPreview();
  updateFrameworkStatus("有未保存修改", "is-dirty");
  renderFrameworkMap();
  renderFrameworkOutlinePreview($("#framework-outline-preview"), editor.value);
  if (state.frameworkPresentationOpen) window.requestAnimationFrame(renderFrameworkPresentation);
  clearTimeout(state.frameworkDebounce);
  state.frameworkDebounce = setTimeout(() => saveFramework("autosave"), 900);
}

async function loadProjectFramework(projectId) {
  if (!projectId) return;
  state.frameworkWorld = null;
  state.frameworkPreviewNodeId = null;
  state.frameworkNeedsFit = true;
  state.frameworkPan = { x: 0, y: 0, scale: 1 };
  try {
    const data = await request(`/api/projects/${encodeURIComponent(projectId)}/framework`);
    state.currentFramework = data;
    // 切换项目时先清空旧项目内容，避免“没有框架的项目”沿用上一个项目的 Markdown。
    // 已有保存框架优先；只有当前分析明确属于该项目时才使用分析结果兜底。
    const projectAnalysis = state.currentAnalysis?.project_id === projectId ? state.currentAnalysis : null;
    $("#framework-markdown").value = data.markdown || (projectAnalysis?.topic_outline?.length ? frameworkMarkdownFromOutline(projectAnalysis.topic_outline, state.selectedProject?.name || "文档") : "");
    state.frameworkLayout = data.layout || "mindmap";
    updateFrameworkLayoutControls();
    state.frameworkNodes = parseFrameworkMarkdown($("#framework-markdown").value);
    updateFrameworkStatus(data.markdown ? "已保存" : "未生成");
    renderFrameworkMap();
    $("#framework-line-count").textContent = `${$("#framework-markdown").value.split(/\r?\n/).length} 行 · ${state.frameworkNodes.length} 个节点`;
    const focusEditor = $("#framework-markdown-focus-editor");
    if (focusEditor) focusEditor.value = $("#framework-markdown").value;
    updateFrameworkFocusLineCount();
    renderFrameworkMarkdownFocusPreview();
    renderFrameworkOutlinePreview($("#framework-outline-preview"), $("#framework-markdown").value);
    updateFrameworkViewControls();
    if (data.supporting_analysis) renderAnalysisResult(data.supporting_analysis);
  } catch (error) {
    showMessage("#analysis-message", error.message, "error");
  }
}

async function saveFramework(source = "manual") {
  const projectId = $("#analysis-project")?.value;
  const editor = $("#framework-markdown");
  if (!projectId || !editor || !editor.value.trim()) {
    if (source !== "autosave") showMessage("#analysis-message", "请先生成或输入 Markdown 框架。", "error");
    return;
  }
  try {
    const framework = await request(`/api/projects/${encodeURIComponent(projectId)}/framework`, { method: "PUT", body: JSON.stringify({ markdown: editor.value, layout: state.frameworkLayout, source, skills: selectedSkillNames("#analysis-skill-options"), material_ids: state.projectMaterials.map((item) => item.id), analysis_id: state.currentAnalysis?.id || "", node_count: state.frameworkNodes.length, supporting_analysis: state.currentAnalysis }) });
    state.currentFramework = framework;
    updateFrameworkStatus("已保存", "is-saved");
    if (source !== "autosave") showMessage("#analysis-message", "框架已保存，并生成一个新的本地版本。", "success");
  } catch (error) {
    updateFrameworkStatus("保存失败", "is-error");
    if (source !== "autosave") showMessage("#analysis-message", error.message, "error");
  }
}

async function generateFrameworkWithAI(event) {
  if (event) event.preventDefault();
  const projectId = $("#analysis-project")?.value;
  if (!projectId) { showMessage("#analysis-message", "请先创建并选择项目。", "error"); return; }
  if (!state.projectMaterials.length) { showMessage("#analysis-message", "请先添加至少一份需求材料。", "error"); return; }
  const button = $("#run-analysis-button");
  if (button) button.disabled = true;
  showMessage("#analysis-message", "正在根据材料和 Skill 生成 Markdown 框架…");
  try {
    const result = await request(`/api/projects/${encodeURIComponent(projectId)}/framework/generate`, { method: "POST", body: JSON.stringify({ analysis_note: $("#analysis-note").value.trim(), skills: selectedSkillNames("#analysis-skill-options"), layout: state.frameworkLayout }) });
    state.currentFramework = result;
    $("#framework-markdown").value = result.markdown || "";
    state.currentAnalysis = result.supporting_analysis || null;
    state.frameworkNodes = parseFrameworkMarkdown($("#framework-markdown").value);
    state.frameworkNeedsFit = true;
    renderFrameworkMap();
    $("#framework-line-count").textContent = `${$("#framework-markdown").value.split(/\r?\n/).length} 行 · ${state.frameworkNodes.length} 个节点`;
    const focusEditor = $("#framework-markdown-focus-editor");
    if (focusEditor) focusEditor.value = $("#framework-markdown").value;
    updateFrameworkFocusLineCount();
    renderFrameworkMarkdownFocusPreview();
    renderFrameworkOutlinePreview($("#framework-outline-preview"), $("#framework-markdown").value);
    updateFrameworkStatus("已生成，未保存修改", "is-dirty");
    renderAnalysisResult(state.currentAnalysis);
    showMessage("#analysis-message", "文档框架已生成，可直接编辑 Markdown 或切换图形布局。", "success");
    await loadProjects();
  } catch (error) {
    showMessage("#analysis-message", error.message, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

function exportFrameworkMarkdown() {
  const content = $("#framework-markdown")?.value || "";
  if (!content.trim()) { showMessage("#analysis-message", "暂无可导出的框架。", "error"); return; }
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${state.selectedProject?.name || "文档框架"}-框架.md`;
  link.click();
  URL.revokeObjectURL(link.href);
  showMessage("#analysis-message", "Markdown 框架已下载。", "success");
}

function frameworkTopicPayload(node, prompt, skills, options = {}) {
  const summary = String(node?.summary || "").trim();
  return {
    topic_type: node?.topic_type === "task" ? "task" : "concept",
    title: String(node?.title || "").trim(),
    shortdesc: summary || `说明“${String(node?.title || "本章节").trim()}”相关内容。`,
    brief: options.brief ?? summary,
    chapter_summary: summary,
    generation_prompt: String(prompt || "").trim(),
    skills: skills || selectedSkillNames("#analysis-skill-options"),
    inherit_project_skills: true,
    heading_level: Math.max(1, Math.min(3, Number(node?.level || 2) - 1)),
    framework_node_key: `line:${node?.lineIndex ?? ""}`,
    material_ids: options.materialIds ?? (state.currentFramework?.material_ids || state.projectMaterials.map((item) => item.id)),
    include_image_placeholder: Boolean(options.includeImagePlaceholder),
    include_ref_placeholder: Boolean(options.includeRefPlaceholder),
    ai_generate: true,
  };
}

function renderFrameworkTopicResult(topic) {
  state.frameworkTopic = topic;
  const xml = $("#framework-topic-xml");
  if (xml) xml.value = topic?.xml || "";
  const status = $("#framework-topic-output-status");
  if (status) status.textContent = topic ? `${topic.generation_source === "ai" ? "AI 已生成" : "已生成"} · ${topic.validation?.status || "待校验"}` : "尚未生成";
  const save = $("#save-framework-topic-xml");
  if (save) save.disabled = !topic;
  renderValidation(topic?.validation, "#framework-topic-validation", "#framework-topic-output-status");
}

async function openFrameworkTopicEditor(node) {
  const projectId = $("#analysis-project")?.value || state.selectedProject?.id;
  if (!projectId || !node) return;
  const currentNode = state.frameworkNodes.find((item) => item.id === node.id) || node;
  if (state.frameworkTopicLoading && state.frameworkTopicNode?.id === currentNode.id && state.frameworkTopicOpenPromise) {
    return state.frameworkTopicOpenPromise;
  }
  const openToken = ++state.frameworkTopicOpenToken;
  state.frameworkTopicNode = currentNode;
  state.frameworkTopic = null;
  state.frameworkTopicDraftSkills = null;
  state.frameworkPanel = "topic";
  state.frameworkTopicLoading = true;
  updateFrameworkPanelControls();
  const project = state.selectedProject || state.projects.find((item) => item.id === projectId) || {};
  const dialog = $("#framework-topic-dialog");
  // 先显示弹窗和当前节点的最小上下文，再等待已有 Topic 查询结果。
  // 本地数据读取或磁盘较慢时，用户仍能立即看到点击已经生效。
  $("#framework-topic-project-name").textContent = project.name || "当前项目";
  $("#framework-topic-project-product").textContent = project.product || "未填写产品";
  $("#framework-topic-project-version").textContent = project.version || "未填写版本";
  $("#framework-topic-title").value = currentNode.title || "";
  $("#framework-topic-type").value = currentNode.topic_type === "task" ? "task" : "concept";
  $("#framework-topic-level").value = String(Math.max(1, Math.min(3, currentNode.level - 1)));
  $("#framework-topic-summary").value = currentNode.summary || "";
  $("#framework-topic-brief").value = currentNode.summary || "";
  $("#framework-topic-prompt").value = $("#analysis-note")?.value || "";
  $("#framework-topic-context").textContent = `正在读取“${currentNode.title}”的 Topic 数据…`;
  $("#framework-topic-message").textContent = "正在读取已有 Topic…";
  renderFrameworkTopicMaterialOptions(state.currentFramework?.material_ids || state.projectMaterials.map((item) => item.id));
  renderSkillOptions("#framework-topic-skill-options");
  renderFrameworkTopicResult(null);
  dialog?.classList.remove("is-drawer");
  if (dialog && !dialog.open) dialog.showModal();
  const task = (async () => {
    const existingData = await request(`/api/projects/${encodeURIComponent(projectId)}/topics`).catch(() => ({ topics: [] }));
    // 如果用户在请求返回前切换了节点，旧请求只做清理，不得覆盖新节点。
    if (openToken !== state.frameworkTopicOpenToken || state.frameworkTopicNode?.id !== currentNode.id) return;
    const topic = (existingData.topics || []).find((item) => item.framework_node_key === `line:${currentNode.lineIndex}`) || (existingData.topics || []).find((item) => item.title === currentNode.title && item.topic_type === currentNode.topic_type);
    if (topic) state.frameworkTopic = topic;
    $("#framework-topic-title").value = topic?.title || currentNode.title;
    $("#framework-topic-type").value = topic?.topic_type === "task" ? "task" : currentNode.topic_type === "task" ? "task" : "concept";
    $("#framework-topic-level").value = String(topic?.heading_level || Math.max(1, Math.min(3, currentNode.level - 1)));
    $("#framework-topic-summary").value = topic?.chapter_summary || topic?.shortdesc || currentNode.summary || "";
    $("#framework-topic-brief").value = topic?.brief || topic?.chapter_summary || currentNode.summary || "";
    $("#framework-topic-prompt").value = topic?.generation_prompt || $("#analysis-note")?.value || "";
    $("#framework-topic-context").textContent = `来自框架第 ${currentNode.level} 级节点 · ${state.projectMaterials.length} 份材料 · 可在生成前调整 Skill 和提示词。`;
    renderFrameworkTopicMaterialOptions(topic?.material_ids ?? state.currentFramework?.material_ids ?? state.projectMaterials.map((item) => item.id));
    $("#framework-topic-image-placeholder").checked = Boolean(topic?.include_image_placeholder);
    $("#framework-topic-ref-placeholder").checked = Boolean(topic?.include_ref_placeholder);
    renderSkillOptions("#framework-topic-skill-options");
    renderFrameworkTopicResult(topic);
    $("#framework-topic-message").textContent = "";
  })();
  state.frameworkTopicOpenPromise = task;
  try {
    await task;
  } finally {
    if (openToken === state.frameworkTopicOpenToken) {
      state.frameworkTopicLoading = false;
      state.frameworkTopicOpenPromise = null;
      updateFrameworkPanelControls();
    }
  }
}

function frameworkTopicDialogPayload() {
  const node = state.frameworkTopicNode || {};
  const summary = $("#framework-topic-summary")?.value.trim() || "";
  const brief = $("#framework-topic-brief")?.value.trim() || "";
  const materialIds = [...($("#framework-topic-materials")?.selectedOptions || [])].map((option) => option.value);
  return {
    ...frameworkTopicPayload({ ...node, title: $("#framework-topic-title").value.trim(), topic_type: $("#framework-topic-type").value, level: Number($("#framework-topic-level").value) + 1, summary }, $("#framework-topic-prompt").value, selectedSkillNames("#framework-topic-skill-options"), {
      brief: brief || summary,
      materialIds,
      includeImagePlaceholder: $("#framework-topic-image-placeholder")?.checked,
      includeRefPlaceholder: $("#framework-topic-ref-placeholder")?.checked,
    }),
    title: $("#framework-topic-title").value.trim(),
    shortdesc: summary || `说明“${$("#framework-topic-title").value.trim()}”相关内容。`,
    chapter_summary: summary,
    heading_level: Number($("#framework-topic-level").value) || 1,
    inherit_project_skills: skillInheritanceEnabled("#framework-topic-skill-options"),
  };
}

function clearFrameworkTopicForm() {
  const node = state.frameworkTopicNode;
  if (!node) return;
  state.frameworkTopic = null;
  state.frameworkTopicDraftSkills = null;
  $("#framework-topic-title").value = "";
  $("#framework-topic-summary").value = "";
  $("#framework-topic-brief").value = "";
  $("#framework-topic-prompt").value = "";
  $("#framework-topic-image-placeholder").checked = false;
  $("#framework-topic-ref-placeholder").checked = false;
  const materials = $("#framework-topic-materials");
  if (materials) [...materials.options].forEach((option) => { option.selected = false; });
  $("#framework-topic-xml").value = "";
  renderFrameworkTopicResult(null);
  renderSkillOptions("#framework-topic-skill-options");
  showMessage("#framework-topic-message", "已清空本次 Topic 输入和 XML，可重新填写。", "success");
}

async function generateFrameworkTopic(forceRegenerate = false) {
  const projectId = $("#analysis-project")?.value || state.selectedProject?.id;
  const node = state.frameworkTopicNode;
  if (!projectId || !node) return;
  const payload = frameworkTopicDialogPayload();
  if (!payload.title) {
    showMessage("#framework-topic-message", "Topic 标题不能为空。", "error");
    return;
  }
  const buttons = [$("#generate-framework-topic"), $("#regenerate-framework-topic"), $("#save-framework-topic-xml")];
  buttons.forEach((button) => { if (button) button.disabled = true; });
  showMessage("#framework-topic-message", forceRegenerate || state.frameworkTopic ? "正在根据最新提示词重新生成 XML…" : "正在生成 Topic XML…");
  try {
    let topic;
    if (state.frameworkTopic?.id) {
      topic = await request(`/api/projects/${encodeURIComponent(projectId)}/topics/${encodeURIComponent(state.frameworkTopic.id)}/generate`, { method: "POST", body: JSON.stringify(payload) });
    } else {
      topic = await request(`/api/projects/${encodeURIComponent(projectId)}/topics/generate`, { method: "POST", body: JSON.stringify(payload) });
    }
    renderFrameworkTopicResult(topic);
    state.frameworkTopicNode.topic_id = topic.id;
    showMessage("#framework-topic-message", "Topic XML 已生成并保存，可继续手工修改。", "success");
    await loadProjectTopics(projectId);
    await loadProjects();
  } catch (error) {
    showMessage("#framework-topic-message", error.message, "error");
  } finally {
    buttons.forEach((button) => { if (button) button.disabled = false; });
    if (!state.frameworkTopic) $("#save-framework-topic-xml").disabled = true;
  }
}

async function saveFrameworkTopicXml() {
  if (!state.frameworkTopic?.id) return;
  const projectId = state.frameworkTopic.project_id;
  showMessage("#framework-topic-message", "正在保存 XML 修改…");
  try {
    const topic = await request(`/api/projects/${encodeURIComponent(projectId)}/topics/${encodeURIComponent(state.frameworkTopic.id)}`, { method: "PUT", body: JSON.stringify({ xml: $("#framework-topic-xml").value }) });
    renderFrameworkTopicResult(topic);
    await loadProjectTopics(projectId);
    showMessage("#framework-topic-message", "XML 修改已保存。", "success");
  } catch (error) {
    showMessage("#framework-topic-message", error.message, "error");
  }
}

async function copyFrameworkTopicXml() {
  const content = $("#framework-topic-xml")?.value || "";
  if (!content) { showMessage("#framework-topic-message", "暂无可复制的 XML。", "error"); return; }
  try {
    await navigator.clipboard.writeText(content);
  } catch (error) {
    const area = $("#framework-topic-xml");
    area.focus(); area.select(); document.execCommand("copy");
  }
  showMessage("#framework-topic-message", "XML 已复制到剪贴板。", "success");
}

function downloadFrameworkTopic() {
  const content = $("#framework-topic-xml")?.value || "";
  const title = $("#framework-topic-title")?.value.trim() || "topic";
  if (!content) { showMessage("#framework-topic-message", "暂无可下载的 XML。", "error"); return; }
  const format = $("#framework-topic-download-format")?.value || "xml";
  let body = content;
  let extension = format;
  let type = "text/plain;charset=utf-8";
  if (format === "markdown") { body = `# ${title}\n\n\`\`\`xml\n${content}\n\`\`\`\n`; extension = "md"; type = "text/markdown;charset=utf-8"; }
  if (format === "word") { body = `<html><head><meta charset="utf-8"></head><body><h1>${escapeHtml(title)}</h1><pre>${escapeHtml(content)}</pre></body></html>`; extension = "doc"; type = "application/msword;charset=utf-8"; }
  const blob = new Blob([body], { type });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob); link.download = `${title}.${extension}`; link.click(); URL.revokeObjectURL(link.href);
  showMessage("#framework-topic-message", `已下载 ${extension.toUpperCase()} 文件。`, "success");
}

async function batchGenerateFrameworkTopics() {
  const projectId = $("#analysis-project")?.value || state.selectedProject?.id;
  const nodes = state.frameworkNodes.filter((node) => !node.is_document_title && node.title.trim());
  if (!projectId) { showMessage("#analysis-message", "请先选择项目。", "error"); return; }
  if (!nodes.length) { showMessage("#analysis-message", "当前框架没有可生成的 Topic 节点。", "error"); return; }
  const button = $("#batch-generate-topics-button");
  if (button) button.disabled = true;
  const data = await request(`/api/projects/${encodeURIComponent(projectId)}/topics`).catch(() => ({ topics: [] }));
  let completed = 0; let failed = 0;
  showMessage("#analysis-message", `开始批量生成，共 ${nodes.length} 个 Topic…`);
  try {
    for (const node of nodes) {
      const existing = (data.topics || []).find((item) => item.framework_node_key === `line:${node.lineIndex}`);
      const payload = frameworkTopicPayload(node, $("#analysis-note")?.value || "", selectedSkillNames("#analysis-skill-options"));
      try {
        if (existing) await request(`/api/projects/${encodeURIComponent(projectId)}/topics/${encodeURIComponent(existing.id)}/generate`, { method: "POST", body: JSON.stringify(payload) });
        else await request(`/api/projects/${encodeURIComponent(projectId)}/topics/generate`, { method: "POST", body: JSON.stringify(payload) });
        completed += 1;
      } catch (error) {
        failed += 1;
      }
      showMessage("#analysis-message", `批量生成进度：${completed + failed}/${nodes.length}（成功 ${completed}，失败 ${failed}）`);
    }
    await loadProjectTopics(projectId);
    await loadProjects();
    showMessage("#analysis-message", `批量生成完成：成功 ${completed} 个，失败 ${failed} 个。`, failed ? "error" : "success");
  } finally {
    if (button) button.disabled = false;
  }
}

function renderAnalysisItems(selector, items, emptyText = "暂无") {
  const node = $(selector);
  if (!node) return;
  if (!items?.length) {
    node.innerHTML = `<div class="tree-empty">${escapeHtml(emptyText)}</div>`;
    return;
  }
  node.innerHTML = items.map((item) => {
    const title = item.item || item.question || item.title || "未命名条目";
    const details = [item.evidence, item.reason, item.suggestion, item.basis].filter(Boolean);
    const tags = [item.confidence, item.owner, item.priority].filter(Boolean);
    const sources = item.source_materials?.length ? `来源：${item.source_materials.join("、")}` : "来源：未标注";
    return `<article class="analysis-item"><div class="analysis-item-title">${escapeHtml(title)}${tags.length ? `<span>${escapeHtml(tags.join(" · "))}</span>` : ""}</div>${details.map((detail) => `<p>${escapeHtml(detail)}</p>`).join("")}<small>${escapeHtml(sources)}</small></article>`;
  }).join("");
}

function renderAnalysisOutline(items) {
  const node = $("#analysis-outline");
  if (!node) return;
  if (!items?.length) {
    node.innerHTML = `<div class="tree-empty">暂无 Topic 框架。</div>`;
    return;
  }
  node.innerHTML = items.map((item, index) => `<div class="analysis-outline-row" style="--outline-indent:${Math.max(0, Number(item.level || 1) - 1) * 18}px"><span class="outline-order">${String(index + 1).padStart(2, "0")}</span><span class="outline-type">${escapeHtml(item.type === "task" ? "TASK" : "CONCEPT")}</span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.shortdesc || item.basis || "待补充短描述")}</small>${item.change_status ? `<em class="outline-change-status">${escapeHtml(item.change_status)}</em>` : ""}</div>`).join("");
}

function renderAnalysisResult(result) {
  state.currentAnalysis = result || null;
  const badge = $("#analysis-status-badge");
  const meta = $("#analysis-meta");
  const summary = $("#analysis-summary");
  if (!result) {
    if (badge) { badge.textContent = "未分析"; badge.className = "count-badge"; }
    if (meta) meta.textContent = "完成分析后，这里会显示分析版本和证据范围。";
    if (summary) summary.innerHTML = `<div class="report-empty">等待需求分析</div>`;
    ["#confirmed-count", "#missing-count", "#question-count", "#outline-count"].forEach((selector) => { if ($(selector)) $(selector).textContent = "0"; });
    renderAnalysisItems("#confirmed-items", [], "—");
    renderAnalysisItems("#missing-items", [], "—");
    renderAnalysisItems("#question-items", [], "—");
    renderAnalysisOutline([]);
    return;
  }
  const confirmed = result.confirmed_items || [];
  const missing = result.missing_materials || [];
  const questions = result.questions || [];
  const outline = result.topic_outline || [];
  if (badge) { badge.textContent = questions.length || missing.length ? "需确认" : "已完成"; badge.className = `count-badge ${questions.length || missing.length ? "is-invalid" : "is-valid"}`; }
  if (meta) meta.textContent = `${formatDate(result.created_at)} · ${result.model || "AI 模型"} · ${result.material_ids?.length || 0} 份材料 · 版本 ${result.id || "—"}`;
  if (summary) summary.innerHTML = `<p>${escapeHtml(result.summary || "AI 未返回摘要，请检查原始材料和分析结果。")}</p>`;
  [["#confirmed-count", confirmed.length], ["#missing-count", missing.length], ["#question-count", questions.length], ["#outline-count", outline.length]].forEach(([selector, value]) => {
    if ($(selector)) $(selector).textContent = value;
  });
  renderAnalysisItems("#confirmed-items", confirmed);
  renderAnalysisItems("#missing-items", missing);
  renderAnalysisItems("#question-items", questions);
  renderAnalysisOutline(outline);
}

function renderAnalysisHistory() {
  const node = $("#analysis-history");
  if (!node) return;
  if (!state.analysisVersions.length) { node.innerHTML = ""; return; }
  node.innerHTML = `<div class="analysis-history-heading">历史分析版本</div>${state.analysisVersions.slice().reverse().map((item) => `<div class="analysis-history-row"><span>${escapeHtml(formatDate(item.created_at))}</span><span>${escapeHtml(item.model || "AI")}</span><span>${item.topic_count || 0} 个 Topic · ${item.question_count || 0} 个待确认</span></div>`).join("")}`;
}

async function loadProjectAnalysis(projectId) {
  if (!projectId) return;
  try {
    const data = await request(`/api/projects/${encodeURIComponent(projectId)}/analysis`);
    if (state.selectedProject?.id !== projectId && $("#analysis-project")?.value !== projectId) return;
    state.analysisVersions = data.versions || [];
    renderAnalysisResult(data.latest);
    renderAnalysisHistory();
  } catch (error) {
    showMessage("#analysis-message", error.message, "error");
  }
}

async function runRequirementsAnalysis(event) {
  return generateFrameworkWithAI(event);
}

function renderSkillList() {
  const list = $("#skill-list");
  const count = $("#skill-count");
  if (!list) return;
  if (count) count.textContent = state.skills.length;
  if (!state.skills.length) {
    list.innerHTML = `<div class="tree-empty">暂无 Skill。</div>`;
    return;
  }
  list.innerHTML = state.skills.map((skill) => `
    <button type="button" class="skill-list-item ${state.currentSkillId === skill.id ? "is-selected" : ""}" data-skill-id="${escapeHtml(skill.id)}">
      <span class="skill-list-mark ${skill.required ? "is-required" : ""}">${skill.required ? "✓" : "◆"}</span><span class="skill-list-copy"><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description || "未填写描述")}</small></span><span class="skill-list-state">${skill.required ? "必选" : skill.source === "builtin" ? (skill.enabled ? "内置 · 启用" : "内置 · 停用") : skill.enabled ? "启用" : "停用"}</span>
    </button>
  `).join("");
  list.querySelectorAll("[data-skill-id]").forEach((node) => node.addEventListener("click", () => editSkill(node.dataset.skillId)));
}

function formatFileSize(size) {
  const value = Number(size || 0);
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.ceil(value / 1024)} KB`;
  return `${value} B`;
}

function renderSkillAttachments() {
  const list = $("#skill-attachment-list");
  if (!list) return;
  if (!state.skillAttachments.length) {
    list.innerHTML = `<div class="tree-empty">暂无附件</div>`;
    return;
  }
  list.innerHTML = state.skillAttachments.map((attachment) => {
    const key = attachment.id || attachment.client_id;
    const link = attachment.download_url ? `<a href="${escapeHtml(attachment.download_url)}" target="_blank" rel="noreferrer">${escapeHtml(attachment.name)}</a>` : `<strong>${escapeHtml(attachment.name)}</strong>`;
    return `<div class="skill-attachment-item"><span class="attachment-mark">↳</span><span class="attachment-copy">${link}<small>${escapeHtml(attachment.mime_type || "本地文件")} · ${formatFileSize(attachment.size)}${attachment.data_url ? " · 待保存" : ""}</small></span><button type="button" class="icon-button is-danger" data-remove-attachment="${escapeHtml(key)}" aria-label="移除附件">×</button></div>`;
  }).join("");
  list.querySelectorAll("[data-remove-attachment]").forEach((button) => button.addEventListener("click", () => {
    state.skillAttachments = state.skillAttachments.filter((item) => (item.id || item.client_id) !== button.dataset.removeAttachment);
    renderSkillAttachments();
  }));
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(`附件“${file.name}”读取失败。`));
    reader.readAsDataURL(file);
  });
}

async function handleSkillAttachments(event) {
  const files = [...(event.target.files || [])];
  event.target.value = "";
  for (const file of files) {
    if (file.size > 12 * 1024 * 1024) {
      showMessage("#skill-message", `附件“${file.name}”不能超过 12 MB。`, "error");
      continue;
    }
    if (state.skillAttachments.length >= 20) {
      showMessage("#skill-message", "每个 Skill 最多支持 20 个附件。", "error");
      break;
    }
    try {
      state.skillAttachments.push({ client_id: `pending_${Date.now()}_${Math.random().toString(16).slice(2)}`, name: file.name, mime_type: file.type || "application/octet-stream", size: file.size, data_url: await readFileAsDataUrl(file) });
    } catch (error) {
      showMessage("#skill-message", error.message, "error");
    }
  }
  renderSkillAttachments();
}

function resetSkillEditor() {
  state.currentSkillId = null;
  $("#skill-form")?.reset();
  $("#skill-enabled").checked = true;
  $("#skill-editor-title").textContent = "新建 Skill";
  $("#skill-message").textContent = "";
  $("#skill-name").disabled = false;
  $("#skill-description").disabled = false;
  $("#skill-content").readOnly = false;
  $("#skill-enabled").disabled = false;
  $("#delete-skill-button").disabled = true;
  $("#save-skill-button").disabled = false;
  state.skillAttachments = [];
  renderSkillAttachments();
  renderSkillList();
}

function editSkill(skillId) {
  const skill = state.skills.find((item) => item.id === skillId);
  if (!skill) return;
  state.currentSkillId = skill.id;
  $("#skill-name").value = skill.name || "";
  $("#skill-description").value = skill.description || "";
  $("#skill-content").value = skill.content || "";
  state.skillAttachments = (skill.attachments || []).map((item) => ({ ...item }));
  $("#skill-enabled").checked = skill.enabled !== false;
  $("#skill-editor-title").textContent = skill.source === "builtin" ? skill.name : "编辑 Skill";
  // 内置 Skill 的名称和必选状态固定，但内容、说明和附件可以由用户维护。
  $("#skill-name").disabled = skill.source === "builtin";
  $("#skill-description").disabled = false;
  $("#skill-content").readOnly = false;
  $("#skill-enabled").disabled = Boolean(skill.required);
  $("#delete-skill-button").disabled = skill.source === "builtin";
  $("#save-skill-button").disabled = false;
  renderSkillAttachments();
  renderSkillList();
}

function prepareNewSkillEditor() {
  resetSkillEditor();
  $("#skill-name").disabled = false;
  $("#skill-description").disabled = false;
  $("#skill-content").readOnly = false;
  $("#skill-enabled").disabled = false;
  $("#save-skill-button").disabled = false;
  $("#skill-name").focus();
}

function importSkillFile(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const rawName = file.name.replace(/\.(md|markdown|txt)$/i, "");
    const content = String(reader.result || "");
    const frontmatterName = content.match(/^name:\s*(.+)$/im)?.[1]?.trim();
    const frontmatterDescription = content.match(/^description:\s*["']?(.+?)["']?$/im)?.[1]?.trim();
    prepareNewSkillEditor();
    $("#skill-name").value = frontmatterName || (rawName === "SKILL" ? "自定义 Skill" : rawName);
    $("#skill-description").value = frontmatterDescription || `从 ${file.name} 导入`;
    $("#skill-content").value = content;
    showMessage("#skill-message", `已读取 ${file.name}，请确认信息后保存。`, "success");
  };
  reader.onerror = () => showMessage("#skill-message", "Skill 文件读取失败，请重试。", "error");
  reader.readAsText(file, "utf-8");
}

async function saveSkill(event) {
  event.preventDefault();
  const payload = { name: $("#skill-name").value.trim(), description: $("#skill-description").value.trim(), content: $("#skill-content").value, enabled: $("#skill-enabled").checked, attachments: state.skillAttachments };
  try {
    const url = state.currentSkillId ? `/api/skills/${encodeURIComponent(state.currentSkillId)}` : "/api/skills";
    const skill = await request(url, { method: state.currentSkillId ? "PUT" : "POST", body: JSON.stringify(payload) });
    await loadSkills();
    editSkill(skill.id);
    showMessage("#skill-message", "Skill 已保存，可在 Topic 生成时选择。", "success");
  } catch (error) {
    showMessage("#skill-message", error.message, "error");
  }
}

async function deleteCurrentSkill() {
  if (!state.currentSkillId) return;
  const skill = state.skills.find((item) => item.id === state.currentSkillId);
  if (!skill || skill.required) return;
  if (!window.confirm(`确定删除“${skill.name}”吗？`)) return;
  try {
    await request(`/api/skills/${encodeURIComponent(skill.id)}`, { method: "DELETE" });
    resetSkillEditor();
    await loadSkills();
    showMessage("#skill-message", "Skill 已删除。", "success");
  } catch (error) {
    showMessage("#skill-message", error.message, "error");
  }
}

function addOutlineItem(item = { title: "", level: 1 }) {
  state.outlineItems.push({ title: item.title || "", level: Number(item.level) || 1 });
  renderOutlineBuilder();
}

function renderOutlineBuilder() {
  const builder = $("#outline-builder");
  if (!builder) return;
  if (!state.outlineItems.length) {
    builder.innerHTML = `<div class="outline-empty">暂未添加章节，生成时将使用“功能概述”。</div>`;
    return;
  }
  builder.innerHTML = state.outlineItems.map((item, index) => `
    <div class="outline-row" data-outline-index="${index}"><span class="outline-index">${String(index + 1).padStart(2, "0")}</span><input class="outline-title" type="text" value="${escapeHtml(item.title)}" placeholder="例如：功能概述" aria-label="第 ${index + 1} 个章节标题" /><select class="outline-level" aria-label="第 ${index + 1} 个章节层级"><option value="1" ${item.level === 1 ? "selected" : ""}>1 级</option><option value="2" ${item.level === 2 ? "selected" : ""}>2 级</option><option value="3" ${item.level === 3 ? "selected" : ""}>3 级</option></select><button type="button" class="icon-button" data-outline-up="${index}" aria-label="上移">↑</button><button type="button" class="icon-button" data-outline-down="${index}" aria-label="下移">↓</button><button type="button" class="icon-button is-danger" data-outline-remove="${index}" aria-label="删除">×</button></div>
  `).join("");
  builder.querySelectorAll(".outline-title").forEach((input) => input.addEventListener("input", (event) => { state.outlineItems[Number(event.target.closest(".outline-row").dataset.outlineIndex)].title = event.target.value; }));
  builder.querySelectorAll(".outline-level").forEach((select) => select.addEventListener("change", (event) => { state.outlineItems[Number(event.target.closest(".outline-row").dataset.outlineIndex)].level = Number(event.target.value); }));
  builder.querySelectorAll("[data-outline-up]").forEach((button) => button.addEventListener("click", () => moveOutlineItem(Number(button.dataset.outlineUp), -1)));
  builder.querySelectorAll("[data-outline-down]").forEach((button) => button.addEventListener("click", () => moveOutlineItem(Number(button.dataset.outlineDown), 1)));
  builder.querySelectorAll("[data-outline-remove]").forEach((button) => button.addEventListener("click", () => { state.outlineItems.splice(Number(button.dataset.outlineRemove), 1); renderOutlineBuilder(); }));
}

function moveOutlineItem(index, delta) {
  const nextIndex = index + delta;
  if (nextIndex < 0 || nextIndex >= state.outlineItems.length) return;
  [state.outlineItems[index], state.outlineItems[nextIndex]] = [state.outlineItems[nextIndex], state.outlineItems[index]];
  renderOutlineBuilder();
}

function collectOutlineItems() {
  return state.outlineItems.map((item) => ({ title: String(item.title || "").trim(), level: Number(item.level) || 1 })).filter((item) => item.title);
}

function toggleTopicFields() {
  const isTask = $("#topic-type")?.value === "task";
  $("#topic-outline-label")?.classList.toggle("is-hidden", isTask);
  $("#topic-prereq-label")?.classList.toggle("is-hidden", !isTask);
  $("#topic-steps-label")?.classList.toggle("is-hidden", !isTask);
}

function splitInput(selector) {
  return $(selector).value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function renderValidation(validation, reportSelector = "#topic-validation", badgeSelector = "#topic-status-badge") {
  const report = $(reportSelector);
  const badge = $(badgeSelector);
  if (!report || !badge) return;
  if (!validation) {
    report.innerHTML = `<div class="report-empty">等待生成 XML</div>`;
    badge.textContent = "未生成";
    badge.className = "count-badge";
    return;
  }
  const items = [
    ...(validation.errors || []).map((item) => `<li class="report-error">ERROR · ${escapeHtml(item)}</li>`),
    ...(validation.warnings || []).map((item) => `<li class="report-warning">WARN · ${escapeHtml(item)}</li>`),
  ];
  report.innerHTML = `<div class="report-summary"><span class="report-dot ${validation.ok ? "is-ok" : "is-error"}"></span><strong>${escapeHtml(validation.status)}</strong><span>GUID ${validation.guid_count} · 占位符 ${validation.placeholder_count}</span></div>${items.length ? `<ul>${items.join("")}</ul>` : `<div class="report-pass">XML 可解析，未发现 GUID 或待处理占位符。</div>`}`;
  badge.textContent = validation.status;
  badge.className = `count-badge ${validation.ok ? "is-valid" : "is-invalid"}`;
}

function renderTopicResult(topic) {
  state.currentTopic = topic;
  state.topicInheritProjectSkills = topic?.inherit_project_skills !== false;
  $("#topic-xml").value = topic.xml || "";
  const sourceLabel = topic.generation_source === "ai" ? `AI 生成${topic.generation_model ? ` · ${topic.generation_model}` : ""}` : "本地模板";
  const skillLabel = (topic.skills || []).join(" → ");
  $("#topic-meta").textContent = `${topic.title} · ${topic.topic_type === "task" ? "Task" : topic.topic_type === "appendix" ? "附录类 Concept" : "Concept"} · ${sourceLabel} · Skill：${skillLabel || "HIK Writing Skill"} · ${topic.inherit_project_skills === false ? "独立配置" : "继承项目"}`;
  $("#save-topic-xml").disabled = false;
  renderValidation(topic.validation);
  renderSkillOptions();
}

function renderExpandedTopic(topic) {
  const panel = $("#topic-expanded-editor");
  if (!panel) return;
  if (!topic) {
    panel.classList.add("is-hidden");
    panel.innerHTML = "";
    return;
  }
  panel.classList.remove("is-hidden");
  panel.innerHTML = `<div class="expanded-editor-heading"><div><p class="section-kicker">XML CODE / EXPANDED TOPIC</p><h3>${escapeHtml(topic.title)}</h3><span>${escapeHtml(topic.topic_type === "task" ? "Task" : topic.topic_type === "appendix" ? "附录类 Concept" : "Concept")} · ${topic.level || topic.heading_level || 1} 级标题</span></div><div class="expanded-editor-tools"><span class="count-badge" id="tree-status-badge">未校验</span><button type="button" class="secondary-button compact-button" id="close-expanded-topic">收起</button></div></div><textarea id="tree-xml-editor" class="xml-editor" spellcheck="false"></textarea><div class="validation-report" id="tree-validation"></div><div class="form-actions"><button type="button" class="primary-button" id="save-tree-xml">保存 XML 修改</button></div><div class="inline-message" id="tree-message" role="status"></div>`;
  $("#tree-xml-editor").value = topic.xml || "";
  renderValidation(topic.validation, "#tree-validation", "#tree-status-badge");
  $("#close-expanded-topic").addEventListener("click", () => renderExpandedTopic(null));
  $("#save-tree-xml").addEventListener("click", saveExpandedTopicXml);
}

async function openTopicForProject(projectId) {
  await selectProject(projectId);
  showView("topic-view");
  $("#topic-project").value = projectId;
  clearTopicForm();
}

async function expandTopicXml(projectId, topicId) {
  if (!projectId || !topicId) return;
  try {
    const topic = await request(`/api/projects/${encodeURIComponent(projectId)}/topics/${encodeURIComponent(topicId)}`);
    state.selectedProject = state.projects.find((project) => project.id === projectId) || state.selectedProject;
    renderTopicResult(topic);
    renderExpandedTopic(topic);
  } catch (error) {
    showMessage("#topic-message", error.message, "error");
  }
}

async function submitTopic(mode) {
  const form = $("#topic-form");
  if (!form.reportValidity()) return;
  const projectId = $("#topic-project").value;
  if (!projectId) {
    showMessage("#topic-message", "请先创建并选择项目。", "error");
    return;
  }
  const generationMode = $("#topic-mode").value || "new";
  const targetId = $("#topic-target")?.value || "";
  const targetTopic = state.projectTopics.find((topic) => topic.id === targetId);
  if (generationMode === "optimize" && !targetTopic) {
    showMessage("#topic-message", "优化模式请选择一个已有 Topic。", "error");
    return;
  }
  const buttons = [$("#ai-generate-topic"), $("#template-generate-topic"), $("#clear-topic-form")];
  buttons.forEach((button) => { if (button) button.disabled = true; });
  showMessage("#topic-message", generationMode === "optimize" ? "正在基于原 Topic 优化 XML…" : mode === "ai" ? "正在调用 AI 生成 XML…" : "正在生成本地模板…");
  try {
    const payload = {
      generation_mode: generationMode,
      topic_type: $("#topic-type").value,
      title: $("#topic-title").value.trim(),
      shortdesc: $("#topic-shortdesc").value.trim(),
      brief: $("#topic-brief").value.trim(),
      chapter_summary: targetTopic?.chapter_summary || $("#topic-shortdesc").value.trim(),
      generation_prompt: generationMode === "optimize" ? $("#topic-optimization-prompt").value.trim() : "",
      outline: collectOutlineItems(),
      prerequisites: splitInput("#topic-prerequisites"),
      steps: splitInput("#topic-steps"),
      skills: selectedSkillNames(),
      heading_level: Number($("#topic-heading-level").value) || 1,
      material_ids: [...($("#topic-materials")?.selectedOptions || [])].map((option) => option.value),
      inherit_project_skills: skillInheritanceEnabled(),
      include_image_placeholder: $("#topic-image-placeholder").checked,
      include_ref_placeholder: $("#topic-ref-placeholder").checked,
      ai_generate: mode === "ai",
    };
    const endpoint = generationMode === "optimize"
      ? `/api/projects/${encodeURIComponent(projectId)}/topics/${encodeURIComponent(targetId)}/generate`
      : `/api/projects/${encodeURIComponent(projectId)}/topics`;
    const topic = await request(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderTopicResult(topic);
    showMessage("#topic-message", generationMode === "optimize" ? "优化版 XML 已保存，可继续人工审核。" : mode === "ai" ? "AI XML 已生成并保存，可继续人工审核。" : "模板 XML 已生成并保存，可继续人工编辑。", "success");
    await loadProjects();
    await loadProjectTopics(projectId);
  } catch (error) {
    showMessage("#topic-message", error.message, "error");
  } finally {
    buttons.forEach((button) => { if (button) button.disabled = false; });
  }
}

function createTopic(event) {
  event.preventDefault();
  submitTopic("ai");
}

function generateTemplateTopic() {
  submitTopic("template");
}

async function saveTopicXml() {
  if (!state.currentTopic) return;
  showMessage("#topic-message", "正在保存 XML 修改…");
  try {
    const topic = await request(`/api/projects/${encodeURIComponent(state.currentTopic.project_id)}/topics/${encodeURIComponent(state.currentTopic.id)}`, {
      method: "PUT",
      body: JSON.stringify({ xml: $("#topic-xml").value }),
    });
    renderTopicResult(topic);
    showMessage("#topic-message", "XML 修改已保存。", "success");
  } catch (error) {
    showMessage("#topic-message", error.message, "error");
  }
}

async function saveExpandedTopicXml() {
  if (!state.currentTopic) return;
  showMessage("#tree-message", "正在保存 XML 修改…");
  try {
    const topic = await request(`/api/projects/${encodeURIComponent(state.currentTopic.project_id)}/topics/${encodeURIComponent(state.currentTopic.id)}`, {
      method: "PUT",
      body: JSON.stringify({ xml: $("#tree-xml-editor").value }),
    });
    renderTopicResult(topic);
    renderExpandedTopic(topic);
    showMessage("#tree-message", "XML 修改已保存。", "success");
  } catch (error) {
    showMessage("#tree-message", error.message, "error");
  }
}

function clearTopicForm() {
  $("#topic-form").reset();
  $("#topic-project").value = state.selectedProject?.id || "";
  state.currentTopic = null;
  state.topicInheritProjectSkills = true;
  state.topicDraftSkills = null;
  $("#topic-xml").value = "";
  $("#topic-meta").textContent = "生成后可直接编辑 XML，并保存到当前项目的 topics 目录。";
  $("#save-topic-xml").disabled = true;
  $("#topic-message").textContent = "";
  renderExpandedTopic(null);
  state.outlineItems = [];
  renderOutlineBuilder();
  renderSkillOptions();
  renderValidation(null);
  toggleTopicFields();
  toggleTopicMode();
  renderTopicMaterialOptions();
}

async function loadSettings() {
  const settings = await request("/api/settings");
  $("#provider").value = settings.provider || "openai-compatible";
  $("#base-url").value = settings.base_url || "";
  $("#model").value = settings.model || "";
  $("#temperature").value = settings.temperature ?? 0.2;
  $("#timeout").value = settings.timeout_seconds ?? 60;
  $("#api-key").placeholder = settings.api_key_configured ? "已配置，留空表示保持现有 Key" : "输入后保存到系统凭据存储";
}

async function saveSettings(event) {
  event.preventDefault();
  showMessage("#settings-message", "正在保存…");
  try {
    const payload = {
      provider: $("#provider").value,
      base_url: $("#base-url").value.trim(),
      model: $("#model").value.trim(),
      api_key: $("#api-key").value,
      temperature: Number($("#temperature").value),
      timeout_seconds: Number($("#timeout").value),
    };
    const settings = await request("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    $("#api-key").value = "";
    $("#api-key").placeholder = settings.api_key_configured ? "已配置，留空表示保持现有 Key" : "输入后保存到系统凭据存储";
    showMessage("#settings-message", "配置已保存，API Key 未写入项目文件。", "success");
  } catch (error) {
    showMessage("#settings-message", error.message, "error");
  }
}

async function testConnection() {
  showMessage("#settings-message", "正在测试连接…");
  try {
    const result = await request("/api/settings/test", { method: "POST", body: "{}" });
    showMessage("#settings-message", `连接成功：${result.endpoint}`, "success");
    $("#connection-card").innerHTML = `<span class="status-dot"></span><div><strong>连接成功</strong><p>${escapeHtml(result.model)} · HTTP ${result.status}</p></div>`;
  } catch (error) {
    showMessage("#settings-message", error.message, "error");
    $("#connection-card").innerHTML = `<span class="status-dot" style="background:#b64e42"></span><div><strong>连接失败</strong><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function createProject(event) {
  event.preventDefault();
  showMessage("#project-message", "正在创建…");
  try {
    const project = await request("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        name: $("#project-name").value.trim(),
        product: $("#project-product").value.trim(),
        version: $("#project-version").value.trim(),
        description: $("#project-description").value.trim(),
        mode: $("#project-mode").value,
        base_project_id: $("#project-base-project").value,
        reference_project_ids: checkedReferenceProjectIds("#project-reference-projects"),
        skills: ["HIK Writing Skill", "HIK DITA Rule", ...splitInput("#project-skills")],
        cover: state.coverSelection || { type: "asset", file: editorialAssets[0]?.file },
      }),
    });
    state.selectedProject = project;
    closeDialog();
    await loadProjects();
  } catch (error) {
    showMessage("#project-message", error.message, "error");
  }
}

async function openDialog(initialMode = "new") {
  $("#project-form").reset();
  $("#project-mode").value = initialMode;
  toggleProjectModeFields();
  renderProjectCreationOptions();
  $("#project-message").textContent = "";
  $("#project-dialog").showModal();
  $("#project-name").focus();
  $("#project-cover-file-name").textContent = "正在读取素材…";
  try {
    await loadEditorialAssets();
    resetCoverSelection();
  } catch (error) {
    $("#project-cover-file-name").textContent = error.message;
    $("#project-cover-gallery").innerHTML = `<p class="cover-empty">素材读取失败，请检查 web/assets/editorial 文件夹。</p>`;
  }
}

function closeDialog() {
  $("#project-dialog").close();
}

function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
}

async function boot() {
  try {
    const savedTheme = localStorage.getItem("hik-framework-theme");
    if (savedTheme && FRAMEWORK_THEME_PALETTES[savedTheme]) state.frameworkTheme = savedTheme;
  } catch (error) { /* 使用默认示例四色主题 */ }
  setupNavigation();
  updateFrameworkThemeControls();
  updateFrameworkLayoutControls();
  document.querySelectorAll("[data-framework-theme]").forEach((button) => button.addEventListener("click", () => applyFrameworkTheme(button.dataset.frameworkTheme)));
  $("#framework-theme-select")?.addEventListener("change", (event) => {
    applyFrameworkTheme(event.target.value);
  });
  $("#new-project-button").addEventListener("click", openDialog);
  $("#analysis-back-button")?.addEventListener("click", () => showView("projects-view"));
  document.querySelectorAll("[data-mode-filter]").forEach((card) => {
    const applyModeFilter = () => {
      const mode = card.dataset.modeFilter || "new";
      state.projectModeFilter = state.projectModeFilter === mode ? "all" : mode;
      document.querySelectorAll("[data-mode-filter]").forEach((item) => item.classList.toggle("is-filtered", state.projectModeFilter === item.dataset.modeFilter));
      renderProjects();
    };
    card.addEventListener("click", (event) => {
      if (event.target.closest?.("[data-create-project]")) return;
      applyModeFilter();
    });
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        applyModeFilter();
      }
    });
  });
  document.querySelectorAll("[data-create-project]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    openDialog(button.dataset.createProject || "new");
  }));
  $("#close-dialog").addEventListener("click", closeDialog);
  $("#cancel-dialog").addEventListener("click", closeDialog);
  $("#close-cover-preview")?.addEventListener("click", () => $("#cover-preview-dialog")?.close());
  $("#cover-preview-dialog")?.addEventListener("click", (event) => { if (event.target === $("#cover-preview-dialog")) $("#cover-preview-dialog").close(); });
  $("#project-form").addEventListener("submit", createProject);
  $("#project-mode").addEventListener("change", toggleProjectModeFields);
  $("#project-cover-file").addEventListener("change", handleCoverUpload);
  $("#analysis-form").addEventListener("submit", runRequirementsAnalysis);
  $("#analysis-material-files").addEventListener("change", handleAnalysisMaterialFiles);
  $("#paste-material-button")?.addEventListener("click", () => { $("#analysis-pasted-text")?.classList.toggle("is-hidden"); $("#save-pasted-material")?.classList.toggle("is-hidden"); $("#analysis-pasted-text")?.focus(); });
  $("#save-pasted-material")?.addEventListener("click", savePastedMaterial);
  $("#framework-excel-file")?.addEventListener("change", importFrameworkExcel);
  $("#reload-analysis-button")?.addEventListener("click", async () => {
    const projectId = $("#analysis-project")?.value;
    if (projectId) await Promise.all([loadProjectMaterials(projectId), loadProjectAnalysis(projectId), loadProjectFramework(projectId)]);
  });
  $("#analysis-project").addEventListener("change", async () => {
    const projectId = $("#analysis-project").value;
    if (!projectId) return;
    await selectProject(projectId);
    renderSkillOptions("#analysis-skill-options");
    await Promise.all([loadProjectMaterials(projectId), loadProjectAnalysis(projectId), loadProjectFramework(projectId)]);
  });
  $("#framework-markdown")?.addEventListener("input", handleFrameworkMarkdownInput);
  $("#framework-markdown")?.addEventListener("click", (event) => syncFrameworkPreviewSelectionFromEditor(event.currentTarget));
  $("#framework-markdown")?.addEventListener("keyup", (event) => syncFrameworkPreviewSelectionFromEditor(event.currentTarget));
  $("#framework-markdown")?.addEventListener("paste", handleFrameworkMarkdownPaste);
  $("#framework-markdown-paste")?.addEventListener("click", () => pasteFrameworkFromClipboard($("#framework-markdown")));
  $("#framework-markdown-preview")?.addEventListener("click", () => {
    setFrameworkPanel("map");
    setFrameworkView("outline");
  });
  document.querySelectorAll("[data-framework-view]").forEach((button) => button.addEventListener("click", () => setFrameworkView(button.dataset.frameworkView)));
  $("#framework-markdown-fullscreen")?.addEventListener("click", openFrameworkMarkdownFullscreen);
  $("#framework-markdown-focus-close")?.addEventListener("click", closeFrameworkMarkdownFullscreen);
  $("#framework-markdown-focus-paste")?.addEventListener("click", () => pasteFrameworkFromClipboard($("#framework-markdown-focus-editor")));
  $("#framework-markdown-focus-editor")?.addEventListener("input", (event) => {
    const mainEditor = $("#framework-markdown");
    if (mainEditor && mainEditor.value !== event.currentTarget.value) mainEditor.value = event.currentTarget.value;
    handleFrameworkMarkdownInput();
  });
  $("#framework-markdown-focus-editor")?.addEventListener("click", (event) => syncFrameworkPreviewSelectionFromEditor(event.currentTarget));
  $("#framework-markdown-focus-editor")?.addEventListener("keyup", (event) => syncFrameworkPreviewSelectionFromEditor(event.currentTarget));
  $("#framework-markdown-focus-editor")?.addEventListener("paste", handleFrameworkMarkdownPaste);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("#framework-markdown-focus")?.classList.contains("is-open")) {
      event.preventDefault();
      closeFrameworkMarkdownFullscreen();
    }
  });
  $("#regenerate-framework-button")?.addEventListener("click", () => generateFrameworkWithAI());
  $("#batch-generate-topics-button")?.addEventListener("click", batchGenerateFrameworkTopics);
  $("#save-framework-button")?.addEventListener("click", () => saveFramework("manual"));
  $("#export-framework-button")?.addEventListener("click", exportFrameworkMarkdown);
  $("#toggle-analysis-support")?.addEventListener("click", () => {
    const body = $("#analysis-support-body");
    const button = $("#toggle-analysis-support");
    body?.classList.toggle("is-collapsed");
    if (button) button.textContent = body?.classList.contains("is-collapsed") ? "展开" : "收起";
  });
  document.querySelectorAll("[data-framework-layout]").forEach((button) => button.addEventListener("click", () => {
    state.frameworkLayout = button.dataset.frameworkLayout || "mindmap";
    state.frameworkNeedsFit = true;
    document.querySelectorAll("[data-framework-layout]").forEach((item) => item.classList.toggle("is-active", item === button));
    renderFrameworkMap();
    if (state.frameworkPresentationOpen) window.requestAnimationFrame(renderFrameworkPresentation);
    updateFrameworkStatus("布局已切换，未保存修改", "is-dirty");
  }));
  $("#framework-layout-select")?.addEventListener("change", (event) => {
    state.frameworkLayout = event.target.value || "mindmap";
    state.frameworkNeedsFit = true;
    renderFrameworkMap();
    if (state.frameworkPresentationOpen) window.requestAnimationFrame(renderFrameworkPresentation);
    updateFrameworkStatus("布局已切换，未保存修改", "is-dirty");
  });
  $("#framework-map-reset")?.addEventListener("click", () => {
    fitFrameworkMap();
  });
  $("#framework-map-zoom-in")?.addEventListener("click", () => {
    const { width, height } = frameworkMapViewportSize();
    setFrameworkScaleAt(state.frameworkPan.scale * 1.2, width / 2, height / 2);
  });
  $("#framework-map-zoom-out")?.addEventListener("click", () => {
    const { width, height } = frameworkMapViewportSize();
    setFrameworkScaleAt(state.frameworkPan.scale / 1.2, width / 2, height / 2);
  });
  $("#framework-map-fit")?.addEventListener("click", fitFrameworkMap);
  $("#framework-summary-toggle")?.addEventListener("click", toggleFrameworkSummaries);
  $("#framework-map-fullscreen")?.addEventListener("click", toggleFrameworkFullscreen);
  $("#framework-toggle-map")?.addEventListener("click", () => {
    setFrameworkPanel(state.frameworkPanel === "map" ? "none" : "map");
  });
  $("#framework-toggle-topic")?.addEventListener("click", () => toggleFrameworkTopicPanel());
  setupFrameworkPresentation();
  document.addEventListener("fullscreenchange", () => {
    updateFrameworkFullscreenLabel();
    window.setTimeout(() => { if (state.frameworkWorld) fitFrameworkMap(); }, 80);
  });
  setupFrameworkMapGestures();
  setupFrameworkMapResizeObserver();
  updateFrameworkViewControls();
  updateFrameworkPanelControls();
  $("#topic-form").addEventListener("submit", createTopic);
  $("#template-generate-topic").addEventListener("click", generateTemplateTopic);
  $("#topic-type").addEventListener("change", toggleTopicFields);
  $("#topic-mode").addEventListener("change", toggleTopicMode);
  $("#topic-target").addEventListener("change", (event) => applyTopicTarget(event.target.value));
  $("#topic-project").addEventListener("change", async () => {
    if ($("#topic-project").value) {
      await selectProject($("#topic-project").value);
      renderTopicTargetOptions();
      renderTopicMaterialOptions();
    }
  });
  $("#clear-topic-form").addEventListener("click", clearTopicForm);
  $("#save-topic-xml").addEventListener("click", saveTopicXml);
  $("#framework-topic-form")?.addEventListener("submit", (event) => { event.preventDefault(); generateFrameworkTopic(false); });
  $("#close-framework-topic-dialog")?.addEventListener("click", () => $("#framework-topic-dialog")?.close());
  $("#framework-topic-dialog")?.addEventListener("close", () => {
    const dialog = $("#framework-topic-dialog");
    dialog?.classList.remove("is-drawer");
    // 关闭时使未完成的读取请求失效，避免旧请求完成后把 loading 状态
    // 留在界面上，导致下一次打开被误判为“仍在加载”。
    state.frameworkTopicOpenToken += 1;
    state.frameworkTopicLoading = false;
    state.frameworkTopicOpenPromise = null;
    state.frameworkPanel = "none";
    updateFrameworkPanelControls();
  });
  $("#clear-framework-topic-form")?.addEventListener("click", clearFrameworkTopicForm);
  $("#regenerate-framework-topic")?.addEventListener("click", () => generateFrameworkTopic(true));
  $("#save-framework-topic-xml")?.addEventListener("click", saveFrameworkTopicXml);
  $("#copy-framework-topic-xml")?.addEventListener("click", copyFrameworkTopicXml);
  $("#download-framework-topic")?.addEventListener("click", downloadFrameworkTopic);
  $("#add-outline-item").addEventListener("click", () => addOutlineItem());
  $("#skills-view")?.addEventListener("click", (event) => {
    if (event.target.closest("#new-skill-button")) prepareNewSkillEditor();
  });
  $("#skill-form").addEventListener("submit", saveSkill);
  $("#skill-import-file").addEventListener("change", importSkillFile);
  $("#skill-attachment-files").addEventListener("change", handleSkillAttachments);
  document.addEventListener("change", (event) => {
    const inheritInput = event.target.closest?.("input[data-skill-inherit]");
    if (!inheritInput) return;
    const container = inheritInput.closest(".skill-options");
    const selector = container?.id ? `#${container.id}` : "";
    if (!selector) return;
    const selected = selectedSkillNames(selector);
    if (selector === "#topic-skill-options") {
      state.topicInheritProjectSkills = inheritInput.checked;
      state.topicDraftSkills = selected;
    } else if (selector === "#framework-topic-skill-options") {
      state.frameworkTopicDraftSkills = selected;
    }
    renderSkillOptions(selector);
  });
  $("#cancel-skill-edit").addEventListener("click", resetSkillEditor);
  $("#delete-skill-button").addEventListener("click", deleteCurrentSkill);
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#test-connection").addEventListener("click", testConnection);
  try {
    await request("/api/health");
    $("#service-status").innerHTML = `<span class="status-dot"></span> 本地服务正常`;
    await Promise.all([loadProjects(), loadSettings(), loadSkills()]);
    renderOutlineBuilder();
    toggleTopicFields();
    toggleTopicMode();
    renderProjectCreationOptions();
  } catch (error) {
    $("#service-status").textContent = `服务异常：${error.message}`;
  }
}

boot();
