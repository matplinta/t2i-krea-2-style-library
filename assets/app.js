(() => {
  'use strict';

  const FAVORITES_KEY = 'krea2-style-library-favorites-v2';
  const BASE_PROMPT_KEY = 'krea2-style-library-base-prompt-v1';
  const SHOW_BASE_IMAGE_KEY = 'krea2-style-library-show-base-image-v1';
  const CARD_DETAILS_KEY = 'krea2-style-library-card-details-v1';
  const GRID_COLUMNS_KEY = 'krea2-style-library-grid-columns-v1';
  const BASE_IMAGE_ID = 'base';
  const $ = (selector) => document.querySelector(selector);

  const state = {
    styles: [],
    basePrompts: [],
    manifestImages: {},
    favorites: new Set(),
    activePromptId: '',
    showBaseImage: false,
    showCardDetails: false,
    gridColumns: 5,
  };
  let viewerImages = [];
  let viewerIndex = -1;
  let touchGesture = null;
  let touchNavigationTimer = null;

  function loadFavorites() {
    try {
      const value = JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]');
      return new Set(Array.isArray(value) ? value.filter((id) => typeof id === 'string') : []);
    } catch (_) {
      return new Set();
    }
  }

  function saveFavorites() {
    try {
      localStorage.setItem(FAVORITES_KEY, JSON.stringify([...state.favorites]));
    } catch (_) {
      showNotice('Favorites could not be saved in this browser.');
    }
  }

  function loadActivePromptId() {
    try {
      return localStorage.getItem(BASE_PROMPT_KEY) || '';
    } catch (_) {
      return '';
    }
  }

  function saveActivePromptId() {
    try {
      localStorage.setItem(BASE_PROMPT_KEY, state.activePromptId);
    } catch (_) {
      // The selector still works for the current session.
    }
  }

  function loadBaseImagePreference() {
    try {
      return localStorage.getItem(SHOW_BASE_IMAGE_KEY) === 'true';
    } catch (_) {
      return false;
    }
  }

  function saveBaseImagePreference() {
    try {
      localStorage.setItem(SHOW_BASE_IMAGE_KEY, String(state.showBaseImage));
    } catch (_) {
      // The toggle still works for the current session.
    }
  }

  function loadCardDetailsPreference() {
    try {
      const stored = localStorage.getItem(CARD_DETAILS_KEY);
      return stored === null ? false : stored !== 'false';
    } catch (_) {
      return false;
    }
  }

  function saveCardDetailsPreference() {
    try {
      localStorage.setItem(CARD_DETAILS_KEY, String(state.showCardDetails));
    } catch (_) {
      // The toggle still works for the current session.
    }
  }

  function applyCardDetailsVisibility() {
    $('#show-card-details').checked = state.showCardDetails;
    $('#catalog').classList.toggle('details-hidden', !state.showCardDetails);
  }

  function loadGridColumnsPreference() {
    try {
      const value = Number.parseInt(localStorage.getItem(GRID_COLUMNS_KEY) || '', 10);
      return Number.isInteger(value) ? Math.min(8, Math.max(1, value)) : 5;
    } catch (_) {
      return 5;
    }
  }

  function saveGridColumnsPreference() {
    try {
      localStorage.setItem(GRID_COLUMNS_KEY, String(state.gridColumns));
    } catch (_) {
      // The slider still works for the current session.
    }
  }

  function responsiveColumnCap() {
    if (window.innerWidth <= 700) return 2;
    if (window.innerWidth <= 1050) return 3;
    if (window.innerWidth <= 1320) return 4;
    return 8;
  }

  function applyGridColumns() {
    const columnCap = responsiveColumnCap();
    const visibleColumns = Math.min(state.gridColumns, columnCap);
    $('#grid-columns').max = String(columnCap);
    $('#grid-columns').value = String(visibleColumns);
    $('#grid-columns-value').value = String(visibleColumns);
    $('#grid-columns-value').textContent = String(visibleColumns);
    $('#grid-columns').title = visibleColumns === state.gridColumns
      ? `${visibleColumns} images per row`
      : `${state.gridColumns} selected; showing ${visibleColumns} at this viewport width`;
    $('#catalog').style.setProperty('--columns', String(visibleColumns));
  }

  async function fetchJson(path) {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
    return response.json();
  }

  function unique(values) {
    return [...new Set(values)];
  }

  function configureFilters() {
    const categorySelect = $('#category-filter');
    const categories = unique(state.styles.flatMap((style) => style.categories || []))
      .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    categorySelect.replaceChildren(new Option('All categories', ''));
    categories.forEach((category) => categorySelect.add(new Option(category, category)));

    const promptSelect = $('#base-prompt');
    promptSelect.replaceChildren();
    if (!state.basePrompts.length) {
      promptSelect.add(new Option('No base prompts configured', ''));
      promptSelect.disabled = true;
      state.activePromptId = '';
      return;
    }

    promptSelect.disabled = false;
    state.basePrompts.forEach((prompt) => promptSelect.add(new Option(prompt.label, prompt.id)));
    const savedPrompt = loadActivePromptId();
    state.activePromptId = state.basePrompts.some((prompt) => prompt.id === savedPrompt)
      ? savedPrompt
      : state.basePrompts[0].id;
    promptSelect.value = state.activePromptId;
  }

  function activePrompt() {
    return state.basePrompts.find((prompt) => prompt.id === state.activePromptId) || null;
  }

  function updatePromptViewer() {
    const prompt = activePrompt();
    const viewButton = $('#view-base-prompt');
    viewButton.disabled = !prompt;
    $('#base-prompt-heading').textContent = prompt ? prompt.label : 'Base prompt';
    $('#base-prompt-text').textContent = prompt ? prompt.prompt : '';
  }

  function imageRecord(styleId) {
    if (!state.activePromptId) return null;
    const record = state.manifestImages[`${state.activePromptId}/${styleId}`];
    return record && record.status === 'complete' && record.path ? record : null;
  }

  function filteredStyles() {
    const query = $('#search').value.trim().toLocaleLowerCase();
    const category = $('#category-filter').value;
    const favoritesOnly = $('#favorites-only').checked;
    const sort = $('#sort').value;

    const rows = state.styles.filter((style) => {
      const searchable = `${style.name}\n${style.descriptor}\n${(style.categories || []).join(' ')}`
        .toLocaleLowerCase();
      return (!query || searchable.includes(query))
        && (!category || style.categories.includes(category))
        && (!favoritesOnly || state.favorites.has(style.id));
    });

    if (sort === 'az') {
      rows.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
    } else if (sort === 'za') {
      rows.sort((a, b) => b.name.localeCompare(a.name, undefined, { sensitivity: 'base' }));
    } else if (sort === 'favorites') {
      rows.sort((a, b) => Number(state.favorites.has(b.id))
        - Number(state.favorites.has(a.id)) || a.order - b.order);
    }
    return rows;
  }

  function heartIcon() {
    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(namespace, 'path');
    path.setAttribute('d', 'M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78Z');
    svg.appendChild(path);
    return svg;
  }

  function copyIcon() {
    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const rect = document.createElementNS(namespace, 'rect');
    rect.setAttribute('x', '9');
    rect.setAttribute('y', '9');
    rect.setAttribute('width', '12');
    rect.setAttribute('height', '12');
    rect.setAttribute('rx', '2');
    const path = document.createElementNS(namespace, 'path');
    path.setAttribute('d', 'M15 9V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h4');
    svg.append(rect, path);
    return svg;
  }

  async function copyToClipboard(text) {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch (_) {
        // Fall through to the local-file-compatible copy method.
      }
    }
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand('copy');
    area.remove();
    if (!copied) throw new Error('Clipboard access is unavailable');
  }

  function createStyleCopyButton(style) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'copy-style-button';
    button.setAttribute('aria-label', `Copy ${style.name} style prompt`);
    button.title = 'Copy style name and descriptor';
    button.appendChild(copyIcon());
    button.addEventListener('click', async () => {
      const text = `${style.name}. ${style.descriptor}`;
      try {
        await copyToClipboard(text);
        button.classList.add('copied');
        showNotice(`Copied ${style.name}.`);
        setTimeout(() => button.classList.remove('copied'), 1400);
      } catch (_) {
        showNotice('The style prompt could not be copied in this browser.');
      }
    });
    return button;
  }

  function updateFavoriteButton(button, style) {
    const favorite = state.favorites.has(style.id);
    button.setAttribute('aria-pressed', String(favorite));
    button.setAttribute('aria-label', `${favorite ? 'Remove' : 'Add'} ${style.name} ${favorite ? 'from' : 'to'} favorites`);
    button.title = favorite ? 'Remove from favorites' : 'Add to favorites';
  }

  function createEmptyState() {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No styles match the current filters.';
    return empty;
  }

  function reorderVisibleStyleCards(rows) {
    const catalog = $('#catalog');
    const cards = new Map(
      [...catalog.querySelectorAll('.style-card[data-style-id]')]
        .map((card) => [card.dataset.styleId, card]),
    );
    rows.forEach((style) => {
      const card = cards.get(style.id);
      if (card) catalog.appendChild(card);
    });
  }

  function createFavoriteButton(style) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'favorite-button';
    updateFavoriteButton(button, style);
    button.appendChild(heartIcon());
    button.addEventListener('click', () => {
      if (state.favorites.has(style.id)) state.favorites.delete(style.id);
      else state.favorites.add(style.id);
      saveFavorites();
      updateFavoriteButton(button, style);

      const rows = filteredStyles();
      if ($('#favorites-only').checked) {
        button.closest('.style-card')?.remove();
        if (!rows.length && !$('#catalog .empty-state')) {
          $('#catalog').appendChild(createEmptyState());
        }
      } else if ($('#sort').value === 'favorites') {
        reorderVisibleStyleCards(rows);
      }
      updateCounters(rows.length);
    });
    return button;
  }

  function updateImageViewer() {
    if (!viewerImages.length || viewerIndex < 0) return;
    const image = viewerImages[viewerIndex];
    const fullImage = $('#image-viewer-image');
    fullImage.src = image.currentSrc || image.src;
    fullImage.alt = image.alt;
    $('#image-viewer-style-name').textContent = image.dataset.viewerStyleName || image.alt;
    $('#image-viewer-prompt-label').textContent = image.dataset.viewerPromptLabel || '';
    $('#image-viewer-position').textContent = `${viewerIndex + 1} / ${viewerImages.length}`;

    const hasMultipleImages = viewerImages.length > 1;
    const previousButton = $('#previous-image');
    const nextButton = $('#next-image');
    previousButton.hidden = !hasMultipleImages;
    nextButton.hidden = !hasMultipleImages;
    if (hasMultipleImages) {
      const previousIndex = (viewerIndex - 1 + viewerImages.length) % viewerImages.length;
      const nextIndex = (viewerIndex + 1) % viewerImages.length;
      previousButton.setAttribute('aria-label', `View previous image: ${viewerImages[previousIndex].dataset.viewerStyleName}`);
      nextButton.setAttribute('aria-label', `View next image: ${viewerImages[nextIndex].dataset.viewerStyleName}`);
    }
  }

  function hideTouchViewerNavigation() {
    clearTimeout(touchNavigationTimer);
    touchNavigationTimer = null;
    $('.image-viewer-stage').classList.remove('touch-navigation-visible');
  }

  function revealTouchViewerNavigation() {
    clearTimeout(touchNavigationTimer);
    $('.image-viewer-stage').classList.add('touch-navigation-visible');
    touchNavigationTimer = setTimeout(hideTouchViewerNavigation, 2000);
  }

  function toggleTouchViewerNavigation() {
    if ($('.image-viewer-stage').classList.contains('touch-navigation-visible')) {
      hideTouchViewerNavigation();
    } else {
      revealTouchViewerNavigation();
    }
  }

  function openImageViewer(image) {
    const viewer = $('#image-viewer');
    viewerImages = [...document.querySelectorAll('#catalog .image-wrap img')];
    viewerIndex = viewerImages.indexOf(image);
    if (viewerIndex < 0) {
      viewerImages = [image];
      viewerIndex = 0;
    }
    updateImageViewer();
    if (viewer.open) return;
    if (typeof viewer.showModal === 'function') viewer.showModal();
    else viewer.setAttribute('open', '');
    if (window.matchMedia('(hover: none)').matches) revealTouchViewerNavigation();
  }

  function navigateImageViewer(offset) {
    if (viewerImages.length < 2) return;
    viewerIndex = (viewerIndex + offset + viewerImages.length) % viewerImages.length;
    updateImageViewer();
  }

  function closeImageViewer() {
    const viewer = $('#image-viewer');
    if (typeof viewer.close === 'function' && viewer.open) viewer.close();
    else viewer.removeAttribute('open');
    $('#image-viewer-image').removeAttribute('src');
    viewerImages = [];
    viewerIndex = -1;
    touchGesture = null;
    hideTouchViewerNavigation();
  }

  function createImage(style, { allowFavorite = true } = {}) {
    const generated = imageRecord(style.id);
    const prompt = activePrompt();
    const widthValue = Number(generated?.width || prompt?.width || 1024);
    const heightValue = Number(generated?.height || prompt?.height || 1536);
    const width = Number.isFinite(widthValue) && widthValue > 0 ? widthValue : 1024;
    const height = Number.isFinite(heightValue) && heightValue > 0 ? heightValue : 1536;
    const imageWrap = document.createElement('div');
    imageWrap.className = 'image-wrap';
    imageWrap.style.aspectRatio = `${width} / ${height}`;
    if (allowFavorite) imageWrap.appendChild(createFavoriteButton(style));

    if (!generated) {
      const placeholder = document.createElement('div');
      placeholder.className = 'image-placeholder';
      placeholder.textContent = state.activePromptId
        ? 'Preview unavailable'
        : 'Configure a base prompt to generate previews';
      imageWrap.appendChild(placeholder);
      return imageWrap;
    }

    const image = document.createElement('img');
    image.src = generated.path;
    image.alt = `${style.name} generated with ${activePrompt()?.label || 'the selected base prompt'}`;
    image.dataset.viewerStyleName = style.name;
    image.dataset.viewerPromptLabel = activePrompt()?.label || 'Selected base prompt';
    image.loading = 'lazy';
    image.decoding = 'async';
    image.width = width;
    image.height = height;
    image.tabIndex = 0;
    image.setAttribute('role', 'button');
    image.setAttribute('aria-label', `View full image: ${image.alt}`);
    image.title = 'View full image';
    image.addEventListener('click', () => openImageViewer(image));
    image.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      openImageViewer(image);
    });
    image.addEventListener('error', () => {
      image.remove();
      const placeholder = document.createElement('div');
      placeholder.className = 'image-placeholder';
      placeholder.textContent = 'Preview unavailable';
      imageWrap.appendChild(placeholder);
    }, { once: true });
    imageWrap.appendChild(image);
    return imageWrap;
  }

  function createBaseCard() {
    const prompt = activePrompt();
    const reference = { id: BASE_IMAGE_ID, name: 'Base image — no style' };
    const card = document.createElement('article');
    card.className = 'style-card base-image-card';

    const heading = document.createElement('div');
    heading.className = 'card-heading';
    const title = document.createElement('h2');
    title.className = 'style-name';
    title.textContent = 'Base image — no style';
    heading.appendChild(title);
    card.append(heading, createImage(reference, { allowFavorite: false }));

    const body = document.createElement('div');
    body.className = 'card-body';
    const descriptor = document.createElement('p');
    descriptor.className = 'descriptor';
    descriptor.textContent = prompt
      ? `Reference generated from “${prompt.label}” without a style descriptor.`
      : 'Reference generated without a style descriptor.';
    body.appendChild(descriptor);
    card.appendChild(body);
    return card;
  }

  function createCard(style) {
    const card = document.createElement('article');
    card.className = 'style-card';
    card.dataset.styleId = style.id;

    const heading = document.createElement('div');
    heading.className = 'card-heading';
    const title = document.createElement('h2');
    title.className = 'style-name';
    title.textContent = style.name;
    heading.append(title, createStyleCopyButton(style));
    card.append(heading, createImage(style));

    const body = document.createElement('div');
    body.className = 'card-body';
    const descriptor = document.createElement('p');
    descriptor.className = 'descriptor';
    descriptor.textContent = style.descriptor;
    body.appendChild(descriptor);

    const categories = document.createElement('div');
    categories.className = 'categories';
    style.categories.forEach((category) => {
      const tag = document.createElement('span');
      tag.textContent = category;
      categories.appendChild(tag);
    });
    body.appendChild(categories);
    card.appendChild(body);
    return card;
  }

  function updateCounters(visibleCount) {
    $('#library-summary').textContent = `${state.styles.length} styles`;
    $('#favorite-count').textContent = `${state.favorites.size} favorite${state.favorites.size === 1 ? '' : 's'}`;
    $('#result-count').textContent = `Showing ${visibleCount} of ${state.styles.length}`;
    $('#export-all').disabled = state.styles.length === 0;
    $('#export-favorites').disabled = state.favorites.size === 0;
  }

  function render() {
    const rows = filteredStyles();
    const catalog = $('#catalog');
    catalog.replaceChildren();
    const fragment = document.createDocumentFragment();
    if (state.showBaseImage && activePrompt()) fragment.appendChild(createBaseCard());
    if (!rows.length) {
      fragment.appendChild(createEmptyState());
    } else {
      rows.forEach((style) => fragment.appendChild(createCard(style)));
    }
    catalog.appendChild(fragment);
    updateCounters(rows.length);
  }

  function exportShape(style) {
    return {
      name: style.name,
      descriptor: style.descriptor,
      categories: [...style.categories],
    };
  }

  function downloadJson(filename, styles) {
    const content = `${JSON.stringify(styles.map(exportShape), null, 2)}\n`;
    const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  let noticeTimer = null;
  function showNotice(message) {
    const notice = $('#notice');
    notice.textContent = message;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => {
      if (notice.textContent === message) notice.textContent = '';
    }, 3500);
  }

  function bindEvents() {
    $('#mobile-menu-toggle').addEventListener('click', (event) => {
      const header = $('.site-header');
      const isOpen = header.classList.toggle('mobile-menu-open');
      event.currentTarget.setAttribute('aria-expanded', String(isOpen));
    });
    $('#search').addEventListener('input', render);
    ['#sort', '#category-filter', '#favorites-only'].forEach((selector) => {
      $(selector).addEventListener('change', render);
    });
    $('#show-base-image').addEventListener('change', (event) => {
      state.showBaseImage = event.target.checked;
      saveBaseImagePreference();
      render();
    });
    $('#show-card-details').addEventListener('change', (event) => {
      state.showCardDetails = event.target.checked;
      saveCardDetailsPreference();
      applyCardDetailsVisibility();
    });
    $('#grid-columns').addEventListener('input', (event) => {
      state.gridColumns = Number.parseInt(event.target.value, 10);
      saveGridColumnsPreference();
      applyGridColumns();
    });
    window.addEventListener('resize', applyGridColumns);
    $('#base-prompt').addEventListener('change', (event) => {
      state.activePromptId = event.target.value;
      saveActivePromptId();
      updatePromptViewer();
      render();
    });
    $('#view-base-prompt').addEventListener('click', () => {
      updatePromptViewer();
      const dialog = $('#base-prompt-dialog');
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    });
    $('#close-base-prompt').addEventListener('click', () => {
      const dialog = $('#base-prompt-dialog');
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    });
    $('#base-prompt-dialog').addEventListener('click', (event) => {
      if (event.target !== event.currentTarget) return;
      if (typeof event.currentTarget.close === 'function') event.currentTarget.close();
      else event.currentTarget.removeAttribute('open');
    });
    $('#close-image-viewer').addEventListener('click', closeImageViewer);
    $('#previous-image').addEventListener('click', () => navigateImageViewer(-1));
    $('#next-image').addEventListener('click', () => navigateImageViewer(1));
    const imageViewerStage = $('.image-viewer-stage');
    imageViewerStage.addEventListener('pointerdown', (event) => {
      if (event.pointerType !== 'touch' || event.target.closest('.image-viewer-nav')) return;
      touchGesture = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
      };
    });
    imageViewerStage.addEventListener('pointerup', (event) => {
      if (event.pointerType !== 'touch') return;
      if (event.target.closest('.image-viewer-nav')) {
        revealTouchViewerNavigation();
        touchGesture = null;
        return;
      }
      if (!touchGesture || touchGesture.pointerId !== event.pointerId) return;
      const deltaX = event.clientX - touchGesture.startX;
      const deltaY = event.clientY - touchGesture.startY;
      touchGesture = null;
      if (Math.abs(deltaX) >= 48 && Math.abs(deltaX) > Math.abs(deltaY) * 1.2) {
        navigateImageViewer(deltaX < 0 ? 1 : -1);
        revealTouchViewerNavigation();
      } else if (Math.abs(deltaX) < 12 && Math.abs(deltaY) < 12) {
        toggleTouchViewerNavigation();
      }
    });
    imageViewerStage.addEventListener('pointercancel', () => {
      touchGesture = null;
    });
    $('#image-viewer').addEventListener('click', (event) => {
      if (event.target === event.currentTarget) closeImageViewer();
    });
    $('#image-viewer').addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      navigateImageViewer(event.key === 'ArrowLeft' ? -1 : 1);
    });
    $('#image-viewer').addEventListener('close', () => {
      $('#image-viewer-image').removeAttribute('src');
      viewerImages = [];
      viewerIndex = -1;
      touchGesture = null;
      hideTouchViewerNavigation();
    });
    $('#export-all').addEventListener('click', () => {
      downloadJson('krea2-styles.json', state.styles);
      showNotice(`Exported ${state.styles.length} styles.`);
      $('.export-menu').removeAttribute('open');
    });
    $('#export-favorites').addEventListener('click', () => {
      const favorites = state.styles.filter((style) => state.favorites.has(style.id));
      downloadJson('krea2-favorite-styles.json', favorites);
      showNotice(`Exported ${favorites.length} favorite${favorites.length === 1 ? '' : 's'}.`);
      $('.export-menu').removeAttribute('open');
    });
    document.addEventListener('click', (event) => {
      const menu = $('.export-menu');
      if (menu.open && !menu.contains(event.target)) menu.removeAttribute('open');
    });
  }

  async function init() {
    state.favorites = loadFavorites();
    state.showBaseImage = loadBaseImagePreference();
    state.showCardDetails = loadCardDetailsPreference();
    state.gridColumns = loadGridColumnsPreference();
    bindEvents();
    $('#show-base-image').checked = state.showBaseImage;
    applyCardDetailsVisibility();
    applyGridColumns();
    try {
      const [catalog, promptConfig, manifest] = await Promise.all([
        fetchJson('data/styles.json'),
        fetchJson('data/base_prompts.json'),
        fetchJson('data/generation_manifest.json'),
      ]);
      state.styles = Array.isArray(catalog.styles) ? catalog.styles : [];
      state.basePrompts = Array.isArray(promptConfig.prompts)
        ? promptConfig.prompts.filter((prompt) => prompt.enabled !== false)
        : [];
      state.manifestImages = manifest.images && typeof manifest.images === 'object'
        ? manifest.images
        : {};
      const validIds = new Set(state.styles.map((style) => style.id));
      state.favorites = new Set([...state.favorites].filter((id) => validIds.has(id)));
      saveFavorites();
      configureFilters();
      updatePromptViewer();
      render();
    } catch (error) {
      $('#catalog').innerHTML = '<div class="empty-state">The catalog could not be loaded. Start the local web server from the project directory and reload this page.</div>';
      $('#result-count').textContent = 'Catalog unavailable';
      showNotice(error.message);
    }
  }

  init();
})();
