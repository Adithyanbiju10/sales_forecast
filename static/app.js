// Global state
let metadata = { stores: [], products: [] };
let activeStoreId = "";
let activeProductId = "";
let currentHistory = [];
let currentForecast = [];
let currentSimulation = [];
let activeHistoryDays = 30; // Default range

// Chart instances
let forecastChartInstance = null;
let simulatorChartInstance = null;
let importanceChartInstance = null;

// Polling interval for model training
let trainingPollInterval = null;

document.addEventListener("DOMContentLoaded", () => {
    initApp();
    setupEventListeners();
});

// App Initialization
async function initApp() {
    updateSystemTime();
    setInterval(updateSystemTime, 1000);
    
    try {
        await loadMetadata();
        if (metadata.stores.length > 0 && metadata.products.length > 0) {
            activeStoreId = metadata.stores[0].id;
            activeProductId = metadata.products[0].id;
            
            populateSelects();
            updateProductMeta();
            
            // Initial data fetch
            await refreshAllData();
            await updateModelMetricsTab();
        }
    } catch (err) {
        console.error("Initialization error:", err);
        showNotification("Failed to connect to backend service.", "error");
    }
}

function updateSystemTime() {
    const timeEl = document.getElementById("system-time");
    if (timeEl) {
        const now = new Date();
        timeEl.textContent = now.toLocaleTimeString();
    }
}

// Load metadata (stores, products, baseline metrics)
async function loadMetadata() {
    const res = await fetch("/api/metadata");
    if (!res.ok) throw new Error("Metadata endpoint failed");
    metadata = await res.json();
}

// Populate select elements in sidebar
function populateSelects() {
    const storeSelect = document.getElementById("store-select");
    const productSelect = document.getElementById("product-select");
    
    storeSelect.innerHTML = metadata.stores
        .map(s => `<option value="${s.id}">${s.name} (${s.id})</option>`)
        .join("");
        
    productSelect.innerHTML = metadata.products
        .map(p => `<option value="${p.id}">${p.name} (${p.id})</option>`)
        .join("");
        
    storeSelect.value = activeStoreId;
    productSelect.value = activeProductId;
}

// Update the product metadata text under the selector
function updateProductMeta() {
    const metaEl = document.getElementById("product-meta");
    const product = metadata.products.find(p => p.id === activeProductId);
    if (product && metaEl) {
        metaEl.innerHTML = `
            <strong>Base Price:</strong> $${product.base_price.toFixed(2)}<br>
            <strong>Avg Demand:</strong> ${product.base_demand} units/day<br>
            <strong>Elasticity:</strong> ${product.elasticity} (highly responsive)
        `;
    }
}

