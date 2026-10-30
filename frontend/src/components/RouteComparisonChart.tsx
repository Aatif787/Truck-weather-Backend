import { useState } from 'react'
import type { RouteItem } from '../types'

interface RouteComparisonChartProps {
  routes: RouteItem[]
  selectedRouteId: string
  onSelectRoute: (id: string) => void
  fuelPrice: number
  fuelMpg: number
  onUpdateFuel: (price: number, mpg: number) => void
}

function formatDuration(seconds: number): string {
  const totalMins = Math.round(seconds / 60)
  const hrs = Math.floor(totalMins / 60)
  const mins = totalMins % 60
  if (hrs > 0) return `${hrs}h ${mins}m`
  return `${mins}m`
}

export function RouteComparisonChart({
  routes,
  selectedRouteId,
  onSelectRoute,
  fuelPrice,
  fuelMpg,
  onUpdateFuel,
}: RouteComparisonChartProps) {
  const [showFuelConfig, setShowFuelConfig] = useState(false)

  // Find max distance across routes to normalize bar widths
  const maxDistance = Math.max(...routes.map((r) => r.distance_miles), 1)

  return (
    <section className="route-comparison-card scroll-reveal" aria-label="Route Comparison & Fuel Analytics">
      <div className="comparison-header-row">
        <div>
          <div className="section-pill-tag">MULTI-ROUTE COMPARISON</div>
          <h3>Route Risk Mileage Distribution & Fuel Modeling</h3>
          <p className="section-sub">
            Compare alternatives across actual road distance, weather risk exposure miles, and projected Class 8 fuel costs.
          </p>
        </div>

        <button
          type="button"
          className="fuel-toggle-btn"
          onClick={() => setShowFuelConfig(!showFuelConfig)}
        >
          <span>⛽ Fuel Configurator: ${fuelPrice.toFixed(2)}/gal @ {fuelMpg.toFixed(1)} MPG</span>
          <span className="toggle-arrow">{showFuelConfig ? '▲' : '▼'}</span>
        </button>
      </div>

      {/* Configurable Fuel Baseline Settings Drawer */}
      {showFuelConfig && (
        <div className="fuel-config-drawer">
          <div className="fuel-config-grid">
            <div className="fuel-input-group">
              <label htmlFor="fuelPriceInput">Diesel Price ($/gal):</label>
              <div className="fuel-input-row">
                <input
                  id="fuelPriceInput"
                  type="number"
                  step="0.05"
                  min="2.00"
                  max="8.00"
                  value={fuelPrice}
                  onChange={(e) => onUpdateFuel(Number(e.target.value) || 3.85, fuelMpg)}
                />
                <div className="fuel-preset-chips">
                  <button type="button" onClick={() => onUpdateFuel(3.50, fuelMpg)}>$3.50</button>
                  <button type="button" onClick={() => onUpdateFuel(3.85, fuelMpg)}>$3.85</button>
                  <button type="button" onClick={() => onUpdateFuel(4.25, fuelMpg)}>$4.25</button>
                </div>
              </div>
            </div>

            <div className="fuel-input-group">
              <label htmlFor="fuelMpgInput">Class 8 Fleet MPG:</label>
              <div className="fuel-input-row">
                <input
                  id="fuelMpgInput"
                  type="number"
                  step="0.1"
                  min="3.0"
                  max="12.0"
                  value={fuelMpg}
                  onChange={(e) => onUpdateFuel(fuelPrice, Number(e.target.value) || 6.5)}
                />
                <div className="fuel-preset-chips">
                  <button type="button" onClick={() => onUpdateFuel(fuelPrice, 5.8)}>5.8 (Loaded)</button>
                  <button type="button" onClick={() => onUpdateFuel(fuelPrice, 6.5)}>6.5 (Avg)</button>
                  <button type="button" onClick={() => onUpdateFuel(fuelPrice, 7.2)}>7.2 (Aero)</button>
                </div>
              </div>
            </div>
          </div>
          <p className="fuel-drawer-note">
            Planning baseline: Fuel figures represent modeled estimates calculated via <code>(Distance / MPG) × Diesel Price</code> and are not real-time engine ECM measurements.
          </p>
        </div>
      )}

      {/* Pure React SVG Stacked Risk Bar Chart */}
      <div className="chart-wrapper">
        <div className="chart-legend-row">
          <span className="legend-label">Risk Exposure Breakdown:</span>
          <span className="legend-item"><span className="legend-swatch low" /> Low Risk</span>
          <span className="legend-item"><span className="legend-swatch moderate" /> Moderate</span>
          <span className="legend-item"><span className="legend-swatch high" /> High Risk</span>
          <span className="legend-item"><span className="legend-swatch severe" /> Severe / No Travel</span>
        </div>

        <div className="chart-bars-list">
          {routes.map((route, idx) => {
            const isSelected = route.id === selectedRouteId
            const dist = route.distance_miles
            const severeMi = route.severe_miles || 0
            const highMi = route.high_miles || 0
            const modMi = route.moderate_miles || 0
            const lowMi = route.low_miles !== undefined ? route.low_miles : Math.max(0, dist - severeMi - highMi - modMi)

            // Percentages relative to max route distance
            const totalBarPct = Math.min(100, Math.max(10, (dist / maxDistance) * 100))
            const lowPct = dist > 0 ? (lowMi / dist) * 100 : 100
            const modPct = dist > 0 ? (modMi / dist) * 100 : 0
            const highPct = dist > 0 ? (highMi / dist) * 100 : 0
            const sevPct = dist > 0 ? (severeMi / dist) * 100 : 0

            const estGallons = (dist / fuelMpg)
            const estCost = estGallons * fuelPrice

            return (
              <div
                key={route.id}
                className={`chart-bar-row ${isSelected ? 'row-selected' : ''}`}
                onClick={() => onSelectRoute(route.id)}
              >
                <div className="bar-label-col">
                  <div className="bar-route-title">
                    <span className="bar-rank-badge">#{idx + 1}</span>
                    <strong className="bar-route-name">{route.name}</strong>
                    {route.is_recommended && <span className="bar-rec-tag">Safest</span>}
                    {route.has_no_travel && <span className="bar-no-travel-tag">No Travel</span>}
                  </div>
                  <span className="bar-metrics-sub">
                    {dist.toFixed(1)} mi | {formatDuration(route.duration_seconds)} | est ${estCost.toFixed(2)}
                  </span>
                </div>

                <div className="bar-track-col">
                  <div className="bar-outer-track" style={{ width: `${totalBarPct}%` }}>
                    {lowPct > 0 && (
                      <div
                        className="bar-segment low"
                        style={{ width: `${lowPct}%` }}
                        title={`Low Risk: ${lowMi.toFixed(1)} miles`}
                      />
                    )}
                    {modPct > 0 && (
                      <div
                        className="bar-segment moderate"
                        style={{ width: `${modPct}%` }}
                        title={`Moderate Risk: ${modMi.toFixed(1)} miles`}
                      />
                    )}
                    {highPct > 0 && (
                      <div
                        className="bar-segment high"
                        style={{ width: `${highPct}%` }}
                        title={`High Risk: ${highMi.toFixed(1)} miles`}
                      />
                    )}
                    {sevPct > 0 && (
                      <div
                        className="bar-segment severe"
                        style={{ width: `${sevPct}%` }}
                        title={`Severe Risk: ${severeMi.toFixed(1)} miles`}
                      />
                    )}
                  </div>
                  <span className="bar-end-miles">{dist.toFixed(1)} mi</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Comparison Data Table */}
      <div className="comparison-table-wrapper">
        <table className="comparison-table">
          <thead>
            <tr>
              <th>Alternative</th>
              <th>Distance <span className="th-sub">[MEASURED]</span></th>
              <th>Duration <span className="th-sub">[MODELED]</span></th>
              <th>Safety Score</th>
              <th>High Risk</th>
              <th>Severe</th>
              <th>Est. Fuel (Gal)</th>
              <th>Est. Fuel ($)</th>
              <th>Select</th>
            </tr>
          </thead>
          <tbody>
            {routes.map((r, idx) => {
              const isSelected = r.id === selectedRouteId
              const estGallons = (r.distance_miles / fuelMpg)
              const estCost = estGallons * fuelPrice
              const score = r.safety_score !== undefined ? Math.round(r.safety_score) : 'N/A'

              return (
                <tr
                  key={r.id}
                  className={`comparison-row ${isSelected ? 'row-active' : ''}`}
                  onClick={() => onSelectRoute(r.id)}
                >
                  <td>
                    <div className="table-route-cell">
                      <span className="table-rank">#{idx + 1}</span>
                      <strong>{r.name}</strong>
                      {r.is_recommended && <span className="table-rec-badge">RECOMMENDED</span>}
                      {r.has_no_travel && <span className="table-warn-badge">NO TRAVEL</span>}
                    </div>
                  </td>
                  <td><strong>{r.distance_miles.toFixed(1)} mi</strong></td>
                  <td>{formatDuration(r.duration_seconds)}</td>
                  <td>
                    <span
                      className="table-score-badge"
                      style={{
                        color: typeof score === 'number' && score >= 80 ? '#15803D' : typeof score === 'number' && score >= 50 ? '#A16207' : '#DC2626'
                      }}
                    >
                      {score}/100
                    </span>
                  </td>
                  <td>{(r.high_miles || 0).toFixed(1)} mi</td>
                  <td>
                    <span className={r.severe_miles && r.severe_miles > 0 ? 'text-danger bold' : ''}>
                      {(r.severe_miles || 0).toFixed(1)} mi
                    </span>
                  </td>
                  <td>{estGallons.toFixed(1)} gal (est)</td>
                  <td><strong>${estCost.toFixed(2)}</strong> <span className="val-sub">(est)</span></td>
                  <td>
                    <button
                      type="button"
                      className={`table-select-btn ${isSelected ? 'btn-active' : ''}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        onSelectRoute(r.id)
                      }}
                    >
                      {isSelected ? '✓ Active' : 'Select'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

