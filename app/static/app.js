(function () {
    const loginSection = document.getElementById("login-section");
    const downloadSection = document.getElementById("download-section");
    const loginError = document.getElementById("login-error");

    // Initial state — server tells us via a body data attribute or we just check
    // whether a session cookie is present. We'll do a quick GET /me.
    fetch("/me", { credentials: "same-origin" }).then((r) => {
        if (r.status === 200) {
            downloadSection.classList.remove("hidden");
        } else {
            loginSection.classList.remove("hidden");
        }
    });

    // Login form: handle errors inline (default form post would replace the page).
    document.getElementById("login-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const r = await fetch("/login", {
            method: "POST",
            body: fd,
            credentials: "same-origin",
        });
        if (r.ok) {
            location.reload();
        } else {
            loginError.textContent = "Incorrect password";
            loginError.classList.remove("hidden");
        }
    });

    // Download flow: preflight first (so we can show errors inline), then submit
    // the hidden form so the browser handles the streaming response natively.
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
        status.textContent = "Resolving…";
        status.classList.remove("hidden");

        const r = await fetch("/download/preflight", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ url }),
        });

        if (!r.ok) {
            const body = await r.json().catch(() => ({}));
            error.textContent = body.detail || "Could not resolve URL";
            error.classList.remove("hidden");
            status.classList.add("hidden");
            dlBtn.disabled = false;
            return;
        }

        const info = await r.json();
        status.textContent = `Preparing your download (${info.entry_count} ${
            info.entry_count === 1 ? "track" : "tracks"
        })…`;

        // Trigger streaming download via hidden form.
        document.getElementById("hidden-url").value = url;
        document.getElementById("hidden-download").submit();

        // Re-enable after a short delay (the page doesn't navigate, but the
        // form submit kicks off the download).
        setTimeout(() => {
            dlBtn.disabled = false;
            status.textContent = "Download started. You can submit another URL.";
        }, 1500);
    });
})();
