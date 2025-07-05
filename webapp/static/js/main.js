// static/js/main.js

document.addEventListener("DOMContentLoaded", () => {
  const table = document.getElementById("worklist-table");
  const input = document.getElementById("worklist-search");

  if (table) {
    const rows = Array.from(table.tBodies[0].rows);

    // 1) Highlight truly empty cells
    rows.forEach(row => {
      row.querySelectorAll("td").forEach(td => {
        if (!td.innerText.trim()) td.classList.add("missing");
      });
    });

    // 2) Simple client-side search/filter
    if (input) {
      input.addEventListener("input", () => {
        const q = input.value.toLowerCase();
        rows.forEach(row => {
          row.style.display = row.innerText.toLowerCase().includes(q)
            ? ""
            : "none";
        });
      });
    }
  }
});