// Setup Event Listeners
function setupEventListeners() {
    // Tab Navigation
    document.querySelectorAll(".nav-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const tabId = btn.getAttribute("data-tab");
            
            // Switch navigation state
            document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            // Switch tabs
            document.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));
            document.getElementById(tabId).classList.add("active");
            
            // Trigger chart redraws if necessary
            if (tabId === "forecast-tab") {
                renderForecastChart();
            } else if (tabId === "simulator-tab") {
                resetSimulatorSliders();
                renderSimulatorChart();
            } else if (tabId === "model-tab") {
                updateModelMetricsTab();
            }
        });
    });

    // Select selectors
    document.getElementById("store-select").addEventListener("change", async (e) => {
        activeStoreId = e.target.value;
        await refreshAllData();
    });

    document.getElementById("product-select").addEventListener("change", async (e) => {
        activeProductId = e.target.value;
        updateProductMeta();
        await refreshAllData();
    });

    // Refresh data button
    document.getElementById("refresh-data-btn").addEventListener("click", async () => {
        await refreshAllData();
        showNotification("Data refreshed successfully", "success");
    });

    // Quick train button
    document.getElementById("quick-train-btn").addEventListener("click", triggerModelTraining);
    document.getElementById("train-model-action-btn").addEventListener("click", triggerModelTraining);

    // Simulation Sliders
    const sliders = [
        { id: "price-slider", valId: "price-slider-val", suffix: "%" },
        { id: "temp-slider", valId: "temp-slider-val", suffix: "°C" },
        { id: "precip-slider", valId: "precip-slider-val", transform: v => (v / 100).toFixed(1) }
    ];

    sliders.forEach(slider => {
        const input = document.getElementById(slider.id);
        const display = document.getElementById(slider.valId);
        
        input.addEventListener("input", (e) => {
            let val = e.target.value;
            if (slider.suffix) {
                if (slider.id === "price-slider" && val > 0) {
                    display.textContent = `+${val}${slider.suffix}`;
                } else {
                    display.textContent = `${val}${slider.suffix}`;
                }
            } else if (slider.transform) {
                display.textContent = slider.transform(val);
            }
        });
    });

    // Run Simulation button click
    document.getElementById("run-simulation-btn").addEventListener("click", runSimulation);

    // ── NEW FEATURE LISTENERS ──

    // Historical range toggle pills
    document.querySelectorAll(".range-btn").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            const days = parseInt(btn.getAttribute("data-days"));
            activeHistoryDays = days;

            // Update active pill state
            document.querySelectorAll(".range-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            // Re-fetch historical data and re-render
            await fetchHistoricalRange();
        });
    });

    // CSV Export button
    document.getElementById("export-csv-btn").addEventListener("click", exportForecastCSV);

    // Safety stock slider — recalculate inventory on change
    document.getElementById("safety-stock-slider").addEventListener("input", (e) => {
        const days = parseInt(e.target.value);
        document.getElementById("safety-stock-val").textContent = `${days}d`;
        updateInventoryRecommendation();
    });
}

// Re-fetch historical and forecasted values
async function refreshAllData() {
    try {
        // Fetch forecast + last 30 history from forecast endpoint
        const res = await fetch(`/api/forecast?store_id=${activeStoreId}&product_id=${activeProductId}`);
        if (!res.ok) throw new Error("Forecast fetch failed");
        
        const data = await res.json();
        currentForecast = data.forecast;

        // Fetch historical with current active range
        await fetchHistoricalRange(data.history_last_30);
        
        // Reset simulation overlay
        currentSimulation = [];
        
        // Render current view
        const activeTab = document.querySelector(".nav-btn.active").getAttribute("data-tab");
        if (activeTab === "forecast-tab") {
            renderForecastChart();
        } else if (activeTab === "simulator-tab") {
            renderSimulatorChart();
        }
        
        updateKPICards();
        updateInventoryRecommendation();
    } catch (err) {
        console.error("Error refreshing data:", err);
        showNotification("Error downloading latest forecast data.", "error");
    }
}

// Fetch historical data for the active day range
async function fetchHistoricalRange(fallback = null) {
    try {
        const res = await fetch(`/api/historical?store_id=${activeStoreId}&product_id=${activeProductId}&days=${activeHistoryDays}`);
        if (!res.ok) throw new Error("Historical fetch failed");
        currentHistory = await res.json();
        renderForecastChart();
    } catch (err) {
        // Fall back to provided data
        if (fallback) {
            currentHistory = fallback;
            renderForecastChart();
        }
        console.error("Historical range fetch error:", err);
    }
}

// Update KPI cards with animated counters
function updateKPICards() {
    if (currentHistory.length === 0 || currentForecast.length === 0) return;
    
    // Avg Historical Demand
    const avgHist = currentHistory.reduce((sum, row) => sum + row.sales, 0) / currentHistory.length;
    animateKPIValue("kpi-avg-hist", Math.round(avgHist));
    
    // Total Volume
    const totalVolume = currentForecast.reduce((sum, row) => sum + row.sales, 0);
    animateKPIValue("kpi-total-volume", totalVolume, v => v.toLocaleString());
    
    // Projected Peak
    let peakSales = -1;
    let peakDateStr = "";
    currentForecast.forEach(row => {
        if (row.sales > peakSales) {
            peakSales = row.sales;
            peakDateStr = row.date;
        }
    });
    
    const peakDateObj = new Date(peakDateStr);
    const formattedPeakDate = peakDateObj.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    
    animateKPIValue("kpi-peak-forecast", peakSales);
    document.getElementById("kpi-peak-date").textContent = `Peak on ${formattedPeakDate}`;
    
    // Product Elasticity
    const product = metadata.products.find(p => p.id === activeProductId);
    if (product) {
        animateKPIValue("kpi-elasticity", product.elasticity, v => v.toFixed(1));
    }
}

