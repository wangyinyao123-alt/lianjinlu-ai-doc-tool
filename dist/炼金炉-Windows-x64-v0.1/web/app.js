const state = {
  projects: [],
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
};

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
  });
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
  $("#project-count").textContent = state.projects.length;
  if (!state.projects.length) {
    list.innerHTML = `<div class="empty-state"><div><div class="empty-icon">＋</div><p>还没有项目</p><p>先创建一个文档项目。</p></div></div>`;
    return;
  }
  list.innerHTML = state.projects.map((project) => `
    <button class="project-card ${state.selectedProject?.id === project.id ? "is-selected" : ""}" data-project-id="${project.id}">
      <div class="project-card-body">
        <div class="project-card-copy">
          <h4>${escapeHtml(project.name)}</h4>
          <div class="project-meta"><span>${escapeHtml(project.product || "未填写产品")}</span><span>${escapeHtml(project.version || "未填写版本")}</span></div>
          <div class="project-stage">${escapeHtml(project.stage)} · ${formatDate(project.updated_at)}</div>
        </div>
        ${project.cover_url ? `<img class="project-cover-thumb" src="${escapeHtml(project.cover_url)}" alt="${escapeHtml(project.name)} 项目封面" />` : `<span class="project-cover-thumb cover-placeholder">◎</span>`}
      </div>
    </button>
  `).join("");
  list.querySelectorAll("[data-project-id]").forEach((node) => {
    node.addEventListener("click", () => selectProject(node.dataset.projectId));
  });
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
        ${project.cover_url ? `<img class="detail-cover" src="${escapeHtml(project.cover_url)}" alt="${escapeHtml(project.name)} 项目封面" />` : `<div class="detail-cover cover-placeholder">◎</div>`}
        <span class="count-badge">${escapeHtml(project.stage)}</span>
      </div>
    </div>
    <div class="detail-facts">
      <div class="fact"><div class="fact-label">产品 / 模块</div><div class="fact-value">${escapeHtml(project.product || "—")}</div></div>
      <div class="fact"><div class="fact-label">版本</div><div class="fact-value">${escapeHtml(project.version || "—")}</div></div>
      <div class="fact"><div class="fact-label">启用 Skill</div><div class="fact-value">HIK Writing</div></div>
    </div>
    <div class="pipeline">
      <p class="section-kicker">PIPELINE</p>
      <div class="pipeline-row"><span class="pipeline-step active">项目</span><span class="pipeline-arrow">→</span><span class="pipeline-step">素材</span><span class="pipeline-arrow">→</span><span class="pipeline-step">需求分析</span><span class="pipeline-arrow">→</span><span class="pipeline-step">Topic</span></div>
    </div>
    <div class="topic-tree-block"><div class="topic-tree-heading"><div><p class="section-kicker">TOPIC TREE / DRAG TO RESTRUCTURE</p><strong>项目 Topic</strong></div><span class="panel-note">仅显示标题</span></div><div id="topic-tree" class="topic-tree"><div class="tree-empty">正在读取 Topic…</div></div><p class="tree-hint">拖动标题调整顺序；向右拖动可设置为下一级。单击标题展开 XML Code。</p></div>
    <div id="topic-expanded-editor" class="topic-expanded-editor is-hidden"></div>
    <div class="detail-actions"><button type="button" class="primary-button" data-create-topic="${escapeHtml(project.id)}">＋ 新建 Topic</button><span class="detail-skill-note">${escapeHtml((project.skills || ["HIK Writing Skill"]).join(" · "))}</span></div>
  `;
  panel.querySelector("[data-create-topic]")?.addEventListener("click", () => openTopicForProject(project.id));
  renderTopicTree();
  loadProjectTopics(project.id);
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
  renderTopicProjects();
  renderAnalysisProjects();
}

async function loadProjectTopics(projectId) {
  try {
    const data = await request(`/api/projects/${encodeURIComponent(projectId)}/topics`);
    if (state.selectedProject?.id !== projectId) return;
    state.projectTopics = data.topics || [];
    renderTopicTree();
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
  tree.innerHTML = state.projectTopics.map((topic) => `
    <button type="button" class="topic-tree-item" draggable="true" data-topic-id="${escapeHtml(topic.id)}" data-level="${topic.level || topic.heading_level || 1}">
      <span class="drag-handle" aria-hidden="true">⋮⋮</span><span class="topic-tree-title">${escapeHtml(topic.title)}</span>
    </button>
  `).join("");
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
    await Promise.all([loadProjectMaterials(projectId), loadProjectAnalysis(projectId)]);
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
    if (state.selectedProject) {
      $("#analysis-project").value = state.selectedProject.id;
      loadProjectMaterials(state.selectedProject.id);
      loadProjectAnalysis(state.selectedProject.id);
    }
  }
  if (viewId === "topic-view") {
    renderTopicProjects();
    renderSkillOptions();
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

function renderAnalysisProjects() {
  const select = $("#analysis-project");
  if (!select) return;
  const currentValue = state.selectedProject?.id || select.value;
  select.innerHTML = state.projects.length
    ? state.projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`).join("")
    : `<option value="">请先创建项目</option>`;
  if (currentValue && state.projects.some((project) => project.id === currentValue)) select.value = currentValue;
}

