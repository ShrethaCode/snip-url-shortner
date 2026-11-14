/**
 * Snip URL Shortener — Client-side interaction script
 */

// Copy text to clipboard with animated button feedback
function copyToClipboard(text, btnElement) {
  if (!navigator.clipboard) {
    // Fallback for older browsers
    const textarea = document.createElement("textarea");
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      showCopyFeedback(btnElement);
    } catch (err) {
      console.error("Fallback copy failed:", err);
    }
    document.body.removeChild(textarea);
    return;
  }

  navigator.clipboard.writeText(text).then(function() {
    showCopyFeedback(btnElement);
  }).catch(function(err) {
    console.error("Clipboard copy failed:", err);
  });
}

function showCopyFeedback(btn) {
  if (!btn) return;
  const originalText = btn.innerHTML;
  btn.innerHTML = "&#10003; Copied!";
  btn.classList.add("btn-copied");

  setTimeout(function() {
    btn.innerHTML = originalText;
    btn.classList.remove("btn-copied");
  }, 1800);
}

// Live client-side filter for the links table
function filterLinks() {
  const input = document.getElementById("linkSearchInput");
  if (!input) return;

  const query = input.value.toLowerCase().trim();
  const rows = document.querySelectorAll("#linksTable tbody tr.link-row");
  const noResults = document.getElementById("noSearchResults");

  let visibleCount = 0;

  rows.forEach(function(row) {
    const searchData = (row.getAttribute("data-search") || "").toLowerCase();
    if (searchData.indexOf(query) !== -1) {
      row.style.display = "";
      visibleCount++;
    } else {
      row.style.display = "none";
    }
  });

  if (noResults) {
    noResults.style.display = visibleCount === 0 ? "block" : "none";
  }
}
