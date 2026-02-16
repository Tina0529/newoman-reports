/**
 * auth.js - Simple client-side password gate
 * SHA-256 hash comparison with sessionStorage persistence
 */
(function() {
    // SHA-256 hash of the password (default: "newoman2025")
    const PASSWORD_HASH = 'cf73b8e05bec3277b86496eca8eddd2fbd6dc793a4105ee19ecc3335cd658aae';

    const AUTH_KEY = 'dashboard_authenticated';

    async function sha256(message) {
        const msgBuffer = new TextEncoder().encode(message);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }

    function isAuthenticated() {
        return sessionStorage.getItem(AUTH_KEY) === 'true';
    }

    function showApp() {
        document.getElementById('auth-modal').style.display = 'none';
        document.getElementById('app').style.display = 'block';
        document.getElementById('admin-btn').style.display = 'inline-flex';
    }

    function showAuthModal() {
        document.getElementById('auth-modal').style.display = 'flex';
        document.getElementById('app').style.display = 'none';
        setTimeout(() => document.getElementById('auth-password').focus(), 100);
    }

    async function handleLogin() {
        const password = document.getElementById('auth-password').value;
        const hash = await sha256(password);

        if (hash === PASSWORD_HASH) {
            sessionStorage.setItem(AUTH_KEY, 'true');
            showApp();
            // Trigger dashboard initialization
            if (window.initDashboard) window.initDashboard();
        } else {
            document.getElementById('auth-error').style.display = 'block';
            document.getElementById('auth-password').value = '';
            document.getElementById('auth-password').focus();
        }
    }

    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', function() {
        if (isAuthenticated()) {
            showApp();
            if (window.initDashboard) window.initDashboard();
        } else {
            showAuthModal();
        }

        document.getElementById('auth-submit').addEventListener('click', handleLogin);
        document.getElementById('auth-password').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') handleLogin();
        });

        // Admin panel toggle
        document.getElementById('admin-btn').addEventListener('click', function() {
            const panel = document.getElementById('admin-panel');
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        });
    });
})();