function renderSkillOptions(containerSelector = "#topic-skill-options") {
  const container = $(containerSelector);
  if (!container) return;
  if (!state.skills.length) {
    container.innerHTML = `<div class="field-hint">暂无可用 Skill，请先配置 Skill。</div>`;
    return;
  }
  const projectSkills = state.selectedProject?.skills || [];
  const selected = new Set(containerSelector === "#analysis-skill-options" ? projectSkills : (state.currentTopic?.skills || projectSkills));
  container.innerHTML = state.skills.map((skill) => {
    const checked = skill.required || selected.has(skill.name);
    const disabled = skill.required || !skill.enabled;
    return `<label class="skill-choice ${disabled && !skill.required ? "is-disabled" : ""}"><input type="checkbox" data-skill-name="${escapeHtml(skill.name)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} /> <span><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description || (skill.required ? "必选规范 Skill" : "自定义生成约束"))}</small></span>${skill.required ? '<em>必选</em>' : skill.enabled ? "" : '<em>已停用</em>'}</label>`;
  }).join("");
}

async function loadSkills() {
  const data = await request("/api/skills");
  state.skills = data.skills || [];
  renderSkillOptions();
  renderSkillOptions("#analysis-skill-options");
  renderSkillList();
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
  if (!state.projectMaterials.length) {
    list.innerHTML = `<div class="tree-empty">还没有材料，请选择本地文件上传。</div>`;
    return;
  }
  list.innerHTML = state.projectMaterials.map((material) => `
    <div class="analysis-material-item">
      <span class="material-file-mark">${escapeHtml((material.extension || "FILE").replace(".", "").slice(0, 4).toUpperCase())}</span>
      <span class="material-file-copy"><a href="${escapeHtml(material.download_url)}" target="_blank" rel="noreferrer">${escapeHtml(material.name)}</a><small>${escapeHtml(formatFileSize(material.size))} · ${escapeHtml(material.extract_message || "")}</small></span>
      <span class="material-file-status status-${escapeHtml(material.extract_status)}">${escapeHtml(formatAnalysisStatus(material.extract_status))}</span>
      <button type="button" class="icon-button is-danger" data-delete-material="${escapeHtml(material.id)}" aria-label="删除材料">×</button>
    </div>
  `).join("");
  list.querySelectorAll("[data-delete-material]").forEach((button) => button.addEventListener("click", () => deleteAnalysisMaterial(button.dataset.deleteMaterial)));
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
  node.innerHTML = items.map((item, index) => `<div class="analysis-outline-row" style="--outline-indent:${Math.max(0, Number(item.level || 1) - 1) * 18}px"><span class="outline-order">${String(index + 1).padStart(2, "0")}</span><span class="outline-type">${escapeHtml(item.type === "task" ? "TASK" : "CONCEPT")}</span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.shortdesc || item.basis || "待补充短描述")}</small></div>`).join("");
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
  $("#confirmed-count").textContent = confirmed.length;
  $("#missing-count").textContent = missing.length;
  $("#question-count").textContent = questions.length;
  $("#outline-count").textContent = outline.length;
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
  event.preventDefault();
  const projectId = $("#analysis-project")?.value;
  if (!projectId) { showMessage("#analysis-message", "请先创建并选择项目。", "error"); return; }
  if (!state.projectMaterials.length) { showMessage("#analysis-message", "请先上传至少一份需求材料。", "error"); return; }
  const button = $("#run-analysis-button");
  if (button) button.disabled = true;
  showMessage("#analysis-message", "正在提取证据并调用 AI 分析…");
  try {
    const result = await request(`/api/projects/${encodeURIComponent(projectId)}/analysis`, {
      method: "POST",
      body: JSON.stringify({ analysis_note: $("#analysis-note").value.trim(), skills: selectedSkillNames("#analysis-skill-options") }),
    });
    renderAnalysisResult(result);
    await loadProjectAnalysis(projectId);
    await loadProjects();
    showMessage("#analysis-message", "需求分析已保存，可根据待确认问题补充材料或进入 Topic 开发。", "success");
  } catch (error) {
    showMessage("#analysis-message", error.message, "error");
  } finally {
    if (button) button.disabled = false;
  }
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
      <span class="skill-list-mark ${skill.required ? "is-required" : ""}">${skill.required ? "✓" : "◆"}</span><span class="skill-list-copy"><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description || "未填写描述")}</small></span><span class="skill-list-state">${skill.required ? "必选" : skill.enabled ? "启用" : "停用"}</span>
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
  $("#skill-editor-title").textContent = skill.required ? "HIK Writing Skill" : "编辑 Skill";
  $("#skill-name").disabled = Boolean(skill.required);
  $("#skill-description").disabled = Boolean(skill.required);
  $("#skill-content").readOnly = Boolean(skill.required);
  $("#skill-enabled").disabled = Boolean(skill.required);
  $("#delete-skill-button").disabled = Boolean(skill.required);
  $("#save-skill-button").disabled = Boolean(skill.required);
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
  $("#topic-xml").value = topic.xml || "";
  const sourceLabel = topic.generation_source === "ai" ? `AI 生成${topic.generation_model ? ` · ${topic.generation_model}` : ""}` : "本地模板";
  $("#topic-meta").textContent = `${topic.title} · ${topic.topic_type === "task" ? "Task" : topic.topic_type === "appendix" ? "附录类 Concept" : "Concept"} · ${sourceLabel} · 已保存到当前项目`;
  $("#save-topic-xml").disabled = false;
  renderValidation(topic.validation);
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
  document.querySelector('[data-view="topic-view"]')?.click();
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
  const buttons = [$("#ai-generate-topic"), $("#template-generate-topic"), $("#clear-topic-form")];
  buttons.forEach((button) => { if (button) button.disabled = true; });
  showMessage("#topic-message", mode === "ai" ? "正在调用 AI 生成 XML…" : "正在生成本地模板…");
  try {
    const topic = await request(`/api/projects/${encodeURIComponent(projectId)}/topics`, {
      method: "POST",
      body: JSON.stringify({
        topic_type: $("#topic-type").value,
        title: $("#topic-title").value.trim(),
        shortdesc: $("#topic-shortdesc").value.trim(),
        brief: $("#topic-brief").value.trim(),
        outline: collectOutlineItems(),
        prerequisites: splitInput("#topic-prerequisites"),
        steps: splitInput("#topic-steps"),
        skills: selectedSkillNames(),
        heading_level: Number($("#topic-heading-level").value) || 1,
        include_image_placeholder: $("#topic-image-placeholder").checked,
        include_ref_placeholder: $("#topic-ref-placeholder").checked,
        ai_generate: mode === "ai",
      }),
    });
    renderTopicResult(topic);
    showMessage("#topic-message", mode === "ai" ? "AI XML 已生成并保存，可继续人工审核。" : "模板 XML 已生成并保存，可继续人工编辑。", "success");
    await loadProjects();
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
        skills: ["HIK Writing Skill", ...splitInput("#project-skills")],
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

async function openDialog() {
  $("#project-form").reset();
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
  setupNavigation();
  $("#new-project-button").addEventListener("click", openDialog);
  $("#close-dialog").addEventListener("click", closeDialog);
  $("#cancel-dialog").addEventListener("click", closeDialog);
  $("#project-form").addEventListener("submit", createProject);
  $("#project-cover-file").addEventListener("change", handleCoverUpload);
  $("#analysis-form").addEventListener("submit", runRequirementsAnalysis);
  $("#analysis-material-files").addEventListener("change", handleAnalysisMaterialFiles);
  $("#reload-analysis-button").addEventListener("click", async () => {
    const projectId = $("#analysis-project")?.value;
    if (projectId) await Promise.all([loadProjectMaterials(projectId), loadProjectAnalysis(projectId)]);
  });
  $("#analysis-project").addEventListener("change", async () => {
    const projectId = $("#analysis-project").value;
    if (!projectId) return;
    await selectProject(projectId);
    renderSkillOptions("#analysis-skill-options");
    await Promise.all([loadProjectMaterials(projectId), loadProjectAnalysis(projectId)]);
  });
  $("#topic-form").addEventListener("submit", createTopic);
  $("#template-generate-topic").addEventListener("click", generateTemplateTopic);
  $("#topic-type").addEventListener("change", toggleTopicFields);
  $("#topic-project").addEventListener("change", async () => {
    if ($("#topic-project").value) await selectProject($("#topic-project").value);
  });
  $("#clear-topic-form").addEventListener("click", clearTopicForm);
  $("#save-topic-xml").addEventListener("click", saveTopicXml);
  $("#add-outline-item").addEventListener("click", () => addOutlineItem());
  $("#skills-view")?.addEventListener("click", (event) => {
    if (event.target.closest("#new-skill-button")) prepareNewSkillEditor();
  });
  $("#skill-form").addEventListener("submit", saveSkill);
  $("#skill-import-file").addEventListener("change", importSkillFile);
  $("#skill-attachment-files").addEventListener("change", handleSkillAttachments);
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
  } catch (error) {
    $("#service-status").textContent = `服务异常：${error.message}`;
  }
}

boot();
