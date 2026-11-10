(function () {
  const wrap = document.getElementById("placementWrap");
  if (!wrap) return; // no PDF in this batch

  const batchId = wrap.dataset.batchId;
  const pageImg = document.getElementById("pageImg");
  const pageSelect = document.getElementById("targetPageSelect");
  const fileSelect = document.getElementById("previewFileSelect");
  const targetPageInput = document.getElementById("targetPageInput");
  const testDetectBtn = document.getElementById("testDetectBtn");
  const detectStatusMsg = document.getElementById("detectStatusMsg");
  const highlightBox = document.getElementById("keywordHighlightBox");
  const highlightLabel = document.getElementById("keywordHighlightLabel");
  const keywordsInput = document.getElementById("keywordsInput");

  const sigOverlay = document.getElementById("sigOverlay");
  const stampOverlay = document.getElementById("stampOverlay");
  const closeSigBtn = document.getElementById("closeSigBtn");
  const closeStampBtn = document.getElementById("closeStampBtn");
  const restoreSigBtn = document.getElementById("restoreSigBtn");
  const restoreStampBtn = document.getElementById("restoreStampBtn");
  const existingStampAlert = document.getElementById("existingStampAlert");
  const includeSigCheckbox = document.getElementById("includeSignature");
  const includeStampCheckbox = document.getElementById("includeStamp");

  let stampUserClosed = false;
  let sigUserClosed = false;

  if (closeSigBtn) {
    closeSigBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      sigUserClosed = true;
      if (sigOverlay) sigOverlay.style.display = "none";
      if (restoreSigBtn) restoreSigBtn.style.display = "inline-flex";
      if (includeSigCheckbox) includeSigCheckbox.checked = false;
    });
  }

  if (restoreSigBtn) {
    restoreSigBtn.addEventListener("click", function () {
      sigUserClosed = false;
      if (sigOverlay) sigOverlay.style.display = "block";
      restoreSigBtn.style.display = "none";
      if (includeSigCheckbox) includeSigCheckbox.checked = true;
    });
  }

  if (closeStampBtn) {
    closeStampBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      stampUserClosed = true;
      if (stampOverlay) stampOverlay.style.display = "none";
      if (restoreStampBtn) restoreStampBtn.style.display = "inline-flex";
      if (includeStampCheckbox) includeStampCheckbox.checked = false;
    });
  }

  if (restoreStampBtn) {
    restoreStampBtn.addEventListener("click", function () {
      stampUserClosed = false;
      if (stampOverlay) stampOverlay.style.display = "block";
      restoreStampBtn.style.display = "none";
      if (includeStampCheckbox) includeStampCheckbox.checked = true;
    });
  }

  let currentPageCount = parseInt(wrap.dataset.pageCount, 10) || 1;

  function updatePreviewImage() {
    const fileId = fileSelect ? fileSelect.value : "";
    const val = pageSelect.value;
    targetPageInput.value = val;
    const pageNum = val === "last" ? currentPageCount : parseInt(val, 10);
    pageImg.src = `/batch/${batchId}/preview-image?page=${pageNum}&file_id=${fileId}&t=${Date.now()}`;
    if (highlightBox) highlightBox.style.display = "none";
    if (detectStatusMsg) detectStatusMsg.style.display = "none";
  }

  function updatePageSelectOptions(count) {
    if (!pageSelect) return;
    const currentVal = pageSelect.value;
    pageSelect.innerHTML = "";
    const lastOpt = document.createElement("option");
    lastOpt.value = "last";
    lastOpt.textContent = `Last page (Page ${count})`;
    pageSelect.appendChild(lastOpt);

    for (let p = 1; p <= count; p++) {
      const opt = document.createElement("option");
      opt.value = p.toString();
      opt.textContent = `Page ${p}`;
      if (currentVal === p.toString()) opt.selected = true;
      pageSelect.appendChild(opt);
    }
    if (currentVal === "last") lastOpt.selected = true;
  }

  function handleFileSwitch() {
    const fileId = fileSelect ? fileSelect.value : "";
    if (!fileId) return;

    fetch(`/batch/${batchId}/file-info/${fileId}`)
      .then(res => res.json())
      .then(info => {
        if (info.total_pages) {
          currentPageCount = info.total_pages;
          wrap.dataset.pageCount = currentPageCount;
          updatePageSelectOptions(currentPageCount);
        }
        if (info.has_existing_stamp) {
          if (stampOverlay) stampOverlay.style.display = "none";
          if (restoreStampBtn) restoreStampBtn.style.display = "none";
          if (existingStampAlert) existingStampAlert.style.display = "block";
        } else {
          if (existingStampAlert) existingStampAlert.style.display = "none";
          if (!stampUserClosed && stampOverlay) {
            stampOverlay.style.display = "block";
            if (restoreStampBtn) restoreStampBtn.style.display = "none";
          }
        }
        updatePreviewImage();
      })
      .catch(() => {
        updatePreviewImage();
      });
  }

  // Trigger file check on initial load
  if (fileSelect && fileSelect.value) {
    handleFileSwitch();
  }

  if (pageSelect) {
    pageSelect.addEventListener("change", updatePreviewImage);
  }

  if (fileSelect) {
    fileSelect.addEventListener("change", handleFileSwitch);
  }

  // Keyword auto-detect test
  if (testDetectBtn) {
    testDetectBtn.addEventListener("click", function () {
      const fileId = fileSelect ? fileSelect.value : "";
      const val = pageSelect.value;
      const pageNum = val === "last" ? currentPageCount : parseInt(val, 10);
      const kws = keywordsInput ? encodeURIComponent(keywordsInput.value) : "";

      detectStatusMsg.style.display = "block";
      detectStatusMsg.innerHTML = '<span class="muted" style="display:inline-flex; align-items:center; gap:6px;"><svg class="icon spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-linecap="round"/></svg> Scanning page text for keywords...</span>';

      fetch(`/batch/${batchId}/detect-keyword?page=${pageNum}&file_id=${fileId}&keywords=${kws}`)
        .then(res => res.json())
        .then(data => {
          if (data.matches && data.matches.length > 0) {
            const m = data.matches[0];
            detectStatusMsg.innerHTML = `<span style="color:#059669; display:inline-flex; align-items:center; gap:6px;"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Match found: <strong>"${m.text}"</strong> (keyword: ${m.matched_keyword})</span>`;
            if (highlightBox && highlightLabel) {
              highlightBox.style.display = "block";
              highlightBox.style.left = `${m.x0_pct}%`;
              highlightBox.style.top = `${m.y0_pct}%`;
              highlightBox.style.width = `${Math.max(m.x1_pct - m.x0_pct, 10)}%`;
              highlightBox.style.height = `${Math.max(m.y1_pct - m.y0_pct, 3)}%`;
              highlightLabel.textContent = `Matched: ${m.matched_keyword}`;
            }
          } else {
            if (highlightBox) highlightBox.style.display = "none";
            detectStatusMsg.innerHTML = '<span class="muted" style="display:inline-flex; align-items:center; gap:6px;"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg> No keyword match on this specific page. Engine will scan other pages or use fallback position.</span>';
          }
        })
        .catch(err => {
          detectStatusMsg.innerHTML = `<span class="error" style="display:inline-flex; align-items:center; gap:6px;"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> Detection error: ${err.message}</span>`;
        });
    });
  }

  function makeDraggable(overlayId, xInputId, yInputId, wInputId, sliderId, valSpanId) {
    const el = document.getElementById(overlayId);
    if (!el) return;
    const xInput = document.getElementById(xInputId);
    const yInput = document.getElementById(yInputId);
    const wInput = document.getElementById(wInputId);
    const slider = document.getElementById(sliderId);
    const valSpan = document.getElementById(valSpanId);

    function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }

    function updateHiddenFromStyle() {
      const wrapRect = wrap.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      const xPct = ((elRect.left - wrapRect.left) / wrapRect.width) * 100;
      const yPct = ((elRect.top - wrapRect.top) / wrapRect.height) * 100;
      if (xInput) xInput.value = clamp(xPct, 0, 100).toFixed(2);
      if (yInput) yInput.value = clamp(yPct, 0, 100).toFixed(2);
    }

    let dragging = false;
    let offsetX = 0;
    let offsetY = 0;

    el.addEventListener("mousedown", (e) => {
      dragging = true;
      const elRect = el.getBoundingClientRect();
      offsetX = e.clientX - elRect.left;
      offsetY = e.clientY - elRect.top;
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const wrapRect = wrap.getBoundingClientRect();
      let left = e.clientX - wrapRect.left - offsetX;
      let top = e.clientY - wrapRect.top - offsetY;
      left = clamp(left, 0, wrapRect.width - el.offsetWidth);
      top = clamp(top, 0, wrapRect.height - el.offsetHeight);
      el.style.left = `${(left / wrapRect.width) * 100}%`;
      el.style.top = `${(top / wrapRect.height) * 100}%`;
      updateHiddenFromStyle();
    });

    document.addEventListener("mouseup", () => {
      dragging = false;
    });

    if (slider) {
      slider.addEventListener("input", () => {
        el.style.width = `${slider.value}%`;
        if (wInput) wInput.value = slider.value;
        if (valSpan) valSpan.textContent = `${slider.value}%`;
        updateHiddenFromStyle();
      });
    }

    updateHiddenFromStyle();
    if (wInput) wInput.value = parseFloat(el.style.width) || 20;
  }

  makeDraggable("sigOverlay", "sigXInput", "sigYInput", "sigWInput", "sigWidthSlider", "sigWidthVal");
  makeDraggable("stampOverlay", "stampXInput", "stampYInput", "stampWInput", "stampWidthSlider", "stampWidthVal");
})();
