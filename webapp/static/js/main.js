document.addEventListener("DOMContentLoaded", () => {
  const table      = document.getElementById("worklist-table");
  const input      = document.getElementById("worklist-search");
  const selectAll  = document.getElementById("select-all");
  const bulkField  = document.getElementById("bulk-field");
  const bulkText   = document.getElementById("bulk-value-text");
  const bulkSelect = document.getElementById("bulk-value-select");
  const bulkSiteIn = document.getElementById("bulk-site-input");
  const bulkSiteId = document.getElementById("bulk-site-id");
  const bulkApply  = document.getElementById("bulk-apply");
  const bulkSend   = document.getElementById("bulk-send");

  // 1) Highlight visible missing (cols 1–6)
  if (table) {
    Array.from(table.tBodies[0].rows).forEach(row => {
      for (let i = 1; i <= 6; i++) {
        const td = row.cells[i];
        if (td && !td.innerText.trim()) td.classList.add("missing");
      }
    });
  }

  // 2) Search/filter
  if (input && table) {
    const rows = Array.from(table.tBodies[0].rows);
    input.addEventListener("input", () => {
      const q = input.value.toLowerCase();
      rows.forEach(r => {
        r.style.display = r.innerText.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }

  // 3) Select-all
  if (selectAll) {
    selectAll.addEventListener("change", e => {
      document.querySelectorAll(".row-checkbox")
        .forEach(cb => cb.checked = e.target.checked);
    });
  }

  // 4) Bulk-field UI
  if (bulkField) {
    bulkField.addEventListener("change", () => {
      const f = bulkField.value;
      bulkText.style.display   = "none";
      bulkSelect.style.display = "none";
      bulkSiteIn.style.display = "none";

      if (f === "collection_site") {
        bulkSiteIn.style.display = "";
      } else if (window.bulkFieldOptions[f]) {
        bulkSelect.innerHTML = "<option value=''>— select —</option>";
        window.bulkFieldOptions[f].forEach(o => bulkSelect.append(new Option(o,o)));
        bulkSelect.style.display = "";
      } else {
        bulkText.style.display = "";
      }
    });
  }

  // 4b) Bulk‐site autocomplete
  if (bulkSiteIn) {
    bulkSiteIn.addEventListener("input", () => {
      bulkSiteId.value = window.siteMap[bulkSiteIn.value] || "";
    });
  }

  function getSelectedCcfids() {
    return Array.from(
      document.querySelectorAll(".row-checkbox:checked")
    ).map(cb => cb.closest("tr").dataset.ccfid);
  }
  function getBulkValue() {
    if (bulkSiteIn && bulkSiteIn.style.display !== "none") return bulkSiteIn.value;
    if (bulkSelect && bulkSelect.style.display !== "none") return bulkSelect.value;
    return bulkText ? bulkText.value : "";
  }

  // 5) Bulk‐apply
  if (bulkApply) {
    bulkApply.addEventListener("click", async () => {
      const ccfids = getSelectedCcfids();
      const field  = bulkField.value;
      const value  = getBulkValue();
      if (!ccfids.length) return alert("No rows selected");
      if (!field)       return alert("Select a field");

      if (field === "collection_site") {
        let r = await fetch("/worklist/bulk_update", {
          method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({ ccfids, field, value })
        });
        if (!r.ok) return alert("Failed to update site name");
        r = await fetch("/worklist/bulk_update", {
          method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({
            ccfids,
            field:"collection_site_id",
            value:bulkSiteId.value
          })
        });
        if (!r.ok) return alert("Failed to update site ID");
        return location.reload();
      }

      const r = await fetch("/worklist/bulk_update", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ ccfids, field, value })
      });
      if (!r.ok) {
        const e = await r.json().catch(()=>null);
        return alert(e?.error||"Bulk update failed");
      }
      location.reload();
    });
  }

  // 6) Bulk‐send
  if (bulkSend) {
    bulkSend.addEventListener("click", async () => {
      const ccfids = getSelectedCcfids();
      if (!ccfids.length) return alert("No rows selected");
      const r = await fetch("/worklist/bulk_send", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ ccfids })
      });
      if (!r.ok) return alert("Bulk send failed");
      location.reload();
    });
  }

  // ——— Needs Attention (all fields + rules) ———
  if (table) {
    const rules = {
      location:        row => row.dataset.companyCode === "A1310",
      laboratory:      row => !/POCT|Alcohol/i.test(row.dataset.testType),
      batValue:        row => /Alcohol Breath Test/i.test(row.dataset.testType),
      regulationBody:  row => row.dataset.regulation === "DOT",
      positiveFor:     row => /^Positive/.test(row.dataset.testResult)
    };
    const labels = {
      primaryId:        "Primary ID",
      companyName:      "Company",
      companyCode:      "Company Code",
      firstName:        "First",
      lastName:         "Last",
      collectionDate:   "Collection Date",
      mroReceived:      "Result Date",
      collectionSite:   "Site",
      laboratory:       "Laboratory",
      panel:            "Panel",
      location:         "Location",
      testReason:       "Reason",
      testType:         "Test Type",
      testResult:       "Result",
      regulation:       "Regulation",
      regulationBody:   "Regulation Body",
      batValue:         "BAT Value",
      positiveFor:      "Positive For"
    };

    Array.from(table.tBodies[0].rows).forEach(row => {
      const missing = [];
      Object.entries(labels).forEach(([key,label]) => {
        const val = row.dataset[key] || "";
        // if there’s a rule and it returns false, skip this field
        if (rules[key] && !rules[key](row)) return;
        if (!val || val === "None") missing.push(label);
      });
      const cell = row.querySelector(".needs-attention");
      if (cell) cell.innerText = missing.join(", ");
    });
  }
});
