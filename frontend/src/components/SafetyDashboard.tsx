import type { RouteItem } from '../types'

interface SafetyDashboardProps {
  selectedRoute: RouteItem
  allRoutes: RouteItem[]
  onSelectRoute: (id: string) => void
  severeAlertsCount: number
  onDownloadPdf: () => void
}

function formatDuration(seconds: number): string {
  const totalMins = Math.round(seconds / 60)
  const hrs = Math.floor(totalMins / 60)
  const mins = totalMins % 60
  if (hrs > 0) return `${hrs}h ${mins}m`
  return `${mins}m`
}

export function SafetyDashboard({
  selectedRoute,
  allRoutes,
  onSelectRoute,
  severeAlertsCount,
  onDownloadPdf,
}: SafetyDashboardProps) {
  const safetyScore = selectedRoute.safety_score !== undefined
    ? Math.round(selectedRoute.safety_score)
    : Math.max(0, Math.round(100 - (selectedRoute.average_risk_score || 0) * 25))

  const scoreTier =
    safetyScore >= 80 ? 'optimal' : safetyScore >= 50 ? 'moderate' : 'critical'

  const scoreColor =
    safetyScore >= 80 ? '#15803D' : safetyScore >= 50 ? '#A16207' : '#DC2626'

  const highRiskMiles = (
    (selectedRoute.high_miles || 0) + (selectedRoute.severe_miles || 0)
  ).toFixed(1)

  return (
    <section className="safety-dashboard-card scroll-reveal" aria-label="Safety Analytics Dashboard">
      <div className="dashboard-header-row">
        <div className="dashboard-title-group">
          <div className="dashboard-pill-badge">HGV METRICS</div>
          <h3>Safety Analytics & Operations Dashboard</h3>
          <p className="dashboard-sub">
            Real-time deterministic safety index and risk telemetry for selected highway corridor.
          </p>
        </div>

        <div className="dashboard-header-actions">
          <button
            type="button"
            className="download-pdf-btn"
            onClick={onDownloadPdf}
            title="Generate and download comprehensive PDF Trip Report"
          >
            <span className="btn-icon">📄</span>
            <span>Download Trip Report (PDF)</span>
          </button>
        </div>
      </div>

      {/* Route Switcher Selector Tabs */}
      <div className="dashboard-route-tabs" role="tablist">
        {allRoutes.map((r, idx) => {
          const isSelected = r.id === selectedRoute.id
          return (
            <button
              key={r.id}
              type="button"
              role="tab"
              aria-selected={isSelected}
              className={`dashboard-route-tab ${isSelected ? 'active' : ''}`}
              onClick={() => onSelectRoute(r.id)}
            >
              <span className="tab-rank">#{idx + 1}</span>
              <span className="tab-name">{r.name}</span>
              {r.is_recommended && <span className="tab-badge-rec">Safest</span>}
              {r.has_no_travel && <span className="tab-badge-no-travel">No Travel</span>}
              <span className="tab-score" style={{ color: r.safety_score && r.safety_score < 50 ? '#DC2626' : undefined }}>
                {r.safety_score !== undefined ? `${Math.round(r.safety_score)}/100` : ''}
              </span>
            </button>
          )
        })}
      </div>

      {/* 5 High-Impact KPI Cards */}
      <div className="kpi-grid">
        {/* KPI 1: Safety Score */}
        <div className={`kpi-card kpi-${scoreTier}`}>
          <div className="kpi-card-header">
            <span className="kpi-card-title">Safety Score</span>
            <span className="kpi-data-type-tag modeled">MODELED</span>
          </div>
          <div className="kpi-main-val">
            <span className="kpi-number" style={{ color: scoreColor }}>{safetyScore}</span>
            <span className="kpi-unit">/100</span>
          </div>
          <div className="kpi-progress-bar-bg">
            <div
              className="kpi-progress-bar-fill"
              style={{ width: `${Math.min(100, Math.max(0, safetyScore))}%`, backgroundColor: scoreColor }}
            />
          </div>
          <span className="kpi-caption">
            {safetyScore >= 80 ? 'Low risk clearance' : safetyScore >= 50 ? 'Caution: Elevated weather' : 'Severe weather hazard'}
          </span>
        </div>

        {/* KPI 2: Total Distance */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">Total Distance</span>
            <span className="kpi-data-type-tag measured">MEASURED</span>
          </div>
          <div className="kpi-main-val">
            <span className="kpi-number">{selectedRoute.distance_miles.toFixed(1)}</span>
            <span className="kpi-unit">miles</span>
          </div>
          <span className="kpi-sub-metric">
            {selectedRoute.checkpoints_count || selectedRoute.checkpoints.length} weather waypoints
          </span>
          <span className="kpi-caption">OpenRouteService HGV road path</span>
        </div>

        {/* KPI 3: Estimated Duration */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">Estimated Duration</span>
            <span className="kpi-data-type-tag modeled">MODELED</span>
          </div>
          <div className="kpi-main-val">
            <span className="kpi-number">{formatDuration(selectedRoute.duration_seconds)}</span>
          </div>
          <span className="kpi-sub-metric">
            Avg speed {(selectedRoute.distance_miles / (selectedRoute.duration_seconds / 3600)).toFixed(0)} mph
          </span>
          <span className="kpi-caption">At commercial truck profile</span>
        </div>

        {/* KPI 4: High-Risk Miles */}
        <div className={`kpi-card ${Number(highRiskMiles) > 0 ? 'kpi-warning' : 'kpi-safe'}`}>
          <div className="kpi-card-header">
            <span className="kpi-card-title">High-Risk Miles</span>
            <span className="kpi-data-type-tag modeled">MODELED</span>
          </div>
          <div className="kpi-main-val">
            <span className="kpi-number">{highRiskMiles}</span>
            <span className="kpi-unit">mi</span>
          </div>
          <span className="kpi-sub-metric">
            {(selectedRoute.severe_miles || 0).toFixed(1)} mi severe | {(selectedRoute.high_miles || 0).toFixed(1)} mi high
          </span>
          <span className="kpi-caption">Adverse conditions along corridor</span>
        </div>

        {/* KPI 5: Weather Alerts */}
        <div className={`kpi-card ${severeAlertsCount > 0 ? 'kpi-danger' : 'kpi-safe'}`}>
          <div className="kpi-card-header">
            <span className="kpi-card-title">Weather Alerts</span>
            <span className="kpi-data-type-tag modeled">MODELED</span>
          </div>
          <div className="kpi-main-val">
            <span className="kpi-number">{severeAlertsCount}</span>
            <span className="kpi-unit">alerts</span>
          </div>
          <span className="kpi-sub-metric">
            {severeAlertsCount === 0 ? 'Clear passage' : 'Severe / No-Travel alerts'}
          </span>
          <span className="kpi-caption">Threshold breaches at waypoints</span>
        </div>
      </div>

      {/* Transparency Footer distinguishing measured road geometry from modeled forecasts */}
      <div className="dashboard-transparency-note">
        <span className="note-badge">Telemetry Methodology</span>
        <span className="note-text">
          <strong>Measured Data:</strong> Route geometry and highway mileage are computed via OpenRouteService HGV road networks.
          {' '}<strong>Modeled Estimates:</strong> ETAs, fuel consumption, and weather risk scores are projected using Open-Meteo deterministic 0–48h forecasts matched to waypoint arrival intervals.
        </span>
      </div>
    </section>
  )
}
