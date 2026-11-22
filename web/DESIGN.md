# Farmer interface design principles

Use these principles with [Emil Kowalski's Apple Design skill](https://www.ui-skills.com/skills/emilkowalski/apple-design) for frontend work. Design mobile first and keep the map usable while farmers select parcels. These are design tools, not effects to add indiscriminately: choose the ones that improve each interaction and verify the result on a phone and a desktop.

## Typography and readability

- Enable font kerning and choose a legible system face with a clear x-height. Adjust tracking and leading for the chosen size and language; avoid changes that make text harder to read.
- Use tabular numbers where quantities or identifiers are compared or updated. Keep body text at a comfortable line length where space permits, and avoid isolated widows or orphans when editing copy.
- Use optical alignment where icons or controls look unbalanced, rather than assuming geometric centering always looks right.

## Interaction and layout

- Provide clear affordances and touch targets of at least 44 by 44 CSS pixels. Respect device safe areas, including bottom gesture regions.
- Avoid unexpected layout shifts: reserve space or animate intentional changes without moving a target while it is being tapped. Keep the drawer in its chosen state when selecting on the map; adjust the visible map when its size changes. Cap the selected-parcel list at two visible rows and scroll the list for more.
- Use progressive disclosure for secondary information. Search suggestions should behave as an accessible combobox, with an identifiable field, clear results, keyboard access and useful empty and error states.
- Give immediate feedback for reversible actions. Optimistic updates to server-backed data must also handle failure and restore or reconcile the previous state; never imply a backend save has succeeded when it has not.

## Motion and colour

- Make changes originate from the triggering control when useful. Use short, interruptible motion, optional subtle stagger for new list items, and shared-element transitions only when they clarify continuity. Honour `prefers-reduced-motion` and avoid motion that blocks input.
- Use OKLCH where it helps develop a coherent, accessible palette, with a fallback when browser support requires it. Maintain readable contrast and the agreed project colours; do not change the palette without a design decision.
