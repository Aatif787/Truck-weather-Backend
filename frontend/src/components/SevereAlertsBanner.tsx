import type { SevereAlert } from '../types'

interface SevereAlertsBannerProps {
  severeAlerts: SevereAlert[]
  selectedRouteId: string
  selectedRouteName?: string
  onInspectCheckpoint: (routeId: string, checkpointIndex: number) => void
}

function formatAlertTime(isoString: string): string {
  try {
    const d = new Date(isoString)
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return isoString
  }
}

export function SevereAlertsBanner({
  severeAlerts,
  selectedRouteId,
  selectedRouteName,
  onInspectCheckpoint,
}: SevereAlertsBannerProps) {
  const currentRouteAlerts = severeAlerts.filter((a) => a.route_id === selectedRouteId)

  if (currentRouteAlerts.length === 0) {
    return (
      <div className="safe-passage-banner scroll-reveal">
        <div className="safe-icon">✓</div>
        <div className="safe-content">
          <strong>No Severe Weather Alerts on {selectedRouteName || 'Selected Route'}</strong>
          <p>
            All waypoint forecasts along this corridor remain within standard Class 8 commercial operating tolerances.
            Continue standard dispatch protocol.
          </p>
        </div>
      </div>
    )
  }

  const hasNoTravel = currentRouteAlerts.some((a) => a.risk === 'NO_TRAVEL')

  return (
    <section
      className={`severe-alerts-section ${hasNoTravel ? 'has-no-travel' : 'has-severe'} scroll-reveal`}
      aria-label="Severe Weather Warnings"
    >
      <div className="severe-section-header">
        <div className="severe-header-left">
          <span className="severe-pulse-icon">{hasNoTravel ? '⛔' : '⚠️'}</span>
          <div>
            <h4>
              {hasNoTravel ? 'CRITICAL DISPATCH WARNING: NO_TRAVEL CONDITIONS' : 'SEVERE WEATHER ADVISORY'}
            </h4>
            <p className="severe-header-sub">
              {currentRouteAlerts.length} checkpoint{currentRouteAlerts.length > 1 ? 's' : ''} along{' '}
              {selectedRouteName || selectedRouteId} exceed safe commercial thresholds.
            </p>
          </div>
        </div>

        <div className="severe-source-tag">
          Open-Meteo Deterministic Forecast (0–48h)
        </div>
      </div>

      <div className="severe-alerts-list">
        {currentRouteAlerts.map((alert) => {
          const isNoTravel = alert.risk === 'NO_TRAVEL'
          return (
            <div
              key={`${alert.route_id}-${alert.checkpoint_index}`}
              className={`severe-alert-card ${isNoTravel ? 'alert-no-travel' : 'alert-severe'}`}
            >
              <div className="alert-card-top">
                <div className="alert-meta">
                  <span className={`risk-badge ${isNoTravel ? 'badge-no-travel' : 'badge-severe'}`}>
                    {alert.risk}
                  </span>
                  <span className="alert-cp-label">
                    Waypoint #{alert.checkpoint_index + 1} ({alert.distance_from_origin_miles.toFixed(1)} mi)
                  </span>
                  <span className="alert-eta">
                    ETA: {formatAlertTime(alert.estimated_arrival_time)}
                  </span>
                </div>

                <button
                  type="button"
                  className="alert-inspect-btn"
                  onClick={() => onInspectCheckpoint(alert.route_id, alert.checkpoint_index)}
                >
                  Locate on Map ➔
                </button>
              </div>

              {/* Weather Data Values */}
              <div className="alert-readings-row">
                <div className="reading-item">
                  <span className="reading-label">Wind Velocity:</span>
                  <span className="reading-val">{alert.wind_speed_mph !== null ? `${alert.wind_speed_mph} mph` : 'N/A'}</span>
                </div>
                <div className="reading-item">
                  <span className="reading-label">Precipitation:</span>
                  <span className="reading-val">
                    {alert.rain_intensity_in_hr !== null ? `${alert.rain_intensity_in_hr} in/hr` : '0 in/hr'} rain |{' '}
                    {alert.snow_intensity_in_hr !== null ? `${alert.snow_intensity_in_hr} in/hr` : '0 in/hr'} snow
                  </span>
                </div>
                {alert.load_adjusted_wind_risk && (
                  <div className="reading-item">
                    <span className="reading-label">Load-Adjusted Wind:</span>
                    <span className="reading-val text-warning">{alert.load_adjusted_wind_risk}</span>
                  </div>
                )}
              </div>

              {/* Driver Protocol / Recommended Action */}
              <div className="alert-action-box">
                <span className="action-tag">Driver Protocol:</span>
                <span className="action-text">{alert.recommended_action}</span>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

