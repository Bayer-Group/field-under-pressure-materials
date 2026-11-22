// Turning one chat message into DOM: sanitised markdown, [n] markers linked to their citations, the
// list of sources, the chart and the observation buttons.

import DOMPurify from "dompurify";
import { marked } from "marked";

import { type ChatMessage, type Citation, type GuideCitation, isConfirmObservation, toCitation } from "../api/types";
import { formatDate, h, icon, ICONS } from "../dom";
import { hasDataUrl, renderChart } from "./chart";

export interface MessageHooks {
  /** A risk citation was clicked. */
  focusField(fieldId: number): void;
  /** Resolves a field id to its name (for risk citations). */
  fieldName(fieldId: number): Promise<string>;
  /** Resolves a threat code to its Polish name. */
  threatName(code: string): Promise<string>;
  /** Zapisz / Anuluj under a pending observation draft. */
  answerDraft(answer: "Zapisz" | "Anuluj", fieldId: number | null): void;
}

export interface RenderedMessage {
  element: HTMLElement;
  /** Zapisz / Anuluj buttons, if the message carries a pending observation draft. */
  actionButtons: HTMLButtonElement[];
}

// The default DOMPurify list keeps <style>, forms, media and style="": a farmer's text quoted in a draft (or a
// model's answer) could restyle the whole page or load an image from anywhere. Answers need text formatting only.
const PURIFY = {
  FORBID_TAGS: ["style", "form", "input", "button", "select", "textarea", "img", "video", "audio", "iframe", "dialog", "svg", "math"],
  FORBID_ATTR: ["style", "class", "id"],
};
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {  // links in an answer never replace the app
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

/** Markdown -> sanitised HTML. Never inserts the model's output as raw HTML. */
export function markdownToHtml(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false, gfm: true, breaks: true }) as string, PURIFY);
}

/** Readable titles of the guides (file names in field-under-pressure-materials/metodyki/). */
const DOCUMENT_TITLES: Record<string, string> = {
  "metodyka_-_PSZENICA_-_www.pdf": "Metodyka integrowanej ochrony pszenicy",
  "pszenicy_ozimej_i_jarej__DLA_PRODUCENTOW.pdf": "Ochrona pszenicy ozimej i jarej – poradnik dla producentów",
  "kukurydzy__DLA_PRODUCENTOW.pdf": "Ochrona kukurydzy – poradnik dla producentów",
  "Metodyka_integrowanej_ochrony_kukurydzy_dla_doradcow_2019.pdf": "Metodyka integrowanej ochrony kukurydzy dla doradców (2019)",
  "PORADNIK_METODYCZNY_-_ZBOZA_GIORiN.pdf": "Poradnik metodyczny: zboża (GIORiN)",
  "ryzyka_zebrane.xlsx": "Zestawienie warunków ryzyka",
};

function documentTitle(document: string): string {
  return DOCUMENT_TITLES[document] ?? document.replace(/\.(pdf|xlsx)$/i, "").replace(/_+/g, " ").replace(/\s+-\s+/g, " – ").trim();
}

function guideLabel(citation: GuideCitation): string {
  const title = documentTitle(citation.document);
  if (citation.sheet) return `${title} – ${citation.sheet}, wiersz ${citation.row ?? "?"}`;
  const page = citation.printed_page ?? citation.page;
  return page !== null && page !== undefined ? `${title}, s. ${page}` : title;
}

