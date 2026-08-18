(() => {
  "use strict";

  const body = document.body;
  const totalPages = Number(body.dataset.pageCount);
  const pageUrlTemplate = body.dataset.pageUrlTemplate;
  const pageImage = document.getElementById("pdf-page");
  const pdfCanvas = document.getElementById("pdf-canvas");
  const loading = document.getElementById("page-loading");
  const currentPageLabel = document.getElementById("current-page");
  const defaultPageInput = document.getElementById("default-page");
  const previousPageButton = document.getElementById("previous-page");
  const nextPageButton = document.getElementById("next-page");
  const zoomOutButton = document.getElementById("zoom-out");
  const zoomInButton = document.getElementById("zoom-in");
  const zoomLabel = document.getElementById("zoom-label");
  const form = document.getElementById("grading-form");
  const previousExam = document.getElementById("previous-exam");
  const workspace = document.querySelector(".workspace");
  const panelResizer = document.getElementById("panel-resizer");

  const zoomLevels = [0.8, 1, 1.25, 1.5, 2, 2.5, 3];
  let zoomIndex = 2;
  let currentPage = 1;
  let formSubmitting = false;
  let pendingZoomAnchor = null;
  let lastPinchStep = 0;

  const clampPage = (value) => Math.min(totalPages, Math.max(1, value));

  function pageUrl(page, scale) {
    return pageUrlTemplate.replace("999999", String(page)) + `?scale=${scale}`;
  }

  function captureViewportAnchor(clientX, clientY) {
    const bounds = pdfCanvas.getBoundingClientRect();
    const localX = clientX == null ? bounds.width / 2 : clientX - bounds.left;
    const localY = clientY == null ? bounds.height / 2 : clientY - bounds.top;
    return {
      localX,
      localY,
      ratioX: (pdfCanvas.scrollLeft + localX) / Math.max(pdfCanvas.scrollWidth, 1),
      ratioY: (pdfCanvas.scrollTop + localY) / Math.max(pdfCanvas.scrollHeight, 1),
    };
  }

  function renderPage(page) {
    const targetPage = clampPage(page);
    const pageChanged = targetPage !== currentPage;
    currentPage = targetPage;
    if (pageChanged) {
      pdfCanvas.scrollLeft = 0;
      pdfCanvas.scrollTop = 0;
      pendingZoomAnchor = null;
    }
    const zoom = zoomLevels[zoomIndex];
    loading.classList.remove("hidden");
    pageImage.src = pageUrl(currentPage, zoom);
    pageImage.alt = `Page ${currentPage} of exam ${body.dataset.studentId}`;
    currentPageLabel.textContent = String(currentPage);
    zoomLabel.textContent = `${Math.round((zoom / 1.25) * 100)}%`;
    previousPageButton.disabled = currentPage <= 1;
    nextPageButton.disabled = currentPage >= totalPages;
    zoomOutButton.disabled = zoomIndex === 0;
    zoomInButton.disabled = zoomIndex === zoomLevels.length - 1;
  }

  pageImage.addEventListener("load", () => {
    loading.classList.add("hidden");
    if (pendingZoomAnchor) {
      const anchor = pendingZoomAnchor;
      pendingZoomAnchor = null;
      requestAnimationFrame(() => {
        pdfCanvas.scrollLeft = anchor.ratioX * pdfCanvas.scrollWidth - anchor.localX;
        pdfCanvas.scrollTop = anchor.ratioY * pdfCanvas.scrollHeight - anchor.localY;
      });
    }
  });
  pageImage.addEventListener("error", () => {
    loading.textContent = "Could not render this page";
  });
  previousPageButton.addEventListener("click", () => renderPage(currentPage - 1));
  nextPageButton.addEventListener("click", () => renderPage(currentPage + 1));

  function changeZoom(direction, clientX = null, clientY = null) {
    const nextIndex = Math.min(zoomLevels.length - 1, Math.max(0, zoomIndex + direction));
    if (nextIndex === zoomIndex) return;
    pendingZoomAnchor = captureViewportAnchor(clientX, clientY);
    zoomIndex = nextIndex;
    renderPage(currentPage);
  }

  zoomOutButton.addEventListener("click", () => changeZoom(-1));
  zoomInButton.addEventListener("click", () => changeZoom(1));

  pdfCanvas.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const now = performance.now();
    if (now - lastPinchStep < 90) return;
    lastPinchStep = now;
    changeZoom(event.deltaY < 0 ? 1 : -1, event.clientX, event.clientY);
  }, { passive: false });

  let panStart = null;
  pageImage.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    panStart = {
      x: event.clientX,
      y: event.clientY,
      scrollLeft: pdfCanvas.scrollLeft,
      scrollTop: pdfCanvas.scrollTop,
    };
    pageImage.setPointerCapture(event.pointerId);
    pdfCanvas.classList.add("dragging");
  });
  pageImage.addEventListener("pointermove", (event) => {
    if (!panStart) return;
    pdfCanvas.scrollLeft = panStart.scrollLeft - (event.clientX - panStart.x);
    pdfCanvas.scrollTop = panStart.scrollTop - (event.clientY - panStart.y);
  });
  const stopPanning = (event) => {
    if (!panStart) return;
    panStart = null;
    pdfCanvas.classList.remove("dragging");
    if (pageImage.hasPointerCapture(event.pointerId)) pageImage.releasePointerCapture(event.pointerId);
  };
  pageImage.addEventListener("pointerup", stopPanning);
  pageImage.addEventListener("pointercancel", stopPanning);

  const DEFAULT_GRADING_WIDTH = 430;
  const MIN_GRADING_WIDTH = 320;
  const MIN_PDF_WIDTH = 480;
  const MAX_GRADING_WIDTH = 720;

  function clampGradingWidth(width) {
    const available = Math.max(MIN_GRADING_WIDTH, window.innerWidth - MIN_PDF_WIDTH);
    return Math.round(Math.min(MAX_GRADING_WIDTH, available, Math.max(MIN_GRADING_WIDTH, width)));
  }

  function setGradingWidth(width, persist = false) {
    if (window.innerWidth <= 900) return;
    const clamped = clampGradingWidth(width);
    workspace.style.setProperty("--grading-width", `${clamped}px`);
    panelResizer.setAttribute("aria-valuenow", String(clamped));
    if (persist) localStorage.setItem("exam-grader-panel-width", String(clamped));
  }

  const savedPanelWidth = Number(localStorage.getItem("exam-grader-panel-width"));
  setGradingWidth(Number.isFinite(savedPanelWidth) && savedPanelWidth > 0 ? savedPanelWidth : DEFAULT_GRADING_WIDTH);

  panelResizer.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || window.innerWidth <= 900) return;
    event.preventDefault();
    panelResizer.setPointerCapture(event.pointerId);
    panelResizer.classList.add("active");
    document.body.classList.add("resizing-panels");
  });
  panelResizer.addEventListener("pointermove", (event) => {
    if (!panelResizer.hasPointerCapture(event.pointerId)) return;
    setGradingWidth(window.innerWidth - event.clientX);
  });
  const stopResizing = (event) => {
    if (!panelResizer.hasPointerCapture(event.pointerId)) return;
    panelResizer.releasePointerCapture(event.pointerId);
    panelResizer.classList.remove("active");
    document.body.classList.remove("resizing-panels");
    localStorage.setItem("exam-grader-panel-width", panelResizer.getAttribute("aria-valuenow"));
  };
  panelResizer.addEventListener("pointerup", stopResizing);
  panelResizer.addEventListener("pointercancel", stopResizing);
  panelResizer.addEventListener("dblclick", () => setGradingWidth(DEFAULT_GRADING_WIDTH, true));
  panelResizer.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const currentWidth = Number(panelResizer.getAttribute("aria-valuenow"));
    setGradingWidth(currentWidth + (event.key === "ArrowLeft" ? 20 : -20), true);
  });
  window.addEventListener("resize", () => {
    const currentWidth = Number(panelResizer.getAttribute("aria-valuenow"));
    setGradingWidth(currentWidth || DEFAULT_GRADING_WIDTH);
  });

  const savedDefault = Number(localStorage.getItem("exam-grader-default-page"));
  const initialDefault = Number.isInteger(savedDefault) && savedDefault > 0 ? savedDefault : 1;
  defaultPageInput.value = String(initialDefault);
  defaultPageInput.addEventListener("change", () => {
    const value = Math.max(1, Number(defaultPageInput.value) || 1);
    defaultPageInput.value = String(Math.floor(value));
    localStorage.setItem("exam-grader-default-page", defaultPageInput.value);
  });
  renderPage(initialDefault);

  document.querySelectorAll("[data-preset-select]").forEach((select) => {
    select.addEventListener("change", () => {
      const option = select.options[select.selectedIndex];
      if (!option || !option.dataset.score) return;
      const card = select.closest("[data-question]");
      card.querySelector('input[type="number"]').value = option.dataset.score;
      card.querySelector("textarea").value = option.dataset.comment;
      form.classList.remove("was-validated");
    });
  });

  function serializedGrades() {
    return JSON.stringify(Array.from(new FormData(form).entries()));
  }

  const initialGrades = serializedGrades();
  const hasUnsavedChanges = () => serializedGrades() !== initialGrades;

  form.addEventListener("submit", (event) => {
    form.classList.add("was-validated");
    if (!form.checkValidity()) {
      event.preventDefault();
      const invalid = form.querySelector(":invalid");
      if (invalid) invalid.focus();
      return;
    }
    formSubmitting = true;
    document.getElementById("next-exam").disabled = true;
  });

  previousExam.addEventListener("click", (event) => {
    if (hasUnsavedChanges() && !window.confirm("Discard unsaved changes and open the previous exam?")) {
      event.preventDefault();
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (!formSubmitting && hasUnsavedChanges()) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      form.requestSubmit();
    }
  });
})();