// ── FEATURE 6: Animated KPI counter ──
function animateKPIValue(elementId, targetValue, formatter = null) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const startValue = 0;
    const duration = 900; // ms
    const startTime = performance.now();

    el.classList.add("updating");

    function step(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease-out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(startValue + (targetValue - startValue) * eased);

        el.textContent = formatter ? formatter(current) : current;

        if (progress < 1) {
            requestAnimationFrame(step);
        } else {
            el.textContent = formatter ? formatter(targetValue) : targetValue;
            el.classList.remove("updating");
        }
    }

    requestAnimationFrame(step);
}

// Reset sliders in Simulator tab to match current forecast defaults
function resetSimulatorSliders() {
    document.getElementById("price-slider").value = 0;
    document.getElementById("price-slider-val").textContent = "0%";
    
    document.getElementById("promo-toggle").checked = false;
    
    document.getElementById("temp-slider").value = 22;
    document.getElementById("temp-slider-val").textContent = "22°C";
    
    document.getElementById("precip-slider").value = 0;
    document.getElementById("precip-slider-val").textContent = "0.0";
    
    document.getElementById("holiday-toggle").checked = false;
    
    document.getElementById("simulation-impact-box").style.display = "none";
}

// ── FEATURE 1: Render historical + baseline forecast with confidence bands ──
function renderForecastChart() {
    const ctx = document.getElementById("forecast-chart").getContext("2d");
    
    if (forecastChartInstance) {
        forecastChartInstance.destroy();
    }
    
    const historyLabels = currentHistory.map(r => r.date);
    const forecastLabels = currentForecast.map(r => r.date);
    const allLabels = [...historyLabels, ...forecastLabels];
    
    const historySales = currentHistory.map(r => r.sales);
    
    // Bridge: last history point connects to first forecast point
    const forecastSales = Array(currentHistory.length - 1).fill(null);
    forecastSales.push(historySales[historySales.length - 1]);
    currentForecast.forEach(r => forecastSales.push(r.sales));
    
    // Confidence band upper and lower
    const upperBand = Array(currentHistory.length - 1).fill(null);
    upperBand.push(historySales[historySales.length - 1]); // bridge
    currentForecast.forEach(r => upperBand.push(r.confidence_upper ?? r.sales));

    const lowerBand = Array(currentHistory.length - 1).fill(null);
    lowerBand.push(historySales[historySales.length - 1]); // bridge
    currentForecast.forEach(r => lowerBand.push(r.confidence_lower ?? r.sales));
    
    // Custom glowing gradients
    const gradientHist = ctx.createLinearGradient(0, 0, 0, 400);
    gradientHist.addColorStop(0, "rgba(161, 85, 243, 0.25)");
    gradientHist.addColorStop(1, "rgba(161, 85, 243, 0.0)");
    
    const gradientFc = ctx.createLinearGradient(0, 0, 0, 400);
    gradientFc.addColorStop(0, "rgba(0, 242, 254, 0.25)");
    gradientFc.addColorStop(1, "rgba(0, 242, 254, 0.0)");

    const gradientBand = ctx.createLinearGradient(0, 0, 0, 400);
    gradientBand.addColorStop(0, "rgba(0, 242, 254, 0.12)");
    gradientBand.addColorStop(1, "rgba(0, 242, 254, 0.01)");
    
    forecastChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: allLabels,
            datasets: [
                // Upper confidence band (filled down to lower band via fill: '+1')
                {
                    label: "Upper Bound",
                    data: upperBand,
                    borderColor: "transparent",
                    backgroundColor: gradientBand,
                    fill: "+1",
                    tension: 0.35,
                    pointRadius: 0,
                    pointHoverRadius: 0
                },
                // Lower confidence band
                {
                    label: "Lower Bound",
                    data: lowerBand,
                    borderColor: "rgba(0, 242, 254, 0.15)",
                    borderWidth: 1,
                    borderDash: [3, 3],
                    backgroundColor: "transparent",
                    fill: false,
                    tension: 0.35,
                    pointRadius: 0,
                    pointHoverRadius: 0
                },
                // Actual historical sales
                {
                    label: "Actual Sales",
                    data: [...historySales, ...Array(currentForecast.length).fill(null)],
                    borderColor: "#a155f3",
                    borderWidth: 3,
                    fill: true,
                    backgroundColor: gradientHist,
                    tension: 0.35,
                    pointBackgroundColor: "#a155f3",
                    pointRadius: 2,
                    pointHoverRadius: 6
                },
                // Forecast line
                {
                    label: "Expected Forecast",
                    data: forecastSales,
                    borderColor: "#00f2fe",
                    borderWidth: 3,
                    borderDash: [6, 4],
                    fill: true,
                    backgroundColor: gradientFc,
                    tension: 0.35,
                    pointBackgroundColor: "#00f2fe",
                    pointRadius: 2,
                    pointHoverRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "#161233",
                    titleColor: "#f0ecfc",
                    bodyColor: "#9f96c7",
                    borderColor: "rgba(255, 255, 255, 0.08)",
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 8,
                    displayColors: true,
                    filter: (item) => item.dataset.label !== "Upper Bound" && item.dataset.label !== "Lower Bound"
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.03)" },
                    ticks: {
                        color: "#665f8a",
                        maxTicksLimit: 12,
                        font: { size: 10, weight: 600 }
                    }
                },
                y: {
                    grid: { color: "rgba(255, 255, 255, 0.03)" },
                    ticks: {
                        color: "#665f8a",
                        font: { size: 10, weight: 600 }
                    }
                }
            }
        }
    });
}

