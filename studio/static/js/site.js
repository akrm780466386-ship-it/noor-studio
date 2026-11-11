(() => {
  const root = document.documentElement;
  const languageButton = document.getElementById("languageToggle");
  const themeButton = document.getElementById("themeToggle");
  const themeIcon = document.getElementById("themeIcon");
  const loader = document.getElementById("loader");

  const readPreference = (key, fallback) => {
    try {
      return localStorage.getItem(key) || fallback;
    } catch (error) {
      console.warn("Could not read a saved site preference.", error);
      return fallback;
    }
  };
  const savePreference = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch (error) {
      console.warn("Could not save a site preference.", error);
    }
  };

  function updateThemeLabel() {
    if (!themeButton) return;
    const light = root.dataset.theme === "light";
    themeButton.setAttribute(
      "aria-label",
      light
        ? (root.lang === "en" ? "Switch to dark mode" : "التبديل إلى الوضع الداكن")
        : (root.lang === "en" ? "Switch to light mode" : "التبديل إلى الوضع الفاتح")
    );
  }

  function setLanguage(language) {
    const english = language === "en";
    root.lang = language;
    root.dir = english ? "ltr" : "rtl";
    document.querySelectorAll("[data-ar][data-en]").forEach((element) => {
      element.textContent = element.dataset[language];
    });
    document.title = document.body.dataset[english ? "titleEn" : "titleAr"];
    if (languageButton) {
      languageButton.textContent = english ? "عربي" : "EN";
      languageButton.setAttribute(
        "aria-label",
        english ? "Switch to Arabic" : "Switch to English"
      );
    }
    const nav = document.querySelector(".main-nav");
    if (nav) nav.setAttribute("aria-label", english ? "Main navigation" : "التنقل الرئيسي");
    updateThemeLabel();
    document.querySelectorAll("form[data-confirm-ar]").forEach((form) => {
      form.dataset.confirm = form.dataset[english ? "confirmEn" : "confirmAr"];
    });
    savePreference("noor-language", language);
  }

  function setTheme(theme) {
    const light = theme === "light";
    root.dataset.theme = theme;
    if (themeIcon) themeIcon.textContent = light ? "☾" : "☼";
    updateThemeLabel();
    savePreference("noor-theme", theme);
  }

  if (languageButton) {
    languageButton.addEventListener("click", () => {
      setLanguage(root.lang === "ar" ? "en" : "ar");
    });
  }
  if (themeButton) {
    themeButton.addEventListener("click", () => {
      setTheme(root.dataset.theme === "light" ? "dark" : "light");
    });
  }
  document.querySelectorAll("form[data-confirm-ar]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const message = form.dataset[root.lang === "en" ? "confirmEn" : "confirmAr"];
      if (!window.confirm(message)) event.preventDefault();
    });
  });

  setLanguage(readPreference("noor-language", "ar"));
  setTheme(readPreference("noor-theme", "dark"));

  if (loader) {
    root.classList.add("is-loading");
    window.setTimeout(() => {
      loader.classList.add("loader-hidden");
      root.classList.remove("is-loading");
      window.setTimeout(() => loader.remove(), 600);
    }, 850);
  }
})();
