'use strict';
(() => {
  const film = document.querySelector('#cell-film');
  const toggle = document.querySelector('#motion-toggle');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const mobile = matchMedia('(max-width: 700px), (pointer: coarse)');
  let enabled = !reduced.matches && !mobile.matches && !navigator.connection?.saveData;
  let visible = true;
  let attempt = 0;
  function reflect() {
    toggle.hidden = false;
    toggle.setAttribute('aria-pressed', String(enabled));
    toggle.textContent = enabled ? '배경 움직임 끄기' : '배경 움직임 켜기';
    document.documentElement.classList.toggle('motion-paused', !enabled || document.hidden);
  }
  async function update() {
    const current = ++attempt;
    reflect();
    if (!enabled || !visible || document.hidden) { film.pause(); return; }
    if (!film.getAttribute('src')) film.src = film.dataset.src;
    try {
      await film.play();
      if (current === attempt && enabled && visible && !document.hidden) film.classList.add('ready');
      else if (!enabled || !visible || document.hidden) film.pause();
    } catch {
      if (current === attempt) { enabled = false; reflect(); }
    }
  }
  toggle.addEventListener('click', () => { enabled = !enabled; update(); });
  reduced.addEventListener('change', () => { if (reduced.matches) { enabled = false; update(); } });
  document.addEventListener('visibilitychange', update);
  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; update(); }, {threshold:.05}).observe(film);
  const network = document.querySelector('.network-art');
  new IntersectionObserver(([entry]) => network.classList.toggle('in-view', entry.isIntersecting)).observe(network);
  const descriptions = [
    '수집 — 필요한 자료와 출처를 사용자가 선택해 모읍니다.',
    '검증 — 받은 자료를 먼저 격리하고, 내 환경에서 확인한 근거를 남깁니다.',
    '공유 — 검토한 방법을 선택해 게시하면 등록한 다른 Cell이 받아볼 수 있습니다.',
    '개선 — 받은 방법을 다시 검토하고 보완합니다. 지능 향상 여부는 별도 평가가 필요합니다.'
  ];
  document.querySelectorAll('[data-node]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-node]').forEach(node => node.setAttribute('aria-pressed', String(node === button)));
    document.querySelector('#network-detail').textContent = descriptions[Number(button.dataset.node)];
  }));
  update();
})();
