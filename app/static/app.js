(function () {
    const loginSection = document.getElementById("login-section");
    const downloadSection = document.getElementById("download-section");
    const loginError = document.getElementById("login-error");

    // ---- random quote in the footer ticker ----
    const quoteEl = document.getElementById("footer-quote");
    if (quoteEl && Array.isArray(window.UDOWN_QUOTES) && window.UDOWN_QUOTES.length) {
        const pick = window.UDOWN_QUOTES[Math.floor(Math.random() * window.UDOWN_QUOTES.length)];
        const attribution = pick.w ? `${pick.a}, ` : pick.a;
        quoteEl.innerHTML = `"${pick.q}" — ${attribution}` + (pick.w ? `<em>${pick.w}</em>` : "");
        // full text on hover for long quotes that get truncated
        quoteEl.title = `"${pick.q}" — ${pick.a}` + (pick.w ? `, ${pick.w}` : "");
    }

    // ---- masthead clock — broadcast tick, separate spans so the colons can blink ----
    const clockEl = document.getElementById("meta-clock");
    const clockH = clockEl?.querySelector(".meta-clock__h");
    const clockM = clockEl?.querySelector(".meta-clock__m");
    const clockS = clockEl?.querySelector(".meta-clock__s");
    const pad = (n) => String(n).padStart(2, "0");
    function tick() {
        if (!clockH) return;
        const d = new Date();
        clockH.textContent = pad(d.getHours());
        clockM.textContent = pad(d.getMinutes());
        clockS.textContent = pad(d.getSeconds());
    }
    tick();
    setInterval(tick, 1000);

    // ---- masthead status indicator ----
    const statusBadge = document.getElementById("meta-status");
    const statusBadgeText = statusBadge?.querySelector(".meta-status__text");
    function setBadge(state, text) {
        if (!statusBadge) return;
        statusBadge.dataset.state = state;
        if (statusBadgeText && text) statusBadgeText.textContent = text;
    }

    // ---- initial state ----
    fetch("/me", { credentials: "same-origin" })
        .then((r) => {
            if (r.status === 200) {
                downloadSection.classList.remove("hidden");
                refreshCookiesStatus();
            } else {
                loginSection.classList.remove("hidden");
            }
        })
        .catch(() => {
            loginSection.classList.remove("hidden");
            setBadge("error", "OFFLINE");
        });

    // ---- cookies panel ----
    const cookiesStatusEl = document.getElementById("cookies-status");
    const cookiesPanel = document.getElementById("cookies-panel");
    const cookiesForm = document.getElementById("cookies-form");
    const cookiesInput = document.getElementById("cookies-input");
    const cookiesMsg = document.getElementById("cookies-msg");
    const cookiesClearBtn = document.getElementById("cookies-clear");

    async function refreshCookiesStatus() {
        try {
            const r = await fetch("/cookies/status", { credentials: "same-origin" });
            const j = await r.json();
            if (j.loaded) {
                cookiesStatusEl.textContent = `✓ loaded (${j.bytes} bytes)`;
                cookiesStatusEl.style.color = "";
            } else {
                cookiesStatusEl.textContent = "✗ not set — paste below to enable youtube downloads";
                cookiesStatusEl.style.color = "var(--accent, #ff9)";
                cookiesPanel?.setAttribute("open", "");
            }
        } catch {
            cookiesStatusEl.textContent = "? unknown";
        }
    }

    cookiesForm?.addEventListener("submit", async (e) => {
        e.preventDefault();
        cookiesMsg.classList.add("hidden");
        cookiesMsg.classList.remove("msg--error");
        const cookies = cookiesInput.value;
        try {
            const r = await fetch("/cookies", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ cookies }),
            });
            const j = await r.json();
            if (r.ok) {
                cookiesMsg.textContent = `saved · ${j.bytes} bytes`;
                cookiesMsg.classList.add("msg--status");
                cookiesMsg.classList.remove("hidden");
                cookiesInput.value = "";
                cookiesPanel?.removeAttribute("open");
                refreshCookiesStatus();
            } else {
                cookiesMsg.textContent = (j.detail || "save failed").toLowerCase();
                cookiesMsg.classList.add("msg--error");
                cookiesMsg.classList.remove("hidden");
            }
        } catch {
            cookiesMsg.textContent = "network error";
            cookiesMsg.classList.add("msg--error");
            cookiesMsg.classList.remove("hidden");
        }
    });

    cookiesClearBtn?.addEventListener("click", async () => {
        cookiesMsg.classList.add("hidden");
        try {
            const r = await fetch("/cookies", {
                method: "DELETE",
                credentials: "same-origin",
            });
            if (r.ok) {
                cookiesInput.value = "";
                refreshCookiesStatus();
            }
        } catch {
            // ignore
        }
    });

    // ---- login ----
    document.getElementById("login-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        loginError.classList.add("hidden");
        setBadge("working", "AUTH");
        const fd = new FormData(e.target);
        try {
            const r = await fetch("/login", {
                method: "POST",
                body: fd,
                credentials: "same-origin",
            });
            if (r.ok) {
                setBadge("done", "OK");
                location.reload();
            } else {
                setBadge("error", "DENIED");
                loginError.textContent = "incorrect passphrase";
                loginError.classList.remove("hidden");
            }
        } catch (err) {
            setBadge("error", "OFFLINE");
            loginError.textContent = "network error";
            loginError.classList.remove("hidden");
        }
    });

    // ---- download flow ----
    const dlForm = document.getElementById("download-form");
    const dlBtn = document.getElementById("download-btn");
    const status = document.getElementById("status");
    const error = document.getElementById("error");

    dlForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        error.classList.add("hidden");
        status.classList.add("hidden");

        const url = document.getElementById("url-input").value;

        dlBtn.disabled = true;
        setBadge("working", "RESOLVE");
        status.textContent = "resolving source…";
        status.classList.remove("hidden");

        let r;
        try {
            r = await fetch("/download/preflight", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ url }),
            });
        } catch (err) {
            setBadge("error", "OFFLINE");
            error.textContent = "network error";
            error.classList.remove("hidden");
            status.classList.add("hidden");
            dlBtn.disabled = false;
            return;
        }

        if (!r.ok) {
            const body = await r.json().catch(() => ({}));
            setBadge("error", "ERROR");
            error.textContent = (body.detail || "could not resolve url").toLowerCase();
            error.classList.remove("hidden");
            status.classList.add("hidden");
            dlBtn.disabled = false;
            return;
        }

        const info = await r.json();
        const noun = info.entry_count === 1 ? "track" : "tracks";
        setBadge("working", "STREAM");
        status.textContent = `preparing ${info.entry_count} ${noun} · streaming zip…`;

        document.getElementById("hidden-url").value = url;
        document.getElementById("hidden-download").submit();

        setTimeout(() => {
            dlBtn.disabled = false;
            setBadge("done", "DONE");
            status.textContent = "stream initiated · check your downloads";
        }, 1500);

        // Drift back to READY after a longer beat.
        setTimeout(() => setBadge("ready", "READY"), 6000);
    });
})();
