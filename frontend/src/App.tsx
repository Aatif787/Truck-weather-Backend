import { useState, useEffect, useRef, type FormEvent } from 'react'
import './App.css'
import { MapView } from './components/MapView'
import { SafetyDashboard } from './components/SafetyDashboard'
import { RecommendationCard } from './components/RecommendationCard'
import { SevereAlertsBanner } from './components/SevereAlertsBanner'
import { RouteComparisonChart } from './components/RouteComparisonChart'
import { generateTripReportPdf } from './services/pdfReport'
import type { RouteAnalysisResponse, RouteItem, Checkpoint } from './types'

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

const PRESET_CORRIDORS = [
  { label: 'Mannheim ➔ Heidelberg', origin: 'Mannheim, Germany', dest: 'Heidelberg, Germany', desc: 'Regional Freight Trunk' },
  { label: 'Frankfurt ➔ Stuttgart', origin: 'Frankfurt, Germany', dest: 'Stuttgart, Germany', desc: 'A5/A8 Industrial Corridor' },
  { label: 'Munich ➔ Nuremberg', origin: 'Munich, Germany', dest: 'Nuremberg, Germany', desc: 'A9 Bavarian Freight Spine' },
  { label: 'Cologne ➔ Dortmund', origin: 'Cologne, Germany', dest: 'Dortmund, Germany', desc: 'Rhine-Ruhr Logistics Link' },
]

function getLoadRuleAdvice(weight: number) {
  if (weight > 40000) {
    return {
      tier: 'Severe Load Tier (>40k lbs)',
      message: 'Wind 35–44 mph escalates to SEVERE due to high tractor-trailer rollover torque.',
      badgeClass: 'badge-high',
    }
  }
  if (weight > 30000) {
    return {
      tier: 'Heavy Load Tier (>30k lbs)',
      message: 'Wind 45–54 mph escalates to NO_TRAVEL to protect against crosswind blowovers.',
      badgeClass: 'badge-moderate',
    }
  }
  return {
    tier: 'Standard Load Tier (≤30k lbs)',
    message: 'Standard wind safety rules apply. Universal NO_TRAVEL at ≥55 mph.',
    badgeClass: 'badge-low',
  }
}

