import type { RouteItem, RouteTradeoffs } from '../types'

interface RecommendationCardProps {
  recommendationRationale?: string
  tradeoffs?: RouteTradeoffs
  recommendedRoute?: RouteItem
  allRoutes: RouteItem[]
  onSelectRoute: (id: string) => void
  warning?: string | null
}

function formatDuration(seconds: number): string {
  const totalMins = Math.round(seconds / 60)
  const hrs = Math.floor(totalMins / 60)
  const mins = totalMins % 60
  if (hrs > 0) return `${hrs}h ${mins}m`
  return `${mins}m`
}

export function RecommendationCard({
  recommendationRationale,
  tradeoffs,
  recommendedRoute,
  allRoutes,
  onSelectRoute,
  warning,
}: RecommendationCardProps) {
  const safestRoute = allRoutes.find((r) => r.id === tradeoffs?.safest_route_id) || recommendedRoute
  const shortestRoute = allRoutes.find((r) => r.id === tradeoffs?.shortest_route_id)
  const fastestRoute = allRoutes.find((r) => r.id === tradeoffs?.fastest_route_id)

  const isAllNoTravel = allRoutes.length > 0 && allRoutes.every((r) => r.has_no_travel)

  return (
    <section className="recommendation-panel scroll-reveal" aria-label="Route Recommendation & Trade-offs">
      {/* Master Warning if provided */}
      {warning && isAllNoTravel && (
        <div className="severe-no-travel-banner">
          <div className="banner-icon-col">⛔</div>
          <div className="banner-text-col">
            <h4>DISPATCH SUSPENSION ADVISED: ALL ROUTES HAZARDOUS</h4>
            <p>{warning}</p>
          </div>
        </div>
      )}

      {warning && !isAllNoTravel && (
        <div className="severe-no-travel-banner">
          <div className="banner-icon-col">⚠️</div>
          <div className="banner-text-col">
            <h4>DISPATCH ADVISORY</h4>
            <p>{warning}</p>
          </div>
        </div>
      )}

      {/* Main Recommendation Block if a safe route exists */}
      {!isAllNoTravel && recommendedRoute && (
        <div className="recommendation-main-block">
          <div className="rec-header-row">
            <div className="rec-badge-pill">★ ALGORITHMIC RECOMMENDATION</div>
            <div className="rec-engine-tag">Rule-Based Multi-Criteria Decision Engine</div>
          </div>

          <div className="rec-body">
            <div className="rec-title-row">
              <h4>Recommended Dispatch: {recommendedRoute.name}</h4>
              <span className="rec-route-id">{recommendedRoute.id}</span>
            </div>

            <p className="rec-rationale-text">
              {recommendationRationale || (
                `${recommendedRoute.name} minimizes meteorological hazard exposure with ${recommendedRoute.severe_miles || 0} severe-weather miles and ${recommendedRoute.high_miles || 0} high-risk miles (Safety Score: ${recommendedRoute.safety_score || 95}/100).`
              )}
            </p>

            {recommendedRoute.has_unknown_weather && (
              <div className="rec-unknown-warning">
                <span className="warn-icon">ℹ️</span>
                <span>
                  <strong>Conservative Evaluation:</strong> Portions of this route contained incomplete or unresolvable weather data. Missing checkpoints were scored conservatively as severe risk to prevent false low-risk assumptions.
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Trade-Off Matrix: Safest vs Shortest vs Fastest */}
      <div className="tradeoffs-container">
        <h4 className="tradeoffs-title">Corridor Trade-Off Matrix (Safest vs. Shortest vs. Fastest)</h4>
        <div className="tradeoffs-grid">
          {/* Safest Option */}
          {safestRoute && (
            <div
              className={`tradeoff-card safest ${safestRoute.id === recommendedRoute?.id ? 'active-rec' : ''}`}
              onClick={() => onSelectRoute(safestRoute.id)}
            >
              <div className="tradeoff-badge">SAFEST ALTERNATIVE</div>
              <h5>{safestRoute.name}</h5>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Safety Score</span>
                <span className="stat-value text-safe">
                  {safestRoute.safety_score !== undefined ? `${Math.round(safestRoute.safety_score)}/100` : 'Optimal'}
                </span>
              </div>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Severe / High Miles</span>
                <span className="stat-value">{safestRoute.severe_miles || 0} mi / {safestRoute.high_miles || 0} mi</span>
              </div>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Distance & Time</span>
                <span className="stat-value">{safestRoute.distance_miles.toFixed(1)} mi | {formatDuration(safestRoute.duration_seconds)}</span>
              </div>
              <span className="tradeoff-summary">
                Minimizes rollover & traction loss hazards. Primary dispatch recommendation.
              </span>
            </div>
          )}

          {/* Shortest Option */}
          {shortestRoute && (
            <div
              className={`tradeoff-card shortest ${shortestRoute.id === recommendedRoute?.id ? 'active-rec' : ''}`}
              onClick={() => onSelectRoute(shortestRoute.id)}
            >
              <div className="tradeoff-badge">SHORTEST DISTANCE</div>
              <h5>{shortestRoute.name}</h5>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Distance</span>
                <span className="stat-value">{shortestRoute.distance_miles.toFixed(1)} mi</span>
              </div>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Distance Delta</span>
                <span className="stat-value">
                  {safestRoute
                    ? (shortestRoute.distance_miles < safestRoute.distance_miles
                      ? `-${(safestRoute.distance_miles - shortestRoute.distance_miles).toFixed(1)} mi vs Safest`
                      : 'Identical to Safest')
                    : 'Baseline'}
                </span>
              </div>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Risk Exposure</span>
                <span className="stat-value">
                  {shortestRoute.severe_miles || 0} mi sev | {shortestRoute.high_miles || 0} mi high
                </span>
              </div>
              <span className="tradeoff-summary">
                {shortestRoute.has_no_travel
                  ? 'Contains NO_TRAVEL checkpoints. Unsafe for dispatch.'
                  : (shortestRoute.id === safestRoute?.id ? 'Direct shortest route is also the safest path.' : 'Saves miles but exposes truck to higher weather risk.')}
              </span>
            </div>
          )}

          {/* Fastest Option */}
          {fastestRoute && (
            <div
              className={`tradeoff-card fastest ${fastestRoute.id === recommendedRoute?.id ? 'active-rec' : ''}`}
              onClick={() => onSelectRoute(fastestRoute.id)}
            >
              <div className="tradeoff-badge">FASTEST DURATION</div>
              <h5>{fastestRoute.name}</h5>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Duration</span>
                <span className="stat-value">{formatDuration(fastestRoute.duration_seconds)}</span>
              </div>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Time Delta</span>
                <span className="stat-value">
                  {safestRoute
                    ? (fastestRoute.duration_seconds < safestRoute.duration_seconds
                      ? `-${Math.round((safestRoute.duration_seconds - fastestRoute.duration_seconds) / 60)} min vs Safest`
                      : 'Identical to Safest')
                    : 'Baseline'}
                </span>
              </div>
              <div className="tradeoff-stat-row">
                <span className="stat-label">Risk Exposure</span>
                <span className="stat-value">
                  {fastestRoute.severe_miles || 0} mi sev | {fastestRoute.high_miles || 0} mi high
                </span>
              </div>
              <span className="tradeoff-summary">
                {fastestRoute.has_no_travel
                  ? 'Contains NO_TRAVEL checkpoints. Unsafe for dispatch.'
                  : (fastestRoute.id === safestRoute?.id ? 'Fastest transit time aligns with lowest risk.' : 'Quicker highway link with higher storm exposure.')}
              </span>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
