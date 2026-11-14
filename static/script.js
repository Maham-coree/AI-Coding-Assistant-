const LEGACY_STORAGE_KEY = "ai-coding-assistant-chats";
const LEGACY_IMPORT_KEY = "ai-coding-assistant-import-offered";
const state = { chats: [], currentChatId: null };

function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
}

async function jsonRequest(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    headers.set("X-CSRFToken", csrfToken());
    if (options.body && typeof options.body !== "string" && !(options.body instanceof FormData)) {
        headers.set("Content-Type", "application/json");
        options.body = JSON.stringify(options.body);
    }
    const response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
        window.location.assign("/login");
        throw new Error("Your session expired. Please log in again.");
    }
    const payload = await response.json();
    if (!response.ok) {
        throw new Error(payload.error || "The request could not be completed.");
    }
    return payload;
}

function getChatById(chatId) {
    return state.chats.find((chat) => chat.id === chatId) || null;
}

function getCurrentChat() {
    return getChatById(state.currentChatId) || state.chats[0] || null;
}

function showToast(message) {
    const toast = document.getElementById("toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function renderHistory() {
    const historyList = document.getElementById("historyList");
    const searchTerm = (document.getElementById("searchHistory")?.value || "").trim().toLowerCase();
    if (!historyList) return;

    historyList.replaceChildren();
    const chats = state.chats.filter((chat) => !searchTerm || chat.title.toLowerCase().includes(searchTerm));
    if (!chats.length) {
        const empty = document.createElement("p");
        empty.className = "empty-history";
        empty.textContent = searchTerm ? "No matching conversations." : "No conversations yet.";
        historyList.appendChild(empty);
        return;
    }

    chats.forEach((chat) => {
        const item = document.createElement("div");
        item.className = "history-item" + (chat.id === state.currentChatId ? " active" : "");

        const open = document.createElement("button");
        open.type = "button";
        open.className = "history-main";
        open.textContent = chat.title;
        open.addEventListener("click", () => selectChat(chat.id));

        const actions = document.createElement("div");
        actions.className = "history-actions";
        const rename = document.createElement("button");
        rename.type = "button";
        rename.className = "mini-button";
        rename.textContent = "Rename";
        rename.addEventListener("click", () => renameChat(chat.id));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "mini-button danger";
        remove.textContent = "Delete";
        remove.addEventListener("click", () => deleteChat(chat.id));
        actions.append(rename, remove);
        item.append(open, actions);
        historyList.appendChild(item);
    });
}

function renderConversation() {
    const container = document.getElementById("conversationList");
    if (!container) return;
    const chat = getCurrentChat();
    container.replaceChildren();
    const idField = document.getElementById("conversationId");
    if (idField) idField.value = chat?.id || "";

    if (!chat || !chat.messages?.length) {
        const empty = document.createElement("div");
        empty.className = "empty-conversation";
        empty.textContent = "No messages in this conversation yet.";
        container.appendChild(empty);
        return;
    }

    chat.messages.forEach((message) => {
        const entry = document.createElement("article");
        entry.className = `message-entry ${message.role}`;
        const meta = document.createElement("div");
        meta.className = "message-meta";
        meta.textContent = message.role === "user" ? "You" : "AI";
        const content = document.createElement("div");
        content.className = "message-content";
        if (message.role === "assistant") {
            content.innerHTML = message.content;
        } else {
            content.textContent = message.content;
            if (message.code) {
                const code = document.createElement("pre");
                const codeBlock = document.createElement("code");
                codeBlock.textContent = message.code;
                code.appendChild(codeBlock);
                content.appendChild(code);
            }
        }
        entry.append(meta, content);
        container.appendChild(entry);
    });
}

function updateResponsePanel(html, isError = false) {
    const panel = document.getElementById("responseText");
    if (!panel) return;
    panel.classList.toggle("error", isError);
    panel.classList.toggle("empty-state", !html);
    panel.innerHTML = html || "No response yet. Ask a question or paste code to get started.";
    if (window.hljs) {
        panel.querySelectorAll("pre code").forEach((block) => window.hljs.highlightElement(block));
    }
    const hasResponse = Boolean(html && !isError);
    ["copyResponseBtn", "downloadBtn", "speakBtn"].forEach((id) => {
        const button = document.getElementById(id);
        if (button) button.hidden = !hasResponse;
    });
    const codeButton = document.getElementById("copyCodeBtn");
    if (codeButton) codeButton.hidden = !hasResponse || !panel.querySelector("pre code");
}

function showResponseError(message) {
    const panel = document.getElementById("responseText");
    if (!panel) return;
    panel.textContent = message;
    panel.classList.remove("empty-state");
    panel.classList.add("error");
    document.querySelectorAll(".output-actions button").forEach((button) => {
        button.hidden = true;
    });
}

function renderCurrentResponse() {
    const chat = getCurrentChat();
    const lastResponse = chat?.messages?.filter((message) => message.role === "assistant").slice(-1)[0];
    updateResponsePanel(lastResponse?.content || "", false);
}

function refreshWorkspace() {
    renderHistory();
    renderConversation();
    renderCurrentResponse();
}

async function loadChats() {
    const payload = await jsonRequest("/api/conversations");
    state.chats = payload.conversations || [];

    if (!state.chats.length && !localStorage.getItem(LEGACY_IMPORT_KEY)) {
        const saved = localStorage.getItem(LEGACY_STORAGE_KEY);
        if (saved) {
            try {
                const legacyChats = JSON.parse(saved);
                if (Array.isArray(legacyChats) && legacyChats.length) {
                    const importChats = window.confirm(
                        `Import ${legacyChats.length} conversations from this browser into this account? Only import if these chats belong to you.`
                    );
                    if (importChats) {
                        await jsonRequest("/api/conversations/import", { method: "POST", body: { chats: legacyChats } });
                        localStorage.removeItem(LEGACY_STORAGE_KEY);
                        showToast("Your browser conversations were imported.");
                    }
                }
            } catch (error) {
                showToast(error.message || "Could not import browser conversations.");
            } finally {
                localStorage.setItem(LEGACY_IMPORT_KEY, "done");
            }
            const refreshed = await jsonRequest("/api/conversations");
            state.chats = refreshed.conversations || [];
        }
    }

    if (!state.chats.some((chat) => chat.id === state.currentChatId)) {
        state.currentChatId = state.chats[0]?.id || null;
    }
    if (new URLSearchParams(window.location.search).get("new") === "1") {
        await createChat();
        window.history.replaceState({}, "", "/");
    } else if (!state.currentChatId) {
        await createChat();
    }
    refreshWorkspace();
}

async function createChat() {
    const payload = await jsonRequest("/api/conversations", {
        method: "POST",
        body: { title: "New conversation" },
    });
    state.chats.unshift(payload.conversation);
    state.currentChatId = payload.conversation.id;
    refreshWorkspace();
    updateResponsePanel("", false);
    const userInput = document.getElementById("userInput");
    const codeInput = document.getElementById("codeInput");
    if (userInput) userInput.value = "";
    if (codeInput) codeInput.value = "";
    return payload.conversation;
}

function selectChat(chatId) {
    state.currentChatId = chatId;
    refreshWorkspace();
}

async function renameChat(chatId) {
    const chat = getChatById(chatId);
    if (!chat) return;
    const title = window.prompt("Rename this conversation", chat.title);
    if (title === null) return;
    try {
        const payload = await jsonRequest(`/api/conversations/${encodeURIComponent(chatId)}`, {
            method: "PATCH",
            body: { title },
        });
        state.chats = state.chats.map((item) => item.id === chatId ? payload.conversation : item);
        refreshWorkspace();
    } catch (error) {
        showToast(error.message);
    }
}

async function deleteChat(chatId) {
    if (!window.confirm("Delete this conversation? This action cannot be undone.")) return;
    try {
        await jsonRequest(`/api/conversations/${encodeURIComponent(chatId)}`, { method: "DELETE" });
        state.chats = state.chats.filter((chat) => chat.id !== chatId);
        if (state.currentChatId === chatId) state.currentChatId = state.chats[0]?.id || null;
        if (!state.chats.length) await createChat();
        refreshWorkspace();
        showToast("Conversation deleted.");
    } catch (error) {
        showToast(error.message);
    }
}

async function clearCurrentChat() {
    const chat = getCurrentChat();
    if (!chat) return;
    try {
        const payload = await jsonRequest(`/api/conversations/${encodeURIComponent(chat.id)}/messages`, { method: "DELETE" });
        state.chats = state.chats.map((item) => item.id === chat.id ? payload.conversation : item);
        refreshWorkspace();
        showToast("Current chat cleared.");
    } catch (error) {
        showToast(error.message);
    }
}

async function checkApiStatus() {
    const status = document.getElementById("apiStatus");
    if (!status) return;
    try {
        const response = await fetch("/health", { headers: { Accept: "application/json" } });
        const payload = await response.json();
        const hasKey = Boolean(payload.provider_configured);
        status.classList.toggle("ok", hasKey);
        status.classList.toggle("warning", !hasKey);
        status.textContent = hasKey ? "Gemini connected" : "API key missing";
    } catch {
        status.classList.add("warning");
        status.textContent = "Connection check failed";
    }
}

async function submitAssistantForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const userInput = document.getElementById("userInput");
    const codeInput = document.getElementById("codeInput");
    if (!userInput?.value.trim() && !codeInput?.value.trim()) {
        showToast("Please enter a prompt or paste code before submitting.");
        userInput?.focus();
        return;
    }
    let chat = getCurrentChat();
    if (!chat) chat = await createChat();
    const idField = document.getElementById("conversationId");
    if (idField) idField.value = chat.id;
    const askButton = document.getElementById("askBtn");
    if (askButton) {
        askButton.disabled = true;
        askButton.innerHTML = '<span class="spinner"></span> Working...';
    }
    try {
        const response = await fetch("/chat", {
            method: "POST",
            body: new FormData(form),
            headers: { Accept: "application/json" },
        });
        const result = await response.json();
        if (response.status === 401) {
            window.location.assign("/login");
            return;
        }
        if (!response.ok || result.status === "error") {
            if (result.conversation_id) {
                const refreshed = await jsonRequest(`/api/conversations/${encodeURIComponent(result.conversation_id)}`);
                state.chats = state.chats.map((item) => item.id === refreshed.conversation.id ? refreshed.conversation : item);
                refreshWorkspace();
            }
            showResponseError(result.error || "The assistant could not respond.");
            showToast(result.error || "The assistant could not respond.");
            return;
        }
        const saved = result.conversation;
        state.chats = state.chats.map((item) => item.id === saved.id ? saved : item);
        state.currentChatId = saved.id;
        refreshWorkspace();
        updateResponsePanel(result.ai_response || "", false);
        showToast("AI response ready.");
    } catch (error) {
        const message = error.message || "The AI request failed. Please try again.";
        showResponseError(message);
        showToast(message);
    } finally {
        if (askButton) {
            askButton.disabled = false;
            const activeMode = document.querySelector(".mode-button.active")?.textContent.trim() || "Generate";
            askButton.textContent = `✨ ${activeMode}`;
        }
    }
}

