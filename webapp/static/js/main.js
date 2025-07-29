document.addEventListener("DOMContentLoaded", () => {
  const table        = document.getElementById("worklist-table");
  const input        = document.getElementById("worklist-search");
  const selectAll    = document.getElementById("select-all");
  const bulkField    = document.getElementById("bulk-field");
  const bulkText     = document.getElementById("bulk-value-text");
  const bulkSelect   = document.getElementById("bulk-value-select");
  const bulkSiteIn   = document.getElementById("bulk-site-input");
  const bulkSiteId   = document.getElementById("bulk-site-id");
  const bulkApply    = document.getElementById("bulk-apply");
  const bulkSend     = document.getElementById("bulk-send");

  // 1) Highlight empty cells (skip checkbox column)
  if (table) {
    Array.from(table.tBodies[0].rows).forEach(row =>
      row.querySelectorAll("td").forEach(td => {
        if (td.querySelector('input[type="checkbox"]')) return;
        if (!td.innerText.trim()) td.classList.add("missing");
      })
    );
  }

  // 2) Client‑side search/filter
  if (input && table) {
    const rows = Array.from(table.tBodies[0].rows);
    input.addEventListener("input", () => {
      const q = input.value.toLowerCase();
      rows.forEach(r => {
        r.style.display = r.innerText.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }

  // 3) Select‑all toggle
  selectAll?.addEventListener("change", e => {
    document.querySelectorAll(".row-checkbox")
      .forEach(cb => cb.checked = e.target.checked);
  });

  function getSelectedCcfids() {
    return Array.from(
      document.querySelectorAll(".row-checkbox:checked")
    ).map(cb => cb.closest("tr").dataset.ccfid);
  }

  // 4) Bulk‑field change → show the right control
  bulkField?.addEventListener("change", () => {
    const field = bulkField.value;
    // hide all
    bulkText.style.display   = "none";
    bulkSelect.style.display = "none";
    bulkSiteIn.style.display = "none";

    if (field === "collection_site") {
      // show autocomplete
      bulkSiteIn.style.display = "";
    } else if (bulkFieldOptions[field]) {
      // show picklist
      bulkSelect.innerHTML = "<option value=''>— select —</option>";
      bulkFieldOptions[field].forEach(o => {
        bulkSelect.append(new Option(o, o));
      });
      bulkSelect.style.display = "";
    } else {
      // show free‑text
      bulkText.style.display = "";
    }
  });

  // 4b) Autocomplete for Collection Site → populate hidden site ID
  bulkSiteIn?.addEventListener("input", () => {
    bulkSiteId.value = siteMap[bulkSiteIn.value] || "";
  });

  function getBulkValue() {
    if (bulkSiteIn.style.display === "") return bulkSiteIn.value;
    if (bulkSelect.style.display === "") return bulkSelect.value;
    return bulkText.value;
  }

  // 5) Bulk‑apply
  bulkApply?.addEventListener("click", async () => {
    const ccfids = getSelectedCcfids();
    const field  = bulkField.value;
    const value  = getBulkValue();

    if (!ccfids.length)         return alert("No rows selected");
    if (!field)                 return alert("Select a field");

    if (field === "collection_site") {
      // two‑step: name, then ID
      let res = await fetch("/worklist/bulk_update", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ ccfids, field, value })
      });
      if (!res.ok) return alert("Failed to update site name");

      res = await fetch("/worklist/bulk_update", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({
          ccfids,
          field: "collection_site_id",
          value: bulkSiteId.value
        })
      });
      if (!res.ok) return alert("Failed to update site ID");

      return location.reload();
    }

    // single‑field case
    const res = await fetch("/worklist/bulk_update", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ ccfids, field, value })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      return alert(err?.error || "Bulk update failed");
    }
    location.reload();
  });

  // 6) Bulk‑send
  bulkSend?.addEventListener("click", async () => {
    const ccfids = getSelectedCcfids();
    if (!ccfids.length) return alert("No rows selected");

    const res = await fetch("/worklist/bulk_send", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ ccfids })
    });
    if (!res.ok) return alert("Bulk send failed");
    location.reload();
  });
});
