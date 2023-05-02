(function() {
    window.__SPEEDCURVE__ = window.__SPEEDCURVE__ || {};
    window.__SPEEDCURVE__.performanceEntries = [];

    const observer = new PerformanceObserver((list) => {
        list.getEntries().forEach((entry) => {
            window.__SPEEDCURVE__.performanceEntries.push(entry)
        });
    });

    observer.observe({ type: "longtask", buffered: true });
    observer.observe({ type: "largest-contentful-paint", buffered: true });
    observer.observe({ type: "element", buffered: true });
    observer.observe({ type: "paint", buffered: true });

    // Disabled layout shifts for now, since the resulting entries are potentially
    // very large.
    // observer.observe({ type: "layout-shift", buffered: true });
})();