// Run simulated parameters on the backend
async function runSimulation() {
    const priceAdjust = parseFloat(document.getElementById("price-slider").value) / 100;
    const isPromo = document.getElementById("promo-toggle").checked ? 1 : 0;
    const temp = parseFloat(document.getElementById("temp-slider").value);
    const precip = parseFloat(document.getElementById("precip-slider").value) / 100;
    const isHoliday = document.getElementById("holiday-toggle").checked ? 1 : 0;
    
    try {
        const res = await fetch("/api/simulate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                store_id: activeStoreId,
                product_id: activeProductId,
                price_adjust: priceAdjust,
                is_promotion: isPromo,
                weather_temp: temp,
                weather_precip: precip,
                is_holiday: isHoliday
            })
        });
        
        if (!res.ok) throw new Error("Simulation calculation failed");
        
        const data = await res.json();
        currentSimulation = data.simulation;
        
        renderSimulatorChart();
        updateSimulationImpact(data.adjusted_price);
    } catch (err) {
        console.error("Simulation error:", err);
        showNotification("Failed to run scenario analysis.", "error");
    }
}

// Render Simulator standard vs simulated chart
function renderSimulatorChart() {
    const ctx = document.getElementById("simulator-chart").getContext("2d");
    
    if (simulatorChartInstance) {
        simulatorChartInstance.destroy();
    }
    
    const labels = currentForecast.map(r => r.date);
    const standardSales = currentForecast.map(r => r.sales);
    
    const simulatedSales = currentSimulation.length > 0 
        ? currentSimulation.map(r => r.sales) 
        : Array(labels.length).fill(null);
        
    const datasets = [
        {
            label: "Baseline Forecast",
            data: standardSales,
            borderColor: "rgba(0, 242, 254, 0.6)",
            borderWidth: 2,
            backgroundColor: "transparent",
            tension: 0.3,
            pointRadius: 2
        }
    ];
    
    if (currentSimulation.length > 0) {
        datasets.push({
            label: "Simulated Scenario",
            data: simulatedSales,
            borderColor: "#00f5a0",
            borderWidth: 3,
            backgroundColor: "rgba(0, 245, 160, 0.05)",
            fill: true,
            tension: 0.3,
            pointBackgroundColor: "#00f5a0",
            pointRadius: 3,
            pointHoverRadius: 6
        });
    }
    
    simulatorChartInstance = new Chart(ctx, {
        type: "line",
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "#161233",
                    titleColor: "#f0ecfc",
                    bodyColor: "#9f96c7",
                    borderColor: "rgba(255, 255, 255, 0.08)",
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 8
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.03)" },
                    ticks: { color: "#665f8a", font: { size: 10, weight: 600 } }
                },
                y: {
                    grid: { color: "rgba(255, 255, 255, 0.03)" },
                    ticks: { color: "#665f8a", font: { size: 10, weight: 600 } }
                }
            }
        }
    });
}

