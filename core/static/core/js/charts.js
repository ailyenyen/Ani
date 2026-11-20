/* Ani charts (Chart.js). Simple, labelled, readable, and drawn in the current light/dark theme. */
(function () {
  "use strict";
  if (typeof Chart === "undefined") return; // the numbers are already on the page

  var reduceMotion = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Colours come from the CSS theme tokens so charts follow light and dark mode.
  function theme() {
    var css = getComputedStyle(document.documentElement);
    var v = function (name) { return css.getPropertyValue(name).trim(); };
    return {
      line: v("--chart-line"),
      grid: v("--chart-grid"),
      tick: v("--chart-tick"),
      text: v("--chart-text"),
      deep: v("--deep"),
      tooltipBg: v("--tooltip-bg"),
      tooltipFg: v("--tooltip-fg"),
      surface: v("--surface")
    };
  }

  Chart.defaults.font.family = '"Poppins", system-ui, sans-serif';
  Chart.defaults.font.size = 12;

  function animation(extra) {
    if (reduceMotion) return false;
    return Object.assign({ duration: 700, easing: "easeOutQuart" }, extra || {});
  }

  function peso(value) {
    return "₱" + Number(value).toFixed(2);
  }

  function readData(canvas) {
    var el = document.getElementById(canvas.getAttribute("data-source"));
    return el ? JSON.parse(el.textContent) : null;
  }

  function tooltip(t, label) {
    return {
      backgroundColor: t.tooltipBg,
      titleColor: t.tooltipFg,
      bodyColor: t.tooltipFg,
      padding: 10,
      displayColors: false,
      callbacks: label
    };
  }

  function lineChart(canvas, data, t) {
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
          borderColor: t.line,
          backgroundColor: t.line,
          pointBackgroundColor: t.line,
          pointBorderColor: t.surface,
          pointBorderWidth: 1.5,
          borderWidth: 2.25,
          pointRadius: data.values.length > 31 ? 0 : 3.5,
          pointHoverRadius: 6,
          tension: 0.3,
          fill: false
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: animation(),
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: tooltip(t, { label: function (ctx) { return peso(ctx.parsed.y) + " per kg"; } })
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: t.tick, maxTicksLimit: 7, maxRotation: 0 } },
          y: {
            suggestedMin: Math.max(0, min - pad),
            suggestedMax: max + pad,
            grid: { color: t.grid },
            border: { display: false },
            ticks: { color: t.tick, maxTicksLimit: 5, callback: function (v) { return "₱" + v; } }
          }
        }
      }
    });
  }

  // Writes each column's price above it, and marks the highest one.
  var columnLabels = {
    id: "aniColumnLabels",
    afterDatasetsDraw: function (chart, _args, options) {
      var t = options.theme;
      var ctx = chart.ctx;
      var meta = chart.getDatasetMeta(0);
      var best = chart.data.bestIndex;
      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      meta.data.forEach(function (bar, i) {
        ctx.font = "600 14px Poppins, system-ui, sans-serif";
        ctx.fillStyle = t.text;
        ctx.fillText(peso(chart.data.datasets[0].data[i]).replace("₱", ""), bar.x, bar.y - 6);
        if (i === best) {
          ctx.font = "600 12px Poppins, system-ui, sans-serif";
          ctx.fillStyle = t.deep;
          ctx.fillText("★ Highest", bar.x, bar.y - 26);
        }
      });
      ctx.restore();
    }
  };

  function columnChart(canvas, data, t) {
    var max = Math.max.apply(null, data.values);
    var chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: data.labels.map(splitLabel),
        bestIndex: data.bestIndex,
        datasets: [{
          label: "Price per kg",
          data: data.values,
          backgroundColor: data.colors || data.values.map(function () { return t.line; }),
          borderColor: (data.colors || []).map(function (c) { return c === "#D3EBD3" ? "#9CC9A3" : c; }),
          borderWidth: 1,
          borderRadius: { topLeft: 8, topRight: 8 },
          borderSkipped: "bottom",
          maxBarThickness: 64
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: animation({ delay: function (ctx) { return ctx.type === "data" ? ctx.dataIndex * 90 : 0; } }),
        layout: { padding: { top: 34 } },
        plugins: {
          aniColumnLabels: { theme: t },
          legend: { display: false },
          tooltip: tooltip(t, {
            title: function (items) { return [].concat(items[0].label).join(" "); },
            label: function (ctx) { return peso(ctx.parsed.y) + " per kg"; }
          })
        },
        scales: {
          y: { display: false, beginAtZero: true, suggestedMax: max * 1.05 },
          x: {
            grid: { display: false },
            border: { color: t.grid },
            ticks: { color: t.tick, font: { size: 12, weight: "500" }, maxRotation: 0, autoSkip: false }
          }
        }
      },
      plugins: [columnLabels]
    });
    return chart;
  }

  // "DA Bantay Presyo" -> ["DA Bantay", "Presyo"] so labels fit under narrow columns.
  function splitLabel(label) {
    var words = String(label).split(" ");
    if (words.length < 2 || label.length < 10) return label;
    var half = Math.ceil(words.length / 2);
    return [words.slice(0, half).join(" "), words.slice(half).join(" ")];
  }

  function marketTrend(canvas, data, t) {
    var dayMilliseconds = 86400000;
    var days = data.labels.map(function (label) { return Date.parse(label) / dayMilliseconds; });
    function formatDay(day) {
      return new Date(day * dayMilliseconds).toISOString().slice(0, 10);
    }
    return new Chart(canvas, {
      type: "line",
      data: {
        datasets: data.series.map(function (series, index) {
          var color = "hsl(" + (index * 137.5 % 360) + ", 65%, 48%)";
          return {
            label: series.label,
            data: series.values.flatMap(function (price, i) {
              return price === null ? [] : [{ x: days[i], y: price }];
            }),
            borderColor: color,
            backgroundColor: color,
            pointRadius: 3,
            pointHitRadius: 8
          };
        })
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: animation(),
        interaction: { mode: "nearest", intersect: true },
        plugins: {
          legend: { position: "bottom", labels: { color: t.text, usePointStyle: true } },
          tooltip: tooltip(t, {
            title: function (items) { return formatDay(items[0].parsed.x); },
            label: function (ctx) { return ctx.dataset.label + ": " + peso(ctx.parsed.y) + "/" + data.unit; }
          })
        },
        scales: {
          x: { type: "linear", grid: { display: false }, ticks: {
            color: t.tick, maxTicksLimit: 5, maxRotation: 0, precision: 0, callback: formatDay
          } },
          y: { grid: { color: t.grid }, ticks: { color: t.tick } }
        }
      }
    });
  }

  function regionalChart(canvas, group, t) {
    canvas.parentElement.style.height = Math.max(180, 45 + group.markets.length * 32) + "px";
    return new Chart(canvas, {
      type: "bar",
      data: {
        labels: group.markets.map(function (market) { return market.name; }),
        datasets: [{
          label: "Lower reported price",
          data: group.markets.map(function (market) { return market.low; }),
          backgroundColor: group.markets.map(function (market) {
            return market.low === group.markets[0].low ? t.line : "#619470";
          }),
          maxBarThickness: 20
        }]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: animation(),
        plugins: {
          legend: { display: false },
          tooltip: tooltip(t, {
            title: function (items) { return group.markets[items[0].dataIndex].name; },
            label: function (ctx) {
              var market = group.markets[ctx.dataIndex];
              var price = peso(market.low);
              if (market.high !== market.low) price += "–" + peso(market.high);
              return [price + "/" + group.unit, market.region, market.source];
            }
          })
        },
        scales: {
          x: { beginAtZero: true, grid: { color: t.grid }, ticks: { color: t.tick, callback: function (value) { return "₱" + value; } } },
          y: { grid: { display: false }, ticks: { color: t.tick, autoSkip: false, callback: function (value) {
            var label = this.getLabelForValue(value);
            return label.length > 19 ? label.slice(0, 17) + "…" : label;
          } } }
        }
      }
    });
  }

  var charts = [];

  function drawAll() {
    charts.forEach(function (c) { c.destroy(); });
    charts = [];
    var t = theme();
    document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
      var data = readData(canvas);
      if (!data) return;
      var type = canvas.getAttribute("data-chart");
      var chart;
      if (type === "market-trend") {
        chart = marketTrend(canvas, data, t);
      } else if (type === "regional") {
        var selector = document.getElementById(canvas.getAttribute("data-selector"));
        var group = data[selector ? Number(selector.value) : 0];
        if (!group) return;
        chart = regionalChart(canvas, group, t);
      } else {
        if (!data.values || !data.values.length) return;
        chart = type === "columns" ? columnChart(canvas, data, t) : lineChart(canvas, data, t);
      }
      charts.push(chart);
    });
  }

  drawAll();
  document.querySelectorAll("canvas[data-selector]").forEach(function (canvas) {
    document.getElementById(canvas.getAttribute("data-selector")).addEventListener("change", drawAll);
  });
  // Redraw in the new colours when light/dark mode changes.
  document.addEventListener("ani:themechange", function () {
    var saved = reduceMotion;
    reduceMotion = true; // no replayed entrance animation on a theme switch
    drawAll();
    reduceMotion = saved;
  });
})();
