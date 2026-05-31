/* Vanilla JS for the FretWise login / register pages. No dependencies. */
(function () {
  "use strict";

  function $(sel) { return document.querySelector(sel); }

  function showBanner(kind, msg) {
    const el = $("#banner");
    if (!el) return;
    el.className = "auth-banner " + kind;
    el.textContent = msg;
    el.hidden = false;
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await res.json(); } catch (_e) { /* ignore */ }
    return { ok: res.ok, status: res.status, data };
  }

  async function loadMethods() {
    try {
      const res = await fetch("/api/auth/methods");
      const m = await res.json();
      if (m.providers && m.providers.includes("google")) {
        const oidc = $("#oidc");
        const gbtn = $("#google-btn");
        if (oidc) oidc.hidden = false;
        if (gbtn) gbtn.hidden = false;
      }
    } catch (_e) { /* providers are optional */ }
  }

  function initLogin() {
    loadMethods();
    const params = new URLSearchParams(location.search);
    if (params.get("activated") === "1") {
      showBanner("success", "Your account is activated — you can sign in now.");
    } else if (params.get("error") === "activation") {
      showBanner("error", "This activation link is invalid or has expired. Sign in to resend one.");
    }

    const form = $("#login-form");
    const resendRow = $("#resend-row");
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      const email = form.email.value.trim();
      const password = form.password.value;
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        const { ok, status, data } = await postJSON("/api/auth/login", { email, password });
        if (ok) { location.href = "/"; return; }
        if (status === 403) {
          showBanner("error", data.detail || "Account not activated — check your email.");
          if (resendRow) resendRow.hidden = false;
        } else if (status === 401) {
          showBanner("error", data.detail || "Invalid email or password.");
        } else {
          showBanner("error", data.detail || "Sign in failed. Please try again.");
        }
      } catch (_e) {
        showBanner("error", "Network error. Please try again.");
      } finally {
        btn.disabled = false;
      }
    });

    const resendBtn = $("#resend-btn");
    if (resendBtn) {
      resendBtn.addEventListener("click", async function () {
        const email = form.email.value.trim();
        if (!email) { showBanner("error", "Enter your email above first."); return; }
        await postJSON("/api/auth/resend", { email });
        showBanner("info", "If the account exists and is inactive, a new activation link was sent.");
      });
    }
  }

  function initRegister() {
    loadMethods();
    const form = $("#register-form");
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      const email = form.email.value.trim();
      const password = form.password.value;
      const confirm = form.confirm.value;
      if (password !== confirm) { showBanner("error", "Passwords do not match."); return; }
      if (password.length < 8) { showBanner("error", "Password must be at least 8 characters."); return; }
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        const { ok, data } = await postJSON("/api/auth/register", { email, password });
        if (ok) {
          form.hidden = true;
          showBanner("success", data.message || "Check your email to activate your account.");
        } else {
          showBanner("error", data.detail || "Registration failed.");
          btn.disabled = false;
        }
      } catch (_e) {
        showBanner("error", "Network error. Please try again.");
        btn.disabled = false;
      }
    });
  }

  window.FretwiseAuth = { initLogin: initLogin, initRegister: initRegister };
})();