// Calculate and show before/after impact of simulation
function updateSimulationImpact(adjPrice) {
    if (currentForecast.length === 0 || currentSimulation.length === 0) return;
    
    const standardTotal = currentForecast.reduce((sum, row) => sum + row.sales, 0);
    const simulatedTotal = currentSimulation.reduce((sum, row) => sum + row.sales, 0);
    
    const pctDiff = ((simulatedTotal / standardTotal) - 1) * 100;
    
    const impactEl = document.getElementById("impact-percentage");
    const descEl = document.getElementById("impact-description");
    const container = document.getElementById("simulation-impact-box");
    
    container.style.display = "flex";
    
    const sign = pctDiff > 0 ? "+" : "";
    impactEl.textContent = `${sign}${pctDiff.toFixed(1)}%`;
    
    if (pctDiff > 0.1) {
        impactEl.className = "impact-value positive";
        descEl.textContent = `Demand increased by ${Math.round(simulatedTotal - standardTotal)} units. Price calibrated to $${adjPrice.toFixed(2)}.`;
    } else if (pctDiff < -0.1) {
        impactEl.className = "impact-value negative";
        descEl.textContent = `Demand decreased by ${Math.round(standardTotal - simulatedTotal)} units. Price calibrated to $${adjPrice.toFixed(2)}.`;
    } else {
        impactEl.className = "impact-value";
        descEl.textContent = `No net change in total demand volume. Price calibrated to $${adjPrice.toFixed(2)}.`;
    }
}

// ── FEATURE 5: Fetch model metrics with MAPE + baseline comparison ──
async function updateModelMetricsTab() {
    try {
        const res = await fetch("/api/train/status");
        if (!res.ok) throw new Error("Metrics endpoint failed");
        
        const data = await res.json();
        
        if (data.metrics && data.metrics.val_rmse !== undefined) {
            document.getElementById("metric-rmse").textContent = data.metrics.val_rmse.toFixed(2);
            document.getElementById("metric-mae").textContent = data.metrics.val_mae.toFixed(2);
            
            // MAPE
            const mapeEl = document.getElementById("metric-mape");
            if (mapeEl && data.metrics.val_mape !== undefined) {
                mapeEl.textContent = `${data.metrics.val_mape.toFixed(1)}%`;
            }

            const r2 = data.metrics.val_r2;
            const r2El = document.getElementById("metric-r2");
            r2El.textContent = r2.toFixed(4);
            if (r2 > 0.8) {
                r2El.className = "metric-badge emerald";
            } else {
                r2El.className = "metric-badge";
            }
            
            document.getElementById("metric-train-size").textContent = data.metrics.train_size.toLocaleString() + " records";
            document.getElementById("metric-val-size").textContent = data.metrics.val_size.toLocaleString() + " records";
            document.getElementById("metric-timestamp").textContent = data.metrics.timestamp;

            // Baseline comparison chip
            const chip = document.getElementById("baseline-chip");
            if (chip && data.metrics.model_vs_baseline_pct !== undefined) {
                const pct = data.metrics.model_vs_baseline_pct;
                const sign = pct >= 0 ? "+" : "";
                chip.textContent = `${sign}${pct.toFixed(1)}% RMSE vs Baseline`;
                chip.className = `baseline-chip ${pct >= 0 ? "better" : "worse"}`;
            }
        }
        
        // Render Feature Importances Chart
        if (data.importances && data.importances.length > 0) {
            renderImportanceChart(data.importances);
        }
    } catch (err) {
        console.error("Error updating model tab:", err);
    }
}

