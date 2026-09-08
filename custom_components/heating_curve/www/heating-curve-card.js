// Heating Curve Card — draggable piecewise-linear weather-compensation curve
// Points are fixed on the X axis (outdoor temperature grid) and can only be
// dragged vertically (target temperature).
//
// Two configuration modes are supported:
//
// 1) "points" mode — one entity per point (input_number/number), full
//    control over each point's own min/max:
//      points:
//        - x: -20
//          entity: input_number.p1
//        - x: -15
//          entity: input_number.p2
//        ...
//
// 2) "curve_entity" mode — a single entity (typically input_text) holding
//    the whole curve as a JSON array, e.g. "[55,51,48,44,40,36,33,29,25]".
//    Only one helper to create. Points are evenly spaced between grid_min
//    and grid_max:
//      curve_entity: input_text.heatpump_curve
//      point_count: 9
//      grid_min: -20
//      grid_max: 20
//      service_domain: input_text

class HeatingCurveCard extends HTMLElement {
  setConfig(config) {
    const hasPoints = Array.isArray(config.points) && config.points.length >= 2;
    const hasCurveEntity = !!config.curve_entity;
    if (!hasPoints && !hasCurveEntity) {
      throw new Error(
        'heating-curve-card: provide either "points" (array of {x, entity}) or "curve_entity" (single JSON-array entity)'
      );
    }
    this._config = {
      title: 'Heating Curve',
      unit: '°C',
      y_min: 15,
      y_max: 65,
      point_count: 9,
      grid_min: -20,
      grid_max: 20,
      current_x_entity: null,
      current_y_entity: null,
      service_domain: hasCurveEntity ? 'input_text' : 'input_number',
      ...config,
    };
    this._mode = hasPoints ? 'points' : 'curve_entity';
    this._dragIndex = null;
    this._localArray = null; // working copy of the JSON array while dragging (curve_entity mode)
    this._localValues = {}; // entity -> live value while dragging (points mode)
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
      this._built = true;
    }
    this._render();
  }

  getCardSize() {
    return 5;
  }

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .header { font-size: 1.1em; font-weight: 500; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }
        .subtitle { font-size: 0.85em; font-weight: 400; color: var(--secondary-text-color); }
        .wrap { position: relative; width: 100%; }
        svg { width: 100%; height: auto; touch-action: none; overflow: visible; }
        .axis-label { font-size: 9px; fill: var(--secondary-text-color); }
        .grid-line { stroke: var(--divider-color, #444); stroke-width: 1; stroke-dasharray: 2,3; }
        .curve-line { stroke: var(--primary-color); stroke-width: 3; fill: none; }
        .point { fill: var(--primary-color); stroke: var(--card-background-color, #fff); stroke-width: 2; cursor: ns-resize; }
        .point:hover { fill: var(--accent-color, var(--primary-color)); }
        .value-label { font-size: 11px; font-weight: 600; fill: var(--primary-text-color); text-anchor: middle; }
        .now-marker { fill: var(--error-color, #e74c3c); }
        .error { padding: 8px; color: var(--error-color, #e74c3c); font-size: 0.9em; }
      </style>
      <ha-card>
        <div class="header">
          <span>${this._config.title}</span>
          <span id="subtitle" class="subtitle"></span>
        </div>
        <div class="wrap">
          <svg id="svg" viewBox="0 0 500 300"></svg>
        </div>
        <div id="error" class="error"></div>
      </ha-card>
    `;
    this._svg = this.shadowRoot.getElementById('svg');
    this._subtitle = this.shadowRoot.getElementById('subtitle');
    this._errorEl = this.shadowRoot.getElementById('error');
    this._svg.addEventListener('pointermove', (e) => this._onMove(e));
    this._svg.addEventListener('pointerup', (e) => this._onUp(e));
    this._svg.addEventListener('pointercancel', (e) => this._onUp(e));
  }

  // ---- abstract point list: [{x, get(), commit(val)}] ----
  _getPoints() {
    if (this._mode === 'points') {
      return this._config.points.map((pt) => ({
        x: pt.x,
        min: pt.min,
        max: pt.max,
        get: () => this._getPointsVal(pt.entity),
      }));
    }

    const n = this._config.point_count;
    const { grid_min, grid_max } = this._config;
    const step = n > 1 ? (grid_max - grid_min) / (n - 1) : 0;
    const arr = this._getCurveArray();
    return Array.from({ length: n }, (_, i) => ({
      x: Math.round((grid_min + step * i) * 10) / 10,
      get: () => (this._localArray ? this._localArray[i] : arr[i]),
    }));
  }

  _getCurveArray() {
    const n = this._config.point_count;
    const st = this._hass && this._hass.states[this._config.curve_entity];
    if (this._errorEl) this._errorEl.textContent = '';
    if (!st) return new Array(n).fill(this._config.y_min);
    try {
      const parsed = JSON.parse(st.state);
      if (Array.isArray(parsed) && parsed.length === n) {
        return parsed.map((v) => parseFloat(v));
      }
      if (this._errorEl) {
        this._errorEl.textContent = `heating-curve-card: ${this._config.curve_entity} does not hold a JSON array of length ${n}`;
      }
    } catch (err) {
      if (this._errorEl) {
        this._errorEl.textContent = `heating-curve-card: ${this._config.curve_entity} is not valid JSON`;
      }
    }
    return new Array(n).fill(this._config.y_min);
  }

  _writeCurveArray(arr) {
    if (!this._hass) return;
    this._hass.callService(this._config.service_domain, 'set_value', {
      entity_id: this._config.curve_entity,
      value: JSON.stringify(arr),
    });
  }

  _getPointsVal(entity) {
    const st = this._hass && this._hass.states[entity];
    return st ? parseFloat(st.state) : this._config.y_min;
  }

  // ---- coordinate helpers ----
  _padding() {
    return { left: 34, right: 14, top: 14, bottom: 26 };
  }

  _xToPx(i, n) {
    const p = this._padding();
    const w = 500 - p.left - p.right;
    return p.left + (w * i) / (n - 1);
  }

  _yToPx(val) {
    const p = this._padding();
    const h = 300 - p.top - p.bottom;
    const { y_min, y_max } = this._config;
    const ratio = (val - y_min) / (y_max - y_min);
    return p.top + h * (1 - Math.max(0, Math.min(1, ratio)));
  }

  _pxToY(py) {
    const p = this._padding();
    const h = 300 - p.top - p.bottom;
    const { y_min, y_max } = this._config;
    const ratio = 1 - (py - p.top) / h;
    return y_min + ratio * (y_max - y_min);
  }

  // ---- render ----
  _render() {
    if (!this._hass) return;
    const pts = this._getPoints();
    const n = pts.length;
    const svg = this._svg;
    svg.querySelectorAll('.dyn').forEach((el) => el.remove());

    const frag = document.createDocumentFragment();
    const ns = 'http://www.w3.org/2000/svg';

    const { y_min, y_max } = this._config;
    const ySteps = 5;
    for (let s = 0; s <= ySteps; s++) {
      const val = y_min + ((y_max - y_min) * s) / ySteps;
      const py = this._yToPx(val);
      const line = document.createElementNS(ns, 'line');
      line.setAttribute('class', 'grid-line dyn');
      line.setAttribute('x1', this._padding().left);
      line.setAttribute('x2', 500 - this._padding().right);
      line.setAttribute('y1', py);
      line.setAttribute('y2', py);
      frag.appendChild(line);

      const label = document.createElementNS(ns, 'text');
      label.setAttribute('class', 'axis-label dyn');
      label.setAttribute('x', 4);
      label.setAttribute('y', py + 3);
      label.textContent = Math.round(val);
      frag.appendChild(label);
    }

    pts.forEach((pt, i) => {
      const px = this._xToPx(i, n);
      const label = document.createElementNS(ns, 'text');
      label.setAttribute('class', 'axis-label dyn');
      label.setAttribute('x', px);
      label.setAttribute('y', 300 - this._padding().bottom + 14);
      label.setAttribute('text-anchor', 'middle');
      label.textContent = pt.x + '°';
      frag.appendChild(label);
    });

    const path = document.createElementNS(ns, 'polyline');
    path.setAttribute('class', 'curve-line dyn');
    const coords = pts.map((pt, i) => `${this._xToPx(i, n)},${this._yToPx(pt.get())}`).join(' ');
    path.setAttribute('points', coords);
    frag.appendChild(path);

    pts.forEach((pt, i) => {
      const px = this._xToPx(i, n);
      const val = pt.get();
      const py = this._yToPx(val);

      const circle = document.createElementNS(ns, 'circle');
      circle.setAttribute('class', 'point dyn');
      circle.setAttribute('cx', px);
      circle.setAttribute('cy', py);
      circle.setAttribute('r', 8);
      circle.addEventListener('pointerdown', (e) => {
        this._dragIndex = i;
        if (this._mode === 'curve_entity' && !this._localArray) {
          this._localArray = this._getCurveArray();
        }
        try {
          e.target.setPointerCapture(e.pointerId);
        } catch (err) {}
      });
      frag.appendChild(circle);

      const label = document.createElementNS(ns, 'text');
      label.setAttribute('class', 'value-label dyn');
      label.setAttribute('x', px);
      label.setAttribute('y', py - 14);
      label.textContent = Math.round(val * 10) / 10;
      frag.appendChild(label);
    });

    if (this._subtitle) this._subtitle.textContent = '';
    if (this._config.current_x_entity) {
      const xSt = this._hass.states[this._config.current_x_entity];
      const x = xSt ? parseFloat(xSt.state) : null;
      let y = null;
      if (this._config.current_y_entity) {
        const ySt = this._hass.states[this._config.current_y_entity];
        y = ySt ? parseFloat(ySt.state) : null;
      }
      if (x !== null && y !== null && !Number.isNaN(x) && !Number.isNaN(y)) {
        const xMin = pts[0].x;
        const xMax = pts[n - 1].x;
        const xClamped = Math.max(xMin, Math.min(xMax, x));
        const frac = (xClamped - xMin) / (xMax - xMin);
        const px = this._padding().left + (500 - this._padding().left - this._padding().right) * frac;
        const py = this._yToPx(y);
        const marker = document.createElementNS(ns, 'circle');
        marker.setAttribute('class', 'now-marker dyn');
        marker.setAttribute('cx', px);
        marker.setAttribute('cy', py);
        marker.setAttribute('r', 5);
        frag.appendChild(marker);

        if (this._subtitle) {
          this._subtitle.textContent = `now: ${x}° → ${Math.round(y * 10) / 10}${this._config.unit}`;
        }
      }
    }

    svg.appendChild(frag);
  }

  _onMove(e) {
    if (this._dragIndex === null) return;
    const rect = this._svg.getBoundingClientRect();
    const scaleY = 300 / rect.height;
    const py = (e.clientY - rect.top) * scaleY;
    let val = this._pxToY(py);

    const pts = this._getPoints();
    const pt = pts[this._dragIndex];
    const min = pt && pt.min !== undefined ? pt.min : this._config.y_min;
    const max = pt && pt.max !== undefined ? pt.max : this._config.y_max;
    val = Math.max(min, Math.min(max, val));
    val = Math.round(val);

    if (this._mode === 'points') {
      const entity = this._config.points[this._dragIndex].entity;
      this._localValues[entity] = val;
    } else {
      if (!this._localArray) this._localArray = this._getCurveArray();
      this._localArray[this._dragIndex] = val;
    }
    this._render();
  }

  _onUp(e) {
    if (this._dragIndex === null) return;
    const idx = this._dragIndex;
    this._dragIndex = null;

    if (this._mode === 'points') {
      const entity = this._config.points[idx].entity;
      const val = this._localValues[entity];
      if (val !== undefined && this._hass) {
        this._hass.callService(this._config.service_domain, 'set_value', {
          entity_id: entity,
          value: val,
        });
      }
    } else {
      if (this._localArray && this._hass) {
        this._writeCurveArray(this._localArray);
      }
      this._localArray = null;
    }
    this._render();
  }
}

customElements.define('heating-curve-card', HeatingCurveCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'heating-curve-card',
  name: 'Heating Curve Card',
  description: 'Draggable piecewise-linear weather compensation curve',
});
