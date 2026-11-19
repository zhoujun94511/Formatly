(function () {
  var theme;
  try { theme = localStorage.getItem('formatly.theme'); } catch (_) {}
  if (theme !== 'light' && theme !== 'dark') {
    theme = 'light';
    try { if (matchMedia('(prefers-color-scheme: dark)').matches) theme = 'dark'; } catch (_) {}
  }
  document.documentElement.setAttribute('data-theme', theme);
})();