// Feature Importance Horizontal Bar Chart
function renderImportanceChart(importances) {
    const ctx = document.getElementById("importance-chart").getContext("2d");
    
    if (importanceChartInstance) {
        importanceChartInstance.destroy();
    }
    
    const sorted = [...importances].sort((a, b) => b.importance - a.importance).slice(0, 8);
    const labels = sorted.map(item => {
        return item.feature
            .replace("sales_lag_", "Sales Lag (t-")
            .replace("sales_roll_mean_", "Rolling Avg (")
            .replace("weather_temp", "Temperature")
            .replace("weather_precip", "Rainfall")
            .replace("is_promotion", "Promotion Flag")
            .replace("is_holiday", "Holiday Flag")
            .replace("store_id_Store_", "Store ")
            .replace("product_id_Prod_", "Product ")
            .replace("dayofweek", "Day of Week")
            .replace("month", "Month of Year")
            .concat(item.feature.includes("lag") || item.feature.includes("mean") ? ")" : "");
    });
    const values = sorted.map(item => item.importance);
    
    const gradient = ctx.createLinearGradient(0, 0, 400, 0);
    gradient.addColorStop(0, "rgba(161, 85, 243, 0.4)");
    gradient.addColorStop(1, "rgba(0, 242, 254, 0.85)");
    
    importanceChartInstance = new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: gradient,
                borderColor: "#00f2fe",
                borderWidth: 1.5,
                borderRadius: 4,
                borderSkipped: "start"
            }]
        },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "#161233",
                    titleColor: "#f0ecfc",
                    bodyColor: "#9f96c7"
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.02)" },
                    ticks: { color: "#665f8a", font: { size: 9, weight: 600 } }
                },
                y: {
                    grid: { display: false },
                    ticks: { color: "#9f96c7", font: { size: 9, weight: 700 } }
                }
            }
        }
    });
}

// ── FEATURE 2: Inventory Reorder Recommendation ──
function updateInventoryRecommendation() {
    if (currentForecast.length === 0) return;

    const safetyDays = parseInt(document.getElementById("safety-stock-slider").value);
    const forecastTotal = currentForecast.reduce((sum, r) => sum + r.sales, 0);
    const dailyAvg = forecastTotal / currentForecast.length;
    const safetyStock = Math.round(dailyAvg * safetyDays);
    const reorderQty = Math.round(forecastTotal + safetyStock);

    const volEl = document.getElementById("inv-forecast-vol");
    const avgEl = document.getElementById("inv-daily-avg");
    const safetyEl = document.getElementById("inv-safety-stock");
    const reorderEl = document.getElementById("inv-reorder-qty");

    if (volEl) volEl.textContent = forecastTotal.toLocaleString();
    if (avgEl) avgEl.textContent = Math.round(dailyAvg);
    if (safetyEl) safetyEl.textContent = safetyStock.toLocaleString();
    if (reorderEl) reorderEl.textContent = reorderQty.toLocaleString();
}

