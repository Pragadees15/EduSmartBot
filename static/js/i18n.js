// Lightweight client-side i18n for EduSmartBot
// - Loads language dictionaries from /static/i18n/<lang>.json
// - Applies to elements with [data-i18n] and placeholders via [data-i18n-placeholder]

(function() {
  const LANG_STORAGE_KEY = 'lang';
  const DEFAULT_LANG = document.documentElement.getAttribute('lang') || 'en';
  let currentDict = null;

  function getSavedLang() {
    try {
      return localStorage.getItem(LANG_STORAGE_KEY) || DEFAULT_LANG;
    } catch (e) {
      return DEFAULT_LANG;
    }
  }

  function saveLang(lang) {
    try { localStorage.setItem(LANG_STORAGE_KEY, lang); } catch (e) {}
  }

  async function setServerLang(lang) {
    try {
      await fetch('/set-language', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lang })
      });
    } catch (e) {
      // non-blocking
    }
  }

  async function loadDictionary(lang) {
    const response = await fetch(`/static/i18n/${lang}.json`, { cache: 'no-cache' });
    if (!response.ok) throw new Error('Failed to load translations');
    return response.json();
  }

  function resolveKey(obj, key) {
    return key.split('.').reduce((acc, part) => (acc && acc[part] != null ? acc[part] : null), obj);
  }

  function applyTranslations(dict) {
    if (!dict) return;
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      const value = resolveKey(dict, key);
      if (typeof value === 'string') {
        el.textContent = value;
      }
    });

    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      const value = resolveKey(dict, key);
      if (typeof value === 'string') {
        el.setAttribute('placeholder', value);
      }
    });
  }

  async function initI18n() {
    const select = document.getElementById('language-select');
    const saved = getSavedLang();
    let lang = saved;
    if (select) {
      const selectHasSaved = Array.from(select.options).some(o => o.value === saved);
      if (select.value && (!saved || saved === '')) {
        lang = select.value;
      } else if (selectHasSaved) {
        select.value = saved;
        lang = saved;
      } else if (select.value) {
        lang = select.value;
      }
    }
    try {
      const dict = await loadDictionary(lang);
      currentDict = dict;
      applyTranslations(dict);
      document.documentElement.setAttribute('lang', lang);
      saveLang(lang);
      setServerLang(lang);
    } catch (e) {
      if (lang !== 'en') {
        // Fallback to English
        const dict = await loadDictionary('en');
        currentDict = dict;
        applyTranslations(dict);
        document.documentElement.setAttribute('lang', 'en');
        saveLang('en');
      }
    }

    if (select) {
      select.addEventListener('change', async (e) => {
        const newLang = e.target.value;
        try {
          const dict = await loadDictionary(newLang);
          currentDict = dict;
          applyTranslations(dict);
          document.documentElement.setAttribute('lang', newLang);
          saveLang(newLang);
          setServerLang(newLang);
        } catch (err) {
          // Revert if failed
          e.target.value = getSavedLang();
        }
      });
    }
  }

  // Initialize after DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initI18n);
  } else {
    initI18n();
  }

  // Expose a minimal global API for re-applying translations on dynamic DOM updates
  window.I18N = {
    apply: function() { applyTranslations(currentDict); },
    get: function(key, fallback) {
      if (!currentDict) return fallback || '';
      const v = resolveKey(currentDict, key);
      return (v == null ? (fallback || '') : String(v));
    }
  };
})();


