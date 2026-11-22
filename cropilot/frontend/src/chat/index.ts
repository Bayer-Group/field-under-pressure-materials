// The chat window (docs/interfaces.md -> Chat). Conversations from the API, the user's message shown at
// once, then "Myślę…", then the answer. Talks to the map only through events:
//   sends   field:focus (focus_field_id, a clicked risk citation), risks:updated (updated_field_ids)
//   handles field:selected ("Pytasz o: …"; the field goes with the next message)
//           assistant:status (no LLM keys: the chat is greyed out with a short explanation; map and risks work)

import { ApiError, errorMessage } from "../api/client";
import type { ChatMessage } from "../api/types";
import type { AppContext } from "../context";
import { h, icon, ICONS } from "../dom";
import { releaseDetachedCharts } from "./chart";
import { type MessageHooks, renderMessage } from "./render";

const NEW_CONVERSATION = "";

/** Questions from the demo script, one click away in an empty conversation. */
const STARTERS = [
  "Które pole jest dziś najbardziej zagrożone?",
  "Dlaczego to pole jest na czerwono i co mam zrobić?",
  "Jakie są objawy septoriozy paskowanej liści?",
];

export function initChat(container: HTMLElement, ctx: AppContext): void {
  const conversations = h("select", { class: "chat-conversations", "aria-label": "Rozmowy" });
  const newButton = h("button", { type: "button", class: "chat-new", title: "Nowa rozmowa" }, icon(ICONS.plus), "Nowa");
  const list = h("div", { class: "chat-messages", role: "log", "aria-live": "polite" });
  const contextName = h("strong");
  const contextLine = h("div", { class: "chat-context", hidden: true }, icon(ICONS.field), "Pytasz o: ", contextName);
  const input = h("textarea", {
    class: "chat-input",
    rows: 1,
    placeholder: "Zapytaj o pole albo zagrożenie…",
    "aria-label": "Wiadomość",
  });
  const sendButton = h("button", { type: "submit", class: "chat-send", title: "Wyślij", "aria-label": "Wyślij" }, icon(ICONS.send));
  const form = h("form", { class: "chat-form" }, h("div", { class: "composer" }, input, sendButton));
  container.replaceChildren(
    h(
      "div",
      { class: "chat-toolbar" },
      h("div", { class: "chat-title" }, h("h2", {}, "Asystent"), h("span", {}, "ryzyka i metodyki")),
      h("div", { class: "chat-tools" }, conversations, newButton),
    ),
    list,
    h("div", { class: "chat-footer" }, contextLine, form),
  );
  // the composer grows with the text, up to its CSS max-height
  const fitInput = () => {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  };
  input.addEventListener("input", fitInput);

  let conversationId: number | null = null;
  let lastMessageId: number | null = null; // the conversation's last message on the server, if known
  let actionGroups: { messageId: number; buttons: HTMLButtonElement[] }[] = [];
  let busy = false;
  let selectedFieldId: number | null = null;
  let loadToken = 0;
  let available = true; // false: GET /api/health/ says the assistant has no LLM (assistant:status)
  let offReason = "";

  // --- names for risk citations and "Pytasz o"
  const fieldNames = new Map<number, Promise<string>>();
  const fieldName = (fieldId: number): Promise<string> => {
    let name = fieldNames.get(fieldId);
    if (!name) {
      name = ctx.api.getField(fieldId).then(
        (field) => field.name,
        () => {
          fieldNames.delete(fieldId); // a passing error: ask again next time
          return `pole #${fieldId}`;
        },
      );
      fieldNames.set(fieldId, name);
    }
    return name;
  };
  let threatNames: Promise<Map<string, string>> | null = null;
  const threatName = async (code: string): Promise<string> => {
    threatNames ??= ctx.api.getThreats().then(
      (threats) => new Map(threats.map((threat) => [threat.code, threat.name])),
      () => new Map<string, string>(),
    );
    return (await threatNames).get(code) ?? code;
  };

  const hooks: MessageHooks = {
    focusField: (fieldId) => ctx.events.emit("field:focus", { fieldId }),
    fieldName,
    threatName,
    answerDraft: (answer, fieldId) => void send(answer, fieldId ?? selectedFieldId),
  };

  // --- rendering
  const scrollToEnd = () => {
    list.scrollTop = list.scrollHeight;
  };

  const showEmptyHint = () => {
    if (!available) {
      list.replaceChildren(
        h(
          "div",
          { class: "chat-empty chat-off" },
          icon(ICONS.chat, "chat-empty-icon"),
          h("p", {}, h("strong", {}, "Asystent jest wyłączony.")),
          h("p", {}, offReason || "Brak kluczy do modelu językowego."),
          h("p", { class: "muted", title: "Wpisz GEMINI_API_KEY lub GROQ_API_KEY do pliku .env i uruchom serwer ponownie." },
            "Mapa, ryzyka i wyjaśnienia działają bez niego."),
        ),
      );
      return;
    }
    const starters = STARTERS.map((q) => {
      const chip = h("button", { type: "button", class: "chat-starter" }, q);
      chip.addEventListener("click", () => void send(q, selectedFieldId));
      return chip;
    });
    list.replaceChildren(
      h(
        "div",
        { class: "chat-empty" },
        icon(ICONS.chat, "chat-empty-icon"),
        h("p", {}, "Zapytaj o ryzyka na swoich polach, zalecenia z metodyk albo opisz, co widzisz na polu."),
        h("p", { class: "muted" }, "Kliknij pole na mapie, żeby pytać właśnie o nie. Shift+Enter: nowa linia."),
        h("div", { class: "chat-starters" }, ...starters),
      ),
    );
  };

  /** Observation buttons work only on the conversation's last message, and not while a request runs. */
  const refreshActionButtons = () => {
    for (const group of actionGroups) {
      const active = !busy && group.messageId === lastMessageId;
      for (const button of group.buttons) button.disabled = !active;
    }
  };

  const appendMessage = (message: ChatMessage) => {
    list.querySelector(".chat-empty")?.remove();
    const rendered = renderMessage(message, hooks);
    list.append(rendered.element);
    lastMessageId = message.id;
    if (rendered.actionButtons.length) actionGroups.push({ messageId: message.id, buttons: rendered.actionButtons });
  };

  const setBusy = (value: boolean) => {
    busy = value;
    sendButton.disabled = value || !available;
    input.disabled = value || !available;
    newButton.disabled = value;
    conversations.disabled = value;
    refreshActionButtons();
  };

  ctx.events.on("assistant:status", (status) => {
    const changed = status.available !== available;
    available = status.available;
    offReason = status.reason ?? "";
    container.classList.toggle("assistant-off", !available);
    input.placeholder = available ? "Zapytaj o pole albo zagrożenie…" : "Asystent wyłączony (brak kluczy LLM)";
    container.querySelector(".chat-badge")?.remove();
    if (available && !status.rag) {
      container.querySelector(".chat-title")?.append(
        h("span", { class: "chat-badge", title: status.reason ?? "" }, "bez metodyk"),
      );
    }
    setBusy(busy);
    if (changed && !list.querySelector(".msg")) showEmptyHint();
  });

  // --- conversations
  const fillConversations = async () => {
    try {
      const items = await ctx.api.listConversations();
      conversations.replaceChildren(
        h("option", { value: NEW_CONVERSATION }, "Nowa rozmowa"),
        ...items.map((item) => h("option", { value: String(item.id) }, item.title || `Rozmowa ${item.id}`)),
      );
    } catch {
      conversations.replaceChildren(h("option", { value: NEW_CONVERSATION }, "Nowa rozmowa"));
    }
    conversations.value = conversationId === null ? NEW_CONVERSATION : String(conversationId);
  };

  const startNew = () => {
    loadToken++;
    queueMicrotask(releaseDetachedCharts);
    conversationId = null;
    lastMessageId = null;
    actionGroups = [];
    conversations.value = NEW_CONVERSATION;
    showEmptyHint();
    input.focus();
  };

  const openConversation = async (id: number) => {
    const token = ++loadToken;
    // nothing can be sent until the history is in, so a message never lands in the previous conversation
    setBusy(true);
    conversationId = id;
    lastMessageId = null;
    actionGroups = [];
    list.replaceChildren(h("div", { class: "chat-loading" }, "Wczytywanie rozmowy…"));
    try {
      const detail = await ctx.api.getConversation(id);
      if (token !== loadToken) return;
      list.replaceChildren();
      releaseDetachedCharts();
      for (const message of detail.messages) appendMessage(message); // history: no events
      if (!detail.messages.length) showEmptyHint();
      scrollToEnd();
    } catch (error) {
      if (token !== loadToken) return;
      list.replaceChildren(h("div", { class: "chat-error" }, `Nie udało się wczytać rozmowy: ${errorMessage(error)}`));
    } finally {
      if (token === loadToken) setBusy(false);
    }
  };

  // --- sending
  const send = async (text: string, fieldId: number | null, retried = false): Promise<void> => {
    const message = text.trim();
    if (!message || (busy && !retried) || !available) return;
    setBusy(true);
    list.querySelectorAll(".msg-unsent").forEach((element) => element.remove()); // the retry replaces it
    loadToken++; // a conversation still loading must not replace what happens now
    const draftText = input.value;
    input.value = "";
    fitInput();
    list.querySelector(".chat-empty")?.remove();
    list.querySelectorAll(".chat-error").forEach((element) => element.remove());
    const userBubble = h("article", { class: "msg msg-user" }, h("div", { class: "msg-text" }, message));
    const thinking = h(
      "div",
      { class: "msg msg-assistant thinking" },
      h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
      "Myślę…",
    );
    list.append(userBubble, thinking);
    scrollToEnd();

    try {
      const reply = await ctx.api.sendChat({ conversation_id: conversationId, message, field_id: fieldId });
      const isNew = conversationId === null;
      conversationId = reply.conversation_id;
      thinking.remove();
      appendMessage(reply.message);
      scrollToEnd();
      if (reply.message.focus_field_id !== null && reply.message.focus_field_id !== undefined) {
        ctx.events.emit("field:focus", { fieldId: reply.message.focus_field_id });
      }
      if (reply.message.updated_field_ids?.length) {
        ctx.events.emit("risks:updated", { fieldIds: reply.message.updated_field_ids });
      }
      void fillConversations().then(() => {
        if (isNew) conversations.value = String(conversationId);
      });
    } catch (error) {
      lastMessageId = null; // the server may have saved the message (and dropped a pending draft)
      // the data was reloaded (scenario reset): an old conversation or field id. Start over once, quietly.
      if (!retried && error instanceof ApiError && (error.status === 404 || /^field \d+ not found$/.test(error.detail))) {
        thinking.remove();
        userBubble.remove();
        if (error.status === 404) {
          conversationId = null;
          void fillConversations();
        } else {
          selectedFieldId = null;
          contextLine.hidden = true;
        }
        busy = false;
        return await send(message, error.status === 404 ? fieldId : null, true);
      }
      if (error instanceof ApiError && error.status === 503) {
        ctx.events.emit("assistant:status", { available: false, rag: false, reason: error.detail });
      }
      userBubble.classList.add("msg-unsent");
      userBubble.title = "Nie wysłano";
      thinking.replaceWith(h("div", { class: "chat-error" }, `Nie udało się wysłać: ${errorMessage(error)}`));
      if (!input.value) input.value = draftText || message; // keep what the user typed
      fitInput();
      scrollToEnd();
    } finally {
      setBusy(false);
      input.focus();
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void send(input.value, selectedFieldId);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void send(input.value, selectedFieldId);
    }
  });
  newButton.addEventListener("click", startNew);
  conversations.addEventListener("change", () => {
    if (conversations.value === NEW_CONVERSATION) startNew();
    else void openConversation(Number(conversations.value));
  });

  // --- the field selected on the map
  ctx.events.on("field:selected", ({ fieldId }) => {
    selectedFieldId = fieldId;
    if (fieldId === null) {
      contextLine.hidden = true;
      return;
    }
    contextName.textContent = `pole #${fieldId}`;
    contextLine.hidden = false;
    void fieldName(fieldId).then((name) => {
      if (selectedFieldId === fieldId) contextName.textContent = name;
    });
  });

  showEmptyHint();
  void fillConversations();
}
