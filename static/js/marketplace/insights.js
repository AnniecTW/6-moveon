const CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js";
const ANNOTATION_URL = "https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js";
const chartColors = ["#667f70", "#bea875", "#8e9991", "#a77e68", "#b9b3a6"];
let libraryPromise;
let activeCharts = [];

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing?.dataset.loaded === "true") return resolve();
    const script = existing || document.createElement("script");
    script.src = src;
    script.dataset.chartDependency = "true";
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      resolve();
    }, { once: true });
    script.addEventListener("error", reject, { once: true });
    if (!existing) document.head.append(script);
  });
}

function loadChartLibraries() {
  if (window.Chart) return Promise.resolve(window.Chart);
  if (!libraryPromise) {
    libraryPromise = loadScript(CHART_JS_URL)
      .then(() => loadScript(ANNOTATION_URL))
      .then(() => window.Chart);
  }
  return libraryPromise;
}

function destroyCharts() {
  activeCharts.forEach((chart) => chart.destroy());
  activeCharts = [];
}

function commonOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 350 },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: "#35332f",
        titleFont: { size: 10 },
        bodyFont: { size: 10 },
        padding: 9,
        cornerRadius: 6,
      },
    },
  };
}

function priceAnnotations(events) {
  return Object.fromEntries(events.map((event, index) => [
    `price-${event.listing_id}-${index}`,
    {
      type: "line",
      xMin: event.date,
      xMax: event.date,
      borderColor: index % 2 ? "#a77e68" : "#bea875",
      borderWidth: 1,
      borderDash: [4, 4],
      label: {
        display: true,
        position: index % 2 ? "start" : "end",
        backgroundColor: "#fffefa",
        borderColor: "#ddd7cb",
        borderWidth: 1,
        borderRadius: 4,
        color: "#514d46",
        content: [`${event.listing_title}`, `$${event.old_price} → $${event.new_price}`],
        font: { size: 8, weight: "500" },
        padding: 4,
      },
    },
  ]));
}

function renderViewsChart(data) {
  const canvas = document.querySelector("#seller-views-chart");
  if (!canvas) return;
  const options = commonOptions();
  options.scales = {
    x: { grid: { display: false }, ticks: { color: "#78736a", font: { size: 9 } }, border: { display: false } },
    y: { beginAtZero: true, grid: { color: "#ece8df" }, ticks: { color: "#78736a", font: { size: 9 }, precision: 0 }, border: { display: false } },
  };
  options.plugins.annotation = { clip: true, annotations: priceAnnotations(data.price_events || []) };
  activeCharts.push(new window.Chart(canvas, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [{ data: data.views, borderColor: "#667f70", backgroundColor: "rgba(102,127,112,.12)", fill: true, borderWidth: 2, pointRadius: 3, pointBackgroundColor: "#fffefa", pointBorderColor: "#667f70", tension: .35 }],
    },
    options,
  }));
}

function renderInquiryChart(data) {
  const canvas = document.querySelector("#seller-inquiries-chart");
  if (!canvas) return;
  const options = commonOptions();
  options.indexAxis = "y";
  options.scales = {
    x: { beginAtZero: true, suggestedMax: Math.max(1, ...data.values), grid: { color: "#ece8df" }, ticks: { color: "#78736a", font: { size: 9 }, precision: 0 }, border: { display: false } },
    y: { grid: { display: false }, ticks: { color: "#514d46", font: { size: 9 } }, border: { display: false } },
  };
  activeCharts.push(new window.Chart(canvas, {
    type: "bar",
    data: { labels: data.labels, datasets: [{ data: data.values, backgroundColor: "#a9c4b5", borderRadius: 6, barThickness: 12 }] },
    options,
  }));
}

function renderCategoryChart(data) {
  const canvas = document.querySelector("#seller-category-chart");
  const legend = document.querySelector("#seller-category-legend");
  if (!canvas || !legend) return;
  const total = data.values.reduce((sum, value) => sum + value, 0);
  legend.replaceChildren();
  data.labels.forEach((label, index) => {
    const percent = total ? Math.round(data.values[index] / total * 100) : 0;
    const row = document.createElement("div");
    row.className = "category-legend-row";
    const swatch = document.createElement("i");
    swatch.style.background = chartColors[index % chartColors.length];
    const name = document.createElement("span");
    name.textContent = label;
    const value = document.createElement("strong");
    value.textContent = `${percent}%`;
    row.append(swatch, name, value);
    legend.append(row);
  });
  const options = commonOptions();
  options.cutout = "68%";
  activeCharts.push(new window.Chart(canvas, {
    type: "doughnut",
    data: { labels: data.labels, datasets: [{ data: data.values, backgroundColor: chartColors, borderColor: "#fffefa", borderWidth: 3 }] },
    options,
  }));
}

export async function setupSellerInsights() {
  const dataElement = document.querySelector("#seller-insights-data");
  if (!dataElement) return;
  destroyCharts();
  try {
    await loadChartLibraries();
    const data = JSON.parse(dataElement.textContent);
    renderViewsChart(data.views_over_time);
    renderInquiryChart(data.inquiries_by_listing);
    renderCategoryChart(data.category_performance);
  } catch (error) {
    document.querySelectorAll(".chart-frame").forEach((frame) => {
      frame.innerHTML = '<p class="chart-error">Charts could not be loaded. The summary metrics remain available.</p>';
    });
  }
}

document.addEventListener("dashboard:before-swap", destroyCharts);
document.addEventListener("dashboard:content-loaded", setupSellerInsights);
