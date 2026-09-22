const STORAGE_KEY = "lianjinlu-archive-demo-v1";
const defaults = {};
const app = document.querySelector("#archive-app");
const toast = document.querySelector("#archive-toast");
let toastTimer;

function loadDraft() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function showToast(message) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 1800);
}

function saveDraft() {
  const content = {};
  document.querySelectorAll("[data-edit]").forEach((node) => {
    content[node.dataset.edit] = node.innerHTML;
  });
  document.querySelectorAll("[data-editable-content]").forEach((node) => {
    content[node.dataset.editableContent] = node.innerText;
  });
  const fields = {};
  document.querySelectorAll("textarea[id]").forEach((node) => {
    fields[node.id] = node.value;
  });
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ content, fields }));
  showToast("草稿已保存在本地");
}

function applyDraft(draft) {
  const content = draft.content || {};
  document.querySelectorAll("[data-edit]").forEach((node) => {
    if (typeof content[node.dataset.edit] === "string") node.innerHTML = content[node.dataset.edit];
  });
  document.querySelectorAll("[data-editable-content]").forEach((node) => {
    if (typeof content[node.dataset.editableContent] === "string") node.innerText = content[node.dataset.editableContent];
  });
  const fields = draft.fields || {};
  document.querySelectorAll("textarea[id]").forEach((node) => {
    if (typeof fields[node.id] === "string") node.value = fields[node.id];
  });
}

function switchView(viewId) {
  const target = document.getElementById(viewId);
  if (!target) return;
  document.querySelectorAll(".archive-nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === viewId));
  document.querySelectorAll("[data-view-panel]").forEach((view) => {
    view.classList.toggle("is-visible", view.id === viewId);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function handleAction(action) {
  if (action === "open-analysis") switchView("analysis-view");
  else if (action === "open-topic") switchView("topic-view");
  else if (action === "create") showToast("设计稿预览：这里将打开“新建项目”窗口");
  else showToast("设计稿预览：操作已记录，可继续调整文案");
}

document.querySelectorAll(".archive-nav-item").forEach((item) => {
  item.addEventListener("click", () => switchView(item.dataset.view));
});

document.querySelectorAll("[data-demo-action]").forEach((button) => {
  button.addEventListener("click", () => handleAction(button.dataset.demoAction));
});

document.querySelectorAll("[data-panel-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    const mode = button.dataset.panelMode;
    const window = button.closest(".analysis-window");
    if (!window) return;
    window.dataset.activePanel = mode;
    window.querySelectorAll("[data-panel-mode]").forEach((item) => item.classList.toggle("is-active", item === button));
  });
});

document.querySelectorAll(".topic-tree-row, .skill-record").forEach((item) => {
  item.addEventListener("click", () => {
    item.parentElement.querySelectorAll(".topic-tree-row, .skill-record").forEach((row) => row.classList.remove("is-selected"));
    item.classList.add("is-selected");
    showToast("已切换档案条目");
  });
});

document.querySelectorAll("[data-edit]").forEach((node) => {
  node.contentEditable = "true";
});
document.querySelectorAll("[contenteditable='true'], [data-edit]").forEach((node) => {
  node.addEventListener("input", () => {
    node.classList.add("is-dirty");
  });
  node.addEventListener("blur", saveDraft);
  node.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && node.tagName !== "P" && !event.shiftKey) {
      event.preventDefault();
      node.blur();
    }
  });
});
document.querySelectorAll("textarea[id]").forEach((node) => {
  node.addEventListener("input", () => node.classList.add("is-dirty"));
  node.addEventListener("blur", saveDraft);
});

document.querySelector("#reset-demo")?.addEventListener("click", () => {
  localStorage.removeItem(STORAGE_KEY);
  window.location.reload();
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveDraft();
  }
});

applyDraft(loadDraft());

