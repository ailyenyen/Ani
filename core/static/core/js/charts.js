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
      surface: v("--surface"),
      kinds: { retail: v("--c-retail"), wholesale: v("--c-wholesale"), farmgate: v("--c-farmgate") },
      hatch: v("--chart-hatch"),
      muted: v("--chart-tick")
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
          borderColor: (data.colors || []).map(function (c) { return c === "#B9BB9C" ? "#9B9D7D" : c; }),
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

  // Home banner: one line per price type (retail, wholesale, farmgate) over the months.
  function multiChart(canvas, data, t) {
    var all = [];
    data.datasets.forEach(function (d) { d.values.forEach(function (v) { if (v !== null) all.push(v); }); });
    var min = Math.min.apply(null, all), max = Math.max.apply(null, all);
    var pad = Math.max((max - min) * 0.12, 1);
    return new Chart(canvas, {
      type: "line",
      data: {
        labels: data.labels,
        datasets: data.datasets.map(function (d) {
          var colour = t.kinds[d.kind] || t.line;
          return {
            label: d.label, data: d.values, borderColor: colour, backgroundColor: colour,
            pointBackgroundColor: colour, pointBorderColor: t.surface, pointBorderWidth: 1.5,
            borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 6, tension: 0.3, spanGaps: true, fill: false
          };
        })
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: animation(),
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: tooltip(t, {
            label: function (ctx) { return ctx.dataset.label + ": " + (ctx.parsed.y === null ? "no report" : peso(ctx.parsed.y) + "/kg"); }
          })
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: t.tick, maxTicksLimit: 9, maxRotation: 0 } },
          y: {
            suggestedMin: Math.max(0, min - pad), suggestedMax: max + pad,
            grid: { color: t.grid }, border: { display: false },
            ticks: { color: t.tick, maxTicksLimit: 6, callback: function (v) { return "₱" + v; } }
          }
        }
      }
    });
  }

  // Home trend: PSA monthly lines (solid / dashed / dotted), a hatched "not published yet" zone,
  // and hollow markers with the newest report for each price type.
  var DASHES = { retail: [], wholesale: [7, 5], farmgate: [2, 4] };

  function hatchPattern(ctx, colour) {
    var tile = document.createElement("canvas");
    tile.width = tile.height = 8;
    var g = tile.getContext("2d");
    g.strokeStyle = colour;
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(0, 8); g.lineTo(8, 0);
    g.stroke();
    return ctx.createPattern(tile, "repeat");
  }

  var trendExtras = {
    id: "aniTrendExtras",
    beforeDatasetsDraw: function (chart, _args, options) {
      var data = options.data, t = options.theme;
      if (data.publishedUntil === undefined || data.publishedUntil >= data.labels.length - 1) return;
      var x = chart.scales.x, area = chart.chartArea, ctx = chart.ctx;
      var start = x.getPixelForValue(data.publishedUntil);
      ctx.save();
      ctx.fillStyle = hatchPattern(ctx, t.hatch);
      ctx.fillRect(start, area.top, area.right - start, area.bottom - area.top);
      ctx.fillStyle = t.muted;
      ctx.font = "500 12px Poppins, system-ui, sans-serif";
      // Centre the label in the zone when it fits; otherwise anchor it to the right edge so it is never cut off.
      var width = ctx.measureText(data.pendingLabel).width;
      if (area.right - start > width + 16) {
        ctx.textAlign = "center";
        ctx.fillText(data.pendingLabel, (start + area.right) / 2, area.top + 14);
      } else {
        ctx.textAlign = "right";
        ctx.fillText(data.pendingLabel, area.right - 4, area.top + 14);
      }
      ctx.restore();
    },
    afterDatasetsDraw: function (chart, _args, options) {
      var data = options.data, t = options.theme, ctx = chart.ctx;
      ctx.save();
      ctx.font = "600 11.5px Poppins, system-ui, sans-serif";
      ctx.textAlign = "left";
      var area = chart.chartArea, placed = [];
      var overlaps = function (box) {
        return placed.some(function (o) { return box.x < o.x + o.w && o.x < box.x + box.w && box.y < o.y + o.h && o.y < box.y + box.h; });
      };
      // Each label goes beside its point: to the right when there is room (the last point gets
      // a two-line label in the right padding), otherwise above or below, never over another label.
      // The newest point (at the right edge) is placed first so it keeps its spot beside the line end.
      (data.markers || []).slice().sort(function (a, b) { return b.index - a.index; }).forEach(function (marker) {
        var px = chart.scales.x.getPixelForValue(marker.index), py = chart.scales.y.getPixelForValue(marker.value);
        var cut = marker.text.indexOf(" "), price = marker.text.slice(0, cut), when = marker.text.slice(cut + 1);
        var wide = ctx.measureText(marker.text).width, tall = 14;
        var stacked = Math.max(ctx.measureText(price).width, ctx.measureText(when).width);
        var options = [];
        if (marker.index === data.labels.length - 1 && px + 8 + stacked <= chart.width) options.push({ x: px + 8, y: py - 14, w: stacked, h: 28, lines: [price, when] });
        options.push({ x: px - wide / 2, y: py + 10, w: wide, h: tall, lines: [marker.text] });
        options.push({ x: px - wide / 2, y: py - 10 - tall, w: wide, h: tall, lines: [marker.text] });
        options.push({ x: px - 10 - wide, y: py - tall / 2, w: wide, h: tall, lines: [marker.text] });
        options.forEach(function (o) { o.x = Math.max(area.left, Math.min(o.x, chart.width - 2 - o.w)); });
        var box = options.filter(function (o) { return !overlaps(o); })[0] || options[1];
        placed.push(box);
        box.lines.forEach(function (line, i) {
          ctx.fillStyle = i === 0 ? t.text : t.muted;
          ctx.font = i === 0 ? "600 11.5px Poppins, system-ui, sans-serif" : "500 11px Poppins, system-ui, sans-serif";
          ctx.fillText(line, box.x, box.y + 11 + i * 14);
        });
      });
      ctx.restore();
    }
  };

  function trendOverview(canvas, data, t) {
    var all = [];
    data.datasets.forEach(function (d) { d.values.forEach(function (v) { if (v !== null) all.push(v); }); });
    (data.markers || []).forEach(function (m) { all.push(m.value); });
    var min = Math.min.apply(null, all), max = Math.max.apply(null, all);
    var pad = Math.max((max - min) * 0.15, 2);
    var datasets = data.datasets.map(function (d) {
      var colour = t.kinds[d.kind] || t.line;
      return {
        label: d.label, data: d.values, borderColor: colour, backgroundColor: colour, borderDash: DASHES[d.kind] || [],
        borderWidth: 2.5, pointRadius: 0, pointHoverRadius: 5, pointBackgroundColor: colour, tension: 0.3, spanGaps: true, fill: false
      };
    });
    (data.markers || []).forEach(function (m) {
      var values = data.labels.map(function (_l, i) { return i === m.index ? m.value : null; });
      datasets.push({
        label: m.label + " (newest report)", data: values, showLine: false, borderColor: t.kinds[m.kind] || t.line,
        backgroundColor: t.surface, pointRadius: 6, pointHoverRadius: 7, pointBorderWidth: 2.5, pointStyle: "circle"
      });
    });
    return new Chart(canvas, {
      type: "line",
      data: { labels: data.labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: animation(),
        layout: { padding: { right: 64, top: 6 } },
        interaction: { mode: "nearest", axis: "x", intersect: false },
        plugins: {
          legend: { display: false },
          aniTrendExtras: { data: data, theme: t },
          tooltip: tooltip(t, {
            label: function (ctx) { return ctx.parsed.y === null ? null : ctx.dataset.label + ": " + peso(ctx.parsed.y) + "/kg"; }
          })
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: t.tick, maxTicksLimit: 8, maxRotation: 0,
            callback: function (value) { var label = this.getLabelForValue(value); return label.indexOf("Jan") === 0 || value === 0 ? label : label.split(" ")[0]; } } },
          y: {
            suggestedMin: Math.max(0, min - pad), suggestedMax: max + pad,
            grid: { color: t.grid }, border: { display: false },
            ticks: { color: t.tick, maxTicksLimit: 6, callback: function (v) { return "₱" + v; } }
          }
        }
      },
      plugins: [trendExtras]
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
      if (type === "trend-overview") {
        if (!data.datasets || !data.datasets.length) return;
        chart = trendOverview(canvas, data, t);
      } else if (type === "multi") {
        if (!data.datasets || !data.datasets.length) return;
        chart = multiChart(canvas, data, t);
      } else if (type === "market-trend") {
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