// ── FEATURE 4: CSV Export ──
function exportForecastCSV() {
    if (currentForecast.length === 0) {
        showNotification("No forecast data available to export.", "error");
        return;
    }

    const product = metadata.products.find(p => p.id === activeProductId);
    const store = metadata.stores.find(s => s.id === activeStoreId);
    const productName = product ? product.name : activeProductId;
    const storeName = store ? store.name : activeStoreId;

    // Build CSV header
    const headers = ["Date", "Store", "Product", "Forecast Sales", "Lower Bound", "Upper Bound"];
    const rows = currentForecast.map(r => [
        r.date,
        storeName,
        productName,
        r.sales,
        r.confidence_lower ?? r.sales,
        r.confidence_upper ?? r.sales
    ]);

    // Also prepend historical data
    const histHeaders = ["Date", "Store", "Product", "Actual Sales", "Lower Bound", "Upper Bound"];
    const histRows = currentHistory.map(r => [
        r.date,
        storeName,
        productName,
        r.sales,
        "",
        ""
    ]);

    const csvContent = [
        "# PREDICTFLOW FORECAST EXPORT",
        `# Generated: ${new Date().toISOString()}`,
        `# Store: ${storeName} | Product: ${productName}`,
        "",
        "## HISTORICAL DATA",
        histHeaders.join(","),
        ...histRows.map(r => r.join(",")),
        "",
        "## FORECAST (14-DAY)",
        headers.join(","),
        ...rows.map(r => r.join(","))
    ].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `predictflow_${activeStoreId}_${activeProductId}_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    showNotification("Forecast exported as CSV successfully!", "success");
}

// Trigger Model training in background
async function triggerModelTraining() {
    try {
        const res = await fetch("/api/train", { method: "POST" });
        if (!res.ok) throw new Error("Train trigger failed");
        
        const data = await res.json();
        showNotification(data.message, "success");
        
        const actionBtn = document.getElementById("train-model-action-btn");
        const quickBtn = document.getElementById("quick-train-btn");
        
        actionBtn.disabled = true;
        actionBtn.innerHTML = `<span>⏳</span> Pipeline Running...`;
        quickBtn.disabled = true;
        quickBtn.innerHTML = `<span>⏳</span> Training...`;
        
        if (trainingPollInterval) clearInterval(trainingPollInterval);
        trainingPollInterval = setInterval(pollTrainingStatus, 3000);
        
    } catch (err) {
        console.error("Training error:", err);
        showNotification("Failed to trigger pipeline retraining.", "error");
    }
}

// Poll training status
async function pollTrainingStatus() {
    try {
        const res = await fetch("/api/train/status");
        if (!res.ok) return;
        
        const data = await res.json();
        if (!data.is_training) {
            clearInterval(trainingPollInterval);
            trainingPollInterval = null;
            
            const actionBtn = document.getElementById("train-model-action-btn");
            const quickBtn = document.getElementById("quick-train-btn");
            
            actionBtn.disabled = false;
            actionBtn.innerHTML = `<span>⚙️</span> Run Pipeline Re-training`;
            quickBtn.disabled = false;
            quickBtn.innerHTML = `<span>🚀</span> Train Model`;
            
            showNotification("Model pipeline retraining completed!", "success");
            await loadMetadata();
            await refreshAllData();
            await updateModelMetricsTab();
        }
    } catch (err) {
        console.error("Polling error:", err);
    }
}

// Toast Notifications
function showNotification(msg, type = "success") {
    const banner = document.getElementById("notification-banner");
    const text = banner.querySelector(".notification-text");
    const icon = banner.querySelector(".notification-icon");
    
    text.textContent = msg;
    if (type === "error") {
        banner.style.borderColor = "#f35588";
        banner.style.backgroundColor = "rgba(243, 85, 136, 0.08)";
        banner.style.color = "#f35588";
        icon.textContent = "⚠️";
    } else {
        banner.style.borderColor = "#00f2fe";
        banner.style.backgroundColor = "rgba(0, 242, 254, 0.08)";
        banner.style.color = "#00f2fe";
        icon.textContent = "✓";
    }
    
    banner.classList.remove("hidden");
    setTimeout(closeNotification, 6000);
}

function closeNotification() {
    const banner = document.getElementById("notification-banner");
    if (banner) {
        banner.classList.add("hidden");
    }
}
