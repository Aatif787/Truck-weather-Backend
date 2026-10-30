import { useState, type FormEvent } from 'react'
import './App.css'
import { MapView, type RouteItem, type Checkpoint } from './components/MapView'

interface LocationInfo {
  name: string
  coordinates: [number, number]
}

interface RouteAnalysisResponse {
  origin: LocationInfo
  destination: LocationInfo
  departure_datetime: string
  load_weight_lbs: number
  sampling_interval_miles: number
  routes_count: number
  recommended_route_id: string | null
  has_recommended_route: boolean
  warning: string | null
  routes: RouteItem[]
  error?: string
}

function formatDuration(seconds: number): string {
  const totalMins = Math.round(seconds / 60)
  const hrs = Math.floor(totalMins / 60)
  const mins = totalMins % 60
  if (hrs > 0) {
    return `${hrs}h ${mins}m`
  }
  return `${mins}m`
}

function formatDateTime(isoString: string): string {
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

function getRiskClass(risk: string): string {
  switch (risk) {
    case 'LOW':
      return 'badge-low'
    case 'MODERATE':
      return 'badge-moderate'
    case 'HIGH':
      return 'badge-high'
    case 'SEVERE':
      return 'badge-severe'
    case 'NO_TRAVEL':
      return 'badge-no-travel'
    default:
      return 'badge-unknown'
  }
}

function getDefaultDateTime(): string {
  const now = new Date()
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset())
  return now.toISOString().slice(0, 16)
}

