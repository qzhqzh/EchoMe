// This file also runs as the entry module when cached HTML names a removed build.
(() => {
  const url = new URL(window.location.href);
  const retryKey = '_echome_reload';

  if (!url.searchParams.has(retryKey)) {
    url.searchParams.set(retryKey, String(Date.now()));
    window.location.replace(url.href);
    return;
  }

  // Retry automatically only once. Keep login data and offer an explicit retry
  // if an unavailable network or deployment still prevents the page from loading.
  function showRecovery() {
    const root = document.getElementById('app') || document.body;
    const panel = document.createElement('main');
    panel.style.cssText = 'max-width:32rem;margin:18vh auto;padding:24px;font:16px/1.7 system-ui;color:#e2e8f0;background:#0f172a;border-radius:16px';
    const title = document.createElement('h1');
    title.textContent = '页面资源未能加载';
    title.style.cssText = 'font-size:22px;margin:0 0 12px';
    const explanation = document.createElement('p');
    explanation.textContent = '请重新加载页面。你的登录信息和已保存的数据会保留。';
    const retry = document.createElement('button');
    retry.textContent = '重新加载';
    retry.style.cssText = 'border:0;border-radius:8px;padding:12px 20px;background:#4f46e5;color:white;font:inherit;cursor:pointer';
    retry.addEventListener('click', () => {
      const next = new URL(window.location.href);
      next.searchParams.set(retryKey, String(Date.now()));
      window.location.replace(next.href);
    });
    panel.append(title, explanation, retry);
    root.replaceChildren(panel);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', showRecovery, { once: true });
  } else {
    showRecovery();
  }
})();
