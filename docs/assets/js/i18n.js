/**
 * i18n.js - JA/ZH language toggle
 * Uses data-ja / data-zh attributes on elements
 */
(function() {
    const LANG_KEY = 'dashboard_lang';
    let currentLang = localStorage.getItem(LANG_KEY) || 'ja';

    function applyLanguage(lang) {
        currentLang = lang;
        localStorage.setItem(LANG_KEY, lang);

        document.querySelectorAll('[data-ja][data-zh]').forEach(el => {
            const text = el.getAttribute('data-' + lang);
            if (text) {
                if (el.tagName === 'INPUT' && el.type === 'text') {
                    el.placeholder = text;
                } else {
                    el.innerHTML = text;
                }
            }
        });

        // Update toggle label
        const label = document.getElementById('lang-label');
        if (label) {
            label.textContent = lang === 'ja' ? '中文' : '日本語';
        }

        document.documentElement.lang = lang === 'ja' ? 'ja' : 'zh';
    }

    window.i18n = {
        current: () => currentLang,
        apply: applyLanguage,
        toggle: () => applyLanguage(currentLang === 'ja' ? 'zh' : 'ja'),
    };

    document.addEventListener('DOMContentLoaded', function() {
        applyLanguage(currentLang);

        document.getElementById('lang-toggle').addEventListener('click', function() {
            window.i18n.toggle();
        });
    });
})();