/** Replaces [n] in text nodes with links to the source whose `ref` is n (not inside code or links). */
function linkMarkers(root: HTMLElement, anchors: Map<number, string>): void {
  if (!anchors.size) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!(node.parentElement?.closest("code, pre, a"))) nodes.push(node as Text);
  }
  for (const node of nodes) {
    const text = node.data;
    const pattern = /\[(\d+)\]/g;
    if (!pattern.test(text)) continue;
    pattern.lastIndex = 0;
    const fragment = document.createDocumentFragment();
    let last = 0;
    for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
      const anchor = anchors.get(Number(match[1]));
      if (!anchor) continue;
      fragment.append(text.slice(last, match.index));
      const link = h("a", { href: `#${anchor}`, class: "cite-marker" }, match[0]);
      link.addEventListener("click", (event) => {
        event.preventDefault();
        const target = document.getElementById(anchor);
        target?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        target?.classList.remove("flash");
        void target?.offsetWidth; // restart the animation
        target?.classList.add("flash");
      });
      last = match.index + match[0].length;
      // punctuation right after the marker stays on its line ("… 0,72 [1].")
      const trail = /^[.,;:!?)]+/.exec(text.slice(last))?.[0];
      if (trail) {
        fragment.append(h("span", { class: "cite-nowrap" }, link, trail));
        last += trail.length;
        pattern.lastIndex = last;
      } else {
        fragment.append(link);
      }
    }
    fragment.append(text.slice(last));
    node.replaceWith(fragment);
  }
}

function sourceItem(citation: Citation, anchor: string, hooks: MessageHooks): HTMLLIElement {
  if (citation.type === "guide") {
    const ref = citation.ref !== null && citation.ref !== undefined ? String(citation.ref) : null;
    return h(
      "li",
      { id: anchor, class: "source source-guide", title: [citation.section, citation.document].filter(Boolean).join(" · ") },
      ref ? h("span", { class: "src-ref" }, ref) : icon(ICONS.doc, "src-icon"),
      h("span", { class: "src-text" }, guideLabel(citation)),
    );
  }
  const text = h("span", { class: "src-text" }, `ryzyko: pole #${citation.field_id}`);
  const link = h("button", { type: "button", class: "source-risk", title: "Pokaż pole na mapie" }, icon(ICONS.pin, "src-icon"), text);
  link.addEventListener("click", () => hooks.focusField(citation.field_id));
  void Promise.all([hooks.fieldName(citation.field_id), hooks.threatName(citation.threat_code)]).then(
    ([field, threat]) => {
      text.textContent = `${field}: ${threat}, ${formatDate(citation.date)}`;
    },
  );
  return h("li", { id: anchor, class: "source" }, link);
}

export function renderMessage(message: ChatMessage, hooks: MessageHooks): RenderedMessage {
  const isUser = message.role === "user";
  const element = h("article", { class: `msg ${isUser ? "msg-user" : "msg-assistant"}` });
  const actionButtons: HTMLButtonElement[] = [];

  if (isUser) {
    element.append(h("div", { class: "msg-text" }, message.text));
    return { element, actionButtons };
  }

  const text = h("div", { class: "msg-text" });
  text.innerHTML = markdownToHtml(message.text);
  element.append(text);

  const citations = (message.citations ?? []).map(toCitation).filter((c): c is Citation => c !== null);
  const anchors = new Map<number, string>();
  const items = citations.map((citation, index) => {
    const anchor = `cite-${message.id}-${index}`;
    if (citation.type === "guide" && typeof citation.ref === "number") anchors.set(citation.ref, anchor);
    return sourceItem(citation, anchor, hooks);
  });
  linkMarkers(text, anchors);

  if (message.chart && !hasDataUrl(message.chart)) {
    const chart = h("div", { class: "msg-chart" });
    element.append(chart);
    void renderChart(chart, message.chart);
  }

  const action = message.pending_action;
  if (isConfirmObservation(action)) {
    const fieldId = typeof action.draft.field_id === "number" ? action.draft.field_id : null;
    for (const answer of ["Zapisz", "Anuluj"] as const) {
      const button = h("button", { type: "button", class: answer === "Zapisz" ? "primary" : "ghost" }, answer);
      button.addEventListener("click", () => hooks.answerDraft(answer, fieldId));
      actionButtons.push(button);
    }
    element.append(h("div", { class: "msg-actions" }, ...actionButtons));
  }

  if (items.length) {
    element.append(h("div", { class: "msg-sources" }, h("div", { class: "src-title" }, "Źródła"), h("ul", { "aria-label": "Źródła" }, ...items)));
  }
  return { element, actionButtons };
}
