/* Ani charts (Chart.js). Simple, labelled and readable. */
(function () {
  "use strict";
  if (typeof Chart === "undefined") return; // the numbers are already on the page

  var GREEN = "#2E7D32";
  var DEEP = "#185B43";
  var LIGHT = "#A5D6A7";
  var TEXT = "#20352C";
  var MUTED = "#55665D";
  var GRID = "#ECE9DE";

  Chart.defaults.font.family = '"Poppins", system-ui, sans-serif';
  Chart.defaults.font.size = 14;
  Chart.defaults.color = MUTED;
  Chart.defaults.animation = false;

  function peso(value) {
    return "₱" + Number(value).toFixed(2);
  }

  function readData(canvas) {
    var el = document.getElementById(canvas.getAttribute("data-source"));
    return el ? JSON.parse(el.textContent) : null;
  }

  function lineChart(canvas, data) {
    var min = Math.min.apply(null, data.values);
    var max = Math.max.apply(null, data.values);
    var pad = Math.max((max - min) * 0.25, max * 0.03, 0.5);
    return new Chart(canvas, {
      type: "line",
      data: {
        labels: data.labels,
        datasets: [{
          label: "Price per kg",
          data: data.values,
          borderColor: GREEN,
          backgroundColor: GREEN,
          borderWidth: 3,
          pointRadius: data.values.length > 31 ? 0 : 4,
          pointHoverRadius: 6,
          tension: 0.25,
          fill: false
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: TEXT,
            padding: 10,
            displayColors: false,
            callbacks: { label: function (ctx) { return peso(ctx.parsed.y) + " per kg"; } }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 7, maxRotation: 0 } },
          y: {
            suggestedMin: Math.max(0, min - pad),
            suggestedMax: max + pad,
            grid: { color: GRID },
            border: { display: false },
            ticks: { maxTicksLimit: 5, callback: function (v) { return "₱" + v; } }
          }
        }
      }
    });
  }

  // Writes each bar's price at the end of the bar so no hovering is needed.
  var barLabels = {
    id: "aniBarLabels",
    afterDatasetsDraw: function (chart) {
      var ctx = chart.ctx;
      var meta = chart.getDatasetMeta(0);
      ctx.save();
      ctx.font = "600 15px Poppins, system-ui, sans-serif";
      ctx.fillStyle = TEXT;
      ctx.textBaseline = "middle";
      meta.data.forEach(function (bar, i) {
        ctx.fillText(peso(chart.data.datasets[0].data[i]), bar.x + 8, bar.y);
      });
      ctx.restore();
    }
  };

  function barChart(canvas, data) {
    var max = Math.max.apply(null, data.values);
    return new Chart(canvas, {
      type: "bar",
      data: {
        labels: data.labels,
        datasets: [{
          label: "Price per kg",
          data: data.values,
          backgroundColor: data.values.map(function (_v, i) { return i === data.bestIndex ? DEEP : LIGHT; }),
          borderRadius: 6,
          barThickness: 34
        }]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { right: 84 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: TEXT,
            displayColors: false,
            callbacks: { label: function (ctx) { return peso(ctx.parsed.x) + " per kg"; } }
          }
        },
        scales: {
          x: { display: false, beginAtZero: true, suggestedMax: max * 1.02 },
          y: {
            grid: { display: false },
            border: { display: false },
            ticks: { color: TEXT, font: { size: 15, weight: "500" } }
          }
        }
      },
      plugins: [barLabels]
    });
  }

  document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
    var data = readData(canvas);
    if (!data || !data.values || !data.values.length) return;
    if (canvas.getAttribute("data-chart") === "bars") barChart(canvas, data);
    else lineChart(canvas, data);
  });
})();