function App() {
  const [origin, setOrigin] = useState('Heidelberg, Germany')
  const [destination, setDestination] = useState('Mannheim, Germany')
  const [departureDatetime, setDepartureDatetime] = useState(getDefaultDateTime())
  const [loadWeightLbs, setLoadWeightLbs] = useState(35000)
  const [samplingIntervalMiles, setSamplingIntervalMiles] = useState(25)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<RouteAnalysisResponse | null>(null)
  const [selectedRouteId, setSelectedRouteId] = useState<string>('route-1')
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<Checkpoint | null>(null)
  const [expandedRouteId, setExpandedRouteId] = useState<string | null>(null)

  const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault()

    if (!origin.trim() || !destination.trim()) {
      setError('Please provide both origin and destination.')
      return
    }

    if (origin.trim().toLowerCase() === destination.trim().toLowerCase()) {
      setError('Origin and destination cannot be the same location.')
      return
    }

    if (Number(loadWeightLbs) < 0) {
      setError('Truck load weight cannot be negative.')
      return
    }

    setLoading(true)
    setError(null)
    setData(null)
    setSelectedCheckpoint(null)

    try {
      const departureDate = new Date(departureDatetime)
      const departureIso = isNaN(departureDate.getTime())
        ? new Date().toISOString()
        : departureDate.toISOString()

      const response = await fetch(`${apiBase}/api/routes/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          origin: origin.trim(),
          destination: destination.trim(),
          departure_datetime: departureIso,
          load_weight_lbs: Number(loadWeightLbs) || 0,
          sampling_interval_miles: Number(samplingIntervalMiles) || 25,
        }),
      })

      const result = await response.json()

      if (!response.ok) {
        throw new Error(result.error || `Server responded with status ${response.status}`)
      }

      setData(result)
      if (result.routes && result.routes.length > 0) {
        const initialSelectedId = result.recommended_route_id || result.routes[0].id
        setSelectedRouteId(initialSelectedId)
        setExpandedRouteId(initialSelectedId)
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to fetch routes. Please check backend connection.')
      }
    } finally {
      setLoading(false)
    }
  }

  const recommendedRoute = data?.routes.find((r) => r.id === data.recommended_route_id)

  return (
    <div className="app-container">
      <header className="header">
        <h1>Weather-Aware Truck Routing</h1>
        <p className="subtitle">
          Intelligent Highway Route Planning & Checkpoint Weather Risk Assessment
        </p>
      </header>

      <main className="content">
        <form className="route-form" onSubmit={handleSearch}>
          <div className="form-row">
            <div className="form-group flex-1">
              <label htmlFor="origin">Origin</label>
              <input
                id="origin"
                type="text"
                placeholder="e.g. Heidelberg, Germany"
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="form-group flex-1">
              <label htmlFor="destination">Destination</label>
              <input
                id="destination"
                type="text"
                placeholder="e.g. Mannheim, Germany"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                disabled={loading}
              />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group flex-1">
              <label htmlFor="departure">Departure Date & Time</label>
              <input
                id="departure"
                type="datetime-local"
                value={departureDatetime}
                onChange={(e) => setDepartureDatetime(e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="form-group flex-1">
              <label htmlFor="weight">Load Weight (lbs)</label>
              <input
                id="weight"
                type="number"
                min="0"
                step="500"
                placeholder="e.g. 35000"
                value={loadWeightLbs}
                onChange={(e) => setLoadWeightLbs(Number(e.target.value))}
                disabled={loading}
              />
            </div>

            <div className="form-group flex-1">
              <label htmlFor="interval">Sampling Interval</label>
              <select
                id="interval"
                value={samplingIntervalMiles}
                onChange={(e) => setSamplingIntervalMiles(Number(e.target.value))}
                disabled={loading}
              >
                <option value={10}>Every 10 miles</option>
                <option value={25}>Every 25 miles</option>
                <option value={50}>Every 50 miles</option>
              </select>
            </div>
          </div>

          <button type="submit" className="submit-btn" disabled={loading}>
            {loading ? 'Evaluating Routes & Weather Risks...' : 'Find & Rank Routes'}
          </button>
        </form>

        {loading && (
          <div className="loading-card">
            <div className="spinner"></div>
            <p>
              Calculating road routes, querying Open-Meteo forecasts, and evaluating risk
              thresholds...
            </p>
          </div>
        )}

        {error && (
          <div className="error-card">
            <strong>Error:</strong> {error}
          </div>
        )}

        {data && (
          <div className="results-container">
            {/* Top Warning Banner if NO_TRAVEL conditions prevent safe travel */}
            {data.warning && (
              <div className="warning-banner">
                <span className="warning-icon">⚠️</span>
                <div>
                  <strong>Weather Travel Warning:</strong>
                  <p>{data.warning}</p>
                </div>
              </div>
            )}

            {/* Top Recommendation Banner if safe route found */}
            {data.has_recommended_route && recommendedRoute && (
              <div className="recommendation-banner">
                <div className="recommendation-badge-pill">★ BEST ROUTE</div>
                <div className="recommendation-content">
                  <h3>
                    Recommended: {recommendedRoute.name} ({recommendedRoute.id})
                  </h3>
                  <p>
                    {recommendedRoute.distance_miles} miles |{' '}
                    {formatDuration(recommendedRoute.duration_seconds)} | Severe Miles:{' '}
                    <strong>{recommendedRoute.severe_miles ?? 0} mi</strong> | High Miles:{' '}
                    <strong>{recommendedRoute.high_miles ?? 0} mi</strong> | Avg Risk Score:{' '}
                    <strong>{recommendedRoute.average_risk_score ?? 0}</strong>
                  </p>
                </div>
              </div>
            )}

            {/* Trip Info Header */}
            <div className="trip-summary">
              <h3>Trip Analysis Overview</h3>
              <p>
                <strong>Origin:</strong> {data.origin.name} <br />
                <strong>Destination:</strong> {data.destination.name} <br />
                <strong>Departure:</strong> {formatDateTime(data.departure_datetime)} |{' '}
                <strong>Cargo Weight:</strong> {data.load_weight_lbs.toLocaleString()} lbs |{' '}
                <strong>Interval:</strong> {data.sampling_interval_miles} miles
              </p>
            </div>

            {/* 1. Route Comparison Cards */}
            <div className="route-comparison-section">
              <h3>Route Options Ranked by Safety ({data.routes_count})</h3>
              <div className="routes-list">
                {data.routes.map((route) => {
                  const isSelected = selectedRouteId === route.id
                  const isExpanded = expandedRouteId === route.id

                  return (
                    <div
                      key={route.id}
                      className={`route-card ${isSelected ? 'selected-card' : ''}`}
                      onClick={() => setSelectedRouteId(route.id)}
                    >
                      <div className="route-header">
                        <div className="route-header-left">
                          <span className="rank-indicator">#{route.rank}</span>
                          <h4>{route.name}</h4>
                          <span className="route-badge">{route.id}</span>
                          {route.is_recommended && (
                            <span className="recommended-tag">RECOMMENDED</span>
                          )}
                          {route.has_no_travel && (
                            <span className="risk-badge badge-no-travel">NO TRAVEL</span>
                          )}
                          {route.has_unknown_weather && (
                            <span className="risk-badge badge-unknown">INCOMPLETE DATA</span>
                          )}
                        </div>
                        <div className="route-header-actions">
                          <button
                            type="button"
                            className="select-route-btn"
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedRouteId(route.id)
                            }}
                          >
                            {isSelected ? '✓ On Map' : 'Select on Map'}
                          </button>
                          <button
                            type="button"
                            className="toggle-checkpoints-btn"
                            onClick={(e) => {
                              e.stopPropagation()
                              setExpandedRouteId(isExpanded ? null : route.id)
                            }}
                          >
                            {isExpanded
                              ? 'Hide Checkpoints'
                              : `View ${route.checkpoints_count} Checkpoints`}
                          </button>
                        </div>
                      </div>

                      <div className="route-details">
                        <div className="detail-item">
                          <span className="label">Total Distance</span>
                          <span className="value">{route.distance_miles} miles</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">Est. Duration</span>
                          <span className="value">{formatDuration(route.duration_seconds)}</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">Severe Weather Miles</span>
                          <span className="value">{route.severe_miles ?? 0} mi</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">High Weather Miles</span>
                          <span className="value">{route.high_miles ?? 0} mi</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">Avg Risk Score</span>
                          <span className="value">{route.average_risk_score ?? 0}</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">Checkpoints</span>
                          <span className="value">{route.checkpoints_count} points</span>
                        </div>
                      </div>

                      {/* Expandable Checkpoints Table */}
                      {isExpanded && route.checkpoints && route.checkpoints.length > 0 && (
                        <div className="checkpoints-container" onClick={(e) => e.stopPropagation()}>
                          <h5>Checkpoint Weather & Risk Breakdown</h5>
                          <div className="checkpoint-table-wrapper">
                            <table className="checkpoint-table">
                              <thead>
                                <tr>
                                  <th>Marker</th>
                                  <th>ETA</th>
                                  <th>Wind</th>
                                  <th>Rain</th>
                                  <th>Snow</th>
                                  <th>Load-Adjusted Wind</th>
                                  <th>Combined Risk</th>
                                  <th>Action</th>
                                </tr>
                              </thead>
                              <tbody>
                                {route.checkpoints.map((cp) => (
                                  <tr key={cp.checkpoint_index}>
                                    <td>
                                      <strong>
                                        CP {cp.checkpoint_index} ({cp.distance_from_origin_miles} mi)
                                      </strong>
                                    </td>
                                    <td>{formatDateTime(cp.estimated_arrival_time)}</td>
                                    <td>
                                      {cp.wind_speed_mph !== null ? `${cp.wind_speed_mph} mph` : 'N/A'}{' '}
                                      <span className={`risk-badge ${getRiskClass(cp.wind_risk)}`}>
                                        {cp.wind_risk}
                                      </span>
                                    </td>
                                    <td>
                                      {cp.rain_intensity_in_hr !== null
                                        ? `${cp.rain_intensity_in_hr} in`
                                        : 'N/A'}{' '}
                                      <span className={`risk-badge ${getRiskClass(cp.rain_risk)}`}>
                                        {cp.rain_risk}
                                      </span>
                                    </td>
                                    <td>
                                      {cp.snow_intensity_in_hr !== null
                                        ? `${cp.snow_intensity_in_hr} in`
                                        : 'N/A'}{' '}
                                      <span className={`risk-badge ${getRiskClass(cp.snow_risk)}`}>
                                        {cp.snow_risk}
                                      </span>
                                    </td>
                                    <td>
                                      <span
                                        className={`risk-badge ${getRiskClass(
                                          cp.load_adjusted_wind_risk
                                        )}`}
                                      >
                                        {cp.load_adjusted_wind_risk}
                                      </span>
                                    </td>
                                    <td>
                                      <span className={`risk-badge ${getRiskClass(cp.final_risk)}`}>
                                        {cp.final_risk}
                                      </span>
                                    </td>
                                    <td>
                                      <button
                                        type="button"
                                        className="inspect-cp-btn"
                                        onClick={() => {
                                          setSelectedRouteId(route.id)
                                          setSelectedCheckpoint(cp)
                                        }}
                                      >
                                        Inspect
                                      </button>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>

            {/* 2. Interactive Map Section */}
            <MapView
              routes={data.routes}
              selectedRouteId={selectedRouteId}
              onSelectRoute={(id) => setSelectedRouteId(id)}
              selectedCheckpoint={selectedCheckpoint}
              onSelectCheckpoint={(cp) => setSelectedCheckpoint(cp)}
              originName={data.origin.name}
              destinationName={data.destination.name}
              departureDatetime={data.departure_datetime}
            />
          </div>
        )}
      </main>
    </div>
  )
}

export default App
