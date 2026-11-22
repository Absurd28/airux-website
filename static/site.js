// AIRUX website: tabs that open on the visitor's system, and copy buttons. The pages work without it.
"use strict";
document.documentElement.classList.add("js");

function visitorOS() {
  const p = ((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent || "").toLowerCase();
  if (p.includes("win")) return "windows";
  if (p.includes("mac")) return "macos";
  if (p.includes("linux") || p.includes("x11") || p.includes("cros")) return "linux";
  return "windows";
}

function setupTabs(box) {
  const tabs = [...box.querySelectorAll('[role="tab"]')];
  const select = (tab, focus) => {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    }
    if (focus) tab.focus();
  };
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => select(t, false));
    t.addEventListener("keydown", (e) => {
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (d) { e.preventDefault(); select(tabs[(i + d + tabs.length) % tabs.length], true); }
    });
  });
  const os = visitorOS();
  select(tabs.find((t) => t.dataset.os === os) || tabs[0], false);
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = "Copied";
    btn.dataset.done = "";
    setTimeout(() => { btn.textContent = "Copy"; delete btn.dataset.done; }, 1600);
  } catch (_) {
    btn.textContent = "Select and copy";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-tabs]").forEach(setupTabs);
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const holder = btn.parentElement;
      const sha = holder.querySelector("[data-copy-text]");
      const code = holder.querySelector("pre code");
      copyText(sha ? sha.dataset.copyText : code ? code.textContent : "", btn);
    });
  });
});
