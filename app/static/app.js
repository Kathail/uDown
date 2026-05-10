(function () {
    const loginSection = document.getElementById("login-section");
    const downloadSection = document.getElementById("download-section");
    const loginError = document.getElementById("login-error");

    // Live timestamp in the masthead — broadcast-clock vibe.
    const clockEl = document.getElementById("meta-clock");
    function tick() {
        if (!clockEl) return;
        const d = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        clockEl.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }
    tick();
    setInterval(tick, 1000);

    // Initial state — quick GET /me. Fall back to login on network error.
    fetch("/me", { credentials: "same-origin" })
        .then((r) => {
            if (r.status === 200) {
                downloadSection.classList.remove("hidden");
            } else {
                loginSection.classList.remove("hidden");
            }
        })
        .catch(() => {
            loginSection.classList.remove("hidden");
        });

    // Login: handle errors inline so the page doesn't navigate away.
    document.getElementById("login-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        loginError.classList.add("hidden");
        const fd = new FormData(e.target);
        const r = await fetch("/login", {
            method: "POST",
            body: fd,
            credentials: "same-origin",
        });
        if (r.ok) {
            location.reload();
        } else {
            loginError.textContent = "incorrect passphrase";
            loginError.classList.remove("hidden");
        }
    });

    // Download: preflight (cheap, returns inline errors) then submit the hidden
    // form so the browser handles the streaming zip response natively.
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
        status.textContent = "resolving source…";
        status.classList.remove("hidden");

        const r = await fetch("/download/preflight", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ url }),
        });

        if (!r.ok) {
            const body = await r.json().catch(() => ({}));
            error.textContent = (body.detail || "could not resolve url").toLowerCase();
            error.classList.remove("hidden");
            status.classList.add("hidden");
            dlBtn.disabled = false;
            return;
        }

        const info = await r.json();
        const noun = info.entry_count === 1 ? "track" : "tracks";
        status.textContent = `preparing ${info.entry_count} ${noun} · streaming zip…`;

        document.getElementById("hidden-url").value = url;
        document.getElementById("hidden-download").submit();

        setTimeout(() => {
            dlBtn.disabled = false;
            status.textContent = "stream initiated · check your downloads";
        }, 1500);
    });
})();