function wireCommonControls() {
    document.querySelectorAll("[data-toggle-password]").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.getElementById(button.dataset.togglePassword);
            if (!input) return;
            input.type = input.type === "password" ? "text" : "password";
            button.textContent = input.type === "password" ? "Show" : "Hide";
        });
    });
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm)) event.preventDefault();
        });
    });
    document.querySelectorAll("form[data-disable-on-submit]").forEach((form) => {
        form.addEventListener("submit", () => {
            const button = form.querySelector('button[type="submit"]');
            if (button) {
                button.disabled = true;
                button.textContent = "Please wait...";
            }
        });
    });
    document.querySelectorAll(".copy-snippet").forEach((button) => {
        button.addEventListener("click", async () => {
            const block = button.closest(".snippet-card")?.querySelector("pre code");
            try {
                await navigator.clipboard.writeText(block?.textContent || "");
                showToast("Snippet copied.");
            } catch {
                showToast("Copy failed.");
            }
        });
    });
    document.querySelectorAll(".use-template").forEach((button) => {
        button.addEventListener("click", () => {
            window.location.assign(`/?template=${encodeURIComponent(button.dataset.templateId)}`);
        });
    });
}

function wireWorkspaceControls() {
    const form = document.getElementById("assistantForm");
    if (!form) return;
    const modeInput = document.getElementById("modeInput");
    const askButton = document.getElementById("askBtn");
    const themeButton = document.getElementById("darkModeBtn");
    if (themeButton) {
        themeButton.textContent = document.documentElement.classList.contains("dark-mode")
            ? "☀️ Light mode"
            : "🌙 Dark mode";
    }

    document.querySelector(".new-conversation-link")?.addEventListener("click", async (event) => {
        if (window.location.pathname !== "/") return;
        event.preventDefault();
        try {
            await createChat();
        } catch (error) {
            showToast(error.message);
        }
    });
    document.getElementById("clearCurrentChatBtn")?.addEventListener("click", clearCurrentChat);
    document.getElementById("clearBtn")?.addEventListener("click", () => {
        document.getElementById("userInput").value = "";
        document.getElementById("codeInput").value = "";
        document.getElementById("userInput").focus();
    });
    document.getElementById("searchHistory")?.addEventListener("input", renderHistory);

    document.querySelectorAll(".mode-button").forEach((button) => {
        button.addEventListener("click", () => {
            modeInput.value = button.dataset.mode;
            document.querySelectorAll(".mode-button").forEach((item) => item.classList.toggle("active", item === button));
            if (askButton) askButton.textContent = `✨ ${button.textContent.trim()}`;
        });
    });
    document.querySelectorAll(".example-button").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.getElementById("userInput");
            input.value = button.dataset.prompt || "";
            input.focus();
        });
    });
    form.addEventListener("submit", submitAssistantForm);

    document.getElementById("darkModeBtn")?.addEventListener("click", async () => {
        const root = document.documentElement;
        const nextTheme = root.classList.contains("dark-mode") ? "light" : "dark";
        root.classList.toggle("dark-mode", nextTheme === "dark");
        try {
            await jsonRequest("/api/preferences", { method: "POST", body: { theme: nextTheme } });
            document.getElementById("darkModeBtn").textContent = nextTheme === "dark" ? "☀️ Light mode" : "🌙 Dark mode";
        } catch (error) {
            root.classList.toggle("dark-mode", nextTheme !== "dark");
            showToast(error.message);
        }
    });
    document.getElementById("saveSnippetBtn")?.addEventListener("click", async () => {
        const code = document.getElementById("codeInput").value.trim();
        if (!code) {
            showToast("Add code to the snippet field first.");
            return;
        }
        const title = window.prompt("Name this code snippet");
        if (!title?.trim()) return;
        try {
            await jsonRequest("/api/snippets", {
                method: "POST",
                body: { title: title.trim(), code, language: document.getElementById("languageSelect").value },
            });
            showToast("Snippet saved to your library.");
        } catch (error) {
            showToast(error.message);
        }
    });

    document.getElementById("copyResponseBtn")?.addEventListener("click", async () => {
        const text = document.getElementById("responseText")?.innerText || "";
        if (!text || text.includes("No response yet")) return showToast("Nothing to copy yet.");
        try {
            await navigator.clipboard.writeText(text);
            showToast("Response copied.");
        } catch {
            showToast("Copy failed.");
        }
    });
    document.getElementById("copyCodeBtn")?.addEventListener("click", async () => {
        const blocks = document.querySelectorAll("#responseText pre code");
        const code = blocks.length
            ? Array.from(blocks).map((block) => block.textContent).join("\n\n")
            : "";
        if (!code.trim()) return showToast("No code blocks to copy.");
        try {
            await navigator.clipboard.writeText(code);
            showToast("Code copied.");
        } catch {
            showToast("Code copy failed.");
        }
    });
    document.getElementById("downloadBtn")?.addEventListener("click", () => {
        const text = document.getElementById("responseText")?.innerText || "";
        if (!text || text.includes("No response yet")) return showToast("Nothing to download yet.");
        const link = document.createElement("a");
        const objectUrl = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
        link.href = objectUrl;
        link.download = "ai-response.txt";
        link.click();
        URL.revokeObjectURL(objectUrl);
        showToast("File downloaded.");
    });
    document.getElementById("speakBtn")?.addEventListener("click", () => {
        const text = document.getElementById("responseText")?.innerText || "";
        if (!text || text.includes("No response yet")) return showToast("No response available to speak.");
        if (!window.speechSynthesis) return showToast("Speech is not supported in this browser.");
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
        showToast("Speaking response...");
    });

}

async function applyPromptTemplate() {
    const form = document.getElementById("assistantForm");
    const templateId = form?.dataset.templateId;
    if (!templateId) return;
    try {
        const template = await jsonRequest(`/api/prompt-templates/${encodeURIComponent(templateId)}`);
        document.getElementById("userInput").value = template.prompt;
        document.getElementById("modeInput").value = template.mode;
        document.getElementById("languageSelect").value = template.language;
        document.querySelectorAll(".mode-button").forEach((button) => {
            button.classList.toggle("active", button.dataset.mode === template.mode);
        });
        const askButton = document.getElementById("askBtn");
        if (askButton) askButton.textContent = `✨ ${template.mode[0].toUpperCase()}${template.mode.slice(1)}`;
        window.history.replaceState({}, "", "/");
        showToast("Template added to the workspace. Review it before submitting.");
    } catch (error) {
        showToast(error.message);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    wireCommonControls();
    wireWorkspaceControls();
    checkApiStatus();
    applyPromptTemplate();
    if (document.getElementById("historyList")) {
        loadChats().catch((error) => showToast(error.message || "Could not load your conversations."));
    }
});