function App() {
  const [origin, setOrigin] = useState('Heidelberg, Germany')
  const [destination, setDestination] = useState('Mannheim, Germany')
  const [departureDatetime, setDepartureDatetime] = useState(getDefaultDateTime())
  const [loadWeightLbs, setLoadWeightLbs] = useState(35000)
  const [samplingIntervalMiles, setSamplingIntervalMiles] = useState(25)

  // Configurable Commercial Class 8 Fuel Baseline
  const [fuelPrice, setFuelPrice] = useState(3.85)
  const [fuelMpg, setFuelMpg] = useState(6.5)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<RouteAnalysisResponse | null>(null)
  const [selectedRouteId, setSelectedRouteId] = useState<string>('route-1')
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<Checkpoint | null>(null)
  const [expandedRouteId, setExpandedRouteId] = useState<string | null>(null)

  // Scroll effect states
  const [scrollProgress, setScrollProgress] = useState(0)
  const [isScrolled, setIsScrolled] = useState(false)
  const [showScrollTop, setShowScrollTop] = useState(false)
  const [toastMessage, setToastMessage] = useState<string | null>(null)

  const showToast = (msg: string) => {
    setToastMessage(msg)
    setTimeout(() => setToastMessage(null), 2500)
  }

  const handleSwapLocations = () => {
    setOrigin(destination)
    setDestination(origin)
    showToast('Swapped origin and destination')
  }

  const setQuickDeparture = (offsetHours: number) => {
    const d = new Date()
    if (offsetHours > 0) {
      d.setHours(d.getHours() + offsetHours)
    }
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
    setDepartureDatetime(d.toISOString().slice(0, 16))
    showToast(offsetHours === 0 ? 'Set departure: Now' : `Set departure: +${offsetHours}h`)
  }

  const handleCopyManifest = (route: RouteItem) => {
    const manifest = [
      '=== SPOTTER TRUCK ROUTE MANIFEST ===',
      `Route: ${route.name} (${route.id}) - ${route.is_recommended ? 'RECOMMENDED' : 'ALTERNATIVE'}`,
      `Origin: ${data?.origin.name || origin}`,
      `Destination: ${data?.destination.name || destination}`,
      `Departure: ${formatDateTime(data?.departure_datetime || departureDatetime)}`,
      `Gross Cargo: ${Number(loadWeightLbs).toLocaleString()} lbs`,
      `Total Distance: ${route.distance_miles} miles`,
      `Est. Driving Duration: ${formatDuration(route.duration_seconds)}`,
      `Safety Score: ${route.safety_score !== undefined ? `${Math.round(route.safety_score)}/100` : 'N/A'}`,
      `Severe Weather Miles: ${route.severe_miles ?? 0} mi`,
      `High Risk Miles: ${route.high_miles ?? 0} mi`,
      `Est. Fuel Gallons: ${(route.distance_miles / fuelMpg).toFixed(1)} gal (@ ${fuelMpg} MPG)`,
      `Est. Fuel Cost: $${((route.distance_miles / fuelMpg) * fuelPrice).toFixed(2)} (@ $${fuelPrice}/gal)`,
      `Checkpoints Monitored: ${route.checkpoints_count || route.checkpoints?.length || 0}`,
      'Safety Compliance: Automated OpenRouteService HGV + Open-Meteo verified',
    ].join('\n')

    navigator.clipboard.writeText(manifest)
    showToast(`Copied ${route.name} manifest to clipboard!`)
  }

  const handleDownloadPdf = () => {
    if (!data) return
    const curSelectedRoute = data.routes.find((r) => r.id === selectedRouteId) || data.routes[0]
    generateTripReportPdf({
      data,
      selectedRoute: curSelectedRoute,
      fuelPrice,
      fuelMpg,
    })
    showToast('Downloaded Trip Safety Report (PDF)')
  }

  const handleInspectCheckpointFromAlert = (routeId: string, checkpointIndex: number) => {
    setSelectedRouteId(routeId)
    const targetRoute = data?.routes.find((r) => r.id === routeId)
    const targetCp = targetRoute?.checkpoints.find((cp) => cp.checkpoint_index === checkpointIndex)
    if (targetCp) {
      setSelectedCheckpoint(targetCp)
      mapViewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }

  const resultsRef = useRef<HTMLDivElement>(null)
  const mapViewRef = useRef<HTMLDivElement>(null)

  // Track window scroll progress and header elevation
  useEffect(() => {
    const handleScroll = () => {
      const scrollY = window.scrollY
      const docHeight = document.documentElement.scrollHeight - window.innerHeight
      const progress = docHeight > 0 ? (scrollY / docHeight) * 100 : 0
      setScrollProgress(progress)
      setIsScrolled(scrollY > 25)
      setShowScrollTop(scrollY > 280)
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  // IntersectionObserver for smooth scroll-reveal card entrances
  useEffect(() => {
    const elements = document.querySelectorAll('.scroll-reveal:not(.revealed)')
    if (!elements.length) return

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('revealed')
            observer.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.08, rootMargin: '0px 0px -20px 0px' }
    )

    elements.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [data, expandedRouteId])

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

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

        // Smooth auto-scroll to results
        setTimeout(() => {
          resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }, 150)
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
  const currentSelectedRoute = data?.routes.find((r) => r.id === selectedRouteId) || data?.routes[0]
  const severeAlertsCount = (data?.severe_alerts || []).filter((a) => a.route_id === selectedRouteId).length

  return (
    <div className="app-container">
      {/* Top Scroll Progress Bar */}
      <div
        className="scroll-progress-bar"
        style={{ width: `${scrollProgress}%` }}
        aria-hidden="true"
      />

      {/* Floating Action Toast Notification */}
      {toastMessage && (
        <div className="floating-toast" role="status">
          <span className="toast-icon">✓</span>
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Enterprise Header / Navigation Bar */}
      <header className={`header ${isScrolled ? 'scrolled' : ''}`}>
        <div className="header-inner">
          <div className="brand-group">
            <div className="brand-logo-mark" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="1" y="3" width="15" height="13" rx="1"/>
                <polygon points="16 8 20 8 23 11 23 16 16 16 8"/>
                <circle cx="5.5" cy="18.5" r="2.5"/>
                <circle cx="18.5" cy="18.5" r="2.5"/>
              </svg>
            </div>
            <div>
              <div className="brand-title-row">
                <h1>Spotter FleetRoute</h1>
                <span className="brand-tag">DISPATCH v2.5</span>
              </div>
              <p className="subtitle">
                Commercial HGV Route Optimization & Checkpoint Weather Risk Intelligence
              </p>
            </div>
          </div>

          <div className="header-telemetry-status">
            <div className="live-status-pill">
              <span className="status-pulse-dot" />
              <span>Telemetry: ORS + Open-Meteo Deterministic</span>
            </div>
            {data && (
              <button
                type="button"
                className="quick-scroll-results-btn"
                onClick={() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
              >
                ↓ View Results ({data.routes_count})
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="content">
        {/* Quick Corridor Selection Bar */}
        <div className="preset-corridors-bar">
          <span className="preset-corridors-label">Quick Test Corridors:</span>
          <div className="preset-chips-list">
            {PRESET_CORRIDORS.map((pc) => (
              <button
                key={pc.label}
                type="button"
                className="preset-chip"
                onClick={() => {
                  setOrigin(pc.origin)
                  setDestination(pc.dest)
                  showToast(`Selected: ${pc.label}`)
                }}
                disabled={loading}
                title={pc.desc}
              >
                {pc.label}
              </button>
            ))}
          </div>
        </div>

        <form className="route-form" onSubmit={handleSearch}>
          <div className="form-row-locations">
            <div className="form-group flex-1">
              <label htmlFor="origin">
                <span className="label-icon">📍</span> Origin Waypoint
              </label>
              <div className="input-with-clear">
                <input
                  id="origin"
                  type="text"
                  placeholder="e.g. Heidelberg, Germany"
                  value={origin}
                  onChange={(e) => setOrigin(e.target.value)}
                  disabled={loading}
                  required
                />
                {origin && (
                  <button type="button" className="input-clear-btn" onClick={() => setOrigin('')} title="Clear origin">✕</button>
                )}
              </div>
            </div>

            <button
              type="button"
              className="location-swap-btn"
              onClick={handleSwapLocations}
              title="Swap Origin and Destination"
              disabled={loading}
            >
              ⇄
            </button>

            <div className="form-group flex-1">
              <label htmlFor="destination">
                <span className="label-icon">🏁</span> Destination Waypoint
              </label>
              <div className="input-with-clear">
                <input
                  id="destination"
                  type="text"
                  placeholder="e.g. Mannheim, Germany"
                  value={destination}
                  onChange={(e) => setDestination(e.target.value)}
                  disabled={loading}
                  required
                />
                {destination && (
                  <button type="button" className="input-clear-btn" onClick={() => setDestination('')} title="Clear destination">✕</button>
                )}
              </div>
            </div>
          </div>

          <div className="form-row form-row-specs">
            <div className="form-group flex-1">
              <div className="label-row-with-helpers">
                <label htmlFor="departure">Departure Schedule</label>
                <div className="mini-helpers">
                  <button type="button" onClick={() => setQuickDeparture(0)} disabled={loading}>Now</button>
                  <button type="button" onClick={() => setQuickDeparture(2)} disabled={loading}>+2h</button>
                  <button type="button" onClick={() => setQuickDeparture(24)} disabled={loading}>+24h</button>
                </div>
              </div>
              <input
                id="departure"
                type="datetime-local"
                value={departureDatetime}
                onChange={(e) => setDepartureDatetime(e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="form-group flex-1">
              <div className="label-row-with-helpers">
                <label htmlFor="weight">Gross Cargo Weight (lbs)</label>
                <div className="mini-helpers">
                  <button type="button" onClick={() => setLoadWeightLbs(18000)} disabled={loading}>18k</button>
                  <button type="button" onClick={() => setLoadWeightLbs(35000)} disabled={loading}>35k</button>
                  <button type="button" onClick={() => setLoadWeightLbs(44000)} disabled={loading}>44k</button>
                </div>
              </div>
              <input
                id="weight"
                type="number"
                min="0"
                max="80000"
                step="500"
                placeholder="e.g. 35000"
                value={loadWeightLbs}
                onChange={(e) => setLoadWeightLbs(Number(e.target.value))}
                disabled={loading}
              />
            </div>

            <div className="form-group flex-1">
              <label>Sampling Resolution</label>
              <div className="segmented-control" role="group" aria-label="Checkpoint sampling interval">
                <button
                  type="button"
                  className={`segment-btn ${samplingIntervalMiles === 10 ? 'active' : ''}`}
                  onClick={() => setSamplingIntervalMiles(10)}
                  disabled={loading}
                >
                  10 mi
                </button>
                <button
                  type="button"
                  className={`segment-btn ${samplingIntervalMiles === 25 ? 'active' : ''}`}
                  onClick={() => setSamplingIntervalMiles(25)}
                  disabled={loading}
                >
                  25 mi
                </button>
                <button
                  type="button"
                  className={`segment-btn ${samplingIntervalMiles === 50 ? 'active' : ''}`}
                  onClick={() => setSamplingIntervalMiles(50)}
                  disabled={loading}
                >
                  50 mi
                </button>
              </div>
            </div>
          </div>

          {/* Dynamic Cargo Weight Safety Rule Advisory */}
          {(() => {
            const advice = getLoadRuleAdvice(Number(loadWeightLbs) || 0)
            return (
              <div className={`load-rule-advisory-card ${advice.badgeClass}`}>
                <div className="advisory-badge-pill">{advice.tier}</div>
                <p className="advisory-text">{advice.message}</p>
              </div>
            )
          })()}

          <div className="form-actions-row">
            <button type="submit" className="submit-btn" disabled={loading}>
              {loading ? (
                <>
                  <span className="btn-spinner" />
                  <span>Calculating HGV Routes & Sampling Weather...</span>
                </>
              ) : (
                <>
                  <span>⚡ Calculate 3 Safe Routes</span>
                  <span className="btn-key-hint">Enter</span>
                </>
              )}
            </button>
          </div>
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
          <div className="results-container" ref={resultsRef}>
            {/* Top Warning Banner if NO_TRAVEL conditions prevent safe travel */}
            {data.warning && (
              <div className="warning-banner scroll-reveal">
                <span className="warning-icon">⚠️</span>
                <div>
                  <strong>Weather Travel Warning:</strong>
                  <p>{data.warning}</p>
                </div>
              </div>
            )}

            {/* Trip Info Header */}
            <div className="trip-summary scroll-reveal">
              <div className="trip-summary-header">
                <h3>Trip Dispatch Analysis Overview</h3>
                <button
                  type="button"
                  className="trip-download-pdf-btn"
                  onClick={handleDownloadPdf}
                  title="Generate comprehensive PDF dispatch report"
                >
                  <span>📄 PDF Report</span>
                </button>
              </div>
              <p>
                <strong>Origin:</strong> {data.origin.name} <br />
                <strong>Destination:</strong> {data.destination.name} <br />
                <strong>Departure:</strong> {formatDateTime(data.departure_datetime)} |{' '}
                <strong>Cargo Weight:</strong> {data.load_weight_lbs.toLocaleString()} lbs |{' '}
                <strong>Sampling Interval:</strong> {data.sampling_interval_miles} miles |{' '}
                <strong>Baseline Fuel:</strong> ${fuelPrice.toFixed(2)}/gal @ {fuelMpg.toFixed(1)} MPG
              </p>
            </div>

            {/* FEATURE 1: SAFETY ANALYTICS DASHBOARD */}
            {currentSelectedRoute && (
              <SafetyDashboard
                selectedRoute={currentSelectedRoute}
                allRoutes={data.routes}
                onSelectRoute={(id) => setSelectedRouteId(id)}
                severeAlertsCount={severeAlertsCount}
                onDownloadPdf={handleDownloadPdf}
              />
            )}

            {/* FEATURE 2: INTELLIGENT ROUTE RECOMMENDATION & TRADEOFF MATRIX */}
            <RecommendationCard
              recommendationRationale={data.recommendation_rationale}
              tradeoffs={data.tradeoffs}
              recommendedRoute={recommendedRoute}
              allRoutes={data.routes}
              onSelectRoute={(id) => setSelectedRouteId(id)}
              warning={data.warning}
            />

            {/* FEATURE 3: SEVERE WEATHER ALERTS */}
            <SevereAlertsBanner
              severeAlerts={data.severe_alerts || []}
              selectedRouteId={selectedRouteId}
              selectedRouteName={currentSelectedRoute?.name}
              onInspectCheckpoint={handleInspectCheckpointFromAlert}
            />

            {/* FEATURE 5: ROUTE COMPARISON & FUEL COST MODEL + SVG BAR CHART */}
            <RouteComparisonChart
              routes={data.routes}
              selectedRouteId={selectedRouteId}
              onSelectRoute={(id) => setSelectedRouteId(id)}
              fuelPrice={fuelPrice}
              fuelMpg={fuelMpg}
              onUpdateFuel={(price, mpg) => {
                setFuelPrice(price)
                setFuelMpg(mpg)
              }}
            />

            {/* FEATURE 6: INTERACTIVE MAP EXPERIENCE */}
            <div ref={mapViewRef} className="map-scroll-wrapper scroll-reveal">
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

            {/* DETAILED ROUTE CARDS & CHECKPOINTS INSPECTION */}
            <div className="route-comparison-section scroll-reveal">
              <h3>Detailed Route Cards & Waypoint Itinerary ({data.routes_count})</h3>
              <div className="routes-list">
                {data.routes.map((route) => {
                  const isSelected = selectedRouteId === route.id
                  const isExpanded = expandedRouteId === route.id
                  const estGallons = (route.distance_miles / fuelMpg)
                  const estCost = estGallons * fuelPrice

                  return (
                    <div
                      key={route.id}
                      className={`route-card ${isSelected ? 'selected-card' : ''} scroll-reveal delay-${Math.min(3, route.rank || 1)}`}
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
                            className="copy-manifest-btn"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleCopyManifest(route)
                            }}
                            title="Copy complete route manifest for driver dispatch"
                          >
                            📋 Manifest
                          </button>
                          <button
                            type="button"
                            className="select-route-btn"
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedRouteId(route.id)
                            }}
                          >
                            {isSelected ? '✓ Active on Map' : 'Select on Map'}
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
                              ? 'Hide Table'
                              : `Table (${route.checkpoints_count || route.checkpoints?.length || 0})`}
                          </button>
                        </div>
                      </div>

                      <div className="route-details">
                        <div className="detail-item">
                          <span className="label">Total Distance</span>
                          <span className="value">{route.distance_miles.toFixed(1)} miles</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">Est. Duration</span>
                          <span className="value">{formatDuration(route.duration_seconds)}</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">Safety Score</span>
                          <span className="value">
                            {route.safety_score !== undefined ? `${Math.round(route.safety_score)}/100` : 'N/A'}
                          </span>
                        </div>
                        <div className="detail-item">
                          <span className="label">Severe Miles</span>
                          <span className="value">{route.severe_miles ?? 0} mi</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">High Miles</span>
                          <span className="value">{route.high_miles ?? 0} mi</span>
                        </div>
                        <div className="detail-item">
                          <span className="label">Est. Fuel Cost</span>
                          <span className="value">${estCost.toFixed(2)} (est)</span>
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
                                        CP {cp.checkpoint_index + 1} ({cp.distance_from_origin_miles.toFixed(1)} mi)
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
                                          mapViewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
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
          </div>
        )}
      </main>

      {/* Floating Scroll-to-Top Button */}
      <button
        type="button"
        className={`scroll-to-top-btn ${showScrollTop ? 'visible' : ''}`}
        onClick={scrollToTop}
        aria-label="Scroll back to top"
        title="Scroll back to top"
      >
        <span className="scroll-top-arrow" aria-hidden="true">↑</span>
        <span>Top</span>
      </button>
    </div>
  )
}

export default App
